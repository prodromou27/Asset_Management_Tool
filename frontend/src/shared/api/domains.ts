import { apiGet, apiRequest } from './client'
import type {
  Certificate,
  CertificateDeployment,
  CertificateDetail,
  Domain,
  DomainWrite,
  Paginated,
  TlsEndpoint,
  TlsEndpointWrite,
} from './types'

type Query = Record<string, string | undefined>

export const domainKeys = {
  all: ['domains'] as const,
  domains: (q: Query) => ['domains', 'domains', q] as const,
  certificates: (q: Query) => ['domains', 'certificates', q] as const,
  certificate: (id: string) => ['domains', 'certificate', id] as const,
  endpoints: (q: Query) => ['domains', 'endpoints', q] as const,
  deployments: (q: Query) => ['domains', 'deployments', q] as const,
  asset: (id: string) => ['domains', 'asset', id] as const,
}

export const fetchDomains = (query: Query, cursor?: string) =>
  apiGet<Paginated<Domain>>('/domains/', { ...query, cursor })
export const createDomain = (body: DomainWrite) => apiRequest<Domain>('POST', '/domains/', { body })
export const updateDomain = (id: string, version: number, body: Partial<DomainWrite>) =>
  apiRequest<Domain>('PATCH', `/domains/${id}/`, { body, ifMatch: version })
export const retireDomain = (id: string, version: number, reason: string) =>
  apiRequest<Domain>('POST', `/domains/${id}/retire/`, { body: { reason }, ifMatch: version })

export const fetchCertificates = (query: Query, cursor?: string) =>
  apiGet<Paginated<Certificate>>('/certificates/', { ...query, cursor })
export const fetchCertificate = (id: string) => apiGet<CertificateDetail>(`/certificates/${id}/`)
export const uploadCertificates = (pem: string, note: string) =>
  apiRequest<Certificate[]>('POST', '/certificates/', { body: { pem, note } })
export const fetchDeployments = (query: Query, cursor?: string) =>
  apiGet<Paginated<CertificateDeployment>>('/certificates/deployments/', { ...query, cursor })

export const fetchEndpoints = (query: Query, cursor?: string) =>
  apiGet<Paginated<TlsEndpoint>>('/tls-endpoints/', { ...query, cursor })
export const createEndpoint = (body: TlsEndpointWrite) => apiRequest<TlsEndpoint>('POST', '/tls-endpoints/', { body })
export const updateEndpoint = (id: string, version: number, body: Partial<TlsEndpointWrite>) =>
  apiRequest<TlsEndpoint>('PATCH', `/tls-endpoints/${id}/`, { body, ifMatch: version })
export const retireEndpoint = (id: string, version: number, reason: string) =>
  apiRequest<TlsEndpoint>('POST', `/tls-endpoints/${id}/retire/`, { body: { reason }, ifMatch: version })
export const checkEndpoint = (id: string) => apiRequest<TlsEndpoint>('POST', `/tls-endpoints/${id}/check/`)
export const fetchAssetCertificates = (assetId: string) => apiGet<TlsEndpoint[]>(`/assets/${assetId}/certificates/`)
