import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { previewClassification } from '../../shared/api/assets'
import {
  discoveryKeys,
  dismissCategoryReview,
  fetchCategoryReviews,
  reclassifyFromReview,
} from '../../shared/api/discovery'
import { PERMISSIONS, type CategoryReview } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField } from '../../shared/ui/Field'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge, type StatusTone } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from './ReasonDialog'

const KIND: Record<CategoryReview['kind'], { label: string; tone: StatusTone }> = {
  different_class: { label: 'Different asset class', tone: 'danger' },
  different_type: { label: 'Different type', tone: 'warning' },
  more_specific: { label: 'More specific type', tone: 'neutral' },
}

const STATUS: Record<CategoryReview['status'], string> = {
  open: 'Open',
  reclassified: 'Asset reclassified',
  dismissed: 'Current category kept',
  resolved: 'No longer suggested',
}

/** Sources never change an asset's category: a differing source type waits here for a
 * person to reclassify (audited, with template impact) or keep the current category. */
export function CategoryReviews() {
  const { can } = useSession()
  const [status, setStatus] = useState('open')
  const [acting, setActing] = useState<{ review: CategoryReview; keep: boolean } | null>(null)
  const reviews = useInfiniteQuery({
    queryKey: discoveryKeys.categoryReviews(status),
    queryFn: ({ pageParam }) => fetchCategoryReviews(status, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = reviews.data?.pages.flatMap((p) => p.items) ?? []
  const mayDecide = can(PERMISSIONS.assetsReclassify)

  return (
    <>
      <div className="toolbar">
        <SelectField
          label="Status"
          name="review_status"
          options={[...Object.entries(STATUS).map(([value, label]) => ({ value, label })), { value: 'all', label: 'All' }]}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        />
      </div>
      <section className="panel panel--flush" aria-live="polite" aria-label="Category reviews">
        {reviews.isPending && <LoadingState label="Loading category reviews…" />}
        {reviews.isError && <QueryErrorState error={reviews.error} what="category reviews" />}
        {reviews.isSuccess && items.length === 0 && (
          <EmptyState title="No category reviews.">
            A review opens when a linked source reports a device type that maps to a different category than the
            asset&apos;s.
          </EmptyState>
        )}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Category reviews</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Current category</th>
                <th scope="col">Source suggests</th>
                <th scope="col">Source</th>
                <th scope="col">Updated</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id}>
                  <td>
                    <Link to={`/assets/${r.asset.id}`}>{r.asset.name}</Link>
                    <span className="cell-secondary mono">{r.asset.site.code}</span>
                  </td>
                  <td>{r.current_category.path}</td>
                  <td>
                    {r.suggested_category.path}
                    <span className="cell-secondary">
                      <StatusBadge tone={KIND[r.kind].tone} label={KIND[r.kind].label} />
                    </span>
                  </td>
                  <td>
                    {r.instance.name}
                    <span className="cell-secondary">
                      Reported type {r.reported_type || 'unknown'} · device {r.external_id}
                    </span>
                  </td>
                  <td className="nowrap">{formatDateTime(r.modified_at)}</td>
                  <td className="cell-actions">
                    {r.status === 'open' && mayDecide ? (
                      <>
                        <Button variant="quiet" onClick={() => setActing({ review: r, keep: false })}>
                          Reclassify…<span className="visually-hidden"> {r.asset.name}</span>
                        </Button>
                        <Button variant="quiet" onClick={() => setActing({ review: r, keep: true })}>
                          Keep current…<span className="visually-hidden"> category of {r.asset.name}</span>
                        </Button>
                      </>
                    ) : (
                      <span className="cell-muted">
                        {r.status === 'open'
                          ? 'Needs reclassify rights'
                          : `${STATUS[r.status]}${r.resolution_reason ? `: ${r.resolution_reason}` : ''}`}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {reviews.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => reviews.fetchNextPage()} busy={reviews.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </section>
      {acting && <DecisionDialog {...acting} onClose={() => setActing(null)} />}
    </>
  )
}

function DecisionDialog({ review, keep, onClose }: { review: CategoryReview; keep: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const impact = useQuery({
    queryKey: ['assets', 'classification-preview', review.asset.id, review.suggested_category.id],
    queryFn: () => previewClassification(review.asset.id, review.suggested_category.id),
    enabled: !keep,
  })
  const mutation = useMutation({
    mutationFn: (reason: string) =>
      keep
        ? dismissCategoryReview(review.id, review.version, reason)
        : reclassifyFromReview(review.id, review.version, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['discovery', 'category-reviews'] })
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      onClose()
    },
  })
  const missing = impact.data?.required_missing ?? []
  return (
    <ReasonDialog
      title={keep ? `Keep ${review.current_category.name} for ${review.asset.name}?` : `Reclassify ${review.asset.name}?`}
      confirmLabel={keep ? 'Keep current category' : `Change to ${review.suggested_category.name}`}
      help={
        keep
          ? `The asset stays in ${review.current_category.path}. ${review.instance.name} will not propose ${review.suggested_category.name} again unless its report changes.`
          : `Moves the asset from ${review.current_category.path} to ${review.suggested_category.path}. Same asset ID, history, links and relationships are kept.`
      }
      busy={mutation.isPending || (!keep && (impact.isPending || missing.length > 0))}
      error={mutation.error ? mutation.error.message : null}
      onClose={onClose}
      onConfirm={(reason) => mutation.mutate(reason)}
    >
      {!keep && impact.data && (
        <ul className="plain-list" aria-label="Template impact">
          {impact.data.fields_added.length > 0 && (
            <li>Adds fields: {impact.data.fields_added.map((f) => f.label).join(', ')}</li>
          )}
          {impact.data.values_retained_read_only.length > 0 && (
            <li>Keeps as read-only: {impact.data.values_retained_read_only.join(', ')}</li>
          )}
        </ul>
      )}
      {!keep && missing.length > 0 && (
        <p className="inline-note inline-note--warning">
          {review.suggested_category.name} requires {missing.join(', ')}. Fill them with{' '}
          <Link to={`/assets/${review.asset.id}`}>Change category on the asset</Link>; this review then closes
          automatically.
        </p>
      )}
    </ReasonDialog>
  )
}
