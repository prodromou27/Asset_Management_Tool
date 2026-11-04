import { apiGet, apiRequest } from './client'
import type {
  AssetLifecycle,
  LifecycleAssessment,
  LifecycleException,
  LifecycleExceptionWrite,
  LifecycleMatch,
  LifecycleMilestone,
  LifecycleMilestoneWrite,
  LifecyclePolicy,
  LifecycleProduct,
  LifecycleProductDetail,
  LifecycleProductWrite,
  LifecycleRevision,
  LifecycleSource,
  LifecycleSourceWrite,
  LifecycleSummaryRow,
  Paginated,
  VendorAlias,
} from './types'

type Query = Record<string, string | undefined>

export const lifecycleKeys = {
  all: ['lifecycle'] as const,
  products: (q: Query) => ['lifecycle', 'products', q] as const,
  product: (id: string) => ['lifecycle', 'product', id] as const,
  revisions: (id: string) => ['lifecycle', 'product', id, 'revisions'] as const,
  productAssets: (id: string) => ['lifecycle', 'product', id, 'assets'] as const,
  sources: ['lifecycle', 'sources'] as const,
  vendorAliases: ['lifecycle', 'vendor-aliases'] as const,
  findings: (q: Query) => ['lifecycle', 'findings', q] as const,
  summary: ['lifecycle', 'summary'] as const,
  policy: ['lifecycle', 'policy'] as const,
  matches: (q: Query) => ['lifecycle', 'matches', q] as const,
  exceptions: (q: Query) => ['lifecycle', 'exceptions', q] as const,
  asset: (id: string) => ['lifecycle', 'asset', id] as const,
}

const L = '/lifecycle'

export const fetchProducts = (query: Query, cursor?: string) =>
  apiGet<Paginated<LifecycleProduct>>(`${L}/products/`, { ...query, cursor })
export const fetchProduct = (id: string) => apiGet<LifecycleProductDetail>(`${L}/products/${id}/`)
export const createProduct = (body: LifecycleProductWrite) =>
  apiRequest<LifecycleProductDetail>('POST', `${L}/products/`, { body })
export const updateProduct = (
  id: string,
  version: number,
  body: Partial<LifecycleProductWrite> & { is_active?: boolean; reason: string },
) => apiRequest<LifecycleProductDetail>('PATCH', `${L}/products/${id}/`, { body, ifMatch: version })
export const setStatement = (
  id: string,
  version: number,
  body: { support_statement: string; statement_source?: string | null; verify: boolean },
) =>
  apiRequest<LifecycleProductDetail>('POST', `${L}/products/${id}/statement/`, {
    body,
    ifMatch: version,
  })
export const addAlias = (id: string, body: { kind: string; value: string; release?: string; note?: string }) =>
  apiRequest<LifecycleProductDetail>('POST', `${L}/products/${id}/aliases/`, { body })
export const removeAlias = (aliasId: string, reason: string) =>
  apiRequest<LifecycleProductDetail>('POST', `${L}/aliases/${aliasId}/remove/`, { body: { reason } })
export const addMilestone = (id: string, body: LifecycleMilestoneWrite) =>
  apiRequest<LifecycleProductDetail>('POST', `${L}/products/${id}/milestones/`, { body })
export const updateMilestone = (
  id: string,
  version: number,
  body: Partial<LifecycleMilestoneWrite> & { reason: string },
) => apiRequest<LifecycleMilestone>('PATCH', `${L}/milestones/${id}/`, { body, ifMatch: version })
export const reviewMilestone = (
  id: string,
  version: number,
  decision: 'verified' | 'rejected',
  note: string,
) =>
  apiRequest<LifecycleMilestone>('POST', `${L}/milestones/${id}/review/`, {
    body: { decision, note },
    ifMatch: version,
  })
export const fetchRevisions = (id: string) => apiGet<LifecycleRevision[]>(`${L}/products/${id}/revisions/`)
export const fetchProductAssets = (id: string, cursor?: string) =>
  apiGet<Paginated<LifecycleAssessment>>(`${L}/products/${id}/assets/`, { cursor })
export const reassessProduct = (id: string) =>
  apiRequest<void>('POST', `${L}/products/${id}/reassess/`)

export const fetchSources = (q?: string) => apiGet<LifecycleSource[]>(`${L}/sources/`, { q })
export const createSource = (body: LifecycleSourceWrite) =>
  apiRequest<LifecycleSource>('POST', `${L}/sources/`, { body })

export const fetchVendorAliases = () => apiGet<VendorAlias[]>(`${L}/vendor-aliases/`)
export const createVendorAlias = (body: { alias: string; vendor: string }) =>
  apiRequest<VendorAlias>('POST', `${L}/vendor-aliases/`, { body })
export const removeVendorAlias = (id: string, reason: string) =>
  apiRequest<void>('POST', `${L}/vendor-aliases/${id}/remove/`, { body: { reason } })

export const fetchFindings = (query: Query, cursor?: string) =>
  apiGet<Paginated<LifecycleAssessment>>(`${L}/findings/`, { ...query, cursor })
export const fetchSummary = () => apiGet<LifecycleSummaryRow[]>(`${L}/summary/`)
export const fetchPolicy = () => apiGet<LifecyclePolicy>(`${L}/policy/`)
export const fetchMatches = (query: Query, cursor?: string) =>
  apiGet<Paginated<LifecycleMatch>>(`${L}/matches/`, { ...query, cursor })
export const approveMatch = (
  id: string,
  version: number,
  body: { product: string; remember_alias: boolean; note: string },
) => apiRequest<LifecycleMatch>('POST', `${L}/matches/${id}/approve/`, { body, ifMatch: version })
export const rejectMatch = (id: string, version: number, body: { products?: string[]; note: string }) =>
  apiRequest<LifecycleMatch>('POST', `${L}/matches/${id}/reject/`, { body, ifMatch: version })
export const fetchExceptions = (query: Query, cursor?: string) =>
  apiGet<Paginated<LifecycleException>>(`${L}/exceptions/`, { ...query, cursor })
export const revokeException = (id: string, version: number, reason: string) =>
  apiRequest<LifecycleException>('POST', `${L}/exceptions/${id}/revoke/`, {
    body: { reason },
    ifMatch: version,
  })
export const reassessAll = () => apiRequest<void>('POST', `${L}/reassess/`)

export const fetchAssetLifecycle = (assetId: string) =>
  apiGet<AssetLifecycle>(`/assets/${assetId}/lifecycle/`)
export const reassessAsset = (assetId: string) =>
  apiRequest<AssetLifecycle>('POST', `/assets/${assetId}/lifecycle/reassess/`)
export const createException = (assetId: string, body: LifecycleExceptionWrite) =>
  apiRequest<LifecycleException>('POST', `/assets/${assetId}/lifecycle/exceptions/`, { body })
