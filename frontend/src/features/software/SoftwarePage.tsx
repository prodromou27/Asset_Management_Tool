import { useInfiniteQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { fetchInstallations, fetchSoftwareProducts, softwareKeys } from '../../shared/api/software'
import { formatDate } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { DeniedState, EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { Tabs } from '../../shared/ui/Tabs'
import { useSession } from '../../app/useSession'
import { PERMISSIONS } from '../../shared/api/types'
import { AllocationsTab, EntitlementsTab } from '../licenses/EntitlementsTab'
import { M365Subscriptions } from '../licenses/LicensesPage'
import { LIFECYCLE_STATUS } from '../lifecycle/labels'

export function SoftwarePage() {
  const [params, setParams] = useSearchParams()
  const { can } = useSession()
  const tabs = [
    ...(can(PERMISSIONS.assetsView)
      ? [
          { id: 'products', label: 'Installed software', content: <Products /> },
          { id: 'installations', label: 'Installations', content: <Installations /> },
        ]
      : []),
    ...(can(PERMISSIONS.licensesView)
      ? [
          { id: 'entitlements', label: 'Entitlements', content: <EntitlementsTab /> },
          { id: 'allocations', label: 'Allocations', content: <AllocationsTab /> },
          { id: 'm365', label: 'Microsoft 365', content: <M365Subscriptions /> },
        ]
      : []),
  ]
  const first = tabs[0]?.id ?? 'products'
  const tab = params.get('tab') ?? first
  if (tabs.length === 0) return <DeniedState what="software and licenses" />
  return (
    <div className="page page--wide">
      <PageHeader
        title="Software & Licenses"
        meta="Observed installations, recorded purchases and allocations, and Microsoft 365 tenant subscriptions are different totals and are kept apart."
      />
      <Tabs
        label="Software and license sections"
        selected={tab}
        onSelect={(next) => {
          const search = new URLSearchParams(params)
          if (next === first) search.delete('tab')
          else search.set('tab', next)
          setParams(search, { replace: true })
        }}
        tabs={tabs}
      />
    </div>
  )
}

function Products() {
  const [q, setQ] = useState('')
  const [lifecycle, setLifecycle] = useState('')
  const query = { q: q || undefined, lifecycle: lifecycle || undefined }
  const products = useInfiniteQuery({
    queryKey: softwareKeys.products(query),
    queryFn: ({ pageParam }) => fetchSoftwareProducts(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = products.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section aria-label="Software products">
      <p className="inline-note">
        Software reported by Endpoint Central and Intune (when enabled per integration) or recorded by hand. Counts are
        observed installations in your sites, not licenses.
      </p>
      <div className="toolbar">
        <TextField label="Search" name="software-q" value={q} onChange={(e) => setQ(e.target.value)} />
        <SelectField
          label="Lifecycle"
          name="software-lifecycle"
          value={lifecycle}
          onChange={(e) => setLifecycle(e.target.value)}
          options={[
            { value: '', label: 'All products' },
            { value: 'ended', label: 'With versions past end of support' },
            { value: 'review', label: 'With a lifecycle match to review' },
          ]}
        />
      </div>
      <div className="panel panel--flush" aria-live="polite">
        {products.isPending && <LoadingState label="Loading software…" />}
        {products.isError && <QueryErrorState error={products.error} what="software" />}
        {products.isSuccess && items.length === 0 && (
          <EmptyState title="No installed software found.">
            Turn on "Collect installed software" on an Endpoint Central or Intune integration, or
            record software on an asset's Software tab.
          </EmptyState>
        )}
        {items.length > 0 && (
          <table className="data-table data-table--nowrap">
            <caption className="visually-hidden">Software products</caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">Publisher</th>
                <th scope="col">Versions</th>
                <th scope="col">Installations</th>
                <th scope="col">Lifecycle</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link className="table-link" to={`/software/products/${p.id}`}>
                      {p.name}
                    </Link>
                  </td>
                  <td>{p.publisher || <span className="cell-muted">Not reported</span>}</td>
                  <td>{p.version_count}</td>
                  <td>{p.installations.toLocaleString('en-GB')}</td>
                  <td>
                    {p.eos_versions > 0 ? (
                      <StatusBadge
                        tone="danger"
                        label={`${p.eos_versions} ${p.eos_versions === 1 ? 'version' : 'versions'} past end of support`}
                      />
                    ) : (
                      <span className="cell-muted">–</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {products.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => products.fetchNextPage()} busy={products.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </div>
    </section>
  )
}

export function InstallationsTable({ query }: { query: Record<string, string | undefined> }) {
  const rows = useInfiniteQuery({
    queryKey: softwareKeys.installations(query),
    queryFn: ({ pageParam }) => fetchInstallations(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = rows.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <div className="panel panel--flush" aria-live="polite">
      {rows.isPending && <LoadingState label="Loading installations…" />}
      {rows.isError && <QueryErrorState error={rows.error} what="installations" />}
      {rows.isSuccess && items.length === 0 && <EmptyState title="No installations match." />}
      {items.length > 0 && (
        <div className="table-scroll">
          <table className="data-table data-table--nowrap">
            <caption className="visually-hidden">Installations ({rows.data?.pages[0]?.count})</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Product</th>
                <th scope="col">Version</th>
                <th scope="col">Source</th>
                <th scope="col">Last seen</th>
                <th scope="col">Lifecycle</th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => {
                const s = LIFECYCLE_STATUS[r.lifecycle_status]
                return (
                  <tr key={r.id}>
                    <td>
                      {r.asset ? (
                        <Link className="table-link" to={`/assets/${r.asset.id}?tab=software`}>
                          {r.asset.name}
                        </Link>
                      ) : (
                        '–'
                      )}
                      {r.asset && <span className="cell-secondary">{r.asset.site_code}</span>}
                    </td>
                    <td>
                      <Link to={`/software/products/${r.product_id}`}>{r.name}</Link>
                      <span className="cell-secondary">{r.publisher}</span>
                    </td>
                    <td className="mono">{r.version || '–'}</td>
                    <td>{r.source}</td>
                    <td>{formatDate(r.last_seen_at)}</td>
                    <td>
                      <StatusBadge tone={s.tone} label={s.label} />
                    </td>
                  </tr>
                )
              })}
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
    </div>
  )
}

function Installations() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  return (
    <section aria-label="Installations">
      <div className="toolbar">
        <TextField label="Product or publisher" name="inst-q" value={q} onChange={(e) => setQ(e.target.value)} />
        <SelectField
          label="Lifecycle"
          name="inst-lifecycle"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { value: '', label: 'Any' },
            { value: 'eos,security_maintenance_ended', label: 'End of support / security ended' },
            { value: 'expiring', label: 'Approaching end of support' },
            { value: 'unverified', label: 'Needs review' },
          ]}
        />
      </div>
      <InstallationsTable query={{ q: q || undefined, lifecycle_status: status || undefined }} />
    </section>
  )
}
