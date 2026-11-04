import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  approveMatch,
  fetchExceptions,
  fetchFindings,
  fetchMatches,
  fetchPolicy,
  fetchSummary,
  lifecycleKeys,
  reassessAll,
  rejectMatch,
  revokeException,
} from '../../shared/api/lifecycle'
import { PERMISSIONS, type LifecycleMatch } from '../../shared/api/types'
import { formatDate } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { Tabs } from '../../shared/ui/Tabs'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { DIMENSION, EVIDENCE_QUALITY, LIFECYCLE_STATUS, MILESTONE, daysLabel } from './labels'

const STATUS_FILTERS = [
  { value: '', label: 'Any status' },
  { value: 'eos,security_maintenance_ended', label: 'End of support / security ended' },
  { value: 'expiring', label: 'Approaching end of support' },
  { value: 'unknown,unverified', label: 'Unknown or needs review' },
  { value: 'eol_announced', label: 'EOL announced' },
  { value: 'supported,not_announced', label: 'Supported / not announced' },
  { value: 'not_applicable', label: 'Not applicable' },
]

export function LifecyclePage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'findings'
  const queryClient = useQueryClient()
  const reassess = useMutation({
    mutationFn: reassessAll,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: lifecycleKeys.all }),
  })
  const policy = useQuery({ queryKey: lifecycleKeys.policy, queryFn: fetchPolicy })

  return (
    <div className="page page--wide">
      <PageHeader
        title="Lifecycle"
        meta={
          policy.data
            ? `Support status from verified vendor evidence. Warnings ${policy.data.warning_days.join(
                ' and ',
              )} days before a milestone; extended support ${
                policy.data.count_extended_support ? 'counts' : 'is shown but not counted'
              }. Missing evidence is Unknown, never Supported.`
            : 'Support status from verified vendor evidence.'
        }
        actions={
          <>
            <Link className="button button--secondary" to="/lifecycle/catalogue">
              Catalogue
            </Link>
            {can(PERMISSIONS.lifecycleApprove) && (
              <Button busy={reassess.isPending} onClick={() => reassess.mutate()}>
                Reassess all
              </Button>
            )}
          </>
        }
      />
      {reassess.isSuccess && (
        <p className="inline-success" role="status">
          Reassessment started. Results update within a few minutes.
        </p>
      )}
      <SummaryStrip />
      <Tabs
        label="Lifecycle sections"
        selected={tab}
        onSelect={(next) => {
          const search = new URLSearchParams(params)
          if (next === 'findings') search.delete('tab')
          else search.set('tab', next)
          setParams(search, { replace: true })
        }}
        tabs={[
          { id: 'findings', label: 'Findings', content: <Findings /> },
          { id: 'review', label: 'Review queue', content: <ReviewQueue /> },
          { id: 'exceptions', label: 'Exceptions', content: <Exceptions /> },
        ]}
      />
    </div>
  )
}

function SummaryStrip() {
  const summary = useQuery({ queryKey: lifecycleKeys.summary, queryFn: fetchSummary })
  if (!summary.data) return null
  const total = (statuses: string[]) =>
    summary.data
      .filter((r) => r.dimension !== 'software' && statuses.includes(r.effective_status))
      .reduce((n, r) => n + r.count, 0)
  const items = [
    { label: 'End of support', value: total(['eos', 'security_maintenance_ended']) },
    { label: 'Approaching', value: total(['expiring']) },
    { label: 'Unknown / needs review', value: total(['unknown', 'unverified']) },
    { label: 'Supported or announced', value: total(['supported', 'not_announced', 'eol_announced']) },
  ]
  return (
    <dl className="kpi-strip" aria-label="Lifecycle totals (hardware and OS assessments)">
      {items.map((item) => (
        <div key={item.label} className="kpi-strip__item">
          <dt>{item.label}</dt>
          <dd>{item.value.toLocaleString('en-GB')}</dd>
        </div>
      ))}
    </dl>
  )
}

function Findings() {
  const [dimension, setDimension] = useState('')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const query = { dimension: dimension || undefined, status: status || undefined, q: q || undefined }
  const findings = useInfiniteQuery({
    queryKey: lifecycleKeys.findings(query),
    queryFn: ({ pageParam }) => fetchFindings(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = findings.data?.pages.flatMap((p) => p.items) ?? []
  const count = findings.data?.pages[0]?.count

  return (
    <section aria-label="Lifecycle findings">
      <div className="toolbar">
        <SelectField
          label="Dimension"
          name="dimension"
          value={dimension}
          onChange={(e) => setDimension(e.target.value)}
          options={[
            { value: '', label: 'Hardware and OS' },
            { value: 'hardware', label: 'Hardware' },
            { value: 'os', label: 'OS / firmware' },
          ]}
        />
        <SelectField
          label="Status"
          name="status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={STATUS_FILTERS}
        />
        <TextField label="Asset" name="q" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="panel panel--flush" aria-live="polite">
        {findings.isPending && <LoadingState label="Loading findings…" />}
        {findings.isError && <QueryErrorState error={findings.error} what="lifecycle findings" />}
        {findings.isSuccess && items.length === 0 && (
          <EmptyState title="No assessments match.">
            Assessments appear after the catalogue has products and assets are reassessed.
          </EmptyState>
        )}
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table data-table--nowrap">
              <caption className="visually-hidden">Lifecycle findings ({count})</caption>
              <thead>
                <tr>
                  <th scope="col">Asset</th>
                  <th scope="col">Dimension</th>
                  <th scope="col">Product</th>
                  <th scope="col">Status</th>
                  <th scope="col">Milestone</th>
                  <th scope="col">Date</th>
                  <th scope="col">Days left</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Exception</th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => {
                  const s = LIFECYCLE_STATUS[a.effective_status]
                  return (
                    <tr key={a.id}>
                      <td>
                        <Link className="table-link" to={`/assets/${a.asset.id}?tab=lifecycle`}>
                          {a.asset.name}
                        </Link>
                        <span className="cell-secondary">{a.asset.site.code}</span>
                      </td>
                      <td>{DIMENSION[a.dimension]}</td>
                      <td>
                        {a.product ? (
                          <Link to={`/lifecycle/catalogue/${a.product.id}`}>{a.product.label}</Link>
                        ) : (
                          <span className="cell-muted">Not identified</span>
                        )}
                      </td>
                      <td>
                        <StatusBadge tone={s.tone} label={s.label} />
                        {a.status !== a.effective_status && (
                          <span className="cell-secondary">
                            Evidence: {LIFECYCLE_STATUS[a.status].label}
                          </span>
                        )}
                      </td>
                      <td>{a.milestone_type ? MILESTONE[a.milestone_type] : '–'}</td>
                      <td className="nowrap">{formatDate(a.milestone_date)}</td>
                      <td className="nowrap">{daysLabel(a.days_remaining)}</td>
                      <td>{EVIDENCE_QUALITY[a.evidence_quality]}</td>
                      <td className="nowrap">
                        {a.exception ? `Until ${formatDate(a.exception.expires_on)}` : '–'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {findings.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => findings.fetchNextPage()} busy={findings.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </div>
    </section>
  )
}

function observedText(match: LifecycleMatch): string {
  const o = match.observed as Record<string, { value: string; source: { instance: string | null } | null }>
  const parts = Object.entries(o)
    .filter(([, v]) => v?.value)
    .map(([k, v]) => `${k.replace('_', ' ')}: ${v.value}${v.source?.instance ? ` (${v.source.instance})` : ''}`)
  return parts.join(' · ') || 'Nothing recorded'
}

function ReviewQueue() {
  const { can } = useSession()
  const [dimension, setDimension] = useState('')
  const query = { dimension: dimension || undefined }
  const matches = useInfiniteQuery({
    queryKey: lifecycleKeys.matches(query),
    queryFn: ({ pageParam }) => fetchMatches(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const [approving, setApproving] = useState<LifecycleMatch | null>(null)
  const [rejecting, setRejecting] = useState<LifecycleMatch | null>(null)
  const items = matches.data?.pages.flatMap((p) => p.items) ?? []
  const approve = can(PERMISSIONS.lifecycleApprove)

  return (
    <section aria-label="Matches needing review">
      <div className="toolbar">
        <SelectField
          label="Dimension"
          name="review-dimension"
          value={dimension}
          onChange={(e) => setDimension(e.target.value)}
          options={[
            { value: '', label: 'Hardware and OS' },
            { value: 'hardware', label: 'Hardware' },
            { value: 'os', label: 'OS / firmware' },
          ]}
        />
      </div>
      <div className="panel panel--flush" aria-live="polite">
        {matches.isPending && <LoadingState label="Loading review queue…" />}
        {matches.isError && <QueryErrorState error={matches.error} what="the review queue" />}
        {matches.isSuccess && items.length === 0 && (
          <EmptyState title="Nothing to review.">
            Ambiguous, revision and firmware-only matches appear here for a decision.
          </EmptyState>
        )}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Review queue</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Dimension</th>
                <th scope="col">Observed</th>
                <th scope="col">Suggested products</th>
                {approve && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id}>
                  <td>
                    <Link className="table-link" to={`/assets/${m.asset.id}?tab=lifecycle`}>
                      {m.asset.name}
                    </Link>
                    <span className="cell-secondary">{m.asset.site.code}</span>
                  </td>
                  <td>{DIMENSION[m.dimension]}</td>
                  <td>
                    {observedText(m)}
                    <span className="cell-secondary">{m.reason}</span>
                  </td>
                  <td>
                    {m.candidates.map((c) => (
                      <span key={c.product_id} className="cell-secondary">
                        <Link to={`/lifecycle/catalogue/${c.product_id}`}>{c.label}</Link> — {c.reason}
                      </span>
                    ))}
                  </td>
                  {approve && (
                    <td className="nowrap">
                      <div className="action-row">
                        <Button onClick={() => setApproving(m)}>Approve…</Button>
                        <Button variant="quiet" onClick={() => setRejecting(m)}>
                          Reject…
                        </Button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {approving && <ApproveDialog match={approving} onClose={() => setApproving(null)} />}
      {rejecting && <RejectDialog match={rejecting} onClose={() => setRejecting(null)} />}
    </section>
  )
}

function ApproveDialog({ match, onClose }: { match: LifecycleMatch; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [product, setProduct] = useState(match.candidates[0]?.product_id ?? '')
  const [remember, setRemember] = useState(true)
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () => approveMatch(match.id, match.version, { product, remember_alias: remember, note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: lifecycleKeys.all })
      onClose()
    },
  })
  return (
    <Dialog
      open
      title={`Approve match for ${match.asset.name}`}
      confirmLabel="Approve match"
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => product && save.mutate()}
    >
      {save.isError && <ErrorSummary message={save.error.message} fieldErrors={{}} fieldLabels={{}} />}
      <p>{observedText(match)}</p>
      <fieldset className="fieldset field">
        <legend className="field__label">Catalogue product</legend>
        <div className="radio-list">
          {match.candidates.map((c) => (
            <label key={c.product_id} className="radio">
              <input
                type="radio"
                name="approve-product"
                checked={product === c.product_id}
                onChange={() => setProduct(c.product_id)}
              />
              <span>
                {c.label} <span className="cell-muted">— {c.reason}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <label className="checkbox">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <span>
          <span className="checkbox__label">Remember as an approved alias</span>
          <span className="checkbox__description">
            Other assets reporting the same value then match this product automatically.
          </span>
        </span>
      </label>
      <TextAreaField label="Note (optional)" name="approve-note" value={note} onChange={(e) => setNote(e.target.value)} />
    </Dialog>
  )
}

function RejectDialog({ match, onClose }: { match: LifecycleMatch; onClose: () => void }) {
  const queryClient = useQueryClient()
  const reject = useMutation({
    mutationFn: (note: string) => rejectMatch(match.id, match.version, { note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: lifecycleKeys.all })
      onClose()
    },
  })
  return (
    <ReasonDialog
      title={`Reject suggestions for ${match.asset.name}`}
      confirmLabel="Reject suggestions"
      help="The suggested products will not be proposed again for this asset. Its lifecycle stays Unknown until a correct catalogue entry exists."
      busy={reject.isPending}
      error={reject.isError ? reject.error.message : null}
      onClose={onClose}
      onConfirm={(note) => reject.mutate(note)}
    />
  )
}

function Exceptions() {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const [activeOnly, setActiveOnly] = useState('true')
  const query = { active: activeOnly || undefined }
  const exceptions = useInfiniteQuery({
    queryKey: lifecycleKeys.exceptions(query),
    queryFn: ({ pageParam }) => fetchExceptions(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const [revoking, setRevoking] = useState<{ id: string; version: number; name: string } | null>(null)
  const revoke = useMutation({
    mutationFn: (reason: string) => revokeException(revoking!.id, revoking!.version, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: lifecycleKeys.all })
      setRevoking(null)
    },
  })
  const items = exceptions.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section aria-label="Lifecycle exceptions">
      <div className="toolbar">
        <SelectField
          label="Show"
          name="exceptions-active"
          value={activeOnly}
          onChange={(e) => setActiveOnly(e.target.value)}
          options={[
            { value: 'true', label: 'Active exceptions' },
            { value: '', label: 'All, including expired and revoked' },
          ]}
        />
      </div>
      <div className="panel panel--flush" aria-live="polite">
        {exceptions.isPending && <LoadingState label="Loading exceptions…" />}
        {exceptions.isError && <QueryErrorState error={exceptions.error} what="exceptions" />}
        {exceptions.isSuccess && items.length === 0 && (
          <EmptyState title="No exceptions.">Exceptions are granted from an asset's Lifecycle tab.</EmptyState>
        )}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Exceptions</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Dimension</th>
                <th scope="col">Assessed as</th>
                <th scope="col">Reason</th>
                <th scope="col">Approved</th>
                <th scope="col">Expires</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((x) => (
                <tr key={x.id}>
                  <td>
                    <Link className="table-link" to={`/assets/${x.asset.id}?tab=lifecycle`}>
                      {x.asset.name}
                    </Link>
                  </td>
                  <td>{DIMENSION[x.dimension]}</td>
                  <td>{LIFECYCLE_STATUS[x.status].label}</td>
                  <td>
                    {x.reason}
                    {x.compensating_controls && (
                      <span className="cell-secondary">Controls: {x.compensating_controls}</span>
                    )}
                  </td>
                  <td className="nowrap">
                    {x.approved_by}
                    <span className="cell-secondary">{formatDate(x.approved_at)}</span>
                  </td>
                  <td className="nowrap">
                    {x.active ? formatDate(x.expires_on) : x.revoked_at ? 'Revoked' : 'Expired'}
                  </td>
                  <td>
                    {x.active && can(PERMISSIONS.lifecycleApprove) && (
                      <Button
                        variant="quiet"
                        onClick={() => setRevoking({ id: x.id, version: x.version, name: x.asset.name })}
                      >
                        Revoke…
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {revoking && (
        <ReasonDialog
          title={`Revoke exception for ${revoking.name}`}
          confirmLabel="Revoke exception"
          busy={revoke.isPending}
          error={revoke.isError ? revoke.error.message : null}
          onClose={() => setRevoking(null)}
          onConfirm={(reason) => revoke.mutate(reason)}
        />
      )}
    </section>
  )
}
