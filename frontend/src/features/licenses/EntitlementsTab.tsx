import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  endEntitlementAllocation,
  fetchEntitlementAllocations,
  fetchLicenseProducts,
  licenseKeys,
} from '../../shared/api/licenses'
import { PERMISSIONS, type EntitlementAllocation } from '../../shared/api/types'
import { formatDate } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { ExportDialog } from '../exports/ExportDialog'
import { ProductDialog } from './dialogs'
import { METRIC, availableLabel } from './labels'

const n = (value: number) => value.toLocaleString('en-GB')

/** License products with purchased, allocated and available units, and the number of
 * assets that have the linked software installed: four different totals, kept apart. */
export function EntitlementsTab() {
  const { can } = useSession()
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [creating, setCreating] = useState(false)
  const [exporting, setExporting] = useState(false)
  const query = { q: q || undefined }
  const products = useInfiniteQuery({
    queryKey: licenseKeys.products(query),
    queryFn: ({ pageParam }) => fetchLicenseProducts(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = products.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section aria-label="License entitlements">
      <p className="inline-note">
        Purchases recorded by your team. Purchased units count entitlements in term; allocated units are what you
        assigned from them; installed shows assets in your sites with the linked software. ITAM does not judge license
        compliance.
      </p>
      <div className="toolbar">
        <TextField label="Search" name="lp-q" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="toolbar__actions">
          {can(PERMISSIONS.exportsRun) && <Button onClick={() => setExporting(true)}>Export…</Button>}
          {can(PERMISSIONS.licensesManage) && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              New license product
            </Button>
          )}
        </div>
      </div>
      <div className="panel panel--flush" aria-live="polite">
        {products.isPending && <LoadingState label="Loading license products…" />}
        {products.isError && <QueryErrorState error={products.error} what="license products" />}
        {products.isSuccess && items.length === 0 && (
          <EmptyState title="No license products recorded.">
            Add a license product, then record what was purchased, or import entitlements (Imports → License
            entitlements).
          </EmptyState>
        )}
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table data-table--nowrap">
              <caption className="visually-hidden">License products</caption>
              <thead>
                <tr>
                  <th scope="col">Product</th>
                  <th scope="col">Counted per</th>
                  <th scope="col" className="num">
                    Purchased
                  </th>
                  <th scope="col" className="num">
                    Allocated
                  </th>
                  <th scope="col">Available</th>
                  <th scope="col" className="num">
                    Installed (assets)
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((p) => {
                  const available = availableLabel(p.available)
                  return (
                    <tr key={p.id}>
                      <td>
                        <Link className="table-link" to={`/software/licenses/${p.id}`}>
                          {p.name}
                        </Link>
                        <span className="cell-secondary">
                          {[p.publisher, p.sku].filter(Boolean).join(' · ') || 'No publisher or SKU'}
                        </span>
                      </td>
                      <td>{METRIC[p.metric] ?? p.metric}</td>
                      <td className="num">{n(p.purchased)}</td>
                      <td className="num">{n(p.allocated)}</td>
                      <td>{available.over ? <StatusBadge tone="warning" label={available.text} /> : available.text}</td>
                      <td className="num">
                        {p.observed_assets === null ? (
                          <span className="cell-muted">Not linked</span>
                        ) : (
                          n(p.observed_assets)
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {products.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => products.fetchNextPage()} busy={products.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </div>
      <ExportDialog
        open={exporting}
        onClose={() => setExporting(false)}
        family="license_entitlements"
        defaultRelated={['allocations']}
      />
      {creating && (
        <ProductDialog onClose={() => setCreating(false)} onSaved={(p) => navigate(`/software/licenses/${p.id}`)} />
      )}
    </section>
  )
}

/** Allocations from recorded entitlements. Allocations to assets outside your sites are
 * not listed (product totals still count them). */
export function AllocationsTable({
  query,
  showProduct = true,
}: {
  query: Record<string, string | undefined>
  showProduct?: boolean
}) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const [ending, setEnding] = useState<EntitlementAllocation | null>(null)
  const rows = useInfiniteQuery({
    queryKey: licenseKeys.entitlementAllocations(query),
    queryFn: ({ pageParam }) => fetchEntitlementAllocations(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const end = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => endEntitlementAllocation(id, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: licenseKeys.all })
      setEnding(null)
    },
  })
  const manage = can(PERMISSIONS.licensesManage)
  const items = rows.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <div className="panel panel--flush" aria-live="polite">
      {rows.isPending && <LoadingState label="Loading allocations…" />}
      {rows.isError && <QueryErrorState error={rows.error} what="allocations" />}
      {rows.isSuccess && items.length === 0 && <EmptyState title="No allocations." />}
      {items.length > 0 && (
        <div className="table-scroll">
          <table className="data-table data-table--nowrap">
            <caption className="visually-hidden">Allocations</caption>
            <thead>
              <tr>
                <th scope="col">Allocated to</th>
                <th scope="col">{showProduct ? 'License' : 'Entitlement'}</th>
                <th scope="col" className="num">
                  Units
                </th>
                <th scope="col">Allocated</th>
                <th scope="col">Status</th>
                {manage && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td>
                    {a.asset ? (
                      <>
                        <Link className="table-link" to={`/assets/${a.asset.id}`}>
                          {a.asset.name}
                        </Link>
                        <span className="cell-secondary">{a.asset.site_code}</span>
                      </>
                    ) : (
                      <>
                        {a.user_name}
                        <span className="cell-secondary">Named user</span>
                      </>
                    )}
                  </td>
                  <td>
                    {showProduct ? (
                      <>
                        <Link className="table-link" to={`/software/licenses/${a.entitlement.product_id}`}>
                          {a.entitlement.product_label}
                        </Link>
                        <span className="cell-secondary">{a.entitlement.reference}</span>
                      </>
                    ) : (
                      a.entitlement.reference
                    )}
                  </td>
                  <td className="num">{n(a.units)}</td>
                  <td>
                    {formatDate(a.allocated_at)}
                    {a.allocated_by && <span className="cell-secondary">by {a.allocated_by}</span>}
                  </td>
                  <td>
                    {a.ended_at ? (
                      <>
                        <StatusBadge tone="neutral" label={`Ended ${formatDate(a.ended_at)}`} />
                        <span className="cell-secondary">{a.ended_reason}</span>
                      </>
                    ) : (
                      <StatusBadge tone="success" label="Allocated" />
                    )}
                  </td>
                  {manage && (
                    <td>
                      {!a.ended_at && (
                        <Button variant="quiet" onClick={() => setEnding(a)}>
                          End…
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.hasNextPage && (
        <div className="table-footer">
          <Button onClick={() => rows.fetchNextPage()} busy={rows.isFetchingNextPage}>
            Load more
          </Button>
        </div>
      )}
      {ending && (
        <ReasonDialog
          title="End allocation"
          confirmLabel="End allocation"
          help={`The units return to ${ending.entitlement.reference}. The allocation stays in the history.`}
          busy={end.isPending}
          error={end.error?.message}
          onClose={() => setEnding(null)}
          onConfirm={(reason) => end.mutate({ id: ending.id, reason })}
        />
      )}
    </div>
  )
}

export function AllocationsTab() {
  const [q, setQ] = useState('')
  const [target, setTarget] = useState('')
  const [ended, setEnded] = useState(false)
  return (
    <section aria-label="License allocations">
      <p className="inline-note">
        Units allocated from recorded entitlements. Microsoft 365 user assignments are read from the tenant and shown
        under Microsoft 365.
      </p>
      <div className="toolbar">
        <TextField label="Search" name="alloc-list-q" value={q} onChange={(e) => setQ(e.target.value)} />
        <SelectField
          label="Allocated to"
          name="alloc-list-target"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          options={[
            { value: '', label: 'Assets and users' },
            { value: 'asset', label: 'Assets' },
            { value: 'user', label: 'Named users' },
          ]}
        />
        <label className="checkbox">
          <input type="checkbox" checked={ended} onChange={(e) => setEnded(e.target.checked)} /> Show ended
        </label>
      </div>
      <AllocationsTable
        query={{
          q: q || undefined,
          target: target || undefined,
          include_ended: ended ? 'true' : undefined,
        }}
      />
    </section>
  )
}
