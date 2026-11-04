import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { isApiError } from '../../shared/api/client'
import {
  createProduct,
  createVendorAlias,
  fetchProducts,
  fetchSources,
  fetchVendorAliases,
  lifecycleKeys,
  removeVendorAlias,
} from '../../shared/api/lifecycle'
import { PERMISSIONS, type LifecycleProductWrite, type VendorAlias } from '../../shared/api/types'
import { formatDate } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { Tabs } from '../../shared/ui/Tabs'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { SourceDialog } from './SourceDialog'
import { PRODUCT_KIND, SOURCE_TYPE } from './labels'

const KIND_OPTIONS = [
  { value: '', label: 'All kinds' },
  ...Object.entries(PRODUCT_KIND).map(([value, label]) => ({ value, label })),
]

export function CataloguePage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'products'
  return (
    <div className="page page--wide">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/lifecycle">Lifecycle</Link>
      </nav>
      <PageHeader
        title="Lifecycle catalogue"
        meta="Hardware models, OS/firmware releases and software versions with dated, sourced lifecycle milestones. Nothing is pre-loaded; every date needs a source and a reviewer."
      />
      <Tabs
        label="Catalogue sections"
        selected={tab}
        onSelect={(next) => {
          const search = new URLSearchParams(params)
          if (next === 'products') search.delete('tab')
          else search.set('tab', next)
          setParams(search, { replace: true })
        }}
        tabs={[
          { id: 'products', label: 'Products', content: <Products /> },
          { id: 'sources', label: 'Sources', content: <Sources /> },
          { id: 'vendors', label: 'Vendor aliases', content: <VendorAliases /> },
        ]}
      />
    </div>
  )
}

function Products() {
  const { can } = useSession()
  const [kind, setKind] = useState('')
  const [q, setQ] = useState('')
  const [needsReview, setNeedsReview] = useState('')
  const [creating, setCreating] = useState(false)
  const query = { kind: kind || undefined, q: q || undefined, needs_review: needsReview || undefined }
  const products = useInfiniteQuery({
    queryKey: lifecycleKeys.products(query),
    queryFn: ({ pageParam }) => fetchProducts(query, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = products.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <section aria-label="Catalogue products">
      <div className="toolbar">
        <SelectField label="Kind" name="kind" value={kind} onChange={(e) => setKind(e.target.value)} options={KIND_OPTIONS} />
        <TextField label="Search" name="q" value={q} onChange={(e) => setQ(e.target.value)} />
        <SelectField
          label="Dates"
          name="needs_review"
          value={needsReview}
          onChange={(e) => setNeedsReview(e.target.value)}
          options={[
            { value: '', label: 'All products' },
            { value: 'true', label: 'Awaiting verification' },
          ]}
        />
        {can(PERMISSIONS.lifecycleManage) && (
          <div className="toolbar__actions">
            <Button variant="primary" onClick={() => setCreating(true)}>
              New product
            </Button>
          </div>
        )}
      </div>
      <div className="panel panel--flush" aria-live="polite">
        {products.isPending && <LoadingState label="Loading catalogue…" />}
        {products.isError && <QueryErrorState error={products.error} what="the lifecycle catalogue" />}
        {products.isSuccess && items.length === 0 && (
          <EmptyState title="No catalogue products.">
            Add the exact models and releases you run, with dates from the vendor's lifecycle pages.
          </EmptyState>
        )}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Catalogue products</caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">Kind</th>
                <th scope="col">Family</th>
                <th scope="col">Dates</th>
                <th scope="col">Aliases</th>
                <th scope="col">Matched assets</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link className="table-link" to={`/lifecycle/catalogue/${p.id}`}>
                      {[p.vendor, p.name, p.release].filter(Boolean).join(' ')}
                    </Link>
                    {!p.is_active && <span className="cell-secondary">Inactive</span>}
                  </td>
                  <td>{PRODUCT_KIND[p.kind]}</td>
                  <td>{p.family || '–'}</td>
                  <td className="nowrap">
                    {p.milestones_verified} verified
                    {p.milestones_pending > 0 && (
                      <span className="cell-secondary">{p.milestones_pending} awaiting verification</span>
                    )}
                  </td>
                  <td>{p.alias_count}</td>
                  <td>{p.matched_assets}</td>
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
      {creating && <ProductDialog onClose={() => setCreating(false)} />}
    </section>
  )
}

function ProductDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ kind: 'hardware', vendor: '', name: '', release: '', family: '', description: '' })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))
  const save = useMutation({
    mutationFn: () => createProduct({ ...form, kind: form.kind as LifecycleProductWrite['kind'] }),
    onSuccess: (product) => {
      queryClient.invalidateQueries({ queryKey: lifecycleKeys.all })
      navigate(`/lifecycle/catalogue/${product.id}`)
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  const hardware = form.kind === 'hardware'
  return (
    <Dialog open title="New catalogue product" confirmLabel="Create product" busy={save.isPending} onClose={onClose} onConfirm={() => save.mutate()}>
      {save.isError && (
        <ErrorSummary message={save.error.message} fieldErrors={errors} fieldLabels={{ name: 'Name', vendor: 'Vendor', release: 'Release' }} />
      )}
      <SelectField
        label="Kind"
        name="product-kind"
        value={form.kind}
        onChange={set('kind')}
        options={Object.entries(PRODUCT_KIND).map(([value, label]) => ({ value, label }))}
      />
      <TextField label="Vendor" name="product-vendor" value={form.vendor} onChange={set('vendor')} error={errors.vendor} required />
      <TextField
        label={hardware ? 'Model (exact, as the vendor lists it)' : 'Product name'}
        name="product-name"
        value={form.name}
        onChange={set('name')}
        error={errors.name}
        required
      />
      <TextField
        label={hardware ? 'Release (optional)' : 'Release / version'}
        name="product-release"
        help={hardware ? undefined : 'The exact release the dates apply to, for example 17.9 or 22H2.'}
        value={form.release}
        onChange={set('release')}
        error={errors.release}
      />
      <TextField
        label="Product family (optional)"
        name="product-family"
        help="For browsing only. A family name never matches assets on its own."
        value={form.family}
        onChange={set('family')}
      />
    </Dialog>
  )
}

function Sources() {
  const { can } = useSession()
  const [creating, setCreating] = useState(false)
  const sources = useQuery({ queryKey: lifecycleKeys.sources, queryFn: () => fetchSources() })
  return (
    <section aria-label="Evidence sources">
      {can(PERMISSIONS.lifecycleManage) && (
        <div className="toolbar">
          <div className="toolbar__actions">
            <Button onClick={() => setCreating(true)}>New source</Button>
          </div>
        </div>
      )}
      <div className="panel panel--flush">
        {sources.isPending && <LoadingState label="Loading sources…" />}
        {sources.isError && <QueryErrorState error={sources.error} what="sources" />}
        {sources.isSuccess && sources.data.length === 0 && <EmptyState title="No sources recorded." />}
        {sources.data && sources.data.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Evidence sources</caption>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Type</th>
                <th scope="col">Collected</th>
                <th scope="col">Last verified</th>
              </tr>
            </thead>
            <tbody>
              {sources.data.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.url ? (
                      <a href={s.url} target="_blank" rel="noopener noreferrer">
                        {s.title}
                      </a>
                    ) : (
                      s.title
                    )}
                    <span className="cell-secondary">
                      {s.publisher}
                      {s.document_ref && ` · ${s.document_ref}`}
                    </span>
                  </td>
                  <td>{SOURCE_TYPE[s.source_type]}</td>
                  <td className="nowrap">{formatDate(s.collected_on)}</td>
                  <td className="nowrap">{formatDate(s.last_verified_on, 'Not re-verified')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {creating && <SourceDialog onClose={() => setCreating(false)} />}
    </section>
  )
}

function VendorAliases() {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const aliases = useQuery({ queryKey: lifecycleKeys.vendorAliases, queryFn: fetchVendorAliases })
  const [form, setForm] = useState({ alias: '', vendor: '' })
  const [removing, setRemoving] = useState<VendorAlias | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: lifecycleKeys.all })
  const add = useMutation({
    mutationFn: () => createVendorAlias(form),
    onSuccess: () => {
      setForm({ alias: '', vendor: '' })
      refresh()
    },
  })
  const remove = useMutation({
    mutationFn: (reason: string) => removeVendorAlias(removing!.id, reason),
    onSuccess: () => {
      setRemoving(null)
      refresh()
    },
  })
  const manage = can(PERMISSIONS.lifecycleManage)
  return (
    <section aria-label="Vendor aliases">
      <p className="inline-note">
        Map other spellings of a manufacturer to the vendor name used in the catalogue, for example
        "Hewlett Packard Enterprise" to "HPE". Only these explicit aliases are used.
      </p>
      {manage && (
        <form
          className="toolbar"
          onSubmit={(e) => {
            e.preventDefault()
            if (form.alias.trim() && form.vendor.trim()) add.mutate()
          }}
        >
          <TextField label="Reported as" name="vendor-alias" value={form.alias} onChange={(e) => setForm({ ...form, alias: e.target.value })} />
          <TextField label="Catalogue vendor" name="vendor-canonical" value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} />
          <div className="toolbar__actions">
            <Button type="submit" busy={add.isPending}>
              Add alias
            </Button>
          </div>
        </form>
      )}
      {add.isError && <p className="field__error">{add.error.message}</p>}
      <div className="panel panel--flush">
        {aliases.isPending && <LoadingState label="Loading vendor aliases…" />}
        {aliases.isSuccess && aliases.data.length === 0 && <EmptyState title="No vendor aliases." />}
        {aliases.data && aliases.data.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Vendor aliases</caption>
            <thead>
              <tr>
                <th scope="col">Reported as</th>
                <th scope="col">Catalogue vendor</th>
                <th scope="col">Added by</th>
                {manage && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {aliases.data.map((a) => (
                <tr key={a.id}>
                  <td>{a.alias}</td>
                  <td>{a.vendor}</td>
                  <td>{a.created_by ?? '–'}</td>
                  {manage && (
                    <td>
                      <Button variant="quiet" onClick={() => setRemoving(a)}>
                        Remove…
                      </Button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {removing && (
        <ReasonDialog
          title={`Remove vendor alias "${removing.alias}"`}
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
