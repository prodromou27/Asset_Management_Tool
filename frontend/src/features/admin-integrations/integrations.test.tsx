import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { IntegrationInstance, NeighborEvidence, SyncRun } from '../../shared/api/types'
import {
  ASSET_ID,
  CAT_SWITCH,
  apiError,
  makeAsset,
  makeField,
  makeIntegration,
  makeMe,
  mockApi,
  page,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const ID = '99999999-9999-4999-8999-999999999901'
const URL = `/admin/integrations/${ID}`

function librenms(overrides: Partial<IntegrationInstance> = {}): IntegrationInstance {
  return makeIntegration({
    id: ID,
    name: 'LibreNMS HQ',
    source: {
      code: 'librenms',
      name: 'LibreNMS',
      kind: 'network',
      availability: 'beta',
      description: '',
      instance_count: 1,
    },
    base_url: 'https://librenms.corp.example',
    credential_ref: 'env:ITAM_INTEGRATION_LIBRENMS_TOKEN',
    credential_status: 'configured',
    has_adapter: true,
    connector: { auth_schemes: ['bearer', 'x_auth_token'], supports_evidence: true },
    live_integrations_enabled: true,
    live_access_approved: true,
    live_access_approved_by: 'admin.one',
    live_access_approved_at: '2026-11-02T07:00:00Z',
    live_access_reason: 'CAB-2026-114 read-only account',
    status: 'available',
    freshness: 'fresh',
    active_links: 7,
    stale_links: 1,
    open_candidates: 3,
    source_software_version: '24.10.0',
    capabilities: { devices: true, fdb: true, links: false },
    last_test_ok: true,
    last_test_at: '2026-11-02T07:05:00Z',
    last_run: {
      id: 'run-1',
      mode: 'full',
      status: 'succeeded',
      phase: 'done',
      started_at: '2026-11-02T08:00:00Z',
      finished_at: '2026-11-02T08:03:00Z',
      records_received: 10,
      devices_total: 10,
      devices_processed: 10,
      links_refreshed: 7,
      candidates_opened: 3,
      errors: 0,
      warnings: 2,
      error_message: '',
    },
    ...overrides,
  })
}

function makeRun(overrides: Partial<SyncRun> = {}): SyncRun {
  return {
    id: 'run-1',
    mode: 'full',
    status: 'succeeded',
    started_at: '2026-11-02T08:00:00Z',
    finished_at: '2026-11-02T08:03:00Z',
    triggered_by: 'schedule',
    records_received: 10,
    observations_created: 10,
    observations_unchanged: 0,
    candidates_opened: 3,
    candidates_updated: 0,
    links_refreshed: 7,
    links_marked_stale: 0,
    assets_updated: 2,
    conflicts_opened: 0,
    errors: 0,
    error_samples: [],
    warnings: 2,
    warning_samples: [{ external_id: '110', warning: 'Device is disabled in LibreNMS (not polled).' }],
    error_message: '',
    phase: 'done',
    devices_total: 10,
    devices_processed: 10,
    devices_enriched: 10,
    evidence_rows: 5,
    api_requests: 33,
    heartbeat_at: '2026-11-02T08:03:00Z',
    ...overrides,
  } as SyncRun
}

const routes = (instance = librenms(), runs = [makeRun()]) => ({
  'GET /auth/me/': { body: makeMe() },
  [`GET /integrations/${ID}/`]: { body: instance },
  [`GET /integrations/${ID}/runs/`]: { body: page(runs) },
})

describe('LibreNMS integration page', () => {
  it('shows health, capabilities and sync history', async () => {
    mockApi(routes())
    renderApp(URL)

    expect(await screen.findByRole('heading', { name: 'LibreNMS HQ' })).toBeInTheDocument()
    expect(screen.getByText('LibreNMS · Beta (fixture-tested)')).toBeInTheDocument()
    const strip = screen.getByLabelText('Integration status')
    expect(strip).toHaveTextContent('Available')
    expect(strip).toHaveTextContent('Secret available')
    expect(strip).toHaveTextContent('Approved')

    const health = screen.getByRole('region', { name: 'Health' })
    expect(within(health).getByText('7 (1 stale)')).toBeInTheDocument()
    expect(within(health).getByRole('link', { name: '3 awaiting review' })).toHaveAttribute(
      'href',
      `/discovery?instance=${ID}`,
    )
    expect(within(health).getByText('0 / 2 in last run')).toBeInTheDocument()
    expect(within(health).getByText('24.10.0')).toBeInTheDocument()

    const caps = screen.getByRole('region', { name: 'API capabilities' })
    expect(within(caps).getByText('LLDP/CDP neighbours').parentElement).toHaveTextContent('Not available')

    const history = screen.getByRole('region', { name: 'Sync history' })
    expect(await within(history).findByText('schedule')).toBeInTheDocument()
    expect(within(history).getByText('33')).toBeInTheDocument()
    expect(within(history).getByText(/Device 110: Device is disabled/)).toBeInTheDocument()
  })

  it('blocks sync and explains why when the deployment gate is closed', async () => {
    mockApi(routes(librenms({ live_integrations_enabled: false })))
    renderApp(URL)

    expect(await screen.findByText(/Live integrations are disabled for this deployment/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeDisabled()
  })

  it('records live-access approval with a reason', async () => {
    const { calls } = mockApi({
      ...routes(librenms({ live_access_approved: false, live_access_approved_by: null, live_access_reason: '' })),
      [`POST /integrations/${ID}/live-access/`]: { body: librenms() },
    })
    renderApp(URL)

    const panel = await screen.findByRole('region', { name: 'Live access' })
    fireEvent.click(within(panel).getByRole('button', { name: 'Approve live access' }))
    expect(await within(panel).findByText('Enter at least 5 characters.')).toBeInTheDocument()

    fireEvent.change(within(panel).getByLabelText('Approval reference'), {
      target: { value: 'CAB-2026-114 read-only account' },
    })
    fireEvent.click(within(panel).getByRole('button', { name: 'Approve live access' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true))
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      approved: true,
      reason: 'CAB-2026-114 read-only account',
    })
  })

  it('tests the connection and queues a manual sync', async () => {
    let queued = false
    const { calls } = mockApi({
      ...routes(),
      [`GET /integrations/${ID}/`]: () => ({
        body: queued
          ? librenms({ last_run: { ...librenms().last_run!, status: 'running', phase: 'enrichment', devices_processed: 4 } })
          : librenms(),
      }),
      [`POST /integrations/${ID}/test/`]: {
        body: { ok: true, message: 'Connected. Read-only API access works.', version: '24.10.0', capabilities: {} },
      },
      [`POST /integrations/${ID}/sync/`]: () => {
        queued = true
        return { status: 202, body: makeRun({ status: 'queued', phase: '' }) }
      },
    })
    renderApp(URL)

    fireEvent.click(await screen.findByRole('button', { name: 'Test connection' }))
    expect(await screen.findByText(/Connected\. Read-only API access works\. LibreNMS 24\.10\.0\./)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }))
    expect(await screen.findByText('Reading device details · 4 of 10 devices')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeDisabled()
    expect(calls.find((c) => c.path.endsWith('/sync/'))?.body).toEqual({ mode: 'full' })
  })

  it('saves configuration with If-Match and shows server field errors', async () => {
    const { calls } = mockApi({
      ...routes(),
      [`PATCH /integrations/${ID}/`]: apiError(422, 'VALIDATION_ERROR', 'Invalid input.', {
        credential_ref: ['Use env:ITAM_INTEGRATION_<NAME> or file:<name> (a file in the deployment secrets directory).'],
      }),
    })
    renderApp(URL)

    const form = await screen.findByRole('region', { name: 'Configuration' })
    fireEvent.change(within(form).getByLabelText('API token reference'), { target: { value: 'env:DJANGO_SECRET_KEY' } })
    fireEvent.change(within(form).getByLabelText('Retries'), { target: { value: '9' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save configuration' }))
    expect(await within(form).findByText('Enter 0 to 6 retries.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)

    fireEvent.change(within(form).getByLabelText('Retries'), { target: { value: '2' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save configuration' }))
    expect(await within(form).findByText(/Use env:ITAM_INTEGRATION_<NAME>/)).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch?.headers['If-Match']).toBe('"1"')
    expect(patch?.body).toMatchObject({ credential_ref: 'env:DJANGO_SECRET_KEY', max_retries: 2, auth_scheme: 'bearer' })
  })

  it('never shows connector actions for sources without an adapter', async () => {
    mockApi(
      routes(
        librenms({
          has_adapter: false,
          source: { code: 'intune', name: 'Microsoft Intune', kind: 'endpoint', availability: 'planned', description: '', instance_count: 1 },
        }),
        [],
      ),
    )
    renderApp(URL)

    expect(await screen.findByText(/This source has no adapter yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Live access' })).not.toBeInTheDocument()
  })

  it('links from the integrations list and labels beta sources', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /integrations/': { body: [librenms({ live_access_approved: false })] },
      'GET /discovery/sources/': { body: [] },
      'GET /discovery/field-authority/': { body: { precedence: {}, version: 1, modified_at: '2026-11-01T00:00:00Z' } },
    })
    renderApp('/admin/integrations')

    expect(await screen.findByRole('link', { name: 'LibreNMS HQ' })).toHaveAttribute('href', URL)
    expect(screen.getByText('Beta (fixture-tested)')).toBeInTheDocument()
    expect(screen.getByText('Live access not approved')).toBeInTheDocument()
  })
})

describe('Asset network evidence', () => {
  const evidence: NeighborEvidence[] = [
    {
      id: 'n1',
      instance: 'LibreNMS HQ',
      kind: 'lldp',
      direction: 'local',
      local_external_id: '101',
      local_port: 'Gi1/0/1',
      local_asset: { id: ASSET_ID, name: 'sw-core-01' },
      remote_mac: '',
      remote_external_id: '103',
      remote_hostname: 'sw-access-03',
      remote_port: '1/1/49',
      remote_platform: 'Aruba JL659A',
      remote_asset: { id: 'a-103', name: 'sw-access-03' },
      vlan: '',
      is_active: true,
      first_seen_at: '2026-11-02T08:00:00Z',
      last_seen_at: '2026-11-02T08:00:00Z',
      is_physical_link_confirmed: false,
    },
    {
      id: 'n2',
      instance: 'LibreNMS HQ',
      kind: 'fdb',
      direction: 'local',
      local_external_id: '101',
      local_port: 'port 1003',
      local_asset: { id: ASSET_ID, name: 'sw-core-01' },
      remote_mac: '02:00:5e:aa:aa:aa',
      remote_external_id: '',
      remote_hostname: '',
      remote_port: '',
      remote_platform: '',
      remote_asset: null,
      vlan: '10',
      is_active: false,
      first_seen_at: '2026-11-01T08:00:00Z',
      last_seen_at: '2026-11-01T08:00:00Z',
      is_physical_link_confirmed: false,
    },
  ]

  it('shows FDB and neighbour evidence as observations, not cables', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
      [`GET /assets/${ASSET_ID}/network-evidence/`]: { body: evidence },
    })
    renderApp(`/assets/${ASSET_ID}?tab=network`)

    const section = await screen.findByRole('region', { name: 'Observed network evidence' })
    expect(within(section).getByText(/Observed, not a confirmed cable/)).toBeInTheDocument()
    expect(await within(section).findByRole('link', { name: 'sw-access-03' })).toHaveAttribute(
      'href',
      '/assets/a-103?tab=network',
    )
    expect(within(section).getByText('02:00:5e:aa:aa:aa')).toBeInTheDocument()
    expect(within(section).getByText('No longer seen')).toBeInTheDocument()
  })

  it('is hidden from users without discovery access', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe({ permissions: ['assets.view'] }) },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
    })
    renderApp(`/assets/${ASSET_ID}?tab=network`)

    expect(await screen.findByRole('heading', { name: 'Hostnames' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Observed network evidence' })).not.toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/network-evidence/'))).toBe(false)
  })
})

describe('Endpoint Central integration page', () => {
  const endpointCentral = () =>
    librenms({
      name: 'Endpoint Central',
      source: {
        code: 'endpoint_central',
        name: 'Endpoint Central (on-premises)',
        kind: 'endpoint',
        availability: 'beta',
        description: '',
        instance_count: 1,
      },
      base_url: 'https://ec.corp.example:8383',
      auth_scheme: 'authorization',
      connector: { auth_schemes: ['authorization', 'bearer'], supports_evidence: false },
      source_software_version: '11.3.2416.1',
      capabilities: { computers: true, route_api_1_4: true, route_dcapi: false, software: false },
    })

  it('offers only the source’s auth headers and hides network evidence settings', async () => {
    mockApi(routes(endpointCentral()))
    renderApp(URL)

    const form = await screen.findByRole('region', { name: 'Configuration' })
    const header = within(form).getByLabelText('Authentication header')
    expect(within(header).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Authorization: <token>',
      'Authorization: Bearer <token>',
    ])
    expect(within(form).queryByLabelText('FDB/neighbours every (hours)')).not.toBeInTheDocument()
    expect(within(form).getByPlaceholderText('https://endpointcentral.example:8383')).toBeInTheDocument()

    const health = screen.getByRole('region', { name: 'Health' })
    expect(within(health).getByText('Endpoint Central (on-premises) version')).toBeInTheDocument()
    expect(within(health).queryByText('Last FDB/neighbour pass')).not.toBeInTheDocument()

    const caps = screen.getByRole('region', { name: 'API capabilities' })
    expect(within(caps).getByText('Inventory API: api/1.4 (older builds)').parentElement).toHaveTextContent('Available')
    expect(within(caps).getByText('Installed software (not collected yet)').parentElement).toHaveTextContent(
      'Not available',
    )
  })
})
