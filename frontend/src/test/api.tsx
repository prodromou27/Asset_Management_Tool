import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { AppRoutes } from '../app/App'
import { createQueryClient } from '../app/queryClient'
import type {
  AssetCategory,
  AssetDetail,
  AuditEvent,
  CustomFieldDefinition,
  Department,
  Location,
  Me,
  Role,
  SecuritySettings,
  Site,
  User,
} from '../shared/api/types'

type Handler =
  | { status?: number; body?: unknown }
  | ((request: { url: URL; init: RequestInit; body: unknown }) => {
      status?: number
      body?: unknown
    })

export interface Recorded {
  method: string
  path: string
  search: URLSearchParams
  headers: Record<string, string>
  body: unknown
}

/** Routes fetch by "METHOD /path/" (relative to /api/v1). Unmatched calls fail loudly. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Recorded[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost')
    const method = (init.method ?? 'GET').toUpperCase()
    const path = url.pathname.replace(/^\/api\/v1/, '')
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    const headers = (init.headers ?? {}) as Record<string, string>
    calls.push({ method, path, search: url.searchParams, headers, body })

    const handler = routes[`${method} ${path}`]
    if (!handler) throw new Error(`Unmocked request: ${method} ${path}`)
    const result = typeof handler === 'function' ? handler({ url, init, body }) : handler
    const status = result.status ?? 200
    return new Response(status === 204 ? null : JSON.stringify(result.body ?? {}), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)
  return { calls, fetchMock }
}

export function apiError(status: number, code: string, message: string, fieldErrors = {}) {
  return {
    status,
    body: { error: { code, message, request_id: 'req-test-0001', field_errors: fieldErrors } },
  }
}

export function renderApp(path: string) {
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// --- Fixtures (fictitious) -------------------------------------------------------

const ALL_ADMIN = [
  'assets.archive',
  'assets.create',
  'assets.edit',
  'assets.reclassify',
  'assets.view',
  'audit.view',
  'categories.manage',
  'roles.view',
  'settings.security.manage',
  'settings.security.view',
  'sites.manage',
  'users.manage',
  'users.view',
]

export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    id: '00000000-0000-4000-8000-000000000001',
    username: 'admin.one',
    display_name: 'Admin One',
    email: 'admin.one@example.test',
    roles: [{ code: 'system_admin', name: 'System Admin' }],
    permissions: ALL_ADMIN,
    all_sites: true,
    must_change_password: false,
    ...overrides,
  }
}

export const auditorMe = () =>
  makeMe({
    id: '00000000-0000-4000-8000-000000000002',
    username: 'auditor.one',
    display_name: 'Auditor One',
    roles: [{ code: 'auditor', name: 'Auditor' }],
    permissions: ['audit.view', 'roles.view', 'settings.security.view', 'users.view'],
  })

export const operatorMe = () =>
  makeMe({
    id: '00000000-0000-4000-8000-000000000003',
    username: 'operator.one',
    display_name: 'Operator One',
    roles: [{ code: 'asset_operator', name: 'Asset Operator' }],
    permissions: [],
  })

export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    username: 'jane.doe',
    display_name: 'Jane Doe',
    email: 'jane.doe@example.test',
    roles: [{ code: 'asset_operator', name: 'Asset Operator' }],
    all_sites: false,
    sites: [],
    is_active: true,
    is_locked: false,
    locked_until: null,
    must_change_password: false,
    last_login: '2026-11-02T08:15:00Z',
    password_changed_at: '2026-11-01T10:00:00Z',
    disabled_at: null,
    disabled_by: null,
    disabled_reason: '',
    created_at: '2026-11-01T09:00:00Z',
    created_by: 'admin.one',
    modified_at: '2026-11-01T09:00:00Z',
    version: 1,
    ...overrides,
  }
}

export const ROLES: Role[] = [
  {
    code: 'asset_operator',
    name: 'Asset Operator',
    description: 'Maintains authorized business fields.',
    is_system: true,
    permissions: [],
  },
  {
    code: 'auditor',
    name: 'Auditor',
    description: 'Read-only access to evidence and audit.',
    is_system: true,
    permissions: ['audit.view'],
  },
  {
    code: 'system_admin',
    name: 'System Admin',
    description: 'Full administration.',
    is_system: true,
    permissions: ALL_ADMIN,
  },
]

export function makeSecurity(overrides: Partial<SecuritySettings> = {}): SecuritySettings {
  return {
    session_idle_timeout_minutes: 30,
    session_absolute_timeout_hours: 12,
    lockout_threshold: 5,
    lockout_duration_minutes: 15,
    password_min_length: 12,
    version: 1,
    modified_at: '2026-11-01T09:00:00Z',
    modified_by: null,
    ...overrides,
  }
}

export function makeAuditEvent(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: '22222222-2222-4222-8222-222222222222',
    occurred_at: '2026-11-02T09:30:00Z',
    actor_id: '00000000-0000-4000-8000-000000000001',
    actor_label: 'admin.one',
    action: 'users.update',
    object_type: 'user',
    object_id: '11111111-1111-4111-8111-111111111111',
    object_label: 'jane.doe',
    outcome: 'success',
    source: 'api',
    before: { roles: ['asset_operator'], display_name: 'Jane' },
    after: { roles: ['asset_operator', 'auditor'], display_name: 'Jane' },
    detail: '',
    request_id: 'req-abc-123456',
    ip_address: '127.0.0.1',
    ...overrides,
  }
}

export const page = <T,>(items: T[], next_cursor: string | null = null) => ({
  items,
  next_cursor,
  previous_cursor: null,
  count: items.length,
})

// --- Task 003 fixtures -----------------------------------------------------------

export const SITE_HQ: Site = {
  id: '33333333-3333-4333-8333-333333333301',
  code: 'HQ',
  name: 'Headquarters',
  parent: null,
  description: '',
  is_active: true,
  created_at: '2026-11-01T09:00:00Z',
  modified_at: '2026-11-01T09:00:00Z',
  version: 1,
}

export const SITE_BR: Site = { ...SITE_HQ, id: '33333333-3333-4333-8333-333333333302', code: 'BR1', name: 'Branch 1' }

export const ROOM: Location = {
  id: '44444444-4444-4444-8444-444444444401',
  site: SITE_HQ.id,
  parent: null,
  name: 'Server room',
  kind: 'room',
  is_active: true,
  created_at: '2026-11-01T09:00:00Z',
  modified_at: '2026-11-01T09:00:00Z',
  version: 1,
}

export const DEPT: Department = {
  id: '55555555-5555-4555-8555-555555555501',
  name: 'IT',
  code: '',
  is_active: true,
  created_at: '2026-11-01T09:00:00Z',
  modified_at: '2026-11-01T09:00:00Z',
  version: 1,
}

const category = (id: string, name: string, path: string, depth: number, parent: string | null): AssetCategory => ({
  id,
  code: name.toLowerCase().replace(/\W+/g, '-'),
  name,
  parent,
  path,
  depth,
  description: '',
  is_active: true,
  sort_order: 0,
  modified_at: '2026-11-01T09:00:00Z',
  version: 1,
})

export const CAT_NET = category('66666666-6666-4666-8666-666666666601', 'Networking', 'Networking', 0, null)
export const CAT_SWITCH = category('66666666-6666-4666-8666-666666666602', 'Switch', 'Networking / Switch', 1, CAT_NET.id)
export const CAT_WS = category('66666666-6666-4666-8666-666666666603', 'Workstations', 'Workstations', 0, null)
export const CAT_LAPTOP = category('66666666-6666-4666-8666-666666666604', 'Laptop', 'Workstations / Laptop', 1, CAT_WS.id)
export const CATEGORIES = [CAT_NET, CAT_SWITCH, CAT_WS, CAT_LAPTOP]

export function makeField(overrides: Partial<CustomFieldDefinition> = {}): CustomFieldDefinition {
  return {
    id: '77777777-7777-4777-8777-777777777701',
    category: CAT_SWITCH.id,
    key: 'port_count',
    label: 'Port count',
    field_type: 'integer',
    required: true,
    choices: [],
    help_text: '',
    min_value: null,
    max_value: null,
    max_length: null,
    sort_order: 0,
    is_active: true,
    version: 1,
    ...overrides,
  }
}

export const ASSET_ID = '88888888-8888-4888-8888-888888888801'

export function makeAsset(overrides: Partial<AssetDetail> = {}): AssetDetail {
  return {
    id: ASSET_ID,
    name: 'sw-core-01',
    asset_tag: 'IT-001254',
    category: { id: CAT_SWITCH.id, name: 'Switch', path: 'Networking / Switch' },
    manufacturer: 'Example Networks',
    model: 'EX-48',
    serial_number: 'SN-TEST-0001',
    primary_hostname: 'sw-core-01.corp.example',
    primary_ip: '10.10.0.2',
    site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' },
    location: { id: ROOM.id, name: 'Server room' },
    owner: null,
    business_status: 'deployed',
    observation_status: 'manual_only',
    support_status: 'unknown',
    is_archived: false,
    modified_at: '2026-11-02T09:00:00Z',
    version: 3,
    os_name: '',
    os_version: '',
    firmware_version: '17.9.4',
    department: null,
    notes: '',
    custom_fields: { port_count: 48 },
    missing_required_fields: [],
    retained_custom_fields: [],
    hostnames: [
      { id: 'h1', hostname: 'sw-core-01.corp.example', is_primary: true, source: 'manual', source_ref: '', observed_at: null },
      { id: 'h2', hostname: 'sw-core-01-mgmt', is_primary: false, source: 'librenms', source_ref: '317', observed_at: '2026-11-02T08:00:00Z' },
    ],
    interfaces: [{ id: 'i1', name: 'Vlan10', mac_address: '02:00:00:00:00:01', source: 'manual', source_ref: '', observed_at: null }],
    ip_addresses: [{ id: 'a1', address: '10.10.0.2', interface_name: 'Vlan10', is_primary: true, source: 'manual', source_ref: '', observed_at: null }],
    archived_at: null,
    archived_by: null,
    archive_reason: '',
    created_at: '2026-11-01T09:00:00Z',
    created_by: 'admin.one',
    modified_by: 'admin.one',
    ...overrides,
  }
}

export const assetOperatorMe = () =>
  makeMe({
    id: '00000000-0000-4000-8000-000000000004',
    username: 'hq.operator',
    display_name: 'HQ Operator',
    roles: [{ code: 'asset_operator', name: 'Asset Operator' }],
    permissions: ['assets.create', 'assets.edit', 'assets.view'],
    all_sites: false,
  })

export const readerMe = () =>
  makeMe({
    id: '00000000-0000-4000-8000-000000000005',
    username: 'hq.reader',
    display_name: 'HQ Reader',
    roles: [{ code: 'read_only', name: 'Read Only' }],
    permissions: ['assets.view'],
    all_sites: false,
  })
