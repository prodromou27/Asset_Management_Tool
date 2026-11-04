import type { Candidate, IntegrationInstance, SyncRun } from '../../shared/api/types'
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
  serial_other_make: 'Same serial, different manufacturer',
  mac: 'MAC address',
  hostname: 'Hostname',
  name: 'Asset name',
  ip: 'IP address (same site/VRF)',
}

export const KEY_STRENGTH: Record<string, { label: string; tone: StatusTone }> = {
  strong: { label: 'Strong', tone: 'success' },
  corroborating: { label: 'Corroborating', tone: 'neutral' },
  conflicting: { label: 'Conflicting', tone: 'danger' },
}

/** Whether a source attribute agrees with the asset (null: one side unknown). */
export function agreement(value: boolean | null | undefined, unknown: string): string {
  if (value === null || value === undefined) return unknown
  return value ? 'Agrees' : 'Differs'
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

export const RUN_STATUS: Record<SyncRun['status'], { label: string; tone: StatusTone }> = {
  queued: { label: 'Queued', tone: 'neutral' },
  running: { label: 'Running', tone: 'neutral' },
  succeeded: { label: 'Succeeded', tone: 'success' },
  partial: { label: 'Partial', tone: 'warning' },
  failed: { label: 'Failed', tone: 'danger' },
}

export const RUN_PHASE: Record<string, string> = {
  '': 'Waiting for a worker',
  devices: 'Reading the device list',
  enrichment: 'Reading device details',
  reconciliation: 'Reconciling with assets',
  evidence: 'Reading FDB and neighbour evidence',
  security: 'Storing security observations',
  facts: 'Storing security, license or software data',
  software: 'Reading installed software',
  licenses: 'Reading subscriptions and license assignments',
  done: 'Finished',
  failed: 'Stopped',
}

export const CREDENTIAL_STATUS: Record<string, { label: string; tone: StatusTone }> =
  {
    not_set: { label: 'Not set', tone: 'neutral' },
    invalid: { label: 'Invalid reference', tone: 'danger' },
    missing: { label: 'Secret not found', tone: 'danger' },
    configured: { label: 'Secret available', tone: 'success' },
  }

export const EVIDENCE_KIND: Record<string, string> = {
  fdb: 'MAC table (FDB)',
  lldp: 'LLDP neighbour',
  cdp: 'CDP neighbour',
  other: 'Neighbour',
}

export const AVAILABILITY_LABEL: Record<string, string> = {
  available: 'Available',
  beta: 'Beta (fixture-tested)',
  planned: 'Planned',
}
