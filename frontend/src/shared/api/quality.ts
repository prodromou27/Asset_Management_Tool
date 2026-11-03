import { apiGet, apiRequest } from './client'
import type { Paginated, QualityFinding, QualitySummaryRow } from './types'

export interface FindingFilters {
  kind?: string
  status?: string
  severity?: string
  assignee?: string
}

export const qualityKeys = {
  all: ['quality'] as const,
  findings: (filters: FindingFilters) => ['quality', 'findings', filters] as const,
  summary: ['quality', 'summary'] as const,
}

export const fetchFindings = (filters: FindingFilters, cursor?: string) =>
  apiGet<Paginated<QualityFinding>>('/quality/findings/', { ...filters, cursor })
export const fetchQualitySummary = () => apiGet<QualitySummaryRow[]>('/quality/summary/')
export const assignFinding = (id: string, version: number, assignee: string | null) =>
  apiRequest<QualityFinding>('POST', `/quality/findings/${id}/assign/`, { body: { assignee }, ifMatch: version })
export const dismissFinding = (id: string, version: number, reason: string) =>
  apiRequest<QualityFinding>('POST', `/quality/findings/${id}/dismiss/`, { body: { reason }, ifMatch: version })
export const reopenFinding = (id: string, version: number, reason: string) =>
  apiRequest<QualityFinding>('POST', `/quality/findings/${id}/reopen/`, { body: { reason }, ifMatch: version })
export const refreshFindings = () =>
  apiRequest<{ opened: number; refreshed: number; resolved: number }>('POST', '/quality/refresh/')
