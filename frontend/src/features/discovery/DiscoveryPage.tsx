import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  discoveryKeys,
  fetchCandidates,
  fetchConflicts,
  fetchIntegrations,
  fetchRuns,
  resolveConflict,
  type CandidateFilters,
} from '../../shared/api/discovery'
import { isApiError } from '../../shared/api/client'
import { PERMISSIONS, type FieldConflict, type SyncRun } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge, type StatusTone } from '../../shared/ui/StatusBadge'
import { Tabs } from '../../shared/ui/Tabs'
import {
  CANDIDATE_STATUS,
  FIELD_LABEL,
  FRESHNESS,
  INSTANCE_STATUS,
  RULE_LABEL,
  RULE_TONE,
  scoreLabel,
} from './labels'

export function DiscoveryPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'queue'
  return (
    <div className="page page--wide">
      <PageHeader
        title="Discovery"
        meta="Devices reported by integration sources, matched against the asset register. Nothing is merged or created without a decision."
      />
      <Tabs
        label="Discovery sections"
        selected={tab}
        onSelect={(next) => setParams(next === 'queue' ? {} : { tab: next }, { replace: true })}
        tabs={[
          { id: 'queue', label: 'Reconciliation queue', content: <Queue /> },
          { id: 'conflicts', label: 'Field conflicts', content: <Conflicts /> },
          { id: 'sources', label: 'Sources', content: <Sources /> },
        ]}
      />
    </div>
  )
}

// --- Queue ---------------------------------------------------------------------------

function Queue() {
  const [params, setParams] = useSearchParams()
  const filters: CandidateFilters = {
    status: params.get('status') ?? undefined,
    rule: params.get('rule') ?? undefined,
    instance: params.get('instance') ?? undefined,
  }
  const integrations = useQuery({ queryKey: discoveryKeys.integrations, queryFn: fetchIntegrations })
  const candidates = useInfiniteQuery({
    queryKey: discoveryKeys.candidates(filters),
    queryFn: ({ pageParam }) => fetchCandidates(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })

  function update(next: Partial<CandidateFilters>) {
    const search = new URLSearchParams(params)
    for (const [key, value] of Object.entries(next)) {
      if (value) search.set(key, value)
      else search.delete(key)
    }
    setParams(search, { replace: true })
  }

  const items = candidates.data?.pages.flatMap((p) => p.items) ?? []
  const total = candidates.data?.pages[0]?.count

  return (
    <>
      <div className="toolbar">
        <SelectField
          label="Status"
          name="status"
          options={[
            { value: '', label: 'Needs decision (open and on hold)' },
            ...Object.entries(CANDIDATE_STATUS).map(([value, label]) => ({ value, label })),
            { value: 'all', label: 'All' },
          ]}
          value={filters.status ?? ''}
          onChange={(e) => update({ status: e.target.value || undefined })}
        />
        <SelectField
          label="Match type"
          name="rule"
          options={[
            { value: '', label: 'Any' },
            ...Object.entries(RULE_LABEL).map(([value, label]) => ({ value, label })),
          ]}
          value={filters.rule ?? ''}
          onChange={(e) => update({ rule: e.target.value || undefined })}
        />
        <SelectField
          label="Source"
          name="instance"
          options={[
            { value: '', label: 'All sources' },
            ...(integrations.data ?? []).map((i) => ({ value: i.id, label: i.name })),
          ]}
          value={filters.instance ?? ''}
          onChange={(e) => update({ instance: e.target.value || undefined })}
        />
        {total !== undefined && (
          <p className="toolbar__count" aria-live="polite">
            {total} {total === 1 ? 'device' : 'devices'}
          </p>
        )}
      </div>
      <section className="panel panel--flush" aria-live="polite">
        {candidates.isPending && <LoadingState label="Loading reconciliation queue…" />}
        {candidates.isError && <QueryErrorState error={candidates.error} what="the reconciliation queue" />}
        {candidates.isSuccess && items.length === 0 && (
          <EmptyState title="Nothing waiting for a decision.">
            New devices and uncertain matches from sources appear here.
          </EmptyState>
        )}
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Reconciliation candidates</caption>
              <thead>
                <tr>
                  <th scope="col">Device</th>
                  <th scope="col">Source</th>
                  <th scope="col">Match</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Proposed asset</th>
                  <th scope="col">Site</th>
                  <th scope="col">Observed</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => {
                  const n = c.observation.normalized as Record<string, unknown>
                  const host = (n.hostnames as string[] | undefined)?.[0]
                  const label = host ?? [n.manufacturer, n.model].filter(Boolean).join(' ')
                  return (
                    <tr key={c.id}>
                      <td>
                        <Link className="table-link" to={`/discovery/candidates/${c.id}`}>
                          {label || `Device ${c.external_id}`}
                        </Link>
                        <span className="cell-secondary mono">ID {c.external_id}</span>
                      </td>
                      <td>{c.instance.name}</td>
                      <td>
                        <StatusBadge tone={RULE_TONE[c.rule]} label={RULE_LABEL[c.rule]} />
                        {c.conflicts.length > 0 && (
                          <span className="cell-secondary">{c.conflicts.length} issue(s) to check</span>
                        )}
                      </td>
                      <td className="nowrap">{scoreLabel(c.score)}</td>
                      <td>
                        {c.proposed_asset ? (
                          <Link to={`/assets/${c.proposed_asset.id}`}>{c.proposed_asset.name}</Link>
                        ) : (
                          <span className="cell-muted">None</span>
                        )}
                        {c.hidden_match_count > 0 && (
                          <span className="cell-secondary">
                            +{c.hidden_match_count} in sites you cannot access
                          </span>
                        )}
                      </td>
                      <td className="mono">{c.site.code}</td>
                      <td className="nowrap">{formatDateTime(c.observation.observed_at)}</td>
                      <td>{CANDIDATE_STATUS[c.status]}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {candidates.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => candidates.fetchNextPage()} busy={candidates.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </section>
    </>
  )
}

// --- Field conflicts -------------------------------------------------------------------

function Conflicts() {
  const { can } = useSession()
  const [status, setStatus] = useState('open')
  const [resolving, setResolving] = useState<{ conflict: FieldConflict; accept: boolean } | null>(null)
  const conflicts = useInfiniteQuery({
    queryKey: discoveryKeys.conflicts(status),
    queryFn: ({ pageParam }) => fetchConflicts(status, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = conflicts.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <>
      <div className="toolbar">
        <SelectField
          label="Status"
          name="conflict_status"
          options={[
            { value: 'open', label: 'Open' },
            { value: 'accepted', label: 'Observed value accepted' },
            { value: 'dismissed', label: 'Current value kept' },
            { value: 'all', label: 'All' },
          ]}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        />
      </div>
      <section className="panel panel--flush" aria-live="polite">
        {conflicts.isPending && <LoadingState label="Loading field conflicts…" />}
        {conflicts.isError && <QueryErrorState error={conflicts.error} what="field conflicts" />}
        {conflicts.isSuccess && items.length === 0 && (
          <EmptyState title="No field conflicts.">
            Conflicts appear when a source reports a value different from a locked, manually approved value.
          </EmptyState>
        )}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Field conflicts</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Field</th>
                <th scope="col">Current (locked)</th>
                <th scope="col">Reported by source</th>
                <th scope="col">Source</th>
                <th scope="col">Observed</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <Link to={`/assets/${c.asset.id}?tab=evidence`}>{c.asset.name}</Link>
                  </td>
                  <td>{FIELD_LABEL[c.field] ?? c.field}</td>
                  <td className="mono">{c.current_value || <span className="cell-muted">Empty</span>}</td>
                  <td className="mono">{c.observed_value}</td>
                  <td>{c.instance.name}</td>
                  <td className="nowrap">{formatDateTime(c.observed_at)}</td>
                  <td className="cell-actions">
                    {c.status === 'open' && can(PERMISSIONS.assetsEditTechnical) ? (
                      <>
                        <Button variant="quiet" onClick={() => setResolving({ conflict: c, accept: true })}>
                          Accept<span className="visually-hidden"> reported value for {c.asset.name}</span>
                        </Button>
                        <Button variant="quiet" onClick={() => setResolving({ conflict: c, accept: false })}>
                          Keep<span className="visually-hidden"> current value for {c.asset.name}</span>
                        </Button>
                      </>
                    ) : (
                      <span className="cell-muted">
                        {c.status === 'open' ? 'Needs technical edit rights' : c.resolution_reason}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {resolving && <ResolveDialog {...resolving} onClose={() => setResolving(null)} />}
    </>
  )
}

export function ResolveDialog({
  conflict,
  accept,
  onClose,
}: {
  conflict: FieldConflict
  accept: boolean
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string[] | undefined>()
  const mutation = useMutation({
    mutationFn: () =>
      resolveConflict(conflict.id, accept ? 'accept_observed' : 'keep_current', reason.trim()),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['discovery', 'conflicts'] })
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      onClose()
    },
  })
  const field = FIELD_LABEL[conflict.field] ?? conflict.field
  return (
    <Dialog
      open
      title={accept ? `Accept reported ${field}?` : `Keep current ${field}?`}
      confirmLabel={accept ? 'Accept reported value' : 'Keep current value'}
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        if (reason.trim().length < 5) setError(['Enter a reason of at least 5 characters.'])
        else mutation.mutate()
      }}
    >
      <p>
        {accept
          ? `Sets ${field} on ${conflict.asset.name} to "${conflict.observed_value}" from ${conflict.instance.name} and removes the manual lock.`
          : `Keeps "${conflict.current_value}" on ${conflict.asset.name}. The field stays locked; the reported value is recorded as dismissed.`}
      </p>
      {mutation.error && (
        <p className="field__error">
          {isApiError(mutation.error) ? mutation.error.message : 'Could not resolve the conflict.'}
        </p>
      )}
      <TextAreaField
        label="Reason"
        name="resolve_reason"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        error={error}
        autoFocus
      />
    </Dialog>
  )
}

// --- Sources ---------------------------------------------------------------------------

const RUN_STATUS: Record<SyncRun['status'], { label: string; tone: StatusTone }> = {
  succeeded: { label: 'Succeeded', tone: 'success' },
  partial: { label: 'Partial', tone: 'warning' },
  failed: { label: 'Failed', tone: 'danger' },
  running: { label: 'Running', tone: 'neutral' },
}

function Sources() {
  const [selected, setSelected] = useState<string | null>(null)
  const integrations = useQuery({ queryKey: discoveryKeys.integrations, queryFn: fetchIntegrations })
  const runs = useQuery({
    queryKey: discoveryKeys.runs(selected ?? ''),
    queryFn: () => fetchRuns(selected!),
    enabled: Boolean(selected),
  })

  return (
    <div className="stack">
      <section className="panel panel--flush" aria-live="polite">
        {integrations.isPending && <LoadingState label="Loading sources…" />}
        {integrations.isError && <QueryErrorState error={integrations.error} what="sources" />}
        {integrations.data && integrations.data.length === 0 && (
          <EmptyState title="No integrations configured.">
            A System Admin can add one under Administration → Integrations.
          </EmptyState>
        )}
        {integrations.data && integrations.data.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Integration sources and freshness</caption>
            <thead>
              <tr>
                <th scope="col">Integration</th>
                <th scope="col">Status</th>
                <th scope="col">Freshness</th>
                <th scope="col">Last successful sync</th>
                <th scope="col">Linked devices</th>
                <th scope="col">Awaiting decision</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {integrations.data.map((i) => {
                const fresh = FRESHNESS[i.freshness]
                const state = INSTANCE_STATUS[i.status]
                return (
                  <tr key={i.id} className={i.id === selected ? 'row--selected' : undefined}>
                    <td>
                      {i.name}
                      <span className="cell-secondary">
                        {i.source.name}
                        {i.source.availability === 'planned' && ' · adapter planned'}
                      </span>
                    </td>
                    <td>
                      <StatusBadge tone={state.tone} label={state.label} />
                      {i.last_error && <span className="cell-secondary">{i.last_error}</span>}
                    </td>
                    <td>
                      <StatusBadge tone={fresh.tone} label={fresh.label} />
                      <span className="cell-secondary">Stale after {i.stale_after_hours} h</span>
                    </td>
                    <td className="nowrap">{formatDateTime(i.last_success_at)}</td>
                    <td>
                      {i.active_links} active
                      {i.stale_links > 0 && <span className="cell-secondary">{i.stale_links} stale</span>}
                    </td>
                    <td>{i.open_candidates}</td>
                    <td>
                      <Button
                        variant="quiet"
                        aria-current={i.id === selected ? 'true' : undefined}
                        onClick={() => setSelected(i.id)}
                      >
                        Sync history<span className="visually-hidden"> for {i.name}</span>
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
      {selected && (
        <section className="panel panel--flush" aria-labelledby="runs-heading" aria-live="polite">
          <h2 className="section-title section-title--inset" id="runs-heading">
            Sync history
          </h2>
          {runs.isPending && <LoadingState label="Loading sync history…" />}
          {runs.isError && <QueryErrorState error={runs.error} what="sync history" />}
          {runs.data && runs.data.items.length === 0 && <EmptyState title="No sync runs yet." />}
          {runs.data && runs.data.items.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Result</th>
                  <th scope="col">Records</th>
                  <th scope="col">New / unchanged</th>
                  <th scope="col">Candidates</th>
                  <th scope="col">Assets updated</th>
                  <th scope="col">Marked stale</th>
                  <th scope="col">Errors</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.items.map((r) => (
                  <tr key={r.id}>
                    <td className="nowrap">{formatDateTime(r.started_at)}</td>
                    <td>{r.mode === 'full' ? 'Full' : 'Incremental'}</td>
                    <td>
                      <StatusBadge tone={RUN_STATUS[r.status].tone} label={RUN_STATUS[r.status].label} />
                    </td>
                    <td>{r.records_received}</td>
                    <td>
                      {r.observations_created} / {r.observations_unchanged}
                    </td>
                    <td>
                      {r.candidates_opened} new, {r.candidates_updated} updated
                    </td>
                    <td>{r.assets_updated}</td>
                    <td>{r.links_marked_stale}</td>
                    <td>
                      {r.errors}
                      {r.error_samples.length > 0 && (
                        <span className="cell-secondary">{String(r.error_samples[0].error)}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </div>
  )
}
