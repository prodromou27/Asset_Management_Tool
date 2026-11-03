import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  assignFinding,
  dismissFinding,
  fetchFindings,
  fetchQualitySummary,
  qualityKeys,
  refreshFindings,
  reopenFinding,
  type FindingFilters,
} from '../../shared/api/quality'
import { PERMISSIONS, type QualityFinding } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField } from '../../shared/ui/Field'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge, type StatusTone } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from './ReasonDialog'

const FINDING_KIND: Record<QualityFinding['kind'], string> = {
  duplicate_candidate: 'Duplicate candidates',
  model_unknown: 'Model unknown',
  source_stale: 'Source stale',
  owner_missing: 'Owner missing',
}
const SEVERITY: Record<QualityFinding['severity'], { label: string; tone: StatusTone }> = {
  high: { label: 'High', tone: 'danger' },
  medium: { label: 'Medium', tone: 'warning' },
  low: { label: 'Low', tone: 'neutral' },
}
const STATUS: Record<QualityFinding['status'], string> = {
  open: 'Open',
  dismissed: 'Dismissed (accepted as is)',
  resolved: 'Resolved',
}

function Evidence({ f }: { f: QualityFinding }) {
  const others = (f.evidence.assets as { id: string; name: string }[] | undefined) ?? []
  if (others.length === 0) return null
  return (
    <span className="cell-secondary">
      Also on:{' '}
      {others.map((a, n) => (
        <span key={a.id}>
          {n > 0 && ', '}
          <Link to={`/assets/${a.id}`}>{a.name}</Link>
        </span>
      ))}
    </span>
  )
}

/** docs/01 dedicated queues: each finding has severity, evidence, assignee and a
 * resolution state. Findings are recomputed hourly; fixing the asset resolves them. */
export function QualityQueues() {
  const { can, me } = useSession()
  const queryClient = useQueryClient()
  const decide = can(PERMISSIONS.reconciliationDecide)
  const [filters, setFilters] = useState<FindingFilters>({ kind: 'duplicate_candidate' })
  const [acting, setActing] = useState<{ finding: QualityFinding; reopen: boolean } | null>(null)
  const summary = useQuery({ queryKey: qualityKeys.summary, queryFn: fetchQualitySummary })
  const findings = useInfiniteQuery({
    queryKey: qualityKeys.findings(filters),
    queryFn: ({ pageParam }) => fetchFindings(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: qualityKeys.all })
  const assign = useMutation({
    mutationFn: ({ f, assignee }: { f: QualityFinding; assignee: string | null }) =>
      assignFinding(f.id, f.version, assignee),
    onSuccess: invalidate,
  })
  const refresh = useMutation({ mutationFn: refreshFindings, onSuccess: invalidate })
  const items = findings.data?.pages.flatMap((p) => p.items) ?? []
  const update = (next: Partial<FindingFilters>) => setFilters((f) => ({ ...f, ...next }))

  return (
    <>
      <nav className="segmented" aria-label="Data-quality queues">
        {(summary.data ?? []).map((row) => (
          <button
            key={row.kind}
            type="button"
            className={`segmented__item${filters.kind === row.kind ? ' segmented__item--active' : ''}`}
            aria-pressed={filters.kind === row.kind}
            onClick={() => update({ kind: row.kind })}
          >
            {FINDING_KIND[row.kind]} <span className="segmented__count">{row.open}</span>
            {row.high > 0 && <span className="visually-hidden">, {row.high} high severity</span>}
          </button>
        ))}
      </nav>
      <div className="toolbar">
        <SelectField
          label="Status"
          name="finding_status"
          options={[
            ...Object.entries(STATUS).map(([value, label]) => ({ value, label })),
            { value: 'all', label: 'All' },
          ]}
          value={filters.status ?? 'open'}
          onChange={(e) => update({ status: e.target.value === 'open' ? undefined : e.target.value })}
        />
        <SelectField
          label="Severity"
          name="finding_severity"
          options={[
            { value: '', label: 'Any severity' },
            ...Object.entries(SEVERITY).map(([value, s]) => ({ value, label: s.label })),
          ]}
          value={filters.severity ?? ''}
          onChange={(e) => update({ severity: e.target.value || undefined })}
        />
        <SelectField
          label="Assignee"
          name="finding_assignee"
          options={[
            { value: '', label: 'Anyone' },
            { value: 'me', label: 'Assigned to me' },
            { value: 'none', label: 'Unassigned' },
          ]}
          value={filters.assignee ?? ''}
          onChange={(e) => update({ assignee: e.target.value || undefined })}
        />
        {decide && (
          <div className="toolbar__actions">
            <Button busy={refresh.isPending} onClick={() => refresh.mutate()}>
              Re-check now
            </Button>
          </div>
        )}
      </div>
      {refresh.data && (
        <p className="inline-success" role="status">
          Checked: {refresh.data.opened} new, {refresh.data.resolved} resolved.
        </p>
      )}
      {assign.error && <p className="field__error">{assign.error.message}</p>}
      <section className="panel panel--flush" aria-live="polite" aria-label="Data-quality findings">
        {findings.isPending && <LoadingState label="Loading findings…" />}
        {findings.isError && <QueryErrorState error={findings.error} what="data-quality findings" />}
        {findings.isSuccess && items.length === 0 && <EmptyState title="No findings in this queue." />}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">{filters.kind ? FINDING_KIND[filters.kind as QualityFinding['kind']] : 'Findings'}</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Severity</th>
                <th scope="col">Finding</th>
                <th scope="col">Detected</th>
                <th scope="col">Assignee</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.id}>
                  <td>
                    <Link to={`/assets/${f.asset.id}`}>{f.asset.name}</Link>
                    <span className="cell-secondary mono">{f.asset.site.code}</span>
                  </td>
                  <td>
                    <StatusBadge tone={SEVERITY[f.severity].tone} label={SEVERITY[f.severity].label} />
                  </td>
                  <td>
                    {f.summary}
                    <Evidence f={f} />
                    {f.status !== 'open' && (
                      <span className="cell-secondary">
                        {STATUS[f.status]}
                        {f.resolution_reason && `: ${f.resolution_reason}`}
                      </span>
                    )}
                  </td>
                  <td className="nowrap">
                    {formatDateTime(f.detected_at)}
                    <span className="cell-secondary">Last checked {formatDateTime(f.last_confirmed_at)}</span>
                  </td>
                  <td>{f.assignee ? f.assignee.display_name : <span className="cell-muted">Unassigned</span>}</td>
                  <td className="cell-actions">
                    {decide && f.status === 'open' && (
                      <>
                        {f.assignee?.id === me?.id ? (
                          <Button variant="quiet" onClick={() => assign.mutate({ f, assignee: null })}>
                            Unassign<span className="visually-hidden"> {f.asset.name}</span>
                          </Button>
                        ) : (
                          <Button variant="quiet" onClick={() => assign.mutate({ f, assignee: me?.id ?? null })}>
                            Assign to me<span className="visually-hidden"> {f.asset.name}</span>
                          </Button>
                        )}
                        <Button variant="quiet" onClick={() => setActing({ finding: f, reopen: false })}>
                          Dismiss…<span className="visually-hidden"> {f.asset.name}</span>
                        </Button>
                      </>
                    )}
                    {decide && f.status === 'dismissed' && (
                      <Button variant="quiet" onClick={() => setActing({ finding: f, reopen: true })}>
                        Reopen…<span className="visually-hidden"> {f.asset.name}</span>
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {findings.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => findings.fetchNextPage()} busy={findings.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </section>
      {acting && <FindingDialog {...acting} onClose={() => setActing(null)} onDone={invalidate} />}
    </>
  )
}

function FindingDialog({
  finding,
  reopen,
  onClose,
  onDone,
}: {
  finding: QualityFinding
  reopen: boolean
  onClose: () => void
  onDone: () => Promise<void>
}) {
  const mutation = useMutation({
    mutationFn: (reason: string) =>
      reopen ? reopenFinding(finding.id, finding.version, reason) : dismissFinding(finding.id, finding.version, reason),
    onSuccess: async () => {
      await onDone()
      onClose()
    },
  })
  return (
    <ReasonDialog
      title={reopen ? `Reopen finding for ${finding.asset.name}?` : `Dismiss finding for ${finding.asset.name}?`}
      confirmLabel={reopen ? 'Reopen' : 'Dismiss'}
      help={
        reopen
          ? 'The finding returns to the open queue.'
          : 'Accepts the asset as it is. The finding stays dismissed while the condition holds; nothing on the asset changes.'
      }
      busy={mutation.isPending}
      error={mutation.error ? mutation.error.message : null}
      onClose={onClose}
      onConfirm={(reason) => mutation.mutate(reason)}
    />
  )
}
