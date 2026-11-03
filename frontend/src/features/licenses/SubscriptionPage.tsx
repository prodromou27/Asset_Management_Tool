import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchAllocations, fetchSubscription, licenseKeys, type AllocationFilters } from '../../shared/api/licenses'
import type { LicenseSubscriptionDetail } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ASSIGNMENT_STATE, CAPABILITY, METHOD, count } from './labels'

export function SubscriptionPage() {
  const { id = '' } = useParams()
  const sku = useQuery({ queryKey: licenseKeys.subscription(id), queryFn: () => fetchSubscription(id) })
  const crumb = (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <Link to="/licenses">Licenses</Link>
    </nav>
  )
  if (sku.isPending) return <LoadingState label="Loading subscription…" />
  if (sku.isError)
    return (
      <div className="page">
        {crumb}
        <QueryErrorState error={sku.error} what="this subscription" />
      </div>
    )
  const s = sku.data
  const status = CAPABILITY[s.capability_status] ?? { label: s.capability_status || 'Unknown', tone: 'neutral' }
  return (
    <div className="page page--wide">
      {crumb}
      <PageHeader title={s.sku_part_number || s.sku_id} meta={`${s.instance.name} · tenant ${s.tenant_id}`} />
      <p className="inline-note">
        Quantities as reported by the tenant at the snapshot time. &quot;Assigned users&quot; is ITAM&apos;s count of
        distinct users holding the SKU (direct and group assignments counted once). Not a billing or compliance figure.
      </p>
      <dl className="status-strip" aria-label="Subscription quantities">
        <div>
          <dt>Status</dt>
          <dd>
            <StatusBadge tone={status.tone} label={status.label} />
          </dd>
        </div>
        <div>
          <dt>Purchased (enabled)</dt>
          <dd>{count(s.latest?.enabled_units)}</dd>
        </div>
        <div>
          <dt>Consumed (tenant)</dt>
          <dd>{count(s.latest?.consumed_units)}</dd>
        </div>
        <div>
          <dt>Assigned users (ITAM)</dt>
          <dd>{count(s.latest?.assigned_users)}</dd>
        </div>
        <div>
          <dt>Available</dt>
          <dd>{count(s.latest?.available_units)}</dd>
        </div>
      </dl>
      <div className="detail-layout">
        <div className="stack">
          <Allocations skuId={s.id} />
          <Snapshots s={s} />
        </div>
        <div className="detail-layout__side">
          <section className="panel" aria-labelledby="sku-details">
            <h2 className="section-title" id="sku-details">
              Details
            </h2>
            <dl className="meta-grid meta-grid--stacked">
              <dt>SKU ID</dt>
              <dd className="mono">{s.sku_id}</dd>
              <dt>Applies to</dt>
              <dd>{s.applies_to || 'Not reported'}</dd>
              <dt>First seen</dt>
              <dd>{formatDateTime(s.first_seen_at)}</dd>
              <dt>Last seen</dt>
              <dd>{formatDateTime(s.last_seen_at)}</dd>
              <dt>Service plans</dt>
              <dd>{s.service_plans.length ? s.service_plans.join(', ') : 'None reported'}</dd>
            </dl>
            {!s.subscribed && (
              <p className="field__help">
                Users hold this SKU, but the tenant does not list it among its subscriptions (for example an expired
                subscription), so no quantities are reported.
              </p>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function Snapshots({ s }: { s: LicenseSubscriptionDetail }) {
  return (
    <section className="panel panel--flush" aria-labelledby="snapshots-heading">
      <h2 className="section-title section-title--inset" id="snapshots-heading">
        Quantity history
      </h2>
      {s.snapshots.length === 0 ? (
        <EmptyState title="No quantities reported for this SKU." />
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Snapshot</th>
              <th scope="col">Status</th>
              <th scope="col" className="num">Purchased</th>
              <th scope="col" className="num">Warning / suspended</th>
              <th scope="col" className="num">Consumed</th>
              <th scope="col" className="num">Assigned users (direct / group)</th>
            </tr>
          </thead>
          <tbody>
            {s.snapshots.map((snap) => (
              <tr key={snap.id}>
                <td className="nowrap">
                  {formatDateTime(snap.taken_at)}
                  <span className="cell-secondary">Last confirmed {formatDateTime(snap.last_confirmed_at)}</span>
                </td>
                <td>{CAPABILITY[snap.capability_status]?.label ?? (snap.capability_status || 'Unknown')}</td>
                <td className="num">{count(snap.enabled_units)}</td>
                <td className="num">
                  {count(snap.warning_units)} / {count(snap.suspended_units)}
                </td>
                <td className="num">{count(snap.consumed_units)}</td>
                <td className="num">
                  {count(snap.assigned_users)}
                  {snap.assigned_users !== null && (
                    <span className="cell-secondary">
                      {count(snap.direct_users)} / {count(snap.group_users)}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function Allocations({ skuId }: { skuId: string }) {
  const [draft, setDraft] = useState('')
  const [filters, setFilters] = useState<AllocationFilters>({ sku: skuId })
  const rows = useInfiniteQuery({
    queryKey: licenseKeys.allocations(filters),
    queryFn: ({ pageParam }) => fetchAllocations(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = rows.data?.pages.flatMap((p) => p.items) ?? []
  const total = rows.data?.pages[0]?.count

  return (
    <section className="panel panel--flush" aria-labelledby="alloc-heading" aria-live="polite">
      <h2 className="section-title section-title--inset" id="alloc-heading">
        Assigned users{total !== undefined && ` (${total})`}
      </h2>
      <form
        className="toolbar"
        role="search"
        onSubmit={(e: FormEvent) => {
          e.preventDefault()
          setFilters((f) => ({ ...f, q: draft.trim() || undefined }))
        }}
      >
        <TextField label="User" name="alloc_q" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <SelectField
          label="Assignment"
          name="alloc_method"
          options={[
            { value: '', label: 'Any method' },
            { value: 'direct', label: 'Direct only' },
            { value: 'group', label: 'Group only' },
            { value: 'direct_and_group', label: 'Direct and group' },
          ]}
          value={filters.method ?? ''}
          onChange={(e) =>
            setFilters((f) => ({ ...f, method: (e.target.value || undefined) as AllocationFilters['method'] }))
          }
        />
        <SelectField
          label="Include"
          name="alloc_ended"
          options={[
            { value: '', label: 'Current assignments' },
            { value: 'true', label: 'Current and ended' },
          ]}
          value={filters.include_ended ?? ''}
          onChange={(e) => setFilters((f) => ({ ...f, include_ended: e.target.value ? 'true' : undefined }))}
        />
        <div className="toolbar__actions">
          <Button type="submit">Apply</Button>
        </div>
      </form>
      {rows.isPending && <LoadingState label="Loading assignments…" />}
      {rows.isError && <QueryErrorState error={rows.error} what="license assignments" />}
      {rows.isSuccess && items.length === 0 && <EmptyState title="No assignments match." />}
      {items.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">User</th>
              <th scope="col">Assignment</th>
              <th scope="col">State</th>
              <th scope="col">First seen</th>
              <th scope="col">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => {
              const state = ASSIGNMENT_STATE[a.state] ?? { label: a.state, tone: 'neutral' as const }
              return (
                <tr key={a.id}>
                  <td>
                    {a.user.display_name || a.user.user_principal_name}
                    <span className="cell-secondary">{a.user.user_principal_name}</span>
                    {a.user.account_enabled === false && <span className="cell-secondary">Account disabled</span>}
                  </td>
                  <td>
                    {METHOD[a.method] ?? a.method}
                    {a.groups.length > 0 && (
                      <span className="cell-secondary">
                        {a.groups.every((g) => g.display_name)
                          ? a.groups.map((g) => g.display_name).join(', ')
                          : a.groups.length === 1
                            ? '1 group'
                            : `${a.groups.length} groups`}
                      </span>
                    )}
                  </td>
                  <td>
                    <StatusBadge tone={state.tone} label={state.label} />
                  </td>
                  <td className="nowrap">{formatDateTime(a.first_seen_at)}</td>
                  <td className="nowrap">
                    {a.ended_at ? `Ended ${formatDateTime(a.ended_at)}` : formatDateTime(a.last_seen_at)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {rows.hasNextPage && (
        <div className="table-footer">
          <Button onClick={() => rows.fetchNextPage()} busy={rows.isFetchingNextPage}>
            Load more
          </Button>
        </div>
      )}
    </section>
  )
}
