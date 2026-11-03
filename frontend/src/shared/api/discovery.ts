import { apiGet, apiRequest } from './client'
import type {
  AssetEvidence,
  AssetMerge,
  Candidate,
  ConnectionTest,
  DiscoverySource,
  EndpointSecurityState,
  FieldAuthorityPolicy,
  FieldConflict,
  IntegrationInstance,
  IntegrationWrite,
  NeighborEvidence,
  ObservationDetail,
  Paginated,
  SourceLink,
  SyncRun,
} from './types'

export interface CandidateFilters {
  status?: string
  rule?: string
  instance?: string
}

export const discoveryKeys = {
  candidates: (filters: CandidateFilters) => ['discovery', 'candidates', filters] as const,
  candidate: (id: string) => ['discovery', 'candidate', id] as const,
  observation: (id: string) => ['discovery', 'observation', id] as const,
  conflicts: (status: string) => ['discovery', 'conflicts', status] as const,
  sources: ['discovery', 'sources'] as const,
  integrations: ['integrations'] as const,
  integration: (id: string) => ['integrations', id] as const,
  networkEvidence: (assetId: string) => ['assets', 'network-evidence', assetId] as const,
  security: (assetId: string) => ['assets', 'security', assetId] as const,
  runs: (id: string) => ['integrations', id, 'runs'] as const,
  evidence: (assetId: string) => ['assets', 'evidence', assetId] as const,
  authority: ['discovery', 'field-authority'] as const,
}

export const fetchCandidates = (filters: CandidateFilters, cursor?: string) =>
  apiGet<Paginated<Candidate>>('/discovery/candidates/', { ...filters, cursor })
export const fetchCandidate = (id: string) => apiGet<Candidate>(`/discovery/candidates/${id}/`)
export const fetchObservation = (id: string) =>
  apiGet<ObservationDetail>(`/discovery/observations/${id}/`)

export const approveCandidate = (
  id: string,
  version: number,
  body: {
    action: 'link' | 'create'
    reason: string
    asset?: string
    category?: string
    name?: string
    business_status?: string
  },
) => apiRequest<Candidate>('POST', `/reconciliation/${id}/approve/`, { body, ifMatch: version })
export const rejectCandidate = (id: string, version: number, reason: string) =>
  apiRequest<Candidate>('POST', `/reconciliation/${id}/reject/`, { body: { reason }, ifMatch: version })
export const holdCandidate = (id: string, version: number, reason: string) =>
  apiRequest<Candidate>('POST', `/reconciliation/${id}/hold/`, { body: { reason }, ifMatch: version })

export const fetchConflicts = (status: string, cursor?: string) =>
  apiGet<Paginated<FieldConflict>>('/discovery/conflicts/', { status, cursor })
export const resolveConflict = (
  id: string,
  resolution: 'accept_observed' | 'keep_current',
  reason: string,
) =>
  apiRequest<FieldConflict>('POST', `/discovery/conflicts/${id}/resolve/`, {
    body: { resolution, reason },
  })

export const fetchEvidence = (assetId: string) =>
  apiGet<AssetEvidence>(`/assets/${assetId}/evidence/`)
export const lockField = (assetId: string, field: string, reason: string) =>
  apiRequest<AssetEvidence>('POST', `/assets/${assetId}/field-locks/`, { body: { field, reason } })
export const unlockField = (assetId: string, field: string, reason: string) =>
  apiRequest<AssetEvidence>('POST', `/assets/${assetId}/field-locks/unlock/`, {
    body: { field, reason },
  })
export const unlinkSource = (linkId: string, reason: string) =>
  apiRequest<SourceLink>('POST', `/source-links/${linkId}/unlink/`, { body: { reason } })
export const mergeAssets = (survivorId: string, version: number, sourceAsset: string, reason: string) =>
  apiRequest<AssetMerge>('POST', `/assets/${survivorId}/merge/`, {
    body: { source_asset: sourceAsset, reason },
    ifMatch: version,
  })
export const revertMerge = (mergeId: string, reason: string) =>
  apiRequest<AssetMerge>('POST', `/merges/${mergeId}/revert/`, { body: { reason } })

export const fetchSources = () => apiGet<DiscoverySource[]>('/discovery/sources/')
export const fetchIntegrations = () => apiGet<IntegrationInstance[]>('/integrations/')
export const createIntegration = (body: IntegrationWrite) =>
  apiRequest<IntegrationInstance>('POST', '/integrations/', { body })
export const updateIntegration = (id: string, version: number, body: Partial<IntegrationWrite>) =>
  apiRequest<IntegrationInstance>('PATCH', `/integrations/${id}/`, { body, ifMatch: version })
export const fetchRuns = (id: string) => apiGet<Paginated<SyncRun>>(`/integrations/${id}/runs/`)
export const fetchIntegration = (id: string) => apiGet<IntegrationInstance>(`/integrations/${id}/`)
export const testConnection = (id: string) => apiRequest<ConnectionTest>('POST', `/integrations/${id}/test/`)
export const syncNow = (id: string, mode: 'full' | 'incremental') =>
  apiRequest<SyncRun>('POST', `/integrations/${id}/sync/`, { body: { mode } })
export const setLiveAccess = (id: string, approved: boolean, reason: string) =>
  apiRequest<IntegrationInstance>('POST', `/integrations/${id}/live-access/`, { body: { approved, reason } })
export const fetchNetworkEvidence = (assetId: string) =>
  apiGet<NeighborEvidence[]>(`/assets/${assetId}/network-evidence/`)
export const fetchSecurityStates = (assetId: string) =>
  apiGet<EndpointSecurityState[]>(`/assets/${assetId}/security/`)
export const fetchFieldAuthority = () => apiGet<FieldAuthorityPolicy>('/discovery/field-authority/')
export const updateFieldAuthority = (version: number, precedence: Record<string, string[]>) =>
  apiRequest<FieldAuthorityPolicy>('PATCH', '/discovery/field-authority/', {
    body: { precedence },
    ifMatch: version,
  })
