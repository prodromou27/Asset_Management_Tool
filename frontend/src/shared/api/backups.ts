import { apiGet, apiRequest } from './client'
import type { components } from './schema'

export type BackupPolicy = components['schemas']['BackupPolicy']
export type BackupJob = components['schemas']['BackupJob']
export type BackupSummary = components['schemas']['BackupSummary']
export type RestoreDrill = components['schemas']['RestoreDrill']
export type DrillWrite = components['schemas']['RestoreDrillRequest']

export const getBackupPolicy = () => apiGet<BackupPolicy>('/backups/policy/')
export const getBackupSummary = () => apiGet<BackupSummary>('/backups/summary/')
export const getBackupJobs = () => apiGet<BackupJob[]>('/backups/jobs/')
export const getRestoreDrills = () => apiGet<RestoreDrill[]>('/backups/drills/')
export const saveBackupPolicy = (body: Partial<BackupPolicy>, version: number) =>
  apiRequest<BackupPolicy>('PATCH', '/backups/policy/', { body, ifMatch: version })
export const requestBackup = () => apiRequest<BackupJob>('POST', '/backups/jobs/')
export const verifyBackup = (id: string) => apiRequest<BackupJob>('POST', `/backups/jobs/${id}/verify/`)
export const recordDrill = (body: DrillWrite) => apiRequest<RestoreDrill>('POST', '/backups/drills/', { body })
