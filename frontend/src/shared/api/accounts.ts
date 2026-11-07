import { apiGet, apiRequest } from './client'
import { configureDisplay } from '../format'
import type {
  AuthProvider,
  Authorization,
  AuditEvent,
  Me,
  Paginated,
  Role,
  SecuritySettings,
  SecuritySettingsUpdate,
  User,
  UserCreate,
  UserUpdate,
} from './types'

export const queryKeys = {
  me: ['auth', 'me'] as const,
  users: (filters: UserFilters) => ['users', 'list', filters] as const,
  user: (id: string) => ['users', 'detail', id] as const,
  roles: ['roles'] as const,
  audit: (filters: AuditFilters) => ['audit', filters] as const,
  security: ['settings', 'security'] as const,
}

// --- Auth ---------------------------------------------------------------------

export const fetchCsrf = () => apiRequest<void>('GET', '/auth/csrf/')
export const fetchAuthProviders = () => apiGet<AuthProvider[]>('/auth/providers/')
export async function startEntra(next_path: string) {
  await fetchCsrf()
  return apiRequest<Authorization>('POST', '/auth/entra/start/', { body: { next_path } })
}
export const bindEntra = (id: string, version: number, tenant_id: string | null, object_id: string | null) =>
  apiRequest<User>('PATCH', `/users/${id}/entra/`, { body: { tenant_id, object_id }, ifMatch: version })
export async function fetchMe() {
  const me = await apiGet<Me>('/auth/me/')
  configureDisplay(me.display_preferences)
  return me
}

export async function login(username: string, password: string): Promise<Me> {
  await fetchCsrf()
  const me = await apiRequest<Me>('POST', '/auth/local/login/', { body: { username, password } })
  configureDisplay(me.display_preferences)
  return me
}

export const logout = () => apiRequest<void>('POST', '/auth/logout/')

export const changePassword = (current_password: string, new_password: string) =>
  apiRequest<void>('POST', '/auth/password/change/', { body: { current_password, new_password } })

// --- Users --------------------------------------------------------------------

export interface UserFilters {
  q?: string
  status?: string
  role?: string
}

export const fetchUsers = (filters: UserFilters, cursor?: string) =>
  apiGet<Paginated<User>>('/users/', { ...filters, cursor })

export const fetchUser = (id: string) => apiGet<User>(`/users/${id}/`)
export const createUser = (body: UserCreate) => apiRequest<User>('POST', '/users/', { body })
export const updateUser = (id: string, version: number, body: UserUpdate) =>
  apiRequest<User>('PATCH', `/users/${id}/`, { body, ifMatch: version })
export const disableUser = (id: string, reason: string) =>
  apiRequest<User>('POST', `/users/${id}/disable/`, { body: { reason } })
export const enableUser = (id: string) => apiRequest<User>('POST', `/users/${id}/enable/`)
export const unlockUser = (id: string) => apiRequest<User>('POST', `/users/${id}/unlock/`)
export const resetUserPassword = (id: string, password: string) =>
  apiRequest<User>('POST', `/users/${id}/reset-password/`, { body: { password } })

export const fetchRoles = () => apiGet<Role[]>('/roles/')

// --- Audit --------------------------------------------------------------------

export interface AuditFilters {
  action?: string
  actor?: string
  outcome?: string
  object_id?: string
}

export const fetchAuditEvents = (filters: AuditFilters, cursor?: string) =>
  apiGet<Paginated<AuditEvent>>('/audit/events/', { ...filters, cursor })

// --- Security settings --------------------------------------------------------

export const fetchSecuritySettings = () => apiGet<SecuritySettings>('/settings/security/')
export const updateSecuritySettings = (version: number, body: SecuritySettingsUpdate) =>
  apiRequest<SecuritySettings>('PATCH', '/settings/security/', { body, ifMatch: version })
