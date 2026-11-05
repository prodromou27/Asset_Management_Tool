import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EndpointSecurityState, IntegrationInstance } from '../../shared/api/types'
import {
  ASSET_ID,
  CAT_SWITCH,
  makeAsset,
  makeField,
  makeIntegration,
  makeMe,
  mockApi,
  page,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const MACHINE = '1e5c3b2a0d9f8e7c6b5a4f3e2d1c0b9a8f7e6d01'

function makeState(overrides: Partial<EndpointSecurityState> = {}): EndpointSecurityState {
  return {
    id: '55555555-5555-4555-8555-555555555501',
    instance: { id: '99999999-9999-4999-8999-999999999902', name: 'Defender', source: 'defender' },
    external_id: MACHINE,
    link_status: 'active',
    tenant_id: '6d1f0c2e-5a7b-4c3d-9e8f-0a1b2c3d4e5f',
    entra_device_id: 'e1000001-0000-4000-8000-000000000001',
    computer_dns_name: 'lt-0042.corp.example',
    os_platform: 'Windows11',
    os_version: '10.0 (build 22631)',
    onboarding_status: 'Onboarded',
    health_status: 'ImpairedCommunication',
    exposure_level: 'High',
    risk_score: 'Low',
    device_tags: ['Finance', 'VIP'],
    machine_group: 'Workstations',
    first_seen_at: '2026-01-15T09:30:00Z',
    last_seen_at: '2026-11-02T07:41:12Z',
    last_synced_at: '2026-11-02T08:00:00Z',
    source_last_success_at: '2026-11-02T08:00:00Z',
    missing_since: null,
    changed_at: '2026-11-02T08:00:00Z',
    freshness: 'fresh',
    observation_id: null,
    original: { healthStatus: 'ImpairedCommunication', riskScore: 'Low' },
    ...overrides,
  }
}

const assetRoutes = (states: EndpointSecurityState[], me = makeMe()) => ({
  'GET /auth/me/': { body: me },
  [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
  [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
  [`GET /assets/${ASSET_ID}/security/`]: { body: states },
})

describe('Asset security tab', () => {
  it('shows Defender observations apart from asset fields', async () => {
    mockApi(assetRoutes([makeState()]))
    renderApp(`/assets/${ASSET_ID}?tab=security`)

    const panel = await screen.findByRole('region', { name: 'Defender security observation' })
    expect(within(panel).getByText('Onboarded')).toBeInTheDocument()
    expect(within(panel).getByText('Impaired communication')).toBeInTheDocument()
    expect(within(panel).getByText('High')).toBeInTheDocument()
    expect(within(panel).getByText('Finance, VIP')).toBeInTheDocument()
    expect(within(panel).getByText('Fresh')).toBeInTheDocument()
    expect(within(panel).getByText(/not a live online status/)).toBeInTheDocument()
    expect(within(panel).getByText(MACHINE)).toBeInTheDocument()
    expect(within(panel).getByLabelText('Original Defender values')).toHaveTextContent('ImpairedCommunication')
    expect(screen.getByText(/never change the asset.s fields/)).toBeInTheDocument()
  })

  it('explains a machine missing from the latest listing without calling it gone', async () => {
    mockApi(assetRoutes([makeState({ missing_since: '2026-11-03T08:00:00Z', freshness: 'stale' })]))
    renderApp(`/assets/${ASSET_ID}?tab=security`)

    const panel = await screen.findByRole('region', { name: 'Defender security observation' })
    expect(within(panel).getByText('Stale')).toBeInTheDocument()
    expect(within(panel).getByText(/does not mean the device no longer exists/)).toBeInTheDocument()
  })

  it('shows an empty state when no security source is linked', async () => {
    mockApi(assetRoutes([]))
    renderApp(`/assets/${ASSET_ID}?tab=security`)

    expect(await screen.findByText('No security source is linked to this asset.')).toBeInTheDocument()
  })

  it('is hidden from users without discovery access', async () => {
    const { calls } = mockApi(assetRoutes([], makeMe({ permissions: ['assets.view'] })))
    renderApp(`/assets/${ASSET_ID}`)

    expect(await screen.findByRole('tab', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Security' })).not.toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/security/'))).toBe(false)
  })
})

describe('Defender integration page', () => {
  const defender = (overrides: Partial<IntegrationInstance> = {}) =>
    makeIntegration({
      id: '99999999-9999-4999-8999-999999999901',
      name: 'Defender',
      source: {
        code: 'defender',
        name: 'Microsoft Defender for Endpoint',
        kind: 'security',
        availability: 'beta',
        description: '',
        instance_count: 1,
        has_adapter: true,
        required_permissions: [],
      },
      has_adapter: true,
      base_url: 'https://api.security.microsoft.com',
      credential_ref: 'file:defender-app.pem',
      auth_scheme: 'client_certificate',
      tenant_id: '6d1f0c2e-5a7b-4c3d-9e8f-0a1b2c3d4e5f',
      client_id: '7c2d9e1f-3a4b-4c5d-8e6f-2a3b4c5d6e7f',
      connector: {
        auth_schemes: ['client_certificate'],
        supports_evidence: false,
        fixed_base_url: 'https://api.security.microsoft.com',
        required_settings: ['tenant_id', 'client_id'],
        permissions: ['Machine.Read.All'],
        uses_source_timezone: false,
        uses_detail_refresh: false, supports_software: false,
      },
      capabilities: {
        machines: true,
        advanced_hunting: false,
        device_actions: false,
        permission_read_all: true,
        excess_permissions: false,
      },
      ...overrides,
    })

  it('shows the fixed API, certificate-only sign-in and Machine.Read.All', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /integrations/99999999-9999-4999-8999-999999999901/': { body: defender() },
      'GET /integrations/99999999-9999-4999-8999-999999999901/runs/': { body: page([]) },
    })
    renderApp('/admin/integrations/99999999-9999-4999-8999-999999999901')

    const form = await screen.findByRole('region', { name: 'Configuration' })
    expect(within(form).getByText('https://api.security.microsoft.com')).toBeInTheDocument()
    const method = within(form).getByLabelText('Authentication method')
    expect(within(method).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'OAuth client certificate (recommended)',
    ])
    expect(within(form).getByLabelText('Certificate reference')).toHaveValue('file:defender-app.pem')
    const perms = screen.getByRole('region', { name: 'Required permissions' })
    expect(within(perms).getByText('Machine.Read.All')).toBeInTheDocument()
    const caps = screen.getByRole('region', { name: 'API capabilities' })
    expect(within(caps).getByText('Device actions (never used)').parentElement).toHaveTextContent('Not available')
    expect(screen.getByText(/never grant device actions/)).toBeInTheDocument()
  })
})
