import { apiGet, apiRequest } from './client'
import type {
  EntitlementAllocation,
  LicenseAllocate,
  LicenseAllocation,
  LicenseEntitlement,
  LicenseEntitlementWrite,
  LicenseProduct,
  LicenseProductDetail,
  LicenseProductWrite,
  LicenseSubscription,
  LicenseSubscriptionDetail,
  Paginated,
} from './types'

export interface AllocationFilters {
  sku?: string
  q?: string
  method?: 'direct' | 'group' | 'direct_and_group'
  include_ended?: 'true'
}

type Query = Record<string, string | undefined>

export const licenseKeys = {
  all: ['licenses'] as const,
  subscriptions: ['licenses', 'subscriptions'] as const,
  subscription: (id: string) => ['licenses', 'subscription', id] as const,
  allocations: (filters: AllocationFilters) => ['licenses', 'allocations', filters] as const,
  products: (q: Query) => ['licenses', 'products', q] as const,
  product: (id: string) => ['licenses', 'product', id] as const,
  entitlementAllocations: (q: Query) => ['licenses', 'entitlement-allocations', q] as const,
}

export const fetchSubscriptions = () => apiGet<LicenseSubscription[]>('/licenses/subscriptions/')
export const fetchSubscription = (id: string) => apiGet<LicenseSubscriptionDetail>(`/licenses/subscriptions/${id}/`)
export const fetchAllocations = (filters: AllocationFilters, cursor?: string) =>
  apiGet<Paginated<LicenseAllocation>>('/licenses/allocations/', {
    ...filters,
    cursor,
  })

// Manually maintained products, entitlements and allocations (Task 016b).
export const fetchLicenseProducts = (query: Query, cursor?: string) =>
  apiGet<Paginated<LicenseProduct>>('/licenses/products/', {
    ...query,
    cursor,
  })
export const fetchLicenseProduct = (id: string) => apiGet<LicenseProductDetail>(`/licenses/products/${id}/`)
export const createLicenseProduct = (body: LicenseProductWrite) =>
  apiRequest<LicenseProductDetail>('POST', '/licenses/products/', { body })
export const updateLicenseProduct = (id: string, version: number, body: Partial<LicenseProductWrite>) =>
  apiRequest<LicenseProductDetail>('PATCH', `/licenses/products/${id}/`, {
    body,
    ifMatch: version,
  })
export const createEntitlement = (body: LicenseEntitlementWrite) =>
  apiRequest<LicenseEntitlement>('POST', '/licenses/entitlements/', { body })
export const updateEntitlement = (id: string, version: number, body: Partial<LicenseEntitlementWrite>) =>
  apiRequest<LicenseEntitlement>('PATCH', `/licenses/entitlements/${id}/`, {
    body,
    ifMatch: version,
  })
export const retireEntitlement = (id: string, version: number, reason: string) =>
  apiRequest<LicenseEntitlement>('POST', `/licenses/entitlements/${id}/retire/`, {
    body: { reason },
    ifMatch: version,
  })
export const fetchEntitlementAllocations = (query: Query, cursor?: string) =>
  apiGet<Paginated<EntitlementAllocation>>('/licenses/entitlement-allocations/', { ...query, cursor })
export const allocateEntitlement = (id: string, body: LicenseAllocate) =>
  apiRequest<EntitlementAllocation>('POST', `/licenses/entitlements/${id}/allocations/`, { body })
export const endEntitlementAllocation = (id: string, reason: string) =>
  apiRequest<EntitlementAllocation>('POST', `/licenses/entitlement-allocations/${id}/end/`, { body: { reason } })
