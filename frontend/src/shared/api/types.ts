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
export type Site = Schemas['Site']
export type Location = Schemas['Location']
export type Department = Schemas['Department']
export type AssetCategory = Schemas['AssetCategory']
export type CustomFieldDefinition = Schemas['CustomFieldDefinition']
export type AssetListItem = Schemas['AssetList']
export type AssetDetail = Schemas['AssetDetail']
export type AssetWrite = Schemas['AssetWriteRequest']
export type AssetPatch = Schemas['PatchedAssetWriteRequest']
export type AssetHistoryEntry = Schemas['AssetHistory']
export type ClassificationImpact = Schemas['ClassificationImpact']
export type UserLookup = Schemas['UserLookup']
export type FieldType = CustomFieldDefinition['field_type']
export type BusinessStatus = NonNullable<AssetWrite['business_status']>
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
  assetsView: 'assets.view',
  assetsCreate: 'assets.create',
  assetsEdit: 'assets.edit',
  assetsReclassify: 'assets.reclassify',
  assetsArchive: 'assets.archive',
  categoriesManage: 'categories.manage',
  sitesManage: 'sites.manage',
} as const
