import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  approveSoftwareVersion,
  fetchSoftwareProduct,
  rejectSoftwareVersion,
  softwareKeys,
} from '../../shared/api/software'
import { PERMISSIONS, type SoftwareVersion } from '../../shared/api/types'
import { formatDate } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { TextAreaField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { LIFECYCLE_STATUS, MATCH_METHOD, MATCH_STATE, MILESTONE, daysLabel } from '../lifecycle/labels'
import { InstallationsTable } from './SoftwarePage'

export function SoftwareProductPage() {
  const { id = '' } = useParams()
  const productId = Number(id)
  const { can } = useSession()
  const product = useQuery({ queryKey: softwareKeys.product(productId), queryFn: () => fetchSoftwareProduct(productId) })
  const [approving, setApproving] = useState<SoftwareVersion | null>(null)
  const [rejecting, setRejecting] = useState<SoftwareVersion | null>(null)

  if (product.isPending) return <LoadingState label="Loading software…" />
  if (product.isError) return <QueryErrorState error={product.error} what="this software" />
  const p = product.data
  const approve = can(PERMISSIONS.lifecycleApprove)
  return (
    <div className="page page--wide">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/software">Software</Link>
      </nav>
      <PageHeader
        title={p.name}
        meta={`${p.publisher || 'Publisher not reported'} · ${p.installations.toLocaleString('en-GB')} installations in your sites`}
      />
      <section className="panel panel--flush" aria-labelledby="versions-title">
        <div className="panel__header">
          <h2 className="section-title" id="versions-title">
            Versions and lifecycle
          </h2>
        </div>
        <table className="data-table">
          <caption className="visually-hidden">Versions</caption>
          <thead>
            <tr>
              <th scope="col">Version</th>
              <th scope="col">Installations</th>
              <th scope="col">Lifecycle</th>
              <th scope="col">Catalogue match</th>
              <th scope="col">Milestone</th>
              {approve && (
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {p.versions.map((v) => {
              const s = LIFECYCLE_STATUS[v.lifecycle_status]
              return (
                <tr key={v.id}>
                  <td className="mono">{v.version || 'Not reported'}</td>
                  <td>{v.installations}</td>
                  <td>
                    <StatusBadge tone={s.tone} label={s.label} />
                  </td>
                  <td>
                    {v.lifecycle_product ? (
                      <Link to={`/lifecycle/catalogue/${v.lifecycle_product.id}`}>{v.lifecycle_product.label}</Link>
                    ) : v.lifecycle_state === 'candidate' ? (
                      `Suggested: ${v.lifecycle_candidates.map((c) => c.label).join(', ')}`
                    ) : (
                      MATCH_STATE[v.lifecycle_state] ?? v.lifecycle_state
                    )}
                    <span className="cell-secondary">
                      {v.lifecycle_state === 'matched' ? MATCH_METHOD[v.lifecycle_method] : v.lifecycle_reasons[0]}
                    </span>
                  </td>
                  <td className="nowrap">
                    {v.lifecycle_milestone_type
                      ? `${MILESTONE[v.lifecycle_milestone_type as keyof typeof MILESTONE]} ${formatDate(
                          v.lifecycle_milestone_date,
                        )} (${daysLabel(v.lifecycle_days_remaining)})`
                      : '–'}
                  </td>
                  {approve && (
                    <td className="nowrap">
                      {v.lifecycle_state === 'candidate' && (
                        <div className="action-row">
                          <Button onClick={() => setApproving(v)}>Approve…</Button>
                          <Button variant="quiet" onClick={() => setRejecting(v)}>
                            Reject…
                          </Button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
      <h2 className="section-title">Installations in your sites</h2>
      <InstallationsTable query={{ product: String(productId) }} />
      {approving && <ApproveDialog productId={productId} version={approving} onClose={() => setApproving(null)} />}
      {rejecting && <RejectDialog productId={productId} version={rejecting} onClose={() => setRejecting(null)} />}
    </div>
  )
}

function ApproveDialog({ productId, version, onClose }: { productId: number; version: SoftwareVersion; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [product, setProduct] = useState(version.lifecycle_candidates[0]?.product_id ?? '')
  const [remember, setRemember] = useState(true)
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () =>
      approveSoftwareVersion(version.id, version.lifecycle_version, { product, remember_alias: remember, note }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: softwareKeys.product(productId) })
      onClose()
    },
  })
  return (
    <Dialog
      open
      title={`Lifecycle match for version ${version.version || '(not reported)'}`}
      confirmLabel="Approve match"
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => product && save.mutate()}
    >
      {save.isError && <ErrorSummary message={save.error.message} fieldErrors={{}} fieldLabels={{}} />}
      <fieldset className="fieldset field">
        <legend className="field__label">Catalogue product</legend>
        <div className="radio-list">
          {version.lifecycle_candidates.map((c) => (
            <label key={c.product_id} className="radio">
              <input type="radio" name="sw-product" checked={product === c.product_id} onChange={() => setProduct(c.product_id)} />
              <span>
                {c.label} <span className="cell-muted">— {c.reason}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <label className="checkbox">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        <span className="checkbox__label">Remember as an approved alias</span>
      </label>
      <TextAreaField label="Note (optional)" name="sw-note" value={note} onChange={(e) => setNote(e.target.value)} />
    </Dialog>
  )
}

function RejectDialog({ productId, version, onClose }: { productId: number; version: SoftwareVersion; onClose: () => void }) {
  const queryClient = useQueryClient()
  const reject = useMutation({
    mutationFn: (note: string) => rejectSoftwareVersion(version.id, version.lifecycle_version, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: softwareKeys.product(productId) })
      onClose()
    },
  })
  return (
    <ReasonDialog
      title={`Reject suggestions for version ${version.version || '(not reported)'}`}
      confirmLabel="Reject suggestions"
      help="The suggested catalogue products will not be proposed again for this version; its lifecycle stays Unknown."
      busy={reject.isPending}
      error={reject.isError ? reject.error.message : null}
      onClose={onClose}
      onConfirm={(note) => reject.mutate(note)}
    />
  )
}
