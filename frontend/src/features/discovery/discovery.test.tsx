import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  AssetEvidence,
  Candidate,
  CategoryReview,
  FieldConflict,
  IntegrationInstance,
  QualityFinding,
} from '../../shared/api/types'
import {
  ASSET_ID,
  CATEGORIES,
  CAT_SWITCH,
  SITE_HQ,
  apiError,
  assetOperatorMe,
  makeAsset,
  makeField,
  makeIntegration,
  makeMe,
  mockApi,
  page,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const INSTANCE = { id: '99999999-9999-4999-8999-999999999901', name: 'NMS HQ', source: 'fixture' }
const CANDIDATE_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1'
const OBS_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1'

function makeCandidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    id: CANDIDATE_ID,
    instance: INSTANCE,
    external_id: '317',
    site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' },
    status: 'open',
    rule: 'corroborated',
    score: 55,
    proposed_asset: { id: ASSET_ID, name: 'sw-core-01' },
    matches: [
      {
        asset_id: ASSET_ID,
        asset_name: 'sw-core-01',
        score: 55,
        keys: [
          { key: 'mac', strength: 'corroborating', value: '02:00:00:00:00:01' },
          { key: 'hostname', strength: 'corroborating', value: 'sw-core-01.corp.example' },
        ],
        category_agrees: true,
      },
    ],
    hidden_match_count: 1,
    conflicts: [],
    suggested_category: { id: CAT_SWITCH.id, name: 'Switch' },
    assignee: null,
    assigned_at: null,
    observation: {
      id: OBS_ID,
      external_id: '317',
      observed_at: '2026-11-02T08:00:00Z',
      received_at: '2026-11-02T08:01:00Z',
      checksum: 'f'.repeat(64),
      source_version: 'fixture-1',
      normalized: {
        manufacturer: 'Cisco',
        model: 'C9300-48T',
        serial_number: null,
        serial_verified: false,
        hostnames: ['sw-core-01.corp.example'],
        interfaces: [{ name: 'Vlan10', mac: '02:00:00:00:00:01' }],
        ip_addresses: [{ address: '192.0.2.11', vrf: '', interface: 'Vlan10' }],
        device_type: 'switch',
        warnings: ['Serial number looks like a placeholder; treated as unknown.'],
      },
    },
    decision: '',
    decision_reason: '',
    decided_by: null,
    decided_at: null,
    resulting_asset: null,
    created_at: '2026-11-02T08:01:00Z',
    modified_at: '2026-11-02T08:01:00Z',
    version: 2,
    ...overrides,
  }
}

const integration: IntegrationInstance = makeIntegration({ default_site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' } })

describe('Discovery queue', () => {
  it('lists candidates with match type, confidence and hidden-site note', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /integrations/': { body: [integration] },
      'GET /discovery/candidates/': { body: page([makeCandidate()]) },
    })

    renderApp('/discovery')

    const table = await screen.findByRole('table', { name: 'Reconciliation candidates' })
    expect(within(table).getByRole('link', { name: 'sw-core-01.corp.example' })).toHaveAttribute(
      'href',
      `/discovery/candidates/${CANDIDATE_ID}`,
    )
    expect(within(table).getByText('Several identifiers agree')).toBeInTheDocument()
    expect(within(table).getByText('55 · medium')).toBeInTheDocument()
    expect(within(table).getByText('+1 in sites you cannot access')).toBeInTheDocument()
  })

  it('shows source freshness and sync history', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /integrations/': { body: [integration] },
      [`GET /integrations/${INSTANCE.id}/runs/`]: {
        body: page([
          {
            id: 'r1', mode: 'full', status: 'partial', triggered_by: 'cli', started_at: '2026-11-02T08:00:00Z',
            finished_at: '2026-11-02T08:01:00Z', records_received: 5, observations_created: 4, observations_unchanged: 0,
            links_refreshed: 0, links_marked_stale: 0, candidates_opened: 4, candidates_updated: 0, assets_updated: 0,
            conflicts_opened: 0, errors: 1, error_samples: [{ external_id: '9', error: 'observed_at is required' }],
            error_message: '',
          },
        ]),
      },
    })

    renderApp('/discovery?tab=sources')

    const table = await screen.findByRole('table', { name: 'Integration sources and freshness' })
    expect(within(table).getByText('Stale')).toBeInTheDocument()
    expect(within(table).getByText('1 stale')).toBeInTheDocument()
    fireEvent.click(within(table).getByRole('button', { name: /Sync history/ }))
    expect(await screen.findByText('Partial')).toBeInTheDocument()
    expect(screen.getByText('observed_at is required')).toBeInTheDocument()
  })

  it('is denied to roles without discovery.view', async () => {
    mockApi({ 'GET /auth/me/': { body: assetOperatorMe() } })

    renderApp('/discovery')

    expect(await screen.findByText(/do not have access to discovery/i)).toBeInTheDocument()
  })
})

describe('Candidate decision', () => {
  const routes = (candidate = makeCandidate()) => ({
    'GET /auth/me/': { body: makeMe() },
    [`GET /discovery/candidates/${CANDIDATE_ID}/`]: { body: candidate },
    'GET /asset-categories/': { body: CATEGORIES },
    [`GET /discovery/observations/${OBS_ID}/`]: {
      body: { ...candidate.observation, instance: INSTANCE, payload: { manufacturer: 'Cisco Systems, Inc.' }, normalizer_version: 1 },
    },
  })

  it('shows evidence, identifier strength, warnings and raw payload', async () => {
    mockApi(routes())
    renderApp(`/discovery/candidates/${CANDIDATE_ID}`)

    expect(await screen.findByText('Unknown')).toBeInTheDocument() // serial
    expect(screen.getAllByText('Corroborating')).toHaveLength(2)
    expect(screen.getByText(/placeholder; treated as unknown/)).toBeInTheDocument()
    expect(screen.getByText(/1 more possible match/)).toBeInTheDocument()
    expect(screen.getByText(/never links a device automatically/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Show raw payload' }))
    expect(await screen.findByLabelText('Raw source payload')).toHaveTextContent('Cisco Systems, Inc.')
  })

  it('shows a same-serial, different-manufacturer conflict', async () => {
    mockApi(
      routes(
        makeCandidate({
          rule: 'conflict',
          conflicts: ['The serial number matches an asset from a different manufacturer.'],
          matches: [
            {
              asset_id: ASSET_ID,
              asset_name: 'sw-core-01',
              score: 10,
              keys: [{ key: 'serial_other_make', strength: 'conflicting', value: 'FOC2233X0AB (HP)' }],
              category_agrees: true,
              manufacturer_agrees: false,
            },
          ],
        }),
      ),
    )
    renderApp(`/discovery/candidates/${CANDIDATE_ID}`)

    const table = (await screen.findByText('sw-core-01', { selector: 'a' })).closest('table')!
    expect(within(table).getByText('Conflicting')).toBeInTheDocument()
    expect(within(table).getByText(/Same serial, different manufacturer/)).toBeInTheDocument()
    expect(within(table).getByText('Differs')).toBeInTheDocument()
    expect(within(table).getByText('Agrees')).toBeInTheDocument()
  })

  it('links to the proposed asset with a reason and If-Match', async () => {
    const { calls } = mockApi({
      ...routes(),
      [`POST /reconciliation/${CANDIDATE_ID}/approve/`]: {
        body: makeCandidate({ status: 'linked', decided_by: 'admin.one', decision_reason: 'Same switch', resulting_asset: { id: ASSET_ID, name: 'sw-core-01' }, version: 3 }),
      },
    })
    renderApp(`/discovery/candidates/${CANDIDATE_ID}`)

    const panel = (await screen.findByRole('heading', { name: 'Decision' })).closest('section')!
    expect(within(panel).getByLabelText('Asset')).toHaveValue(ASSET_ID)
    fireEvent.click(within(panel).getByRole('button', { name: 'Link device' }))
    expect(within(panel).getByRole('alert')).toHaveTextContent('Reason')

    fireEvent.change(within(panel).getByLabelText('Reason'), { target: { value: 'Same switch' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Link device' }))

    expect(await screen.findByText('Linked')).toBeInTheDocument()
    const call = calls.find((c) => c.path.endsWith('/approve/'))!
    expect(call.headers['If-Match']).toBe('"2"')
    expect(call.body).toEqual({ action: 'link', asset: ASSET_ID, reason: 'Same switch' })
  })

  it('creates a new asset with the suggested category', async () => {
    const { calls } = mockApi({
      ...routes(makeCandidate({ rule: 'new_device', matches: [], proposed_asset: null, hidden_match_count: 0 })),
      [`POST /reconciliation/${CANDIDATE_ID}/approve/`]: { body: makeCandidate({ status: 'created', version: 3 }) },
    })
    renderApp(`/discovery/candidates/${CANDIDATE_ID}`)

    const panel = (await screen.findByRole('heading', { name: 'Decision' })).closest('section')!
    expect(within(panel).getByRole('radio', { name: 'Create a new asset' })).toBeChecked()
    await within(panel).findByRole('option', { name: /Switch/ })
    expect(within(panel).getByLabelText('Category')).toHaveValue(CAT_SWITCH.id)
    fireEvent.change(within(panel).getByLabelText('Reason'), { target: { value: 'New core switch' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Create asset' }))

    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/approve/'))?.body).toEqual({
        action: 'create',
        reason: 'New core switch',
        category: CAT_SWITCH.id,
        business_status: 'deployed',
      }),
    )
  })

  it('reports a version conflict from a concurrent decision', async () => {
    mockApi({
      ...routes(),
      [`POST /reconciliation/${CANDIDATE_ID}/reject/`]: apiError(409, 'CANDIDATE_CLOSED', 'This candidate has already been decided.'),
    })
    renderApp(`/discovery/candidates/${CANDIDATE_ID}`)

    const panel = (await screen.findByRole('heading', { name: 'Decision' })).closest('section')!
    fireEvent.click(within(panel).getByRole('radio', { name: /Reject/ }))
    fireEvent.change(within(panel).getByLabelText('Reason'), { target: { value: 'Lab equipment' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Reject device' }))

    expect(await within(panel).findByText('This candidate has already been decided.')).toBeInTheDocument()
  })
})

describe('Asset source evidence', () => {
  const conflict: FieldConflict = {
    id: 'c1', asset: { id: ASSET_ID, name: 'sw-core-01' }, field: 'os_version', current_value: '17.9.5a',
    observed_value: '17.12.1', reason: 'locked', instance: INSTANCE, observation: OBS_ID,
    observed_at: '2026-11-02T08:00:00Z', status: 'open', created_at: '2026-11-02T08:00:00Z',
    modified_at: '2026-11-02T08:00:00Z', resolved_by: null, resolved_at: null, resolution_reason: '',
  }
  const evidence: AssetEvidence = {
    field_evidence: ['manufacturer', 'model', 'serial_number', 'os_name', 'os_version', 'firmware_version'].map((field) => ({
      field,
      value: field === 'os_version' ? '17.9.5a' : field === 'firmware_version' ? '17.9.3' : 'x',
      provenance:
        field === 'os_version'
          ? { kind: 'manual', instance: null, observed_at: null, recorded_at: '2026-11-02T07:00:00Z', recorded_by: 'hq.engineer' }
          : { kind: 'discovery', instance: INSTANCE, observed_at: '2026-11-02T08:00:00Z', recorded_at: '2026-11-02T08:00:00Z', recorded_by: null },
      lock: field === 'os_version' ? { locked_by: 'hq.engineer', locked_at: '2026-11-02T07:00:00Z', reason: 'Manual edit' } : null,
      sources: [
        {
          instance: INSTANCE,
          external_id: '317',
          value: field === 'os_version' ? '17.12.1' : field === 'firmware_version' ? '17.9.4' : 'x',
          observed_at: '2026-11-02T08:00:00Z',
          link_status: 'active',
          differs: field === 'os_version' || field === 'firmware_version',
        },
      ],
      open_conflicts: field === 'os_version' ? [conflict] : [],
    })),
    links: [
      {
        id: 'l1', instance: INSTANCE, external_id: '317', status: 'active', method: 'approved_candidate',
        first_seen_at: '2026-11-01T08:00:00Z', last_seen_at: '2026-11-02T08:00:00Z', last_observation_id: OBS_ID,
        linked_at: '2026-11-01T08:00:00Z', linked_by: 'admin.one', unlinked_at: null, unlinked_by: null, unlink_reason: '',
      },
    ],
    merges: [],
  }
  const routes = {
    'GET /auth/me/': { body: makeMe() },
    [`GET /assets/${ASSET_ID}/`]: { body: makeAsset({ observation_status: 'recently_seen' }) },
    [`GET /assets/${ASSET_ID}/evidence/`]: { body: evidence },
    [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
  }

  it('shows provenance, lock, differing sources and a conflict to resolve', async () => {
    const { calls } = mockApi({
      ...routes,
      'POST /discovery/conflicts/c1/resolve/': { body: { ...conflict, status: 'accepted' } },
    })
    renderApp(`/assets/${ASSET_ID}?tab=evidence`)

    const row = (await screen.findByRole('rowheader', { name: 'OS version' })).closest('tr')!
    expect(within(row).getByText('Locked')).toBeInTheDocument()
    expect(within(row).getByText('Manual')).toBeInTheDocument()
    expect(within(row).getByText('Differs')).toBeInTheDocument()
    expect(within(row).getByText(/Conflict: NMS HQ reports/)).toBeInTheDocument()
    expect(screen.getByText('Approved match')).toBeInTheDocument()

    fireEvent.click(within(row).getByRole('button', { name: 'Accept' }))
    const dialog = screen.getByRole('dialog', { name: 'Accept reported OS version?' })
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Upgrade confirmed' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Accept reported value' }))

    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/resolve/'))?.body).toEqual({
        resolution: 'accept_observed',
        reason: 'Upgrade confirmed',
      }),
    )
  })

  it('locks a field with a reason', async () => {
    const { calls } = mockApi({ ...routes, [`POST /assets/${ASSET_ID}/field-locks/`]: { body: evidence } })
    renderApp(`/assets/${ASSET_ID}?tab=evidence`)

    fireEvent.click(await screen.findByRole('button', { name: 'Lock Firmware' }))
    const dialog = screen.getByRole('dialog', { name: 'Lock Firmware?' })
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Verified on console' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Lock field' }))

    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/field-locks/'))?.body).toEqual({
        field: 'firmware_version',
        reason: 'Verified on console',
      }),
    )
  })

  it('hides the evidence tab without discovery.view', async () => {
    mockApi({
      'GET /auth/me/': { body: assetOperatorMe() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
    })
    renderApp(`/assets/${ASSET_ID}`)

    await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.queryByRole('tab', { name: 'Source evidence' })).not.toBeInTheDocument()
  })
})

describe('Integrations admin', () => {
  it('marks planned sources and creates an integration', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /integrations/': { body: [] },
      'GET /discovery/sources/': {
        body: [
          { code: 'librenms', name: 'LibreNMS', kind: 'network', availability: 'planned', description: '', instance_count: 0 },
          { code: 'fixture', name: 'Sanitized fixture import', kind: 'import', availability: 'available', description: 'Loads JSON', instance_count: 0 },
        ],
      },
      'GET /discovery/field-authority/': {
        body: { precedence: { os_name: ['librenms', 'fixture'] }, version: 1, modified_at: '2026-11-02T08:00:00Z', modified_by: null },
      },
      'GET /sites/': { body: [SITE_HQ] },
      'POST /integrations/': { status: 201, body: integration },
    })
    renderApp('/admin/integrations')

    expect(await screen.findByText('No integrations configured.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add integration' }))
    const dialog = screen.getByRole('dialog', { name: 'Add integration' })
    fireEvent.change(within(dialog).getByLabelText('Source type'), { target: { value: 'librenms' } })
    expect(within(dialog).getByText(/will not synchronise/)).toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'LibreNMS HQ' } })
    await within(dialog).findByRole('option', { name: /HQ — Headquarters/ })
    fireEvent.change(within(dialog).getByLabelText('Default site'), { target: { value: SITE_HQ.id } })
    fireEvent.change(within(dialog).getByLabelText('Base URL'), { target: { value: 'https://librenms.corp.example' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add integration' }))

    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
        source: 'librenms',
        name: 'LibreNMS HQ',
        default_site: SITE_HQ.id,
        base_url: 'https://librenms.corp.example',
        auto_link_strong_matches: false,
        is_enabled: true,
        stale_after_hours: 48,
      }),
    )
  })

  it('offers Microsoft Intune with a fixed Graph endpoint and a weekly stale default', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /integrations/': { body: [] },
      'GET /discovery/sources/': {
        body: [
          {
            code: 'intune',
            name: 'Microsoft Intune',
            kind: 'endpoint',
            availability: 'beta',
            description: 'Microsoft Graph v1.0 managedDevices (GET only)',
            instance_count: 0,
          },
        ],
      },
      'GET /discovery/field-authority/': {
        body: { precedence: {}, version: 1, modified_at: '2026-11-02T08:00:00Z', modified_by: null },
      },
      'GET /sites/': { body: [SITE_HQ] },
      'POST /integrations/': { status: 201, body: integration },
    })
    renderApp('/admin/integrations')

    const addIntegration = await screen.findByRole('button', { name: 'Add integration' })
    await waitFor(() => expect(addIntegration).toBeEnabled())
    fireEvent.click(addIntegration)
    const dialog = screen.getByRole('dialog', { name: 'Add integration' })
    expect(within(dialog).getByRole('option', { name: 'Microsoft Intune (beta)' })).toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Source type'), { target: { value: 'intune' } })
    expect(within(dialog).queryByLabelText('Base URL')).not.toBeInTheDocument()
    expect(within(dialog).getByText('https://graph.microsoft.com')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Stale after (hours)')).toHaveValue('168')
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Intune' } })
    await within(dialog).findByRole('option', { name: /HQ — Headquarters/ })
    fireEvent.change(within(dialog).getByLabelText('Default site'), { target: { value: SITE_HQ.id } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add integration' }))

    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
        source: 'intune',
        name: 'Intune',
        stale_after_hours: 168,
      }),
    )
  })
})

describe('Queue triage (Task 011)', () => {
  const second = () =>
    makeCandidate({ id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2', external_id: '318', version: 5 })
  const routes = () => ({
    'GET /auth/me/': { body: makeMe() },
    'GET /integrations/': { body: [integration] },
    'GET /discovery/candidates/': { body: page([makeCandidate(), second()]) },
  })

  it('rejects selected devices in bulk with a reason and their versions', async () => {
    const { calls } = mockApi({
      ...routes(),
      'POST /reconciliation/bulk/': {
        body: [
          { id: CANDIDATE_ID, ok: true, error: '' },
          { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2', ok: false, error: 'This record was changed by someone else.' },
        ],
      },
    })
    renderApp('/discovery')

    fireEvent.click(await screen.findByLabelText('Select all shown devices that need a decision'))
    const bar = screen.getByRole('region', { name: 'Bulk actions' })
    expect(within(bar).getByText('2 selected')).toBeInTheDocument()
    fireEvent.click(within(bar).getByRole('button', { name: 'Reject…' }))
    const dialog = screen.getByRole('dialog', { name: 'Reject 2?' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }))
    expect(within(dialog).getByText('Enter a reason of at least 5 characters.')).toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Lab devices' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reject' }))

    expect(await screen.findByText(/1 of 2 updated\./)).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/reconciliation/bulk/')?.body).toEqual({
      action: 'reject',
      reason: 'Lab devices',
      items: [
        { id: CANDIDATE_ID, version: 2 },
        { id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2', version: 5 },
      ],
    })
  })

  it('assigns to me and filters by assignee, age and sort', async () => {
    const { calls } = mockApi({
      ...routes(),
      'POST /reconciliation/bulk/': { body: [{ id: CANDIDATE_ID, ok: true, error: '' }] },
    })
    renderApp('/discovery')

    const boxes = await screen.findAllByLabelText('Select sw-core-01.corp.example')
    fireEvent.click(boxes[0])
    fireEvent.click(screen.getByRole('button', { name: 'Assign to me' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/reconciliation/bulk/')?.body).toEqual({
        action: 'assign',
        assignee: '00000000-0000-4000-8000-000000000001',
        items: [{ id: CANDIDATE_ID, version: 2 }],
      }),
    )

    fireEvent.change(screen.getByLabelText('Assignee'), { target: { value: 'none' } })
    fireEvent.change(screen.getByLabelText('Waiting'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'oldest' } })
    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/discovery/candidates/').at(-1)!
      expect(last.search.get('assignee')).toBe('none')
      expect(last.search.get('older_than_days')).toBe('7')
      expect(last.search.get('ordering')).toBe('oldest')
    })
  })

  it('offers no selection or bulk actions without decide permission', async () => {
    mockApi({ ...routes(), 'GET /auth/me/': { body: makeMe({ permissions: ['discovery.view', 'assets.view'] }) } })
    renderApp('/discovery')

    expect(await screen.findAllByText('sw-core-01.corp.example')).toHaveLength(2)
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })

  it('links and reclassifies in one decision', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /discovery/candidates/${CANDIDATE_ID}/`]: { body: makeCandidate() },
      'GET /asset-categories/': { body: CATEGORIES },
      [`POST /reconciliation/${CANDIDATE_ID}/approve/`]: { body: makeCandidate({ status: 'linked' }) },
    })
    renderApp(`/discovery/candidates/${CANDIDATE_ID}`)

    const panel = (await screen.findByRole('heading', { name: 'Decision' })).closest('section')!
    fireEvent.click(within(panel).getByLabelText(/Also change the asset.s category to Switch/))
    fireEvent.change(within(panel).getByLabelText('Reason'), { target: { value: 'Same switch' } })
    fireEvent.click(within(panel).getByRole('button', { name: 'Link device' }))

    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
        action: 'link',
        asset: ASSET_ID,
        reason: 'Same switch',
        reclassify: true,
        category: CAT_SWITCH.id,
      }),
    )
  })
})

describe('Category reviews (Task 011)', () => {
  const REVIEW_ID = 'cccccccc-cccc-4ccc-8ccc-ccccccccccc1'
  const review: CategoryReview = {
    id: REVIEW_ID,
    asset: { id: ASSET_ID, name: 'LT-0042', site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' } },
    instance: INSTANCE,
    external_id: '301',
    observation_id: OBS_ID,
    current_category: { id: 'c-desktop', name: 'Desktop', path: 'Workstations / Desktop' },
    suggested_category: { id: 'c-laptop', name: 'Laptop', path: 'Workstations / Laptop' },
    reported_type: 'laptop',
    kind: 'different_type',
    status: 'open',
    resolved_by: null,
    resolved_at: null,
    resolution_reason: '',
    created_at: '2026-11-02T08:00:00Z',
    modified_at: '2026-11-02T08:00:00Z',
    version: 3,
  }
  const impact = (missing: string[] = []) => ({
    from_category: 'Workstations / Desktop',
    to_category: 'Workstations / Laptop',
    fields_added: [{ key: 'battery_model', label: 'Battery model', required: missing.length > 0 }],
    fields_kept: [],
    values_retained_read_only: [],
    required_missing: missing,
  })

  it('reclassifies after showing the template impact', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /discovery/category-reviews/': { body: page([review]) },
      [`POST /assets/${ASSET_ID}/classification/preview/`]: { body: impact() },
      [`POST /discovery/category-reviews/${REVIEW_ID}/reclassify/`]: { body: { ...review, status: 'reclassified' } },
    })
    renderApp('/discovery?tab=categories')

    const table = await screen.findByRole('region', { name: 'Category reviews' })
    expect(await within(table).findByText('Workstations / Laptop')).toBeInTheDocument()
    expect(within(table).getByText('Different type')).toBeInTheDocument()
    fireEvent.click(within(table).getByRole('button', { name: /Reclassify… LT-0042/ }))
    const dialog = screen.getByRole('dialog', { name: 'Reclassify LT-0042?' })
    expect(await within(dialog).findByText('Adds fields: Battery model')).toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Confirmed laptop' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change to Laptop' }))

    await waitFor(() => {
      const call = calls.find((c) => c.path.endsWith('/reclassify/'))!
      expect(call.headers['If-Match']).toBe('"3"')
      expect(call.body).toEqual({ reason: 'Confirmed laptop' })
    })
  })

  it('sends the reviewer to the asset when required fields are missing', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /discovery/category-reviews/': { body: page([review]) },
      [`POST /assets/${ASSET_ID}/classification/preview/`]: { body: impact(['battery_model']) },
    })
    renderApp('/discovery?tab=categories')

    fireEvent.click(await screen.findByRole('button', { name: /Reclassify… LT-0042/ }))
    const dialog = screen.getByRole('dialog', { name: 'Reclassify LT-0042?' })
    expect(await within(dialog).findByRole('link', { name: 'Change category on the asset' })).toHaveAttribute(
      'href',
      `/assets/${ASSET_ID}`,
    )
    expect(within(dialog).getByRole('button', { name: 'Change to Laptop' })).toBeDisabled()
  })

  it('keeps the current category with a reason', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /discovery/category-reviews/': { body: page([review]) },
      [`POST /discovery/category-reviews/${REVIEW_ID}/dismiss/`]: { body: { ...review, status: 'dismissed' } },
    })
    renderApp('/discovery?tab=categories')

    fireEvent.click(await screen.findByRole('button', { name: /Keep current… category of LT-0042/ }))
    const dialog = screen.getByRole('dialog', { name: 'Keep Desktop for LT-0042?' })
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Docked laptop as desktop' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep current category' }))
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith('/dismiss/'))?.body).toEqual({ reason: 'Docked laptop as desktop' }),
    )
  })
})

describe('Data-quality queues (Task 011)', () => {
  const FINDING_ID = 'dddddddd-dddd-4ddd-8ddd-ddddddddddd1'
  const finding: QualityFinding = {
    id: FINDING_ID,
    kind: 'duplicate_candidate',
    asset: { id: ASSET_ID, name: 'sw-a', site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' } },
    severity: 'high',
    summary: 'Same manufacturer and serial (Cisco FOC1) as 1 other asset(s).',
    evidence: { match: 'manufacturer_serial', value: 'Cisco FOC1', assets: [{ id: 'other-asset', name: 'sw-b' }] },
    status: 'open',
    assignee: null,
    assigned_at: null,
    detected_at: '2026-11-03T08:00:00Z',
    last_confirmed_at: '2026-11-04T08:00:00Z',
    resolved_at: null,
    resolved_by: null,
    resolution_reason: '',
    version: 1,
  }
  const summary = [
    { kind: 'duplicate_candidate', open: 2, high: 2 },
    { kind: 'model_unknown', open: 5, high: 0 },
    { kind: 'source_stale', open: 0, high: 0 },
    { kind: 'owner_missing', open: 1, high: 0 },
  ]

  it('shows queues with counts, evidence, assignment and dismissal', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /quality/summary/': { body: summary },
      'GET /quality/findings/': { body: page([finding]) },
      [`POST /quality/findings/${FINDING_ID}/assign/`]: { body: { ...finding, version: 2 } },
      [`POST /quality/findings/${FINDING_ID}/dismiss/`]: { body: { ...finding, status: 'dismissed' } },
    })
    renderApp('/discovery?tab=quality')

    const queues = await screen.findByRole('navigation', { name: 'Data-quality queues' })
    expect(await within(queues).findByRole('button', { name: /Model unknown 5/ })).toBeInTheDocument()
    const table = screen.getByRole('region', { name: 'Data-quality findings' })
    expect(await within(table).findByText(/Same manufacturer and serial/)).toBeInTheDocument()
    expect(within(table).getByRole('link', { name: 'sw-b' })).toHaveAttribute('href', '/assets/other-asset')
    expect(within(table).getByText('High')).toBeInTheDocument()

    fireEvent.click(within(table).getByRole('button', { name: 'Assign to me sw-a' }))
    await waitFor(() => {
      const call = calls.find((c) => c.path.endsWith('/assign/'))!
      expect(call.body).toEqual({ assignee: '00000000-0000-4000-8000-000000000001' })
      expect(call.headers['If-Match']).toBe('"1"')
    })

    fireEvent.click(within(table).getByRole('button', { name: 'Dismiss… sw-a' }))
    const dialog = screen.getByRole('dialog', { name: 'Dismiss finding for sw-a?' })
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Spare chassis, same serial by design' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Dismiss' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/dismiss/'))).toBe(true))

    fireEvent.click(within(queues).getByRole('button', { name: /Model unknown 5/ }))
    await waitFor(() =>
      expect(calls.filter((c) => c.path === '/quality/findings/').at(-1)?.search.get('kind')).toBe('model_unknown'),
    )
  })

  it('is read-only without decide permission', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe({ permissions: ['discovery.view', 'assets.view'] }) },
      'GET /quality/summary/': { body: summary },
      'GET /quality/findings/': { body: page([finding]) },
    })
    renderApp('/discovery?tab=quality')

    expect(await screen.findByText(/Same manufacturer and serial/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Assign to me/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Re-check now' })).not.toBeInTheDocument()
  })
})
