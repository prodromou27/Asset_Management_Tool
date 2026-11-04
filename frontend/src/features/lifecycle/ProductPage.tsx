import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { isApiError } from '../../shared/api/client'
import {
  addAlias,
  addMilestone,
  fetchProduct,
  fetchProductAssets,
  fetchRevisions,
  fetchSources,
  lifecycleKeys,
  reassessProduct,
  removeAlias,
  reviewMilestone,
  setStatement,
  updateMilestone,
  updateProduct,
} from '../../shared/api/lifecycle'
import {
  PERMISSIONS,
  type LifecycleAlias,
  type LifecycleMilestone,
  type LifecycleProductDetail,
  type MilestoneType,
} from '../../shared/api/types'
import { formatDate, formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { SourceDialog } from './SourceDialog'
import {
  ALIAS_KINDS,
  DIMENSION,
  LIFECYCLE_STATUS,
  MILESTONE,
  PRODUCT_KIND,
  SOURCE_TYPE,
  VERIFICATION,
  daysLabel,
  productLabel,
} from './labels'

export function ProductPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const queryClient = useQueryClient()
  const product = useQuery({ queryKey: lifecycleKeys.product(id), queryFn: () => fetchProduct(id) })
  const [editing, setEditing] = useState(false)
  const reassess = useMutation({
    mutationFn: () => reassessProduct(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: lifecycleKeys.all }),
  })

  if (product.isPending) return <LoadingState label="Loading product…" />
  if (product.isError) return <QueryErrorState error={product.error} what="this product" />
  const p = product.data
  return (
    <div className="page page--wide">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/lifecycle/catalogue">Lifecycle catalogue</Link>
      </nav>
      <PageHeader
        title={productLabel(p)}
        meta={`${PRODUCT_KIND[p.kind]} · ${DIMENSION[p.dimension]} lifecycle${p.family ? ` · ${p.family}` : ''}${
          p.is_active ? '' : ' · Inactive'
        }`}
        actions={
          <>
            {can(PERMISSIONS.lifecycleManage) && <Button onClick={() => setEditing(true)}>Edit details</Button>}
            {can(PERMISSIONS.lifecycleApprove) && (
              <Button busy={reassess.isPending} onClick={() => reassess.mutate()}>
                Reassess assets
              </Button>
            )}
          </>
        }
      />
      {reassess.isSuccess && (
        <p className="inline-success" role="status">
          Reassessment started for assets matched to this product.
        </p>
      )}
      <div className="detail-layout">
        <div className="stack">
          <Milestones product={p} />
          <AffectedAssets productId={p.id} />
          <Revisions productId={p.id} />
        </div>
        <div className="detail-layout__side">
          <Aliases product={p} />
          <Statement product={p} />
        </div>
      </div>
      {editing && <EditProductDialog product={p} onClose={() => setEditing(false)} />}
    </div>
  )
}

function useRefresh(id: string) {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: lifecycleKeys.product(id) })
    queryClient.invalidateQueries({ queryKey: lifecycleKeys.revisions(id) })
    queryClient.invalidateQueries({ queryKey: lifecycleKeys.productAssets(id) })
  }
}

function Milestones({ product }: { product: LifecycleProductDetail }) {
  const { can } = useSession()
  const refresh = useRefresh(product.id)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<LifecycleMilestone | null>(null)
  const [rejecting, setRejecting] = useState<LifecycleMilestone | null>(null)
  const review = useMutation({
    mutationFn: (args: { m: LifecycleMilestone; decision: 'verified' | 'rejected'; note: string }) =>
      reviewMilestone(args.m.id, args.m.version, args.decision, args.note),
    onSuccess: () => {
      setRejecting(null)
      refresh()
    },
  })
  const approve = can(PERMISSIONS.lifecycleApprove)
  const manage = can(PERMISSIONS.lifecycleManage)
  return (
    <section className="panel panel--flush" aria-labelledby="milestones-title">
      <div className="panel__header">
        <h2 className="section-title" id="milestones-title">
          Lifecycle milestones
        </h2>
        {manage && <Button onClick={() => setAdding(true)}>Add date</Button>}
      </div>
      {review.isError && <p className="field__error panel__note">{review.error.message}</p>}
      {product.milestones.length === 0 ? (
        <EmptyState title="No dates recorded.">
          Assets matched to this product stay Unknown until a sourced date is added and verified.
        </EmptyState>
      ) : (
        <table className="data-table">
          <caption className="visually-hidden">Lifecycle milestones</caption>
          <thead>
            <tr>
              <th scope="col">Milestone</th>
              <th scope="col">Date</th>
              <th scope="col">Source</th>
              <th scope="col">Verification</th>
              {(approve || manage) && (
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {product.milestones.map((m) => (
              <tr key={m.id}>
                <td>
                  {MILESTONE[m.milestone_type]}
                  {m.notes && <span className="cell-secondary">{m.notes}</span>}
                </td>
                <td className="nowrap">{formatDate(m.date)}</td>
                <td>
                  {m.source.url ? (
                    <a href={m.source.url} target="_blank" rel="noopener noreferrer">
                      {m.source.title}
                    </a>
                  ) : (
                    m.source.title
                  )}
                  <span className="cell-secondary">
                    {SOURCE_TYPE[m.source.source_type]} · {m.source.publisher} · collected{' '}
                    {formatDate(m.source.collected_on)}
                  </span>
                </td>
                <td>
                  <StatusBadge tone={VERIFICATION[m.verification].tone} label={VERIFICATION[m.verification].label} />
                  {m.reviewed_by && (
                    <span className="cell-secondary">
                      {m.reviewed_by}, {formatDate(m.reviewed_at)}
                    </span>
                  )}
                </td>
                {(approve || manage) && (
                  <td className="nowrap">
                    <div className="action-row">
                      {approve && m.verification === 'pending' && (
                        <Button
                          busy={review.isPending}
                          onClick={() => review.mutate({ m, decision: 'verified', note: '' })}
                        >
                          Verify
                        </Button>
                      )}
                      {approve && m.verification === 'pending' && (
                        <Button variant="quiet" onClick={() => setRejecting(m)}>
                          Reject…
                        </Button>
                      )}
                      {manage && (
                        <Button variant="quiet" onClick={() => setEditing(m)}>
                          Edit…
                        </Button>
                      )}
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {adding && <MilestoneDialog product={product} onClose={() => setAdding(false)} />}
      {editing && <MilestoneDialog product={product} milestone={editing} onClose={() => setEditing(null)} />}
      {rejecting && (
        <ReasonDialog
          title={`Reject ${MILESTONE[rejecting.milestone_type].toLowerCase()} ${formatDate(rejecting.date)}`}
          confirmLabel="Reject date"
          help="A rejected date is kept for the record but never used in assessments."
          busy={review.isPending}
          error={review.isError ? review.error.message : null}
          onClose={() => setRejecting(null)}
          onConfirm={(note) => review.mutate({ m: rejecting, decision: 'rejected', note })}
        />
      )}
    </section>
  )
}

function MilestoneDialog({
  product,
  milestone,
  onClose,
}: {
  product: LifecycleProductDetail
  milestone?: LifecycleMilestone
  onClose: () => void
}) {
  const refresh = useRefresh(product.id)
  const sources = useQuery({ queryKey: lifecycleKeys.sources, queryFn: () => fetchSources() })
  const [newSource, setNewSource] = useState(false)
  const [form, setForm] = useState({
    milestone_type: (milestone?.milestone_type ?? 'end_of_standard_support') as MilestoneType,
    date: milestone?.date ?? '',
    source: milestone?.source.id ?? '',
    notes: milestone?.notes ?? '',
    reason: '',
  })
  const save = useMutation({
    mutationFn: async () => {
      if (milestone) await updateMilestone(milestone.id, milestone.version, form)
      else
        await addMilestone(product.id, {
          milestone_type: form.milestone_type,
          date: form.date,
          source: form.source,
          notes: form.notes,
        })
    },
    onSuccess: () => {
      refresh()
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  if (newSource) {
    return (
      <SourceDialog
        onClose={() => setNewSource(false)}
        onCreated={(s) => setForm((f) => ({ ...f, source: s.id }))}
      />
    )
  }
  return (
    <Dialog
      open
      title={milestone ? 'Edit lifecycle date' : 'Add lifecycle date'}
      confirmLabel={milestone ? 'Save (needs re-verification)' : 'Add date'}
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ date: 'Date', source: 'Source', reason: 'Reason' }}
        />
      )}
      <SelectField
        label="Milestone"
        name="milestone-type"
        value={form.milestone_type}
        onChange={(e) => setForm({ ...form, milestone_type: e.target.value as MilestoneType })}
        options={Object.entries(MILESTONE).map(([value, label]) => ({ value, label }))}
      />
      <TextField
        label="Date"
        name="milestone-date"
        type="date"
        help="The last day the vendor provides this service, exactly as published."
        value={form.date}
        onChange={(e) => setForm({ ...form, date: e.target.value })}
        error={errors.date}
      />
      <SelectField
        label="Source"
        name="milestone-source"
        value={form.source}
        onChange={(e) => setForm({ ...form, source: e.target.value })}
        error={errors.source}
        options={[
          { value: '', label: sources.isPending ? 'Loading…' : 'Choose a source' },
          ...(sources.data ?? []).map((s) => ({
            value: s.id,
            label: `${s.title} (${SOURCE_TYPE[s.source_type]})`,
          })),
        ]}
      />
      <Button variant="quiet" onClick={() => setNewSource(true)}>
        Record a new source…
      </Button>
      <TextAreaField
        label="Interpretation notes (optional)"
        name="milestone-notes"
        value={form.notes}
        onChange={(e) => setForm({ ...form, notes: e.target.value })}
      />
      {milestone && (
        <TextAreaField
          label="Reason for the change"
          name="milestone-reason"
          value={form.reason}
          onChange={(e) => setForm({ ...form, reason: e.target.value })}
          error={errors.reason}
        />
      )}
      <p className="inline-note">
        New and changed dates are not used until someone with approval rights verifies them.
      </p>
    </Dialog>
  )
}

function Aliases({ product }: { product: LifecycleProductDetail }) {
  const { can } = useSession()
  const refresh = useRefresh(product.id)
  const kinds = ALIAS_KINDS[product.kind]
  const [form, setForm] = useState({ kind: kinds[0].value, value: '', release: '' })
  const [removing, setRemoving] = useState<LifecycleAlias | null>(null)
  const add = useMutation({
    mutationFn: () => addAlias(product.id, form),
    onSuccess: () => {
      setForm({ ...form, value: '', release: '' })
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (reason: string) => removeAlias(removing!.id, reason),
    onSuccess: () => {
      setRemoving(null)
      refresh()
    },
  })
  const manage = can(PERMISSIONS.lifecycleManage)
  const versioned = product.kind !== 'hardware'
  return (
    <section className="panel" aria-labelledby="aliases-title">
      <h2 className="section-title" id="aliases-title">
        Approved aliases
      </h2>
      <p className="field__help">
        Exact alternative names that identify this product. Matching never guesses beyond these.
      </p>
      {product.aliases.length === 0 ? (
        <p className="cell-muted">No aliases.</p>
      ) : (
        <ul className="plain-list">
          {product.aliases.map((a) => (
            <li key={a.id}>
              <span className="mono">{a.value}</span>
              {a.release && <span className="mono"> · {a.release}</span>}
              <span className="cell-secondary">{kinds.find((k) => k.value === a.kind)?.label ?? a.kind}</span>
              {manage && (
                <Button variant="quiet" onClick={() => setRemoving(a)}>
                  Remove…
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {manage && (
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault()
            if (form.value.trim()) add.mutate()
          }}
        >
          {kinds.length > 1 && (
            <SelectField
              label="Alias type"
              name="alias-kind"
              value={form.kind}
              onChange={(e) => setForm({ ...form, kind: e.target.value })}
              options={kinds}
            />
          )}
          <TextField
            label={versioned ? 'Reported name' : 'Reported model or part number'}
            name="alias-value"
            value={form.value}
            onChange={(e) => setForm({ ...form, value: e.target.value })}
          />
          {versioned && (
            <TextField
              label="Reported version or build (optional)"
              name="alias-release"
              help={`Leave empty to mean release ${product.release}.`}
              value={form.release}
              onChange={(e) => setForm({ ...form, release: e.target.value })}
            />
          )}
          {add.isError && <p className="field__error">{add.error.message}</p>}
          <div className="form-actions">
            <Button type="submit" busy={add.isPending}>
              Add alias
            </Button>
          </div>
        </form>
      )}
      {removing && (
        <ReasonDialog
          title={`Remove alias ${removing.value}`}
          confirmLabel="Remove alias"
          busy={remove.isPending}
          error={remove.isError ? remove.error.message : null}
          onClose={() => setRemoving(null)}
          onConfirm={(reason) => remove.mutate(reason)}
        />
      )}
    </section>
  )
}

const STATEMENT_LABEL: Record<string, string> = {
  '': 'None recorded',
  supported: 'Vendor states the product is supported',
  not_announced: 'Vendor has not announced end of life',
}

function Statement({ product }: { product: LifecycleProductDetail }) {
  const { can } = useSession()
  const refresh = useRefresh(product.id)
  const sources = useQuery({
    queryKey: lifecycleKeys.sources,
    queryFn: () => fetchSources(),
    enabled: can(PERMISSIONS.lifecycleApprove),
  })
  const [form, setForm] = useState({
    support_statement: product.support_statement,
    statement_source: product.statement_source?.id ?? '',
  })
  const save = useMutation({
    mutationFn: () =>
      setStatement(product.id, product.version, {
        support_statement: form.support_statement,
        statement_source: form.statement_source || null,
        verify: true,
      }),
    onSuccess: refresh,
  })
  return (
    <section className="panel" aria-labelledby="statement-title">
      <h2 className="section-title" id="statement-title">
        Support statement
      </h2>
      <p className="field__help">
        Used only when no dates are published. Without a verified statement, the product is Unknown.
      </p>
      <p>
        {STATEMENT_LABEL[product.support_statement]}
        {product.statement_verified_by && (
          <span className="cell-secondary">
            Verified by {product.statement_verified_by}, {formatDate(product.statement_verified_at)}
            {product.statement_source && ` · ${product.statement_source.title}`}
          </span>
        )}
      </p>
      {can(PERMISSIONS.lifecycleApprove) && (
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <SelectField
            label="Statement"
            name="statement"
            value={form.support_statement}
            onChange={(e) => setForm({ ...form, support_statement: e.target.value as typeof form.support_statement })}
            options={Object.entries(STATEMENT_LABEL).map(([value, label]) => ({ value, label }))}
          />
          {form.support_statement && (
            <SelectField
              label="Source"
              name="statement-source"
              value={form.statement_source}
              onChange={(e) => setForm({ ...form, statement_source: e.target.value })}
              options={[
                { value: '', label: 'Choose a source' },
                ...(sources.data ?? []).map((s) => ({ value: s.id, label: s.title })),
              ]}
            />
          )}
          {save.isError && <p className="field__error">{save.error.message}</p>}
          <div className="form-actions">
            <Button type="submit" busy={save.isPending}>
              Save and verify
            </Button>
          </div>
        </form>
      )}
    </section>
  )
}

function AffectedAssets({ productId }: { productId: string }) {
  const assets = useInfiniteQuery({
    queryKey: lifecycleKeys.productAssets(productId),
    queryFn: ({ pageParam }) => fetchProductAssets(productId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = assets.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section className="panel panel--flush" aria-labelledby="affected-title">
      <div className="panel__header">
        <h2 className="section-title" id="affected-title">
          Matched assets in your sites ({assets.data?.pages[0]?.count ?? 0})
        </h2>
      </div>
      {assets.isPending && <LoadingState label="Loading assets…" />}
      {assets.isSuccess && items.length === 0 && <EmptyState title="No assets in your sites match this product." />}
      {items.length > 0 && (
        <table className="data-table data-table--nowrap">
          <caption className="visually-hidden">Matched assets</caption>
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Status</th>
              <th scope="col">Date</th>
              <th scope="col">Days left</th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td>
                  <Link className="table-link" to={`/assets/${a.asset.id}?tab=lifecycle`}>
                    {a.asset.name}
                  </Link>
                  <span className="cell-secondary">{a.asset.site.code}</span>
                </td>
                <td>
                  <StatusBadge
                    tone={LIFECYCLE_STATUS[a.effective_status].tone}
                    label={LIFECYCLE_STATUS[a.effective_status].label}
                  />
                </td>
                <td className="nowrap">{formatDate(a.milestone_date)}</td>
                <td className="nowrap">{daysLabel(a.days_remaining)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {assets.hasNextPage && (
        <div className="table-footer">
          <Button onClick={() => assets.fetchNextPage()} busy={assets.isFetchingNextPage}>
            Load more
          </Button>
        </div>
      )}
    </section>
  )
}

function Revisions({ productId }: { productId: string }) {
  const revisions = useQuery({ queryKey: lifecycleKeys.revisions(productId), queryFn: () => fetchRevisions(productId) })
  return (
    <section className="panel" aria-labelledby="revisions-title">
      <h2 className="section-title" id="revisions-title">
        Change history
      </h2>
      {revisions.isPending && <LoadingState label="Loading history…" />}
      {revisions.data && (
        <ol className="change-list change-list--plain">
          {revisions.data.map((r) => (
            <li key={r.number}>
              <span className="mono">#{r.number}</span> {r.action.replace('.', ' ')}
              {r.summary && ` — ${r.summary}`}
              <span className="cell-secondary">
                {r.actor ?? 'system'}, {formatDateTime(r.created_at)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function EditProductDialog({ product, onClose }: { product: LifecycleProductDetail; onClose: () => void }) {
  const refresh = useRefresh(product.id)
  const [form, setForm] = useState({
    vendor: product.vendor,
    name: product.name,
    release: product.release,
    family: product.family,
    description: product.description,
    is_active: product.is_active,
    reason: '',
  })
  const save = useMutation({
    mutationFn: () => updateProduct(product.id, product.version, form),
    onSuccess: () => {
      refresh()
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog open title="Edit catalogue product" confirmLabel="Save changes" busy={save.isPending} onClose={onClose} onConfirm={() => save.mutate()}>
      {save.isError && (
        <ErrorSummary message={save.error.message} fieldErrors={errors} fieldLabels={{ reason: 'Reason', name: 'Name' }} />
      )}
      <TextField label="Vendor" name="edit-vendor" value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} />
      <TextField label="Name" name="edit-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} error={errors.name} />
      <TextField label="Release" name="edit-release" value={form.release} onChange={(e) => setForm({ ...form, release: e.target.value })} />
      <TextField label="Family" name="edit-family" value={form.family} onChange={(e) => setForm({ ...form, family: e.target.value })} />
      <label className="checkbox">
        <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
        <span className="checkbox__label">Active (used for matching)</span>
      </label>
      <TextAreaField
        label="Reason for the change"
        name="edit-reason"
        value={form.reason}
        onChange={(e) => setForm({ ...form, reason: e.target.value })}
        error={errors.reason}
      />
      <p className="inline-note">Changing the vendor, name or release re-matches every asset.</p>
    </Dialog>
  )
}
