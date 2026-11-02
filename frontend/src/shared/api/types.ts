import type { components } from './schema'

type Schemas = components['schemas']

export type Me = Schemas['Me']
export type User = Schemas['User']
export type UserCreate = Schemas['UserCreateRequest']
export type UserUpdate = Schemas['PatchedUserUpdateRequest']
export type Role = Schemas['Role']
export type AuditEvent = Schemas['AuditEvent']
export type SecuritySettings = Schemas['SecuritySettings']
export type SecuritySettingsUpdate = Schemas['PatchedSecuritySettingsUpdateRequest']
export type Paginated<T> = {
  items: T[]
  next_cursor: string | null
  previous_cursor: string | null
  count: number
}

export const PERMISSIONS = {
  usersView: 'users.view',
  usersManage: 'users.manage',
  rolesView: 'roles.view',
  auditView: 'audit.view',
  securityView: 'settings.security.view',
  securityManage: 'settings.security.manage',
} as const
