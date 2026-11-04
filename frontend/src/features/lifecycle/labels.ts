import type { LifecycleStatus, MilestoneType } from '../../shared/api/types'
import type { StatusTone } from '../../shared/ui/StatusBadge'

/** docs/07 status colour discipline; the text always carries the meaning. */
export const LIFECYCLE_STATUS: Record<LifecycleStatus, { label: string; tone: StatusTone }> = {
  supported: { label: 'Supported', tone: 'success' },
  eol_announced: { label: 'EOL announced', tone: 'neutral' },
  expiring: { label: 'Approaching end of support', tone: 'warning' },
  security_maintenance_ended: { label: 'Security updates ended', tone: 'danger' },
  eos: { label: 'End of support', tone: 'danger' },
  not_announced: { label: 'Not announced', tone: 'neutral' },
  unknown: { label: 'Unknown', tone: 'neutral' },
  unverified: { label: 'Needs review', tone: 'warning' },
  not_applicable: { label: 'Not applicable', tone: 'neutral' },
}

export const DIMENSION: Record<string, string> = {
  hardware: 'Hardware',
  os: 'OS / firmware',
  software: 'Software',
}

export const PRODUCT_KIND: Record<string, string> = {
  hardware: 'Hardware model',
  operating_system: 'Operating system',
  firmware: 'Firmware / network OS',
  software: 'Software',
}

export const MILESTONE: Record<MilestoneType, string> = {
  announcement: 'EOL announcement',
  end_of_sale: 'End of sale',
  end_of_maintenance: 'End of maintenance',
  end_of_security_updates: 'End of security updates',
  end_of_standard_support: 'End of standard support',
  end_of_extended_support: 'End of extended support',
  end_of_support: 'Final end of support',
}

export const SOURCE_TYPE: Record<string, string> = {
  vendor: 'Vendor',
  manual: 'Manual record',
  third_party: 'Third party',
}

export const VERIFICATION: Record<string, { label: string; tone: StatusTone }> = {
  pending: { label: 'Awaiting verification', tone: 'warning' },
  verified: { label: 'Verified', tone: 'success' },
  rejected: { label: 'Rejected', tone: 'neutral' },
}

export const MATCH_STATE: Record<string, string> = {
  matched: 'Matched',
  candidate: 'Needs review',
  no_match: 'No match',
  not_applicable: 'Not applicable',
}

export const MATCH_METHOD: Record<string, string> = {
  exact: 'Exact match',
  alias: 'Approved alias',
  manual: 'Approved by reviewer',
  none: '',
}

export const SUPPORT_LEVEL: Record<string, string> = {
  '': '',
  standard: 'Standard support',
  extended: 'Extended support',
  ended: 'Support ended',
}

export const EVIDENCE_QUALITY: Record<string, string> = {
  '': 'No evidence',
  vendor: 'Vendor',
  manual: 'Manual record',
  third_party: 'Third party only',
}

export const ALIAS_KINDS: Record<string, { value: string; label: string }[]> = {
  hardware: [
    { value: 'model', label: 'Model name' },
    { value: 'part_number', label: 'Part number / SKU' },
  ],
  operating_system: [{ value: 'os_name', label: 'OS name (with build)' }],
  firmware: [{ value: 'os_name', label: 'Firmware / OS name' }],
  software: [{ value: 'product_name', label: 'Product name' }],
}

export function daysLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return '–'
  if (days < 0) return `${Math.abs(days)} days ago`
  if (days === 0) return 'Today (last day)'
  return `${days} days`
}

export function productLabel(p: { vendor: string; name: string; release?: string }): string {
  return [p.vendor, p.name, p.release].filter(Boolean).join(' ')
}
