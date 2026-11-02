import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'
import { AppRoutes } from '../app/App'
import { createQueryClient } from '../app/queryClient'
import type { AuditEvent, Me, Role, SecuritySettings, User } from '../shared/api/types'

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
  'audit.view',
  'roles.view',
  'settings.security.manage',
  'settings.security.view',
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
