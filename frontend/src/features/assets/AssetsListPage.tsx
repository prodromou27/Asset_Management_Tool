import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  assetKeys,
  createSavedView,
  deleteSavedView,
  fetchAssets,
  fetchCategories,
  fetchSavedViews,
  fetchSites,
  updateSavedView,
  type AssetFilters,
} from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import { discoveryKeys, fetchIntegrations } from '../../shared/api/discovery'
import {
  PERMISSIONS,
  type AssetColumn,
  type SavedView,
  type SavedViewWrite,
} from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { CheckboxGroup, SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ExportDialog } from '../exports/ExportDialog'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { COLUMNS, loadColumns, normalizeColumns, saveColumns } from './columns'
import {
  BUSINESS_STATUS,
  OBSERVATION_STATUS,
  SUPPORT_STATUS,
  categoryOptions,
  options,
} from './labels'

const FILTER_KEYS = [
  'q',
  'category',
  'site',
  'business_status',
  'support_status',
  'observation_status',
  'source',
  'archived',
] as const

type Ordering = NonNullable<SavedViewWrite['ordering']>

const ORDERING_OPTIONS = [
  { value: '', label: 'Recently modified' },
  { value: 'name', label: 'Name A–Z' },
  { value: '-name', label: 'Name Z–A' },
  { value: 'asset_tag', label: 'Asset tag' },
  { value: '-created_at', label: 'Newest first' },
]

function sameList(a: readonly string[], b: readonly string[]) {
  return a.length === b.length && a.every((v, i) => v === b[i])
}

export function AssetsListPage() {
  const { me, can } = useSession()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const filters: AssetFilters = Object.fromEntries(
    [...FILTER_KEYS, 'ordering'].map((key) => [key, params.get(key) ?? undefined]),
  )
  const viewId = params.get('view')
  const [search, setSearch] = useState(filters.q ?? '')
  const [personalColumns, setPersonalColumns] = useState<AssetColumn[]>(() => loadColumns(me?.id))
  // Unsaved column edits while a saved view is applied (kept per view id).
  const [viewDraft, setViewDraft] = useState<{ id: string; columns: AssetColumn[] } | null>(null)
  const [dialog, setDialog] = useState<'save' | 'delete' | 'columns' | null>(null)
  const [exporting, setExporting] = useState(false)

  const categories = useQuery({ queryKey: assetKeys.categories, queryFn: fetchCategories })
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites })
  const integrations = useQuery({
    queryKey: discoveryKeys.integrations,
    queryFn: fetchIntegrations,
    enabled: can(PERMISSIONS.discoveryView),
  })
  const views = useQuery({ queryKey: assetKeys.savedViews, queryFn: fetchSavedViews })
  const assets = useInfiniteQuery({
    queryKey: assetKeys.list(filters),
    queryFn: ({ pageParam }) => fetchAssets(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })

  const activeView = views.data?.find((v) => v.id === viewId) ?? null
  const viewFilters = activeView ? { ...activeView.filters, ...(activeView.ordering ? { ordering: activeView.ordering } : {}) } : null
  const currentFilters = Object.fromEntries(
    Object.entries(filters).filter(([, v]) => v !== undefined && v !== ''),
  ) as Record<string, string>
  const columns: AssetColumn[] = activeView
    ? viewDraft?.id === activeView.id
      ? viewDraft.columns
      : activeView.columns.length
        ? normalizeColumns(activeView.columns)
        : personalColumns
    : personalColumns
  const viewChanged =
    activeView !== null &&
    (JSON.stringify(Object.entries(viewFilters ?? {}).sort()) !==
      JSON.stringify(Object.entries(currentFilters).sort()) ||
      (activeView.columns.length > 0 && !sameList(activeView.columns, columns)))

  function update(next: Partial<AssetFilters>) {
    const merged = { ...filters, ...next }
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(merged)) if (value) search.set(key, value)
    if (viewId) search.set('view', viewId)
    setParams(search, { replace: true })
  }

  function applyView(id: string) {
    const view = views.data?.find((v) => v.id === id)
    const search = new URLSearchParams()
    if (view) {
      for (const [key, value] of Object.entries(view.filters)) search.set(key, value)
      if (view.ordering) search.set('ordering', view.ordering)
      search.set('view', view.id)
    }
    setViewDraft(null)
    setSearch(view?.filters.q ?? '')
    setParams(search, { replace: true })
  }

  function changeColumns(next: AssetColumn[]) {
    const normalized = normalizeColumns(next)
    if (activeView) {
      setViewDraft({ id: activeView.id, columns: normalized })
    } else {
      setPersonalColumns(normalized)
      saveColumns(me?.id, normalized)
    }
  }

  const updateView = useMutation({
    mutationFn: (view: SavedView) =>
      updateSavedView(view.id, view.version, {
        filters: Object.fromEntries(Object.entries(currentFilters).filter(([k]) => k !== 'ordering')),
        ordering: (currentFilters.ordering ?? '') as Ordering,
        columns,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: assetKeys.savedViews }),
  })

  const items = assets.data?.pages.flatMap((page) => page.items) ?? []
  const total = assets.data?.pages[0]?.count
  const filtered = FILTER_KEYS.some((key) => filters[key])
  const shown = COLUMNS.filter((c) => columns.includes(c.id)).sort(
    (a, b) => columns.indexOf(a.id) - columns.indexOf(b.id),
  )

  return (
    <div className="page page--wide">
      <PageHeader
        title="Assets"
        meta={
          total === undefined
            ? 'Assets in the sites you can access'
            : `${total.toLocaleString('en-GB')} ${total === 1 ? 'asset' : 'assets'}${
                filters.archived === 'only' ? ' (archived)' : ''
              }${activeView ? ` · view “${activeView.name}”` : ''}`
        }
        actions={
          <>
            {can(PERMISSIONS.importsRun) && (
              <Link className="button button--secondary" to="/imports/new?family=asset">
                Import
              </Link>
            )}
            {can(PERMISSIONS.exportsRun) && (
              <Button onClick={() => setExporting(true)}>Export</Button>
            )}
            {can(PERMISSIONS.assetsCreate) && (
              <Link className="button button--primary" to="/assets/new">
                Add asset
              </Link>
            )}
          </>
        }
      />
      <ExportDialog
        open={exporting}
        onClose={() => setExporting(false)}
        family="assets"
        filters={Object.fromEntries(
          FILTER_KEYS.flatMap((key) => (filters[key] ? [[key, filters[key] as string]] : [])),
        )}
      />

      <div className="view-bar">
        <SelectField
          label="Saved view"
          name="saved_view"
          options={[
            { value: '', label: 'Default view' },
            ...(views.data ?? []).map((v) => ({
              value: v.id,
              label: v.is_mine ? `${v.name}${v.is_shared ? ' (shared)' : ''}` : `${v.name} — shared by ${v.owner}`,
            })),
          ]}
          value={viewId ?? ''}
          onChange={(e) => applyView(e.target.value)}
        />
        <div className="view-bar__actions">
          <Button onClick={() => setDialog('save')}>Save as new view</Button>
          {activeView?.is_mine && viewChanged && (
            <Button busy={updateView.isPending} onClick={() => updateView.mutate(activeView)}>
              Update “{activeView.name}”
            </Button>
          )}
          {activeView?.is_mine && (
            <Button variant="quiet" className="button--danger-quiet" onClick={() => setDialog('delete')}>
              Delete view
            </Button>
          )}
          <Button variant="quiet" aria-haspopup="dialog" onClick={() => setDialog('columns')}>
            Columns ({columns.length})
          </Button>
        </div>
        {updateView.error && <p className="field__error">{updateView.error.message}</p>}
      </div>

      <form
        className="toolbar"
        role="search"
        onSubmit={(event: FormEvent) => {
          event.preventDefault()
          update({ q: search.trim() || undefined })
        }}
      >
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
            ...(sites.data ?? []).map((site) => ({ value: site.id, label: `${site.code} — ${site.name}` })),
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
          label="Observation"
          name="observation_status"
          options={[{ value: '', label: 'Any' }, ...options(OBSERVATION_STATUS)]}
          value={filters.observation_status ?? ''}
          onChange={(event) => update({ observation_status: event.target.value || undefined })}
        />
        {integrations.data && integrations.data.length > 0 && (
          <SelectField
            label="Source"
            name="source"
            options={[
              { value: '', label: 'Any source' },
              ...integrations.data.map((i) => ({ value: i.id, label: i.name })),
            ]}
            value={filters.source ?? ''}
            onChange={(event) => update({ source: event.target.value || undefined })}
          />
        )}
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
          <div className="table-scroll table-scroll--sticky">
            <table className="data-table data-table--assets">
              <caption className="visually-hidden">Assets</caption>
              <thead>
                <tr>
                  {shown.map((column) => (
                    <th key={column.id} scope="col">
                      {column.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((asset) => (
                  <tr key={asset.id} className={asset.is_archived ? 'row--archived' : undefined}>
                    {shown.map((column) => (
                      <td key={column.id} className={column.className}>
                        {column.render(asset)}
                      </td>
                    ))}
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

      {dialog === 'columns' && (
        <ColumnsDialog value={columns} onChange={changeColumns} onClose={() => setDialog(null)} />
      )}
      {dialog === 'save' && (
        <SaveViewDialog
          filters={currentFilters}
          columns={columns}
          canShare={can(PERMISSIONS.assetsEdit)}
          onSaved={(view) => {
            const search = new URLSearchParams(params)
            search.set('view', view.id)
            setViewDraft(null)
            setParams(search, { replace: true })
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'delete' && activeView && (
        <DeleteViewDialog view={activeView} onDeleted={() => applyView('')} onClose={() => setDialog(null)} />
      )}
    </div>
  )
}

function ColumnsDialog({
  value,
  onChange,
  onClose,
}: {
  value: AssetColumn[]
  onChange: (columns: AssetColumn[]) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<AssetColumn[]>(value)
  return (
    <Dialog open title="Choose columns" confirmLabel="Apply columns" onConfirm={() => { onChange(draft); onClose() }} onClose={onClose}>
      <CheckboxGroup
        legend="Visible columns"
        name="columns"
        options={COLUMNS.map((c) => ({
          value: c.id,
          label: c.header,
          description: c.id === 'name' ? 'Always shown' : undefined,
        }))}
        value={draft}
        onChange={(next) => setDraft(COLUMNS.map((c) => c.id).filter((id) => id === 'name' || next.includes(id)))}
      />
      <Button variant="quiet" onClick={() => setDraft(COLUMNS.map((c) => c.id).filter((id) => id !== 'observation_status'))}>
        Reset to default
      </Button>
    </Dialog>
  )
}

function SaveViewDialog({
  filters,
  columns,
  canShare,
  onSaved,
  onClose,
}: {
  filters: Record<string, string>
  columns: AssetColumn[]
  canShare: boolean
  onSaved: (view: SavedView) => void
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [shared, setShared] = useState(false)
  const [nameError, setNameError] = useState<string[] | undefined>()
  const { ordering = '', ...rest } = filters
  const mutation = useMutation({
    mutationFn: () =>
      createSavedView({
        name: name.trim(),
        filters: rest,
        ordering: ordering as Ordering,
        columns,
        is_shared: shared,
      }),
    onSuccess: async (view) => {
      await queryClient.invalidateQueries({ queryKey: assetKeys.savedViews })
      onSaved(view)
      onClose()
    },
  })
  const server = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  return (
    <Dialog
      open
      title="Save view"
      confirmLabel="Save view"
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        if (!name.trim()) setNameError(['Enter a name.'])
        else mutation.mutate()
      }}
    >
      <p>
        Saves the current filters, sort order and {columns.length} visible columns.
        {Object.keys(rest).length === 0 && ' No filters are set.'}
      </p>
      {mutation.error && !Object.keys(server).length && <p className="field__error">{mutation.error.message}</p>}
      <TextField label="Name" name="view_name" value={name} onChange={(e) => setName(e.target.value)} error={nameError ?? server.name} autoFocus />
      {canShare && (
        <CheckboxGroup
          legend="Sharing"
          name="view_shared"
          options={[
            {
              value: 'shared',
              label: 'Share with other users',
              description: 'Others can apply it but not change it. Each person still sees only assets in their own sites.',
            },
          ]}
          value={shared ? ['shared'] : []}
          onChange={(v) => setShared(v.includes('shared'))}
        />
      )}
    </Dialog>
  )
}

function DeleteViewDialog({ view, onDeleted, onClose }: { view: SavedView; onDeleted: () => void; onClose: () => void }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => deleteSavedView(view.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: assetKeys.savedViews })
      onDeleted()
      onClose()
    },
  })
  return (
    <Dialog
      open
      title={`Delete view “${view.name}”?`}
      confirmLabel="Delete view"
      confirmVariant="danger"
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => mutation.mutate()}
    >
      <p>
        Removes 1 saved view{view.is_shared ? ', including for everyone it is shared with' : ''}. Assets are not affected.
      </p>
      {mutation.error && <p className="field__error">{mutation.error.message}</p>}
    </Dialog>
  )
}
