import type { ExportJob } from '../../shared/api/types'
import type { StatusTone } from '../../shared/ui/StatusBadge'

export const EXPORT_STATUS: Record<ExportJob['status'], { label: string; tone: StatusTone }> = {
  queued: { label: 'Queued', tone: 'neutral' },
  running: { label: 'Preparing', tone: 'neutral' },
  completed: { label: 'Ready', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  expired: { label: 'Expired', tone: 'neutral' },
}

export const FORMAT_LABEL: Record<ExportJob['file_format'], string> = {
  csv: 'CSV',
  xlsx: 'Excel (XLSX)',
  json: 'JSON',
}

export const SCOPE_LABEL: Record<ExportJob['scope'], string> = {
  filtered: 'Current filters',
  selected: 'Selected records',
  all: 'All records you can see',
}

export const FAMILY_LABEL: Record<string, string> = {
  assets: 'Assets',
  groups: 'Asset groups',
  license_entitlements: 'License entitlements',
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}
