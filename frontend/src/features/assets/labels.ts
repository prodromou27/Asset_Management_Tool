import type { AssetCategory, AssetListItem } from '../../shared/api/types'
import type { StatusTone } from '../../shared/ui/StatusBadge'

export const BUSINESS_STATUS: Record<AssetListItem['business_status'], string> = {
  ordered: 'Ordered',
  in_stock: 'In stock',
  deployed: 'Deployed',
  assigned: 'Assigned',
  in_repair: 'In repair',
  retired: 'Retired',
  disposed: 'Disposed',
  lost: 'Lost',
}

export const OBSERVATION_STATUS: Record<AssetListItem['observation_status'], string> = {
  recently_seen: 'Recently seen',
  stale: 'Stale',
  unreachable: 'Unreachable',
  never_scanned: 'Never scanned',
  manual_only: 'Manual only',
}

export const SUPPORT_STATUS: Record<AssetListItem['support_status'], string> = {
  supported: 'Supported',
  eol_announced: 'EOL announced',
  expiring: 'Expiring',
  security_maintenance_ended: 'Security maintenance ended',
  eos: 'End of support',
  unknown: 'Unknown',
  not_announced: 'Not announced',
}

/** docs/07 status colour discipline; the text always carries the meaning. */
export const SUPPORT_TONE: Record<AssetListItem['support_status'], StatusTone> = {
  supported: 'success',
  eol_announced: 'warning',
  expiring: 'warning',
  security_maintenance_ended: 'danger',
  eos: 'danger',
  unknown: 'neutral',
  not_announced: 'neutral',
}

export const OBSERVATION_TONE: Record<AssetListItem['observation_status'], StatusTone> = {
  recently_seen: 'success',
  stale: 'neutral',
  unreachable: 'warning',
  never_scanned: 'neutral',
  manual_only: 'neutral',
}

export const BUSINESS_TONE: Record<AssetListItem['business_status'], StatusTone> = {
  ordered: 'neutral',
  in_stock: 'neutral',
  deployed: 'success',
  assigned: 'success',
  in_repair: 'warning',
  retired: 'neutral',
  disposed: 'neutral',
  lost: 'danger',
}

export const options = (labels: Record<string, string>) =>
  Object.entries(labels).map(([value, label]) => ({ value, label }))

/** Indented, hierarchy-ordered options; the API already returns depth-first order. */
export function categoryOptions(categories: AssetCategory[], { activeOnly = false } = {}) {
  return categories
    .filter((c) => !activeOnly || c.is_active)
    .map((c) => ({
      value: c.id,
      label: `${' '.repeat(c.depth)}${c.name}${c.is_active ? '' : ' (inactive)'}`,
    }))
}
