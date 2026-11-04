import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  LicenseAllocation,
  LicenseSnapshot,
  LicenseSubscription,
  LicenseSubscriptionDetail,
} from '../../shared/api/types'
import { makeIntegration, makeMe, mockApi, page, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const SKU_ROW = '66666666-6666-4666-8666-666666666601'
const INSTANCE = {
  id: '99999999-9999-4999-8999-999999999903',
  name: 'Microsoft 365',
  last_success_at: '2026-11-02T08:00:00Z',
  stale_after_hours: 48,
}
const LICENSE_ME = () => makeMe({ permissions: ['licenses.view'] })

function snapshot(overrides: Partial<LicenseSnapshot> = {}): LicenseSnapshot {
  return {
    id: '77777777-7777-4777-8777-777777777701',
    taken_at: '2026-11-02T08:00:00Z',
    last_confirmed_at: '2026-11-03T08:00:00Z',
    capability_status: 'Enabled',
    enabled_units: 50,
    warning_units: 0,
    suspended_units: 0,
    locked_out_units: 0,
    consumed_units: 6,
    available_units: 44,
    assigned_users: 6,
    direct_users: 4,
    group_users: 3,
    ...overrides,
  }
}

function subscription(overrides: Partial<LicenseSubscription> = {}): LicenseSubscription {
  return {
    id: SKU_ROW,
    instance: INSTANCE,
    tenant_id: '6d1f0c2e-5a7b-4c3d-9e8f-0a1b2c3d4e5f',
    sku_id: '5a1b0000-0000-4000-8000-0000000000e3',
    sku_part_number: 'SPE_E3',
    applies_to: 'User',
    capability_status: 'Enabled',
    subscribed: true,
    first_seen_at: '2026-11-02T08:00:00Z',
    last_seen_at: '2026-11-03T08:00:00Z',
    missing_since: null,
    freshness: 'fresh',
    latest: snapshot(),
    ...overrides,
  }
}

function detail(): LicenseSubscriptionDetail {
  return {
    ...subscription(),
    service_plans: ['EXCHANGE_S_ENTERPRISE', 'TEAMS1'],
    snapshots: [snapshot({ id: 's2', enabled_units: 75, taken_at: '2026-11-03T08:00:00Z' }), snapshot()],
  }
}

function allocation(overrides: Partial<LicenseAllocation> = {}): LicenseAllocation {
  return {
    id: 'a1',
    sku: { id: SKU_ROW, sku_id: '5a1b0000-0000-4000-8000-0000000000e3', sku_part_number: 'SPE_E3' },
    user: {
      id: 'u1',
      object_id: 'c0000000-0000-4000-8000-000000000003',
      user_principal_name: 'cleo@contoso.example',
      display_name: 'Cleo',
      account_enabled: true,
    },
    method: 'direct_and_group',
    assigned_directly: true,
    group_ids: ['9a000000-0000-4000-8000-00000000000a'],
    groups: [{ id: '9a000000-0000-4000-8000-00000000000a', display_name: 'Licensing - Sales' }],
    state: 'Active',
    paths: [],
    first_seen_at: '2026-11-02T08:00:00Z',
    last_seen_at: '2026-11-03T08:00:00Z',
    changed_at: '2026-11-02T08:00:00Z',
    ended_at: null,
    ...overrides,
  }
}

describe('Licenses', () => {
  it('lists subscriptions with tenant, ITAM and available counts kept apart', async () => {
    mockApi({
      'GET /auth/me/': { body: LICENSE_ME() },
      'GET /licenses/subscriptions/': {
        body: [
          subscription(),
          subscription({
            id: 'x2',
            sku_part_number: 'POWER_BI_PRO',
            capability_status: 'Warning',
            latest: snapshot({ capability_status: 'Warning', warning_units: 10, assigned_users: null }),
          }),
        ],
      },
    })
    renderApp('/licenses')

    const table = await screen.findByRole('region', { name: 'Microsoft 365 subscriptions' })
    const e3 = (await within(table).findByRole('link', { name: 'SPE_E3' })).closest('tr')!
    expect(within(e3).getByText('50')).toBeInTheDocument()
    expect(within(e3).getByText('44')).toBeInTheDocument()
    expect(within(table).getByRole('columnheader', { name: 'Assigned users (ITAM)' })).toBeInTheDocument()
    const pbi = within(table).getByRole('link', { name: 'POWER_BI_PRO' }).closest('tr')!
    expect(within(pbi).getByText('Warning')).toBeInTheDocument()
    expect(within(pbi).getByText('Unknown')).toBeInTheDocument() // count not available
    expect(screen.getByText(/not a billing agreement and not a license compliance/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Licenses' })).toHaveAttribute('href', '/licenses')
  })

  it('shows a SKU drilldown with history and filterable assignments', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: LICENSE_ME() },
      [`GET /licenses/subscriptions/${SKU_ROW}/`]: { body: detail() },
      'GET /licenses/allocations/': { body: page([allocation()]) },
    })
    renderApp(`/licenses/subscriptions/${SKU_ROW}`)

    expect(await screen.findByRole('heading', { name: 'SPE_E3' })).toBeInTheDocument()
    const history = screen.getByRole('region', { name: 'Quantity history' })
    expect(within(history).getByText('75')).toBeInTheDocument()
    const assigned = await screen.findByRole('region', { name: /Assigned users/ })
    expect(await within(assigned).findByText('Cleo')).toBeInTheDocument()
    expect(within(assigned).getByRole('cell', { name: /Direct and group/ })).toHaveTextContent('Licensing - Sales')

    fireEvent.change(within(assigned).getByLabelText('Assignment'), { target: { value: 'group' } })
    const allocationCalls = () => calls.filter((c) => c.path === '/licenses/allocations/')
    await waitFor(() => expect(allocationCalls().some((c) => c.search.get('method') === 'group')).toBe(true))
    expect(allocationCalls().every((c) => c.search.get('sku') === SKU_ROW)).toBe(true)
  })

  it('is not offered to users without licenses.view', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe({ permissions: ['assets.view'] }) } })
    renderApp('/')

    expect(await screen.findByRole('link', { name: 'Assets' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Licenses' })).not.toBeInTheDocument()
  })

  it('shows the Microsoft 365 integration permissions', async () => {
    const ID = '99999999-9999-4999-8999-999999999901'
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /integrations/${ID}/`]: {
        body: makeIntegration({
          name: 'Microsoft 365',
          has_adapter: true,
          source: {
            code: 'm365',
            name: 'Microsoft 365 / Entra',
            kind: 'directory',
            availability: 'beta',
            description: '',
            instance_count: 1,
          },
          base_url: 'https://graph.microsoft.com',
          auth_scheme: 'client_certificate',
          connector: {
            auth_schemes: ['client_certificate', 'client_secret'],
            supports_evidence: false,
            fixed_base_url: 'https://graph.microsoft.com',
            required_settings: ['tenant_id', 'client_id'],
            permissions: ['Organization.Read.All', 'User.Read.All'],
            uses_source_timezone: false,
            uses_detail_refresh: false, supports_software: false,
          },
          capabilities: { subscribed_skus: true, license_assignments: true, group_names: false },
        }),
      },
      [`GET /integrations/${ID}/runs/`]: { body: page([]) },
    })
    renderApp(`/admin/integrations/${ID}`)

    const perms = await screen.findByRole('region', { name: 'Required permissions' })
    expect(within(perms).getByText('Organization.Read.All')).toBeInTheDocument()
    expect(within(perms).getByText('User.Read.All')).toBeInTheDocument()
    const caps = screen.getByRole('region', { name: 'API capabilities' })
    expect(within(caps).getByText('Group names (optional GroupMember.Read.All)').parentElement).toHaveTextContent('Not available')
    const health = screen.getByRole('region', { name: 'Health' })
    expect(within(health).getByText('Licensed users in last run')).toBeInTheDocument()
    expect(within(health).queryByText('Assets matched')).not.toBeInTheDocument()
    expect(within(health).getByRole('link', { name: 'Licenses' })).toHaveAttribute('href', '/licenses')
  })
})
