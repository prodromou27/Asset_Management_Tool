import type { StatusTone } from '../../shared/ui/StatusBadge'

// subscribedSku.capabilityStatus values.
export const CAPABILITY: Record<string, { label: string; tone: StatusTone }> = {
  Enabled: { label: 'Enabled', tone: 'success' },
  Warning: { label: 'Warning', tone: 'warning' },
  Suspended: { label: 'Suspended', tone: 'danger' },
  LockedOut: { label: 'Locked out', tone: 'danger' },
  Deleted: { label: 'Deleted', tone: 'neutral' },
}

// licenseAssignmentState.state values (Unknown: no state reported for the assignment).
export const ASSIGNMENT_STATE: Record<string, { label: string; tone: StatusTone }> = {
  Active: { label: 'Active', tone: 'success' },
  ActiveWithError: { label: 'Active with error', tone: 'warning' },
  Error: { label: 'Error (not assigned)', tone: 'danger' },
  Disabled: { label: 'Disabled', tone: 'neutral' },
  Unknown: { label: 'Assigned (path unknown)', tone: 'neutral' },
}

export const METHOD: Record<string, string> = {
  direct: 'Direct',
  group: 'Group',
  direct_and_group: 'Direct and group',
}

/** A quantity, or "Unknown" when the source or count is not available. */
export const count = (value: number | null | undefined) => (value === null || value === undefined ? 'Unknown' : String(value))

export const METRIC: Record<string, string> = {
  user: 'Per user',
  device: 'Per device',
  core: 'Per core',
  concurrent: 'Concurrent users',
  subscription: 'Subscription',
  other: 'Other',
}

export const ENTITLEMENT_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  active: { label: 'In term', tone: 'success' },
  not_started: { label: 'Not started', tone: 'neutral' },
  expired: { label: 'Ended', tone: 'warning' },
  retired: { label: 'Retired', tone: 'neutral' },
}

/** Purchased minus allocated, labelled without judging compliance. */
export function availableLabel(available: number): { text: string; over: boolean } {
  return available < 0
    ? { text: `${(-available).toLocaleString('en-GB')} more allocated than purchased`, over: true }
    : { text: available.toLocaleString('en-GB'), over: false }
}
