import { apiGet, apiRequest } from './client'
import type {
  AssetGroup,
  AssetGroupRef,
  AssetGroupWrite,
  GroupMembership,
  GroupPreview,
  GroupRuleVersion,
  Paginated,
  RuleField,
} from './types'

/** Rule tree (docs/03): and/or/not combinators over typed conditions. */
export type RuleNode =
  | { op: 'and' | 'or'; rules: RuleNode[] }
  | { op: 'not'; rule: RuleNode }
  | { field: string; operator: string; value: unknown }

export const groupKeys = {
  all: ['groups'] as const,
  list: ['groups', 'list'] as const,
  detail: (id: string) => ['groups', 'detail', id] as const,
  members: (id: string, history: boolean, q: string) => ['groups', 'members', id, history, q] as const,
  versions: (id: string) => ['groups', 'versions', id] as const,
  fields: ['groups', 'fields'] as const,
  forAsset: (assetId: string) => ['groups', 'asset', assetId] as const,
}

export const fetchGroups = () => apiGet<AssetGroup[]>('/groups/')
export const fetchGroup = (id: string) => apiGet<AssetGroup>(`/groups/${id}/`)
export const createGroup = (body: AssetGroupWrite & { name: string; kind: 'static' | 'dynamic' }) =>
  apiRequest<AssetGroup>('POST', '/groups/', { body })
export const updateGroup = (id: string, version: number, body: AssetGroupWrite) =>
  apiRequest<AssetGroup>('PATCH', `/groups/${id}/`, { body, ifMatch: version })
export const archiveGroup = (id: string, version: number, reason: string) =>
  apiRequest<void>('POST', `/groups/${id}/archive/`, { body: { reason }, ifMatch: version })
export const previewRule = (rule: RuleNode) => apiRequest<GroupPreview>('POST', '/groups/preview/', { body: { rule } })
export const previewGroupRule = (id: string, rule: RuleNode) =>
  apiRequest<GroupPreview>('POST', `/groups/${id}/preview/`, { body: { rule } })
export const fetchGroupMembers = (id: string, history: boolean, q: string, cursor?: string) =>
  apiGet<Paginated<GroupMembership>>(`/groups/${id}/assets/`, {
    ...(history ? { history: 'true' } : {}),
    ...(q ? { q } : {}),
    cursor,
  })
export const changeGroupMembers = (id: string, body: { add?: string[]; remove?: string[]; reason?: string }) =>
  apiRequest<{ added: number; removed: number }>('POST', `/groups/${id}/members/`, { body })
export const evaluateGroup = (id: string) =>
  apiRequest<{ added: number; removed: number; members: number }>('POST', `/groups/${id}/evaluate/`)
export const fetchRuleVersions = (id: string) => apiGet<GroupRuleVersion[]>(`/groups/${id}/rule-versions/`)
export const fetchRuleFields = () => apiGet<RuleField[]>('/groups/fields/')
export const fetchAssetGroups = (assetId: string) => apiGet<AssetGroupRef[]>(`/assets/${assetId}/groups/`)
