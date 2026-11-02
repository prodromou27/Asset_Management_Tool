import { apiGet, apiRequest } from './client'
import type {
  AssetCategory,
  AssetDetail,
  AssetHistoryEntry,
  AssetListItem,
  AssetPatch,
  AssetWrite,
  ClassificationImpact,
  CustomFieldDefinition,
  Department,
  Location,
  Paginated,
  Site,
  UserLookup,
} from './types'

export interface AssetFilters {
  q?: string
  category?: string
  site?: string
  location?: string
  department?: string
  owner?: string
  business_status?: string
  support_status?: string
  archived?: string
  ordering?: string
}

export const assetKeys = {
  list: (filters: AssetFilters) => ['assets', 'list', filters] as const,
  detail: (id: string) => ['assets', 'detail', id] as const,
  history: (id: string) => ['assets', 'history', id] as const,
  categories: ['asset-categories'] as const,
  fields: (categoryId: string, effective: boolean) =>
    ['asset-categories', categoryId, 'fields', effective] as const,
  sites: ['sites'] as const,
  locations: (siteId?: string) => ['locations', siteId ?? 'all'] as const,
  departments: ['departments'] as const,
  userLookup: ['users', 'lookup'] as const,
}

// --- Assets ---------------------------------------------------------------------

export const fetchAssets = (filters: AssetFilters, cursor?: string) =>
  apiGet<Paginated<AssetListItem>>('/assets/', { ...filters, cursor })
export const fetchAsset = (id: string) => apiGet<AssetDetail>(`/assets/${id}/`)
export const createAsset = (body: AssetWrite) =>
  apiRequest<AssetDetail>('POST', '/assets/', { body })
export const updateAsset = (id: string, version: number, body: AssetPatch) =>
  apiRequest<AssetDetail>('PATCH', `/assets/${id}/`, { body, ifMatch: version })
export const previewClassification = (
  id: string,
  category: string,
  custom_fields?: Record<string, unknown>,
) =>
  apiRequest<ClassificationImpact>('POST', `/assets/${id}/classification/preview/`, {
    body: { category, custom_fields },
  })
export const reclassifyAsset = (
  id: string,
  version: number,
  body: { category: string; reason: string; custom_fields?: Record<string, unknown> },
) => apiRequest<AssetDetail>('POST', `/assets/${id}/classification/`, { body, ifMatch: version })
export const archiveAsset = (id: string, version: number, reason: string) =>
  apiRequest<AssetDetail>('POST', `/assets/${id}/archive/`, { body: { reason }, ifMatch: version })
export const restoreAsset = (id: string, version: number) =>
  apiRequest<AssetDetail>('POST', `/assets/${id}/restore/`, { ifMatch: version })
export const fetchAssetHistory = (id: string, cursor?: string) =>
  apiGet<Paginated<AssetHistoryEntry>>(`/assets/${id}/history/`, { cursor })

// --- Categories and fields --------------------------------------------------------

export const fetchCategories = () => apiGet<AssetCategory[]>('/asset-categories/')
export const createCategory = (body: { name: string; parent?: string | null; description?: string }) =>
  apiRequest<AssetCategory>('POST', '/asset-categories/', { body })
export const updateCategory = (
  id: string,
  version: number,
  body: Partial<{
    name: string
    parent: string | null
    description: string
    is_active: boolean
    sort_order: number
  }>,
) => apiRequest<AssetCategory>('PATCH', `/asset-categories/${id}/`, { body, ifMatch: version })
export const fetchCategoryFields = (categoryId: string, effective: boolean) =>
  apiGet<CustomFieldDefinition[]>(`/asset-categories/${categoryId}/fields/`, {
    effective: effective ? 'true' : undefined,
  })
export const createCategoryField = (categoryId: string, body: Record<string, unknown>) =>
  apiRequest<CustomFieldDefinition>('POST', `/asset-categories/${categoryId}/fields/`, { body })
export const updateCategoryField = (id: string, version: number, body: Record<string, unknown>) =>
  apiRequest<CustomFieldDefinition>('PATCH', `/custom-fields/${id}/`, { body, ifMatch: version })

// --- Sites, locations, departments, owners ----------------------------------------

export const fetchSites = () => apiGet<Site[]>('/sites/')
export const createSite = (body: Record<string, unknown>) =>
  apiRequest<Site>('POST', '/sites/', { body })
export const updateSite = (id: string, version: number, body: Record<string, unknown>) =>
  apiRequest<Site>('PATCH', `/sites/${id}/`, { body, ifMatch: version })

export const fetchLocations = (siteId?: string) =>
  apiGet<Location[]>('/locations/', { site: siteId })
export const createLocation = (body: Record<string, unknown>) =>
  apiRequest<Location>('POST', '/locations/', { body })
export const updateLocation = (id: string, version: number, body: Record<string, unknown>) =>
  apiRequest<Location>('PATCH', `/locations/${id}/`, { body, ifMatch: version })

export const fetchDepartments = () => apiGet<Department[]>('/departments/')
export const createDepartment = (body: Record<string, unknown>) =>
  apiRequest<Department>('POST', '/departments/', { body })
export const updateDepartment = (id: string, version: number, body: Record<string, unknown>) =>
  apiRequest<Department>('PATCH', `/departments/${id}/`, { body, ifMatch: version })

export const fetchUserLookup = () => apiGet<UserLookup[]>('/users/lookup/')
