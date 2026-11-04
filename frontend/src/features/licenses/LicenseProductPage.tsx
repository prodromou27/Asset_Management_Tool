import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { fetchLicenseProduct, licenseKeys, retireEntitlement } from '../../shared/api/licenses'
import { PERMISSIONS, type LicenseEntitlement } from '../../shared/api/types'
import { formatDate } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { AllocateDialog, EntitlementDialog, ProductDialog } from './dialogs'
import { AllocationsTable } from './EntitlementsTab'
import { ENTITLEMENT_STATUS, METRIC, availableLabel } from './labels'

const n = (value: number) => value.toLocaleString('en-GB')

export function LicenseProductPage() {
  const { id = '' } = useParams()
  const { can } = useSession()
  const queryClient = useQueryClient()
  const product = useQuery({
    queryKey: licenseKeys.product(id),
    queryFn: () => fetchLicenseProduct(id),
  })
  const [editing, setEditing] = useState(false)
  const [recording, setRecording] = useState<LicenseEntitlement | 'new' | null>(null)
  const [allocating, setAllocating] = useState<LicenseEntitlement | null>(null)
  const [retiring, setRetiring] = useState<LicenseEntitlement | null>(null)
  const retire = useMutation({
    mutationFn: ({ e, reason }: { e: LicenseEntitlement; reason: string }) =>
      retireEntitlement(e.id, e.version, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: licenseKeys.all })
      setRetiring(null)
    },
  })

  const crumb = (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <Link to="/software?tab=entitlements">Software &amp; Licenses</Link>
    </nav>
  )
  if (product.isPending) return <LoadingState label="Loading license product…" />
  if (product.isError)
    return (
      <div className="page">
        {crumb}
        <QueryErrorState error={product.error} what="this license product" />
      </div>
    )
  const p = product.data
  const manage = can(PERMISSIONS.licensesManage)
  const available = availableLabel(p.available)
  return (
    <div className="page page--wide">
      {crumb}
      <PageHeader
        title={p.name}
        meta={[p.publisher, p.sku, METRIC[p.metric]].filter(Boolean).join(' · ')}
        actions={
          manage && (
            <>
              <Button onClick={() => setEditing(true)}>Edit product</Button>
              <Button variant="primary" onClick={() => setRecording('new')}>
                Record entitlement
              </Button>
            </>
          )
        }
      />
      {!p.is_active && (
        <p className="inline-note">This license product is inactive; new entitlements cannot be recorded.</p>
      )}
      <dl className="kpi-strip" aria-label="Totals">
        <div className="kpi-strip__item">
          <dt>Purchased units</dt>
          <dd>{n(p.purchased)}</dd>
          <span className="cell-secondary">
            {p.entitlements_in_term} {p.entitlements_in_term === 1 ? 'entitlement' : 'entitlements'} in term
          </span>
        </div>
        <div className="kpi-strip__item">
          <dt>Allocated units</dt>
          <dd>{n(p.allocated)}</dd>
          <span className="cell-secondary">All sites</span>
        </div>
        <div className="kpi-strip__item">
          <dt>Available</dt>
          <dd>{available.over ? <StatusBadge tone="warning" label={available.text} /> : available.text}</dd>
        </div>
        <div className="kpi-strip__item">
          <dt>Installed (assets in your sites)</dt>
          <dd>
            {p.software_product ? (
              <Link to={`/software/products/${p.software_product.id}`}>{n(p.observed_assets ?? 0)}</Link>
            ) : (
              <span className="cell-muted">Not linked</span>
            )}
          </dd>
          {p.software_product && (
            <span className="cell-secondary">
              {`${p.software_product.publisher} ${p.software_product.name}`.trim()}
            </span>
          )}
        </div>
      </dl>
      <p className="inline-note">
        Totals are arithmetic over what was recorded; installations are observed by discovery. ITAM does not judge
        license compliance.
      </p>

      <section className="panel panel--flush" aria-labelledby="ent-title">
        <div className="panel__header">
          <h2 className="section-title" id="ent-title">
            Entitlements
          </h2>
        </div>
        {p.entitlements.length === 0 ? (
          <EmptyState title="No entitlements recorded.">
            {manage ? 'Record what was purchased with “Record entitlement”.' : undefined}
          </EmptyState>
        ) : (
          <div className="table-scroll">
            <table className="data-table data-table--nowrap">
              <caption className="visually-hidden">Entitlements</caption>
              <thead>
                <tr>
                  <th scope="col">Reference</th>
                  <th scope="col">Term</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">
                    Purchased
                  </th>
                  <th scope="col" className="num">
                    Allocated
                  </th>
                  <th scope="col">Supplier / owner</th>
                  {manage && (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {p.entitlements.map((e) => {
                  const s = ENTITLEMENT_STATUS[e.status]
                  return (
                    <tr key={e.id}>
                      <td>
                        {e.reference}
                        <span className="cell-secondary">{e.source === 'import' ? 'Imported' : 'Entered by hand'}</span>
                      </td>
                      <td>
                        {e.starts_on ? formatDate(e.starts_on) : 'Open start'} –{' '}
                        {e.ends_on ? formatDate(e.ends_on) : 'Perpetual'}
                      </td>
                      <td>
                        <StatusBadge tone={s.tone} label={s.label} />
                        {e.retired_reason && <span className="cell-secondary">{e.retired_reason}</span>}
                      </td>
                      <td className="num">{n(e.quantity)}</td>
                      <td className="num">{n(e.allocated)}</td>
                      <td>
                        {e.supplier || <span className="cell-muted">–</span>}
                        {e.owner && <span className="cell-secondary">{e.owner}</span>}
                      </td>
                      {manage && (
                        <td>
                          <div className="cell-actions">
                            {(e.status === 'active' || e.status === 'not_started') && (
                              <Button variant="quiet" onClick={() => setAllocating(e)}>
                                Allocate…
                              </Button>
                            )}
                            {e.status !== 'retired' && (
                              <>
                                <Button variant="quiet" onClick={() => setRecording(e)}>
                                  Edit…
                                </Button>
                                <Button variant="quiet" onClick={() => setRetiring(e)}>
                                  Retire…
                                </Button>
                              </>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <h2 className="section-title">Allocations</h2>
      <AllocationsTable query={{ product: p.id }} showProduct={false} />

      {editing && <ProductDialog product={p} onClose={() => setEditing(false)} />}
      {recording && (
        <EntitlementDialog
          productId={p.id}
          entitlement={recording === 'new' ? undefined : recording}
          onClose={() => setRecording(null)}
        />
      )}
      {allocating && <AllocateDialog entitlement={allocating} onClose={() => setAllocating(null)} />}
      {retiring && (
        <ReasonDialog
          title={`Retire ${retiring.reference}`}
          confirmLabel="Retire entitlement"
          help="Its open allocations end with it. The entitlement stays in the history and is no longer counted."
          busy={retire.isPending}
          error={retire.error?.message}
          onClose={() => setRetiring(null)}
          onConfirm={(reason) => retire.mutate({ e: retiring, reason })}
        />
      )}
    </div>
  )
}
