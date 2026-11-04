import { API_BASE_URL, apiGet, apiRequest } from './client'
import type { ExportCreate, ExportFamily, ExportJob, Paginated } from './types'

export const exportKeys = {
  all: ['exports'] as const,
  families: ['exports', 'families'] as const,
  list: ['exports', 'list'] as const,
  job: (id: string) => ['exports', 'job', id] as const,
}

/** Plain link: the browser downloads with the session cookie; the server checks access. */
export const exportDownloadUrl = (id: string) => `${API_BASE_URL}/exports/${id}/download/`

export const fetchExportFamilies = () => apiGet<ExportFamily[]>('/exports/families/')
export const fetchExports = (cursor?: string) =>
  apiGet<Paginated<ExportJob>>('/exports/', { cursor })
export const fetchExport = (id: string) => apiGet<ExportJob>(`/exports/${id}/`)
export const createExport = (body: ExportCreate) =>
  apiRequest<ExportJob>('POST', '/exports/', { body })

export const isActive = (job: Pick<ExportJob, 'status'>) =>
  job.status === 'queued' || job.status === 'running'
