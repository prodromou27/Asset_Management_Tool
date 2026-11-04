import { apiGet, apiRequest } from './client'
import type { Paginated, SoftwareInstallation, SoftwareProduct, SoftwareProductDetail, SoftwareVersion } from './types'

type Query = Record<string, string | undefined>

export const softwareKeys = {
  all: ['software'] as const,
  products: (q: Query) => ['software', 'products', q] as const,
  product: (id: number) => ['software', 'product', id] as const,
  installations: (q: Query) => ['software', 'installations', q] as const,
  asset: (id: string, removed: boolean) => ['software', 'asset', id, removed] as const,
}

export const fetchSoftwareProducts = (query: Query, cursor?: string) =>
  apiGet<Paginated<SoftwareProduct>>('/software/products/', { ...query, cursor })
export const fetchSoftwareProduct = (id: number) =>
  apiGet<SoftwareProductDetail>(`/software/products/${id}/`)
export const fetchInstallations = (query: Query, cursor?: string) =>
  apiGet<Paginated<SoftwareInstallation>>('/software/installations/', { ...query, cursor })
export const fetchAssetSoftware = (assetId: string, removed: boolean) =>
  apiGet<SoftwareInstallation[]>(`/assets/${assetId}/software/`, { removed: removed ? 'true' : undefined })
export const addManualSoftware = (
  assetId: string,
  body: { name: string; publisher: string; version: string; note: string },
) => apiRequest<SoftwareInstallation>('POST', `/assets/${assetId}/software/`, { body })
export const removeManualSoftware = (id: number, reason: string) =>
  apiRequest<SoftwareInstallation>('POST', `/software/installations/${id}/remove/`, { body: { reason } })
export const approveSoftwareVersion = (
  id: number,
  version: number,
  body: { product: string; remember_alias: boolean; note: string },
) =>
  apiRequest<SoftwareVersion>('POST', `/software/versions/${id}/lifecycle/approve/`, {
    body,
    ifMatch: version,
  })
export const rejectSoftwareVersion = (id: number, version: number, note: string) =>
  apiRequest<SoftwareVersion>('POST', `/software/versions/${id}/lifecycle/reject/`, {
    body: { note },
    ifMatch: version,
  })
