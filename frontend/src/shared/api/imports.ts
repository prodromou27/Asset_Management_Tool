import { API_BASE_URL, apiGet, apiRequest } from './client'
import type { ImportJob, ImportJobSummary, ImportRow, ImportTemplate, Paginated } from './types'

export type ImportMode = 'create_only' | 'update_matched' | 'upsert'

export const importKeys = {
  all: ['imports'] as const,
  templates: ['imports', 'templates'] as const,
  list: ['imports', 'list'] as const,
  job: (id: string) => ['imports', 'job', id] as const,
  rows: (id: string, action: string) => ['imports', 'rows', id, action] as const,
}

export const templateUrl = (family: string) => `${API_BASE_URL}/imports/templates/${family}/csv/`
export const errorsUrl = (id: string) => `${API_BASE_URL}/imports/${id}/errors/`

export const fetchTemplates = () => apiGet<ImportTemplate[]>('/imports/templates/')
export const fetchImports = (cursor?: string) => apiGet<Paginated<ImportJobSummary>>('/imports/', { cursor })
export const fetchImport = (id: string) => apiGet<ImportJob>(`/imports/${id}/`)
export const uploadImport = (family: string, file: File) => {
  const body = new FormData()
  body.append('family', family)
  body.append('file', file)
  return apiRequest<ImportJob>('POST', '/imports/', { body })
}
export const updateImport = (
  id: string,
  version: number,
  body: { mapping?: Record<string, string>; mode?: ImportMode },
) => apiRequest<ImportJob>('PATCH', `/imports/${id}/`, { body, ifMatch: version })
export const previewImport = (id: string, version: number) =>
  apiRequest<ImportJob>('POST', `/imports/${id}/preview/`, { ifMatch: version })
export const commitImport = (id: string, version: number, idempotencyKey: string) =>
  apiRequest<ImportJob>('POST', `/imports/${id}/commit/`, {
    ifMatch: version,
    headers: { 'X-Idempotency-Key': idempotencyKey },
  })
export const rollbackImport = (id: string, version: number, reason: string) =>
  apiRequest<ImportJob>('POST', `/imports/${id}/rollback/`, { body: { reason }, ifMatch: version })
export const fetchImportRows = (id: string, action: string, cursor?: string) =>
  apiGet<Paginated<ImportRow>>(`/imports/${id}/rows/`, { action: action || undefined, cursor })
