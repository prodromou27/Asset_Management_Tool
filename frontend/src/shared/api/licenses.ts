import { apiGet } from './client'
import type { LicenseAllocation, LicenseSubscription, LicenseSubscriptionDetail, Paginated } from './types'

export interface AllocationFilters {
  sku?: string
  q?: string
  method?: 'direct' | 'group' | 'direct_and_group'
  include_ended?: 'true'
}

export const licenseKeys = {
  subscriptions: ['licenses', 'subscriptions'] as const,
  subscription: (id: string) => ['licenses', 'subscription', id] as const,
  allocations: (filters: AllocationFilters) => ['licenses', 'allocations', filters] as const,
}

export const fetchSubscriptions = () => apiGet<LicenseSubscription[]>('/licenses/subscriptions/')
export const fetchSubscription = (id: string) =>
  apiGet<LicenseSubscriptionDetail>(`/licenses/subscriptions/${id}/`)
export const fetchAllocations = (filters: AllocationFilters, cursor?: string) =>
  apiGet<Paginated<LicenseAllocation>>('/licenses/allocations/', { ...filters, cursor })
