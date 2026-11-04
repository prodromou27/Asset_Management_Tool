import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { isApiError } from '../../shared/api/client'
import {
  createException,
  fetchAssetLifecycle,
  fetchPolicy,
  lifecycleKeys,
  reassessAsset,
} from '../../shared/api/lifecycle'
import {
  PERMISSIONS,
  type LifecycleAssessment,
  type LifecycleMatch,
  type LifecycleMilestone,
} from '../../shared/api/types'
import { formatDate, formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import {
  DIMENSION,
  EVIDENCE_QUALITY,
  LIFECYCLE_STATUS,
  MATCH_METHOD,
  MATCH_STATE,
  MILESTONE,
  SOURCE_TYPE,
  SUPPORT_LEVEL,
  daysLabel,
} from './labels'

/** docs/08 asset detail "Lifecycle" tab: one block per dimension with the status, the
 * governing milestone, the evidence behind it, the match and any exception. */
export function AssetLifecyclePanel({ assetId }: { assetId: string }) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const data = useQuery({ queryKey: lifecycleKeys.asset(assetId), queryFn: () => fetchAssetLifecycle(assetId) })
  const reassess = useMutation({
    mutationFn: () => reassessAsset(assetId),
    onSuccess: (result) => {
      queryClient.setQueryData(lifecycleKeys.asset(assetId), result)
      queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
  })
  const [excepting, setExcepting] = useState<string | null>(null)

  if (data.isPending) return <LoadingState label="Loading lifecycle…" />
  if (data.isError) return <QueryErrorState error={data.error} what="lifecycle" />
  const { assessments, matches, exceptions, history, evidence } = data.data
  const canReassess = can(PERMISSIONS.lifecycleManage) || can(PERMISSIONS.lifecycleApprove)

  return (
    <section className="panel" aria-labelledby="lifecycle-title">
      <div className="lifecycle-dimension__head">
        <h2 className="section-title" id="lifecycle-title">
          Lifecycle
        </h2>
        {canReassess && (
          <Button busy={reassess.isPending} onClick={() => reassess.mutate()}>
            {assessments.length ? 'Reassess' : 'Assess now'}
          </Button>
        )}
      </div>
      <p className="field__help">
        Vendor lifecycle only. It does not reflect your maintenance contract or warranty.
      </p>
      {assessments.length === 0 && (
        <p className="inline-note">
          Not assessed yet. Assessments run hourly and after catalogue changes.
        </p>
      )}
      {assessments.map((a) => (
        <Dimension
          key={a.dimension}
          assessment={a}
          match={matches.find((m) => m.dimension === a.dimension)}
          evidence={evidence.filter((m) => a.milestone_ids.includes(m.id))}
          onException={can(PERMISSIONS.lifecycleApprove) ? () => setExcepting(a.dimension) : undefined}
        />
      ))}
      {exceptions.length > 0 && (
        <details className="lifecycle-dimension">
          <summary>Exception history ({exceptions.length})</summary>
          <ul className="plain-list">
            {exceptions.map((x) => (
              <li key={x.id}>
                {DIMENSION[x.dimension]}: {LIFECYCLE_STATUS[x.status].label} until {formatDate(x.expires_on)} —{' '}
                {x.reason}
                <span className="cell-secondary">
                  Approved by {x.approved_by}
                  {x.revoked_at ? ` · revoked by ${x.revoked_by}: ${x.revoke_reason}` : x.active ? '' : ' · expired'}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {history.length > 0 && (
        <details className="lifecycle-dimension">
          <summary>Assessment history</summary>
          <ul className="plain-list">
            {history.map((h, i) => (
              <li key={i}>
                {formatDateTime(h.recorded_at)} · {DIMENSION[h.dimension]}:{' '}
                {LIFECYCLE_STATUS[h.effective_status as keyof typeof LIFECYCLE_STATUS]?.label ?? h.effective_status}
                {h.product_label && ` (${h.product_label})`}
                {h.milestone_date && ` · ${formatDate(h.milestone_date)}`}
              </li>
            ))}
          </ul>
        </details>
      )}
      {excepting && (
        <ExceptionDialog assetId={assetId} dimension={excepting} onClose={() => setExcepting(null)} />
      )}
    </section>
  )
}

function Dimension({
  assessment: a,
  match,
  evidence,
  onException,
}: {
  assessment: LifecycleAssessment
  match?: LifecycleMatch
  evidence: LifecycleMilestone[]
  onException?: () => void
}) {
  const effective = LIFECYCLE_STATUS[a.effective_status]
  const applicable = a.status !== 'not_applicable'
  return (
    <div className="lifecycle-dimension">
      <div className="lifecycle-dimension__head">
        <h3>{DIMENSION[a.dimension]}</h3>
        <StatusBadge tone={effective.tone} label={effective.label} />
        {a.status !== a.effective_status && (
          <span className="cell-muted">Evidence says: {LIFECYCLE_STATUS[a.status].label}</span>
        )}
        {onException && applicable && !a.exception && (
          <Button variant="quiet" onClick={onException}>
            Record exception…
          </Button>
        )}
      </div>
      {applicable && (
        <dl className="meta-grid">
          <dt>Catalogue product</dt>
          <dd>
            {a.product ? (
              <Link to={`/lifecycle/catalogue/${a.product.id}`}>{a.product.label}</Link>
            ) : (
              'Not identified'
            )}
            {match && (
              <span className="cell-secondary">
                {match.state === 'matched' ? MATCH_METHOD[match.method] : MATCH_STATE[match.state]}
                {match.state === 'candidate' && (
                  <>
                    {' '}
                    · <Link to="/lifecycle?tab=review">Review the suggested match</Link>
                  </>
                )}
              </span>
            )}
          </dd>
          {a.milestone_type && (
            <>
              <dt>{MILESTONE[a.milestone_type]}</dt>
              <dd>
                {formatDate(a.milestone_date)} ({daysLabel(a.days_remaining)})
                {a.threshold_days && <span className="cell-secondary">Within the {a.threshold_days}-day warning</span>}
              </dd>
            </>
          )}
          {a.support_level && (
            <>
              <dt>Support level</dt>
              <dd>{SUPPORT_LEVEL[a.support_level]}</dd>
            </>
          )}
          <dt>Evidence</dt>
          <dd>
            {EVIDENCE_QUALITY[a.evidence_quality]}
            {evidence.map((m) => (
              <span key={m.id} className="cell-secondary">
                {MILESTONE[m.milestone_type]} {formatDate(m.date)} —{' '}
                {m.source.url ? (
                  <a href={m.source.url} target="_blank" rel="noopener noreferrer">
                    {m.source.title}
                  </a>
                ) : (
                  m.source.title
                )}{' '}
                ({SOURCE_TYPE[m.source.source_type]}, verified by {m.reviewed_by ?? '–'})
              </span>
            ))}
          </dd>
          {a.exception && (
            <>
              <dt>Exception</dt>
              <dd>
                {LIFECYCLE_STATUS[a.exception.status as keyof typeof LIFECYCLE_STATUS].label} until{' '}
                {formatDate(a.exception.expires_on)}, approved by {a.exception.approved_by}
              </dd>
            </>
          )}
          {match && Object.keys(match.observed).length > 0 && (
            <>
              <dt>Observed</dt>
              <dd>
                {Object.entries(match.observed as Record<string, { value: string; source: { instance: string | null } | null }>)
                  .filter(([, v]) => v.value)
                  .map(([k, v]) => (
                    <span key={k} className="cell-secondary">
                      {k.replace('_', ' ')}: <span className="mono">{v.value}</span>
                      {v.source?.instance ? ` (from ${v.source.instance})` : v.source ? ' (manual)' : ''}
                    </span>
                  ))}
              </dd>
            </>
          )}
        </dl>
      )}
      <ul className="reason-list">
        {a.reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  )
}

const EXCEPTION_STATUSES = [
  'supported',
  'eol_announced',
  'expiring',
  'security_maintenance_ended',
  'eos',
  'not_announced',
  'unknown',
] as const

function ExceptionDialog({ assetId, dimension, onClose }: { assetId: string; dimension: string; onClose: () => void }) {
  const queryClient = useQueryClient()
  const policy = useQuery({ queryKey: lifecycleKeys.policy, queryFn: fetchPolicy })
  const [form, setForm] = useState({
    status: 'supported' as (typeof EXCEPTION_STATUSES)[number],
    reason: '',
    compensating_controls: '',
    expires_on: '',
  })
  const save = useMutation({
    mutationFn: () => createException(assetId, { dimension: dimension as 'hardware' | 'os', ...form }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: lifecycleKeys.all })
      queryClient.invalidateQueries({ queryKey: ['assets'] })
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog
      open
      title={`Lifecycle exception: ${DIMENSION[dimension]}`}
      confirmLabel="Approve exception"
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ reason: 'Reason', expires_on: 'Expires on', status: 'Status' }}
        />
      )}
      <p>
        The exception changes how this asset is reported until it expires. The vendor evidence is not
        changed and stays visible.
      </p>
      <SelectField
        label="Report as"
        name="exception-status"
        value={form.status}
        onChange={(e) => setForm({ ...form, status: e.target.value as typeof form.status })}
        options={EXCEPTION_STATUSES.map((s) => ({ value: s, label: LIFECYCLE_STATUS[s].label }))}
      />
      <TextAreaField
        label="Reason"
        name="exception-reason"
        value={form.reason}
        onChange={(e) => setForm({ ...form, reason: e.target.value })}
        error={errors.reason}
      />
      <TextAreaField
        label="Compensating controls (optional)"
        name="exception-controls"
        value={form.compensating_controls}
        onChange={(e) => setForm({ ...form, compensating_controls: e.target.value })}
      />
      <TextField
        label="Expires on"
        name="exception-expires"
        type="date"
        help={policy.data ? `At most ${policy.data.max_exception_days} days from today.` : undefined}
        value={form.expires_on}
        onChange={(e) => setForm({ ...form, expires_on: e.target.value })}
        error={errors.expires_on}
      />
    </Dialog>
  )
}
