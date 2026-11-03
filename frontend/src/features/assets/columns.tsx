import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { AssetColumn, AssetListItem } from '../../shared/api/types'
import { formatDateTime, formatRelative } from '../../shared/format'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import {
  BUSINESS_STATUS,
  OBSERVATION_STATUS,
  OBSERVATION_TONE,
  SUPPORT_STATUS,
  SUPPORT_TONE,
} from './labels'

export interface ColumnDef {
  id: AssetColumn
  header: string
  className?: string
  render: (asset: AssetListItem) => ReactNode
}

const muted = (text: string) => <span className="cell-muted">{text}</span>

export const COLUMNS: ColumnDef[] = [
  {
    id: 'name',
    header: 'Name / hostname',
    className: 'cell-primary',
    render: (a) => (
      <>
        <Link className="table-link" to={`/assets/${a.id}`}>
          {a.name}
        </Link>
        <span className="cell-secondary mono">
          {[a.asset_tag, a.primary_hostname].filter(Boolean).join(' · ') || ' '}
        </span>
        {a.is_archived && <span className="cell-secondary">Archived</span>}
      </>
    ),
  },
  {
    id: 'category',
    header: 'Category',
    render: (a) => <span title={a.category.path}>{a.category.name}</span>,
  },
  {
    id: 'manufacturer_model',
    header: 'Manufacturer / model',
    render: (a) => (
      <>
        {a.manufacturer || muted('Unknown')}
        {a.model && <span className="cell-secondary">{a.model}</span>}
      </>
    ),
  },
  {
    id: 'serial',
    header: 'Serial',
    className: 'mono',
    render: (a) => a.serial_number || muted('Not recorded'),
  },
  {
    id: 'primary_ip',
    header: 'Primary IP',
    className: 'mono',
    render: (a) => a.primary_ip ?? muted('None'),
  },
  {
    id: 'site',
    header: 'Site / location',
    render: (a) => (
      <>
        <span className="mono">{a.site.code}</span>
        {a.location && <span className="cell-secondary">{a.location.name}</span>}
      </>
    ),
  },
  {
    id: 'owner',
    header: 'Owner',
    render: (a) => a.owner?.display_name ?? muted('Unassigned'),
  },
  {
    id: 'business_status',
    header: 'Business',
    className: 'nowrap',
    render: (a) => BUSINESS_STATUS[a.business_status],
  },
  {
    id: 'observation_status',
    header: 'Observation',
    render: (a) => (
      <StatusBadge
        tone={OBSERVATION_TONE[a.observation_status]}
        label={OBSERVATION_STATUS[a.observation_status]}
      />
    ),
  },
  {
    id: 'support_status',
    header: 'Support',
    render: (a) => (
      <StatusBadge tone={SUPPORT_TONE[a.support_status]} label={SUPPORT_STATUS[a.support_status]} />
    ),
  },
  {
    id: 'last_seen',
    header: 'Last seen',
    className: 'nowrap',
    render: (a) =>
      a.last_seen_at ? (
        <time dateTime={a.last_seen_at} title={formatDateTime(a.last_seen_at)}>
          {formatRelative(a.last_seen_at)}
          <span className="visually-hidden"> ({formatDateTime(a.last_seen_at)})</span>
        </time>
      ) : (
        muted('Never reported')
      ),
  },
  {
    id: 'sources',
    header: 'Sources',
    render: (a) => (a.source_count ? String(a.source_count) : muted('Manual only')),
  },
  {
    id: 'modified',
    header: 'Modified',
    className: 'nowrap',
    render: (a) => formatDateTime(a.modified_at),
  },
]

export const DEFAULT_COLUMNS: AssetColumn[] = COLUMNS.map((c) => c.id).filter(
  (id) => id !== 'observation_status',
)

const storageKey = (userId: string) => `itam.assets.columns.${userId}`

/** Per-user column preference. Unknown or stale ids are dropped; name is always kept. */
export function loadColumns(userId: string | undefined): AssetColumn[] {
  if (!userId) return DEFAULT_COLUMNS
  try {
    const raw = window.localStorage.getItem(storageKey(userId))
    if (!raw) return DEFAULT_COLUMNS
    return normalizeColumns(JSON.parse(raw))
  } catch {
    return DEFAULT_COLUMNS
  }
}

export function saveColumns(userId: string | undefined, columns: AssetColumn[]) {
  if (!userId) return
  try {
    window.localStorage.setItem(storageKey(userId), JSON.stringify(columns))
  } catch {
    // Storage may be unavailable (private mode); the choice then lasts for the session only.
  }
}

export function normalizeColumns(value: unknown): AssetColumn[] {
  const known = new Set(COLUMNS.map((c) => c.id))
  const list = Array.isArray(value) ? value.filter((v): v is AssetColumn => known.has(v)) : []
  const unique = [...new Set(list)]
  return unique.includes('name') ? unique : ['name', ...unique]
}
