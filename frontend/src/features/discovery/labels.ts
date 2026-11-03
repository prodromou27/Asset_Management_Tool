import type { Candidate, IntegrationInstance } from '../../shared/api/types'
import type { StatusTone } from '../../shared/ui/StatusBadge'

export const RULE_LABEL: Record<Candidate['rule'], string> = {
  new_device: 'No matching asset',
  weak: 'Weak identifier only',
  corroborated: 'Several identifiers agree',
  strong: 'Strong identifier',
  conflict: 'Conflicting identifiers',
}

export const RULE_TONE: Record<Candidate['rule'], StatusTone> = {
  new_device: 'neutral',
  weak: 'neutral',
  corroborated: 'warning',
  strong: 'success',
  conflict: 'danger',
}

export const CANDIDATE_STATUS: Record<Candidate['status'], string> = {
  open: 'Open',
  held: 'On hold',
  linked: 'Linked',
  created: 'Asset created',
  rejected: 'Rejected',
  superseded: 'Superseded',
}

export const KEY_LABEL: Record<string, string> = {
  hardware_uuid: 'Hardware UUID',
  serial: 'Manufacturer + serial',
  serial_unverified: 'Serial (manufacturer unknown)',
  mac: 'MAC address',
  hostname: 'Hostname',
  name: 'Asset name',
  ip: 'IP address (same site/VRF)',
}

export const FIELD_LABEL: Record<string, string> = {
  manufacturer: 'Manufacturer',
  model: 'Model',
  serial_number: 'Serial number',
  os_name: 'Operating system',
  os_version: 'OS version',
  firmware_version: 'Firmware',
}

export const FRESHNESS: Record<string, { label: string; tone: StatusTone }> = {
  fresh: { label: 'Fresh', tone: 'success' },
  stale: { label: 'Stale', tone: 'warning' },
  never: { label: 'Never synchronised', tone: 'neutral' },
}

export const INSTANCE_STATUS: Record<IntegrationInstance['status'], { label: string; tone: StatusTone }> = {
  configured: { label: 'Configured', tone: 'neutral' },
  available: { label: 'Available', tone: 'success' },
  degraded: { label: 'Degraded', tone: 'danger' },
  disconnected: { label: 'Disconnected', tone: 'neutral' },
}

/** Score is a confidence hint for reviewers, not a probability. */
export function scoreLabel(score: number): string {
  if (score >= 80) return `${score} · high`
  if (score >= 50) return `${score} · medium`
  if (score > 0) return `${score} · low`
  return '0 · none'
}
