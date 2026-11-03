import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { assetKeys, fetchAssets } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import {
  discoveryKeys,
  fetchEvidence,
  lockField,
  mergeAssets,
  revertMerge,
  unlinkSource,
  unlockField,
} from '../../shared/api/discovery'
import {
  PERMISSIONS,
  type AssetDetail,
  type AssetMerge,
  type FieldConflict,
  type FieldEvidence,
  type SourceLink,
} from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ResolveDialog } from './DiscoveryPage'
import { FIELD_LABEL } from './labels'

const METHOD_LABEL: Record<SourceLink['method'], string> = {
  approved_candidate: 'Approved match',
  created_from_candidate: 'Created from discovery',
  auto_strong_match: 'Automatic strong match',
  merge: 'Moved by merge',
}

type Pending =
  | { kind: 'lock' | 'unlock'; field: FieldEvidence }
  | { kind: 'unlink'; link: SourceLink }
  | { kind: 'revert'; merge: AssetMerge }
  | { kind: 'merge' }
  | { kind: 'resolve'; conflict: FieldConflict; accept: boolean }
  | null

export function EvidencePanel({ asset }: { asset: AssetDetail }) {
  const { can } = useSession()
  const evidence = useQuery({
    queryKey: discoveryKeys.evidence(asset.id),
    queryFn: () => fetchEvidence(asset.id),
  })
  const [pending, setPending] = useState<Pending>(null)
  const canTechnical = can(PERMISSIONS.assetsEditTechnical)

  if (evidence.isPending) return <LoadingState label="Loading source evidence…" />
  if (evidence.isError) return <QueryErrorState error={evidence.error} what="source evidence" />
  const data = evidence.data

  return (
    <div className="stack">
      <section className="panel panel--flush" aria-labelledby="ev-fields">
        <h2 className="section-title section-title--inset" id="ev-fields">
          Technical fields and their sources
        </h2>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Current value</th>
                <th scope="col">Set by</th>
                <th scope="col">Lock</th>
                <th scope="col">Reported by sources</th>
              </tr>
            </thead>
            <tbody>
              {data.field_evidence.map((row) => (
                <tr key={row.field} className="row--top">
                  <th scope="row">{FIELD_LABEL[row.field] ?? row.field}</th>
                  <td className="mono">{row.value || <span className="cell-muted">Unknown</span>}</td>
                  <td>
                    {row.provenance === null ? (
                      <span className="cell-muted">Not recorded</span>
                    ) : row.provenance.kind === 'manual' ? (
                      <>
                        Manual
                        <span className="cell-secondary">
                          {row.provenance.recorded_by ?? 'unknown'}, {formatDateTime(row.provenance.recorded_at)}
                        </span>
                      </>
                    ) : (
                      <>
                        {row.provenance.instance?.name}
                        <span className="cell-secondary">observed {formatDateTime(row.provenance.observed_at)}</span>
                      </>
                    )}
                  </td>
                  <td>
                    {row.lock ? (
                      <>
                        <StatusBadge tone="warning" label="Locked" />
                        <span className="cell-secondary">
                          {row.lock.locked_by ?? 'unknown'}: {row.lock.reason || 'no reason'}
                        </span>
                      </>
                    ) : (
                      <span className="cell-muted">Unlocked</span>
                    )}
                    {canTechnical && (
                      <Button
                        variant="quiet"
                        onClick={() => setPending({ kind: row.lock ? 'unlock' : 'lock', field: row })}
                      >
                        {row.lock ? 'Unlock' : 'Lock'}
                        <span className="visually-hidden"> {FIELD_LABEL[row.field]}</span>
                      </Button>
                    )}
                  </td>
                  <td>
                    {row.sources.length === 0 ? (
                      <span className="cell-muted">No linked source</span>
                    ) : (
                      <ul className="change-list change-list--plain">
                        {row.sources.map((s) => (
                          <li key={`${s.instance.id}-${s.external_id}`}>
                            <span className="mono">{s.value ?? 'not reported'}</span> · {s.instance.name}
                            {s.link_status === 'stale' && ' (stale)'}
                            {s.differs && (
                              <>
                                {' '}
                                <StatusBadge tone="warning" label="Differs" />
                              </>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {row.open_conflicts.map((c) => (
                      <p key={c.id} className="conflict-note">
                        Conflict: {c.instance.name} reports <span className="mono">{c.observed_value}</span>.
                        {canTechnical && (
                          <>
                            {' '}
                            <button type="button" className="link-button" onClick={() => setPending({ kind: 'resolve', conflict: c, accept: true })}>
                              Accept
                            </button>{' '}
                            <button type="button" className="link-button" onClick={() => setPending({ kind: 'resolve', conflict: c, accept: false })}>
                              Keep current
                            </button>
                          </>
                        )}
                      </p>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="field__help table-note">
          Manually entered values are locked automatically; sources can only raise a conflict for them.
        </p>
      </section>

      <section className="panel panel--flush" aria-labelledby="ev-links">
        <h2 className="section-title section-title--inset" id="ev-links">
          Linked sources
        </h2>
        {data.links.length === 0 ? (
          <EmptyState title="No source reports this asset.">It is maintained manually only.</EmptyState>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Integration</th>
                <th scope="col">Device ID</th>
                <th scope="col">Status</th>
                <th scope="col">How linked</th>
                <th scope="col">First seen</th>
                <th scope="col">Last seen</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.links.map((link) => (
                <tr key={link.id}>
                  <td>{link.instance.name}</td>
                  <td className="mono">{link.external_id}</td>
                  <td>
                    <StatusBadge
                      tone={link.status === 'active' ? 'success' : 'warning'}
                      label={link.status === 'active' ? 'Active' : 'Stale'}
                    />
                  </td>
                  <td>
                    {METHOD_LABEL[link.method]}
                    {link.linked_by && <span className="cell-secondary">by {link.linked_by}</span>}
                  </td>
                  <td className="nowrap">{formatDateTime(link.first_seen_at)}</td>
                  <td className="nowrap">{formatDateTime(link.last_seen_at)}</td>
                  <td>
                    {can(PERMISSIONS.reconciliationDecide) && (
                      <Button variant="quiet" className="button--danger-quiet" onClick={() => setPending({ kind: 'unlink', link })}>
                        Unlink<span className="visually-hidden"> {link.instance.name} {link.external_id}</span>
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel panel--flush" aria-labelledby="ev-merges">
        <div className="section-header section-header--inset">
          <h2 className="section-title" id="ev-merges">
            Merges
          </h2>
          {can(PERMISSIONS.assetsMerge) && !asset.is_archived && (
            <Button onClick={() => setPending({ kind: 'merge' })}>Merge a duplicate into this asset</Button>
          )}
        </div>
        {data.merges.length === 0 ? (
          <EmptyState title="No merges involve this asset." />
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Kept asset</th>
                <th scope="col">Merged (archived) asset</th>
                <th scope="col">When</th>
                <th scope="col">Reason</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.merges.map((m) => (
                <tr key={m.id}>
                  <td>
                    <Link to={`/assets/${m.survivor.id}`}>{m.survivor.name}</Link>
                  </td>
                  <td>
                    <Link to={`/assets/${m.merged.id}`}>{m.merged.name}</Link>
                  </td>
                  <td className="nowrap">
                    {formatDateTime(m.performed_at)}
                    <span className="cell-secondary">by {m.performed_by}</span>
                  </td>
                  <td>{m.reason}</td>
                  <td>{m.status === 'merged' ? 'Merged' : `Reverted by ${m.reverted_by ?? 'unknown'}`}</td>
                  <td>
                    {m.status === 'merged' && can(PERMISSIONS.assetsMerge) && (
                      <Button variant="quiet" onClick={() => setPending({ kind: 'revert', merge: m })}>
                        Revert<span className="visually-hidden"> merge of {m.merged.name}</span>
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {pending?.kind === 'resolve' && (
        <ResolveDialog conflict={pending.conflict} accept={pending.accept} onClose={() => setPending(null)} />
      )}
      {pending && pending.kind !== 'resolve' && (
        <ActionDialog asset={asset} pending={pending} onClose={() => setPending(null)} />
      )}
    </div>
  )
}

function ActionDialog({
  asset,
  pending,
  onClose,
}: {
  asset: AssetDetail
  pending: Exclude<Pending, null | { kind: 'resolve' }>
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [search, setSearch] = useState('')
  const [target, setTarget] = useState('')
  const [errors, setErrors] = useState<Record<string, string[]>>({})
  const candidates = useQuery({
    queryKey: assetKeys.list({ q: search, ordering: 'name' }),
    queryFn: () => fetchAssets({ q: search || undefined, ordering: 'name' }),
    enabled: pending.kind === 'merge' && search.trim().length >= 2,
  })

  const mutation = useMutation({
    mutationFn: async (): Promise<unknown> => {
      const why = reason.trim()
      switch (pending.kind) {
        case 'lock':
          return lockField(asset.id, pending.field.field, why)
        case 'unlock':
          return unlockField(asset.id, pending.field.field, why)
        case 'unlink':
          return unlinkSource(pending.link.id, why)
        case 'revert':
          return revertMerge(pending.merge.id, why)
        case 'merge':
          return mergeAssets(asset.id, asset.version, target, why)
      }
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['discovery'] })
      onClose()
    },
  })

  const field = 'field' in pending ? (FIELD_LABEL[pending.field.field] ?? pending.field.field) : ''
  const text = {
    lock: {
      title: `Lock ${field}?`,
      body: `Sources will no longer change ${field} on ${asset.name}; a different reported value raises a conflict instead.`,
      confirm: 'Lock field',
    },
    unlock: {
      title: `Unlock ${field}?`,
      body: `The next report from the highest-authority source may replace the current ${field}.`,
      confirm: 'Unlock field',
    },
    unlink: {
      title: 'Unlink this source?',
      body:
        pending.kind === 'unlink'
          ? `Affects 1 source link (${pending.link.instance.name} / ${pending.link.external_id}). Its identifiers are removed from ${asset.name} and the device returns to the reconciliation queue. Field values and history are kept.`
          : '',
      confirm: 'Unlink source',
    },
    revert: {
      title: 'Revert this merge?',
      body:
        pending.kind === 'revert'
          ? `Restores ${pending.merge.merged.name} and moves its ${pending.merge.moved_link_ids.length} source link(s) and discovered identifiers back.`
          : '',
      confirm: 'Revert merge',
    },
    merge: {
      title: `Merge a duplicate into ${asset.name}`,
      body: `The chosen asset's source links and discovered identifiers move to ${asset.name}; the duplicate is archived (not deleted). This can be reverted.`,
      confirm: 'Merge assets',
    },
  }[pending.kind]

  const options = (candidates.data?.items ?? []).filter((a) => a.id !== asset.id && !a.is_archived)

  return (
    <Dialog
      open
      title={text.title}
      confirmLabel={text.confirm}
      confirmVariant={pending.kind === 'unlink' || pending.kind === 'merge' ? 'danger' : 'primary'}
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        const errs: Record<string, string[]> = {}
        if (reason.trim().length < 5) errs.reason = ['Enter a reason of at least 5 characters.']
        if (pending.kind === 'merge' && !target) errs.target = ['Choose the duplicate asset.']
        setErrors(errs)
        if (!Object.keys(errs).length) mutation.mutate()
      }}
    >
      <p>{text.body}</p>
      {mutation.error && (
        <p className="field__error">
          {isApiError(mutation.error) ? mutation.error.message : 'The action failed.'}
        </p>
      )}
      {pending.kind === 'merge' && (
        <>
          <TextField
            label="Find the duplicate"
            name="merge_search"
            placeholder="Name, tag, serial, hostname…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
          <SelectField
            label="Duplicate asset"
            name="merge_target"
            options={[
              { value: '', label: search.trim().length < 2 ? 'Type at least 2 characters' : 'Choose an asset' },
              ...options.map((a) => ({ value: a.id, label: `${a.name}${a.asset_tag ? ` (${a.asset_tag})` : ''} · ${a.site.code}` })),
            ]}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            error={errors.target}
          />
        </>
      )}
      <TextAreaField
        label="Reason"
        name="action_reason"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        error={errors.reason}
        help="Recorded in the asset history and audit log."
        autoFocus={pending.kind !== 'merge'}
      />
    </Dialog>
  )
}
