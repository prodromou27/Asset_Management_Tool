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
export type Candidate = Schemas['Candidate']
export type CandidateMatch = Schemas['Match']
export type DiscoverySource = Schemas['DiscoverySource']
export type IntegrationInstance = Schemas['IntegrationInstance']
export type IntegrationWrite = Schemas['IntegrationInstanceWriteRequest']
export type SyncRun = Schemas['SyncRun']
export type SyncRunSummary = Schemas['SyncRunSummary']
export type ConnectionTest = Schemas['ConnectionTest']
export type NeighborEvidence = Schemas['NeighborEvidence']
export type EndpointSecurityState = Schemas['EndpointSecurityState']
export type LicenseSubscription = Schemas['Subscription']
export type LicenseSubscriptionDetail = Schemas['SubscriptionDetail']
export type LicenseSnapshot = Schemas['Snapshot']
export type LicenseAllocation = Schemas['Allocation']
export type CategoryReview = Schemas['CategoryReview']
export type BulkResult = Schemas['BulkResult']
export type Assignee = Schemas['Assignee']
export type QualityFinding = Schemas['Finding']
export type QualitySummaryRow = Schemas['SummaryRow']
export type AssetGroup = Schemas['Group']
export type AssetGroupWrite = Schemas['PatchedGroupWriteRequest']
export type GroupMembership = Schemas['Membership']
export type GroupRuleVersion = Schemas['RuleVersion']
export type GroupPreview = Schemas['Preview']
export type RuleField = Schemas['RuleField']
export type AssetGroupRef = Schemas['AssetGroupRef']
export type ImportJob = Schemas['JobDetail']
export type ImportJobSummary = Schemas['Job']
export type ImportRow = Schemas['Row']
export type ImportTemplate = Schemas['Template']
export type FieldConflict = Schemas['FieldConflict']
export type AssetEvidence = Schemas['AssetEvidence']
export type FieldEvidence = Schemas['FieldEvidence']
export type SourceLink = Schemas['SourceLink']
export type AssetMerge = Schemas['AssetMerge']
export type ObservationDetail = Schemas['ObservationDetail']
export type FieldAuthorityPolicy = Schemas['FieldAuthorityPolicy']
export type SavedView = Schemas['SavedView']
export type SavedViewWrite = Schemas['SavedViewWriteRequest']
export type AssetColumn = NonNullable<SavedViewWrite['columns']>[number]
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
  assetsEditTechnical: 'assets.edit_technical',
  assetsMerge: 'assets.merge',
  discoveryView: 'discovery.view',
  reconciliationDecide: 'reconciliation.decide',
  integrationsManage: 'integrations.manage',
  licensesView: 'licenses.view',
  groupsView: 'groups.view',
  groupsManage: 'groups.manage',
  groupsMembers: 'groups.members',
  importsRun: 'imports.run',
} as const
