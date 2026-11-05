import { apiGet, apiRequest } from './client'
import type { components } from './schema'

export type ReportKind = 'inventory' | 'lifecycle' | 'coverage' | 'groups'
export type ReportData = components['schemas']['Report']
export type DigestSchedule = components['schemas']['Schedule']
export type ScheduleWrite = components['schemas']['ScheduleRequest']
export const fetchReport = (kind: ReportKind, filters: Record<string, string>, offset: number) =>
  apiGet<ReportData>(`/reports/${kind}/`, { ...filters, offset: String(offset), limit: '50' })
export const fetchSchedules = () => apiGet<DigestSchedule[]>('/reports/schedules/')
export const fetchSchedule = (id: string) => apiGet<DigestSchedule>(`/reports/schedules/${id}/`)
export const createSchedule = (body: ScheduleWrite) => apiRequest<DigestSchedule>('POST', '/reports/schedules/', { body })
export const updateSchedule = (id: string, version: number, body: Partial<ScheduleWrite>) =>
  apiRequest<DigestSchedule>('PATCH', `/reports/schedules/${id}/`, { body, ifMatch: version })
