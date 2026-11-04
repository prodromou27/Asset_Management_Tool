import type { ImportJob, ImportRow } from '../../shared/api/types'
import type { StatusTone } from '../../shared/ui/StatusBadge'

export const JOB_STATUS: Record<ImportJob['status'], { label: string; tone: StatusTone }> = {
  uploaded: { label: 'Uploaded', tone: 'neutral' },
  previewing: { label: 'Checking', tone: 'neutral' },
  previewed: { label: 'Ready to import', tone: 'warning' },
  committing: { label: 'Importing', tone: 'neutral' },
  completed: { label: 'Completed', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
  rolled_back: { label: 'Rolled back', tone: 'neutral' },
}

export const ACTION: Record<ImportRow['action'], { label: string; tone: StatusTone }> = {
  create: { label: 'Create', tone: 'success' },
  update: { label: 'Update', tone: 'success' },
  skip: { label: 'Skip', tone: 'neutral' },
  conflict: { label: 'Conflict', tone: 'warning' },
  error: { label: 'Error', tone: 'danger' },
}

export const RESULT: Record<string, string> = {
  '': '',
  applied: 'Applied',
  skipped: 'Not applied',
  failed: 'Failed',
  rolled_back: 'Rolled back',
  not_rolled_back: 'Changed since; not rolled back',
}

export const MODE: Record<string, { label: string; help: string }> = {
  create_only: { label: 'Create only', help: 'New records are created; rows that match existing ones are skipped.' },
  update_matched: { label: 'Update matched', help: 'Matching records are updated; rows without a match are skipped.' },
  upsert: { label: 'Create and update', help: 'Matching records are updated and the rest are created.' },
}

export const FAMILY_LABEL: Record<string, string> = {
  asset: 'Assets',
  location: 'Locations',
  group: 'Groups',
  group_membership: 'Static group members',
  license_entitlement: 'License entitlements',
}
