import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  assetKeys,
  fetchAssets,
  fetchCategories,
  fetchSites,
  type AssetFilters,
} from '../../shared/api/assets'
import { PERMISSIONS } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import {
  BUSINESS_STATUS,
  SUPPORT_STATUS,
  SUPPORT_TONE,
  categoryOptions,
  options,
} from './labels'

const FILTER_KEYS = [
  'q',
  'category',
  'site',
  'business_status',
  'support_status',
  'archived',
  'ordering',
] as const

const ORDERING_OPTIONS = [
  { value: '', label: 'Recently modified' },
  { value: 'name', label: 'Name A–Z' },
  { value: '-name', label: 'Name Z–A' },
  { value: 'asset_tag', label: 'Asset tag' },
  { value: '-created_at', label: 'Newest first' },
]

export function AssetsListPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const filters: AssetFilters = Object.fromEntries(
    FILTER_KEYS.map((key) => [key, params.get(key) ?? undefined]),
  )
  const [search, setSearch] = useState(filters.q ?? '')

  const categories = useQuery({ queryKey: assetKeys.categories, queryFn: fetchCategories })
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites })
  const assets = useInfiniteQuery({
    queryKey: assetKeys.list(filters),
    queryFn: ({ pageParam }) => fetchAssets(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })

  function update(next: Partial<AssetFilters>) {
    const merged = { ...filters, ...next }
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(merged)) if (value) search.set(key, value)
    setParams(search, { replace: true })
  }

  function handleSearch(event: FormEvent) {
    event.preventDefault()
    update({ q: search.trim() || undefined })
  }

  const items = assets.data?.pages.flatMap((page) => page.items) ?? []
  const total = assets.data?.pages[0]?.count
  const filtered = FILTER_KEYS.some((key) => key !== 'ordering' && filters[key])

  return (
    <div className="page page--wide">
      <PageHeader
        title="Assets"
        meta={
          total === undefined
            ? 'Assets in the sites you can access'
            : `${total.toLocaleString('en-GB')} ${total === 1 ? 'asset' : 'assets'}${
                filters.archived === 'only' ? ' (archived)' : ''
              }`
        }
        actions={
          can(PERMISSIONS.assetsCreate) && (
            <Link className="button button--primary" to="/assets/new">
              Add asset
            </Link>
          )
        }
      />

      <form className="toolbar" role="search" onSubmit={handleSearch}>
        <TextField
          label="Search"
          name="q"
          type="search"
          placeholder="Name, tag, serial, model, hostname, IP or MAC"
          className="field__control toolbar__search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <SelectField
          label="Category"
          name="category"
          options={[{ value: '', label: 'All categories' }, ...categoryOptions(categories.data ?? [])]}
          value={filters.category ?? ''}
          onChange={(event) => update({ category: event.target.value || undefined })}
        />
        <SelectField
          label="Site"
          name="site"
          options={[
            { value: '', label: 'All my sites' },
            ...(sites.data ?? []).map((site) => ({
              value: site.id,
              label: `${site.code} — ${site.name}`,
            })),
          ]}
          value={filters.site ?? ''}
          onChange={(event) => update({ site: event.target.value || undefined })}
        />
        <SelectField
          label="Business status"
          name="business_status"
          options={[{ value: '', label: 'Any' }, ...options(BUSINESS_STATUS)]}
          value={filters.business_status ?? ''}
          onChange={(event) => update({ business_status: event.target.value || undefined })}
        />
        <SelectField
          label="Support"
          name="support_status"
          options={[{ value: '', label: 'Any' }, ...options(SUPPORT_STATUS)]}
          value={filters.support_status ?? ''}
          onChange={(event) => update({ support_status: event.target.value || undefined })}
        />
        <SelectField
          label="Archived"
          name="archived"
          options={[
            { value: '', label: 'Hide archived' },
            { value: 'include', label: 'Include archived' },
            { value: 'only', label: 'Archived only' },
          ]}
          value={filters.archived ?? ''}
          onChange={(event) => update({ archived: event.target.value || undefined })}
        />
        <SelectField
          label="Sort"
          name="ordering"
          options={ORDERING_OPTIONS}
          value={filters.ordering ?? ''}
          onChange={(event) => update({ ordering: event.target.value || undefined })}
        />
        <div className="toolbar__actions">
          <Button type="submit">Search</Button>
          {filtered && (
            <Button
              variant="quiet"
              onClick={() => {
                setSearch('')
                setParams(new URLSearchParams(), { replace: true })
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
      </form>

      <section className="panel panel--flush" aria-live="polite">
        {assets.isPending && <LoadingState label="Loading assets…" />}
        {assets.isError && <QueryErrorState error={assets.error} what="assets" />}
        {assets.isSuccess && items.length === 0 && (
          <EmptyState title={filtered ? 'No assets match these filters.' : 'No assets yet.'}>
            {filtered
              ? 'Change or clear the filters.'
              : can(PERMISSIONS.assetsCreate)
                ? 'Register the first asset with Add asset.'
                : 'Assets appear here once they are registered in your sites.'}
          </EmptyState>
        )}
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table data-table--assets">
              <caption className="visually-hidden">Assets</caption>
              <thead>
                <tr>
                  <th scope="col">Name / hostname</th>
                  <th scope="col">Category</th>
                  <th scope="col">Manufacturer / model</th>
                  <th scope="col">Serial</th>
                  <th scope="col">Primary IP</th>
                  <th scope="col">Site / location</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Business</th>
                  <th scope="col">Support</th>
                  <th scope="col">Modified</th>
                </tr>
              </thead>
              <tbody>
                {items.map((asset) => (
                  <tr key={asset.id} className={asset.is_archived ? 'row--archived' : undefined}>
                    <td className="cell-primary">
                      <Link className="table-link" to={`/assets/${asset.id}`}>
                        {asset.name}
                      </Link>
                      <span className="cell-secondary mono">
                        {[asset.asset_tag, asset.primary_hostname].filter(Boolean).join(' · ') ||
                          ' '}
                      </span>
                      {asset.is_archived && <span className="cell-secondary">Archived</span>}
                    </td>
                    <td title={asset.category.path}>{asset.category.name}</td>
                    <td>
                      {asset.manufacturer || <span className="cell-muted">Unknown</span>}
                      {asset.model && <span className="cell-secondary">{asset.model}</span>}
                    </td>
                    <td className="mono">
                      {asset.serial_number || <span className="cell-muted">Not recorded</span>}
                    </td>
                    <td className="mono">
                      {asset.primary_ip ?? <span className="cell-muted">None</span>}
                    </td>
                    <td>
                      <span className="mono">{asset.site.code}</span>
                      {asset.location && (
                        <span className="cell-secondary">{asset.location.name}</span>
                      )}
                    </td>
                    <td>
                      {asset.owner?.display_name ?? <span className="cell-muted">Unassigned</span>}
                    </td>
                    <td className="nowrap">{BUSINESS_STATUS[asset.business_status]}</td>
                    <td>
                      <StatusBadge
                        tone={SUPPORT_TONE[asset.support_status]}
                        label={SUPPORT_STATUS[asset.support_status]}
                      />
                    </td>
                    <td className="nowrap">{formatDateTime(asset.modified_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {assets.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => assets.fetchNextPage()} busy={assets.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}
