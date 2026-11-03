import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  archiveAsset,
  assetKeys,
  fetchAsset,
  fetchAssetHistory,
  fetchCategories,
  fetchCategoryFields,
  previewClassification,
  reclassifyAsset,
  restoreAsset,
} from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import { PERMISSIONS, type AssetDetail, type AssetHistoryEntry } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { Tabs } from '../../shared/ui/Tabs'
import { EvidencePanel } from '../discovery/EvidencePanel'
import { FieldEvidenceDrawer } from '../discovery/FieldEvidenceDrawer'
import { NetworkEvidencePanel } from '../discovery/NetworkEvidencePanel'
import { CustomFieldInputs } from './CustomFieldInputs'
import { toApiValues, type CustomValues } from './customValues'
import {
  BUSINESS_STATUS,
  BUSINESS_TONE,
  OBSERVATION_STATUS,
  OBSERVATION_TONE,
  SUPPORT_STATUS,
  SUPPORT_TONE,
  categoryOptions,
} from './labels'

const SOURCE_LABEL: Record<string, string> = {
  manual: 'Manual',
  librenms: 'LibreNMS',
  endpoint_central: 'Endpoint Central',
  intune: 'Intune',
  defender: 'Defender',
  import: 'Import',
}

const CHANGE_LABEL: Record<AssetHistoryEntry['change_type'], string> = {
  created: 'Created',
  updated: 'Updated',
  reassigned: 'Reassigned',
  reclassified: 'Reclassified',
  archived: 'Archived',
  restored: 'Restored',
  discovered: 'Updated from source',
  linked: 'Source linked',
  unlinked: 'Source unlinked',
  merged: 'Merged',
  unmerged: 'Merge reverted',
  field_locked: 'Field locked',
  field_unlocked: 'Field unlocked',
}

export function AssetDetailPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const asset = useQuery({ queryKey: assetKeys.detail(id), queryFn: () => fetchAsset(id) })
  const [notice, setNotice] = useState<string | null>(
    (location.state as { notice?: string } | null)?.notice ?? null,
  )

  if (asset.isPending) return <LoadingState label="Loading asset…" />
  if (asset.isError) {
    return (
      <div className="page">
        <nav aria-label="Breadcrumb" className="breadcrumb">
          <Link to="/assets">Assets</Link>
        </nav>
        <QueryErrorState error={asset.error} what="this asset" />
      </div>
    )
  }
  const data = asset.data
  const tab = params.get('tab') ?? 'overview'

  return (
    <div className="page page--wide">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/assets">Assets</Link>
      </nav>
      <PageHeader
        title={data.name}
        meta={
          <>
            {data.asset_tag && <span className="mono">{data.asset_tag}</span>}
            <span>{data.category.path}</span>
            <span className="mono">{data.site.code}</span>
          </>
        }
        actions={<AssetActions asset={data} onDone={setNotice} />}
      />
      <dl className="status-strip" aria-label="Status">
        <div>
          <dt>Business</dt>
          <dd>
            <StatusBadge
              tone={BUSINESS_TONE[data.business_status]}
              label={BUSINESS_STATUS[data.business_status]}
            />
          </dd>
        </div>
        <div>
          <dt>Observation</dt>
          <dd>
            <StatusBadge
              tone={OBSERVATION_TONE[data.observation_status]}
              label={OBSERVATION_STATUS[data.observation_status]}
            />
          </dd>
        </div>
        <div>
          <dt>Support</dt>
          <dd>
            <StatusBadge
              tone={SUPPORT_TONE[data.support_status]}
              label={SUPPORT_STATUS[data.support_status]}
            />
          </dd>
        </div>
      </dl>
      {data.is_archived && (
        <p className="inline-note inline-note--warning" role="note">
          Archived {formatDateTime(data.archived_at)} by {data.archived_by ?? 'unknown'}:{' '}
          {data.archive_reason || 'no reason recorded'}. The record is read-only until restored.
        </p>
      )}
      {notice && (
        <p className="inline-success" role="status">
          {notice}
        </p>
      )}
      <Tabs
        label="Asset sections"
        selected={tab}
        onSelect={(next) => {
          const search = new URLSearchParams(params)
          if (next === 'overview') search.delete('tab')
          else search.set('tab', next)
          setParams(search, { replace: true })
        }}
        tabs={[
          { id: 'overview', label: 'Overview', content: <Overview asset={data} /> },
          {
            id: 'network',
            label: 'Network',
            content: <Network asset={data} evidence={can(PERMISSIONS.discoveryView)} />,
          },
          ...(can(PERMISSIONS.discoveryView)
            ? [{ id: 'evidence', label: 'Source evidence', content: <EvidencePanel asset={data} /> }]
            : []),
          { id: 'history', label: 'History', content: <History assetId={data.id} /> },
        ]}
      />
    </div>
  )
}

// --- Overview --------------------------------------------------------------------------

function Overview({ asset }: { asset: AssetDetail }) {
  const fields = useQuery({
    queryKey: assetKeys.fields(asset.category.id, true),
    queryFn: () => fetchCategoryFields(asset.category.id, true),
  })
  const { can } = useSession()
  const [evidenceField, setEvidenceField] = useState<string | null>(null)
  const unset = (text = 'Not recorded') => <span className="cell-muted">{text}</span>
  const technical: { field: keyof AssetDetail; label: string; mono?: boolean; empty?: string }[] = [
    { field: 'manufacturer', label: 'Manufacturer', empty: 'Unknown' },
    { field: 'model', label: 'Model', empty: 'Unknown' },
    { field: 'serial_number', label: 'Serial number', mono: true },
    { field: 'os_name', label: 'Operating system' },
    { field: 'os_version', label: 'OS version', mono: true },
    { field: 'firmware_version', label: 'Firmware', mono: true },
  ]

  return (
    <div className="detail-layout">
      <div className="detail-layout__main">
        <section className="panel" aria-labelledby="hw-heading">
          <h2 className="section-title" id="hw-heading">
            Hardware and software
          </h2>
          <dl className="meta-grid meta-grid--two">
            {technical.map(({ field, label, mono, empty }) => (
              <div className="meta-grid__pair" key={field}>
                <dt>{label}</dt>
                <dd className={mono ? 'mono' : undefined}>
                  {(asset[field] as string) || unset(empty)}
                  {can(PERMISSIONS.discoveryView) && (
                    <button
                      type="button"
                      className="link-button evidence-trigger"
                      aria-haspopup="dialog"
                      onClick={() => setEvidenceField(field)}
                    >
                      Evidence<span className="visually-hidden"> for {label}</span>
                    </button>
                  )}
                </dd>
              </div>
            ))}
            <dt>Primary hostname</dt>
            <dd className="mono">{asset.primary_hostname ?? unset('None')}</dd>
            <dt>Primary IP</dt>
            <dd className="mono">{asset.primary_ip ?? unset('None')}</dd>
          </dl>
          <FieldEvidenceDrawer
            assetId={asset.id}
            field={evidenceField}
            onClose={() => setEvidenceField(null)}
          />
        </section>

        <section className="panel" aria-labelledby="cf-heading">
          <h2 className="section-title" id="cf-heading">
            Category fields
          </h2>
          {asset.missing_required_fields.length > 0 && (
            <p className="inline-note inline-note--warning" role="note">
              Required but empty: {asset.missing_required_fields.join(', ')}.
            </p>
          )}
          {fields.isPending && <LoadingState label="Loading fields…" />}
          {fields.isError && <QueryErrorState error={fields.error} what="category fields" />}
          {fields.data && fields.data.length === 0 && asset.retained_custom_fields.length === 0 && (
            <EmptyState title="This category has no custom fields." />
          )}
          {fields.data && fields.data.length > 0 && (
            <dl className="meta-grid meta-grid--two">
              {fields.data.map((definition) => {
                const value = asset.custom_fields[definition.key]
                return (
                  <div className="meta-grid__pair" key={definition.id}>
                    <dt>{definition.label}</dt>
                    <dd>
                      {value === undefined || value === null || value === ''
                        ? unset('Not set')
                        : typeof value === 'boolean'
                          ? value
                            ? 'Yes'
                            : 'No'
                          : String(value)}
                    </dd>
                  </div>
                )
              })}
            </dl>
          )}
          {asset.retained_custom_fields.length > 0 && (
            <>
              <h3 className="subsection-title">Retained from a previous category (read-only)</h3>
              <dl className="meta-grid meta-grid--two">
                {asset.retained_custom_fields.map((key) => (
                  <div className="meta-grid__pair" key={key}>
                    <dt className="mono">{key}</dt>
                    <dd>{String(asset.custom_fields[key])}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </section>

        <section className="panel" aria-labelledby="notes-heading">
          <h2 className="section-title" id="notes-heading">
            Notes
          </h2>
          {asset.notes ? <p className="notes">{asset.notes}</p> : unset('No notes.')}
        </section>
      </div>
      <aside className="detail-layout__side">
        <section className="panel" aria-labelledby="own-heading">
          <h2 className="section-title" id="own-heading">
            Location and ownership
          </h2>
          <dl className="meta-grid meta-grid--stacked">
            <dt>Site</dt>
            <dd>
              <span className="mono">{asset.site.code}</span> {asset.site.name}
            </dd>
            <dt>Location</dt>
            <dd>{asset.location?.name ?? unset('Not set')}</dd>
            <dt>Department</dt>
            <dd>{asset.department?.name ?? unset('Not set')}</dd>
            <dt>Owner</dt>
            <dd>
              {asset.owner ? (
                <>
                  {asset.owner.display_name} <span className="mono">({asset.owner.username})</span>
                </>
              ) : (
                unset('Unassigned')
              )}
            </dd>
          </dl>
        </section>
        <section className="panel" aria-labelledby="rec-heading">
          <h2 className="section-title" id="rec-heading">
            Record
          </h2>
          <dl className="meta-grid meta-grid--stacked">
            <dt>Created</dt>
            <dd>
              {formatDateTime(asset.created_at)}
              {asset.created_by && ` by ${asset.created_by}`}
            </dd>
            <dt>Last modified</dt>
            <dd>
              {formatDateTime(asset.modified_at)}
              {asset.modified_by && ` by ${asset.modified_by}`}
            </dd>
            <dt>Record version</dt>
            <dd className="mono">{asset.version}</dd>
            <dt>Asset ID</dt>
            <dd className="mono">{asset.id}</dd>
          </dl>
        </section>
      </aside>
    </div>
  )
}

// --- Network -----------------------------------------------------------------------

function Network({ asset, evidence }: { asset: AssetDetail; evidence: boolean }) {
  const sourceCell = (row: { source: string; source_ref: string; observed_at: string | null }) => (
    <>
      {SOURCE_LABEL[row.source] ?? row.source}
      {row.source_ref && <span className="cell-secondary mono">{row.source_ref}</span>}
    </>
  )
  const observed = (value: string | null) =>
    value ? formatDateTime(value) : <span className="cell-muted">Not observed</span>

  return (
    <div className="stack">
      <section className="panel panel--flush" aria-labelledby="net-hosts">
        <h2 className="section-title section-title--inset" id="net-hosts">
          Hostnames
        </h2>
        {asset.hostnames.length === 0 ? (
          <EmptyState title="No hostnames recorded." />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Hostname</th>
                <th scope="col">Primary</th>
                <th scope="col">Source</th>
                <th scope="col">Last observed</th>
              </tr>
            </thead>
            <tbody>
              {asset.hostnames.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.hostname}</td>
                  <td>{row.is_primary ? 'Yes' : 'No'}</td>
                  <td>{sourceCell(row)}</td>
                  <td className="nowrap">{observed(row.observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="panel panel--flush" aria-labelledby="net-ifs">
        <h2 className="section-title section-title--inset" id="net-ifs">
          Interfaces
        </h2>
        {asset.interfaces.length === 0 ? (
          <EmptyState title="No interfaces recorded." />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">MAC address</th>
                <th scope="col">Source</th>
                <th scope="col">Last observed</th>
              </tr>
            </thead>
            <tbody>
              {asset.interfaces.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.name}</td>
                  <td className="mono">
                    {row.mac_address || <span className="cell-muted">Not reported</span>}
                  </td>
                  <td>{sourceCell(row)}</td>
                  <td className="nowrap">{observed(row.observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="panel panel--flush" aria-labelledby="net-ips">
        <h2 className="section-title section-title--inset" id="net-ips">
          IP addresses
        </h2>
        {asset.ip_addresses.length === 0 ? (
          <EmptyState title="No IP addresses recorded." />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Address</th>
                <th scope="col">Interface</th>
                <th scope="col">Primary</th>
                <th scope="col">Source</th>
                <th scope="col">Last observed</th>
              </tr>
            </thead>
            <tbody>
              {asset.ip_addresses.map((row) => (
                <tr key={row.id}>
                  <td className="mono">{row.address}</td>
                  <td className="mono">
                    {row.interface_name ?? <span className="cell-muted">None</span>}
                  </td>
                  <td>{row.is_primary ? 'Yes' : 'No'}</td>
                  <td>{sourceCell(row)}</td>
                  <td className="nowrap">{observed(row.observed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {evidence && <NetworkEvidencePanel assetId={asset.id} />}
    </div>
  )
}

// --- History -----------------------------------------------------------------------

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '(empty)'
  if (Array.isArray(value)) return value.length ? value.join(', ') : '(none)'
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    return entries.length ? entries.map(([k, v]) => `${k}: ${String(v)}`).join('; ') : '(none)'
  }
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

function History({ assetId }: { assetId: string }) {
  const history = useInfiniteQuery({
    queryKey: assetKeys.history(assetId),
    queryFn: ({ pageParam }) => fetchAssetHistory(assetId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = history.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <section className="panel panel--flush" aria-live="polite">
      {history.isPending && <LoadingState label="Loading history…" />}
      {history.isError && <QueryErrorState error={history.error} what="asset history" />}
      {history.isSuccess && items.length === 0 && <EmptyState title="No history recorded." />}
      {items.length > 0 && (
        <table className="data-table">
          <caption className="visually-hidden">Asset history, newest first</caption>
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Who</th>
              <th scope="col">Change</th>
              <th scope="col">Details</th>
            </tr>
          </thead>
          <tbody>
            {items.map((entry) => (
              <tr key={entry.id} className="row--top">
                <td className="nowrap">{formatDateTime(entry.occurred_at)}</td>
                <td className="mono">{entry.actor_label}</td>
                <td className="nowrap">
                  {CHANGE_LABEL[entry.change_type]}
                  <span className="cell-secondary">v{entry.version}</span>
                </td>
                <td>
                  {entry.reason && <p className="history-reason">Reason: {entry.reason}</p>}
                  <ul className="change-list">
                    {Object.entries(entry.changes as Record<string, { before: unknown; after: unknown }>).map(
                      ([field, change]) => (
                        <li key={field}>
                          <span className="mono">{field}</span>:{' '}
                          {entry.change_type === 'created' ? (
                            show(change.after)
                          ) : (
                            <>
                              {show(change.before)} <span aria-hidden="true">→</span>
                              <span className="visually-hidden"> changed to </span>{' '}
                              {show(change.after)}
                            </>
                          )}
                        </li>
                      ),
                    )}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {history.hasNextPage && (
        <div className="table-footer">
          <Button onClick={() => history.fetchNextPage()} busy={history.isFetchingNextPage}>
            Load more
          </Button>
        </div>
      )}
    </section>
  )
}

// --- Actions: reclassify, archive, restore --------------------------------------------

type Action = 'reclassify' | 'archive' | 'restore' | null

function AssetActions({ asset, onDone }: { asset: AssetDetail; onDone: (m: string) => void }) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const [action, setAction] = useState<Action>(null)
  const [reason, setReason] = useState('')
  const [target, setTarget] = useState('')
  const [custom, setCustom] = useState<CustomValues>({})
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({})

  const categories = useQuery({
    queryKey: assetKeys.categories,
    queryFn: fetchCategories,
    enabled: action === 'reclassify',
  })
  const targetFields = useQuery({
    queryKey: assetKeys.fields(target, true),
    queryFn: () => fetchCategoryFields(target, true),
    enabled: action === 'reclassify' && Boolean(target),
  })
  const impact = useQuery({
    queryKey: ['assets', 'impact', asset.id, target],
    queryFn: () => previewClassification(asset.id, target),
    enabled: action === 'reclassify' && Boolean(target),
  })

  const mutation = useMutation({
    mutationFn: async (kind: Exclude<Action, null>) => {
      if (kind === 'archive') return archiveAsset(asset.id, asset.version, reason.trim())
      if (kind === 'restore') return restoreAsset(asset.id, asset.version)
      const needed = (targetFields.data ?? []).filter((d) =>
        impact.data?.required_missing.includes(d.key),
      )
      return reclassifyAsset(asset.id, asset.version, {
        category: target,
        reason: reason.trim(),
        custom_fields: Object.fromEntries(
          Object.entries(toApiValues(needed, custom)).filter(([, v]) => v !== null),
        ),
      })
    },
    onSuccess: (updated, kind) => {
      queryClient.setQueryData(assetKeys.detail(asset.id), updated)
      queryClient.invalidateQueries({ queryKey: ['assets', 'list'] })
      queryClient.invalidateQueries({ queryKey: assetKeys.history(asset.id) })
      onDone(
        {
          archive: `${asset.name} archived. It is hidden from the default inventory view.`,
          restore: `${asset.name} restored.`,
          reclassify: `Category changed to ${updated.category.path}.`,
        }[kind],
      )
      setAction(null)
    },
  })

  function open(kind: Exclude<Action, null>) {
    mutation.reset()
    setReason('')
    setTarget('')
    setCustom({})
    setClientErrors({})
    setAction(kind)
  }

  function confirm() {
    if (!action) return
    const errors: Record<string, string[]> = {}
    if (action !== 'restore' && reason.trim().length < 5) {
      errors.reason = ['Enter a reason of at least 5 characters.']
    }
    if (action === 'reclassify' && !target) errors.category = ['Choose the new category.']
    setClientErrors(errors)
    if (Object.keys(errors).length === 0) mutation.mutate(action)
  }

  const serverErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = { ...serverErrors, ...clientErrors }
  const summary =
    mutation.error && Object.keys(serverErrors).length === 0 ? mutation.error.message : null
  const archived = asset.is_archived
  const neededFields = (targetFields.data ?? []).filter((d) =>
    impact.data?.required_missing.includes(d.key),
  )

  return (
    <>
      {!archived && can(PERMISSIONS.assetsEdit) && (
        <Link className="button button--primary" to={`/assets/${asset.id}/edit`}>
          Edit
        </Link>
      )}
      {!archived && can(PERMISSIONS.assetsReclassify) && (
        <Button onClick={() => open('reclassify')}>Change category</Button>
      )}
      {can(PERMISSIONS.assetsArchive) &&
        (archived ? (
          <Button onClick={() => open('restore')}>Restore</Button>
        ) : (
          <Button variant="quiet" className="button--danger-quiet" onClick={() => open('archive')}>
            Archive
          </Button>
        ))}

      <Dialog
        open={action === 'archive'}
        title={`Archive ${asset.name}?`}
        confirmLabel="Archive asset"
        confirmVariant="danger"
        busy={mutation.isPending}
        onConfirm={confirm}
        onClose={() => setAction(null)}
      >
        <p>
          Affects 1 asset. It is hidden from the default inventory and becomes read-only. Nothing
          is deleted; history and identifiers are kept, and it can be restored.
        </p>
        {summary && <p className="field__error">{summary}</p>}
        <TextAreaField
          label="Reason"
          name="archive_reason"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          error={errors.reason}
          help="Recorded in the asset history and audit log."
          autoFocus
        />
      </Dialog>

      <Dialog
        open={action === 'restore'}
        title={`Restore ${asset.name}?`}
        confirmLabel="Restore asset"
        busy={mutation.isPending}
        onConfirm={confirm}
        onClose={() => setAction(null)}
      >
        <p>The asset returns to the inventory and can be edited again.</p>
        {summary && <p className="field__error">{summary}</p>}
      </Dialog>

      <Dialog
        open={action === 'reclassify'}
        title={`Change category of ${asset.name}`}
        confirmLabel="Change category"
        busy={mutation.isPending}
        onConfirm={confirm}
        onClose={() => setAction(null)}
      >
        <p>
          Current: <strong>{asset.category.path}</strong>
        </p>
        {summary && <p className="field__error">{summary}</p>}
        <SelectField
          label="New category"
          name="new_category"
          options={[
            { value: '', label: 'Choose a category' },
            ...categoryOptions(categories.data ?? [], { activeOnly: true }).filter(
              (o) => o.value !== asset.category.id,
            ),
          ]}
          value={target}
          onChange={(e) => {
            setTarget(e.target.value)
            setCustom({})
          }}
          error={errors.category}
        />
        {target && impact.isPending && <LoadingState label="Checking field impact…" />}
        {impact.data && (
          <div className="impact" aria-live="polite">
            <p className="subsection-title">Field impact</p>
            <ul className="change-list">
              <li>
                Added:{' '}
                {impact.data.fields_added.length
                  ? impact.data.fields_added
                      .map((f) => `${f.label}${f.required ? ' (required)' : ''}`)
                      .join(', ')
                  : 'none'}
              </li>
              <li>
                Kept:{' '}
                {impact.data.fields_kept.length ? impact.data.fields_kept.join(', ') : 'none'}
              </li>
              <li>
                Retained read-only:{' '}
                {impact.data.values_retained_read_only.length
                  ? impact.data.values_retained_read_only.join(', ')
                  : 'none'}
              </li>
            </ul>
          </div>
        )}
        {neededFields.length > 0 && (
          <CustomFieldInputs
            definitions={neededFields}
            values={custom}
            errors={errors}
            onChange={(key, value) => setCustom((c) => ({ ...c, [key]: value }))}
          />
        )}
        <TextAreaField
          label="Reason"
          name="reclassify_reason"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          error={errors.reason}
          help="Required. Recorded in the asset history and audit log."
        />
      </Dialog>
    </>
  )
}
