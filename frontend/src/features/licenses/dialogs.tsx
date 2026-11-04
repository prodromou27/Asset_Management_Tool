import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { assetKeys, fetchAssets } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import {
  allocateEntitlement,
  createEntitlement,
  createLicenseProduct,
  licenseKeys,
  updateEntitlement,
  updateLicenseProduct,
} from '../../shared/api/licenses'
import { fetchSoftwareProducts, softwareKeys } from '../../shared/api/software'
import type { LicenseEntitlement, LicenseProductDetail } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { ErrorSummary } from '../../shared/ui/States'
import { METRIC } from './labels'

function useRefresh() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: licenseKeys.all })
}

/** Create or edit a license product. Linking installed software only adds an observed
 * count next to the purchased quantity; it never merges the two. */
export function ProductDialog({
  product,
  onClose,
  onSaved,
}: {
  product?: LicenseProductDetail
  onClose: () => void
  onSaved?: (p: LicenseProductDetail) => void
}) {
  const refresh = useRefresh()
  const [form, setForm] = useState({
    publisher: product?.publisher ?? '',
    name: product?.name ?? '',
    sku: product?.sku ?? '',
    metric: product?.metric ?? 'user',
    note: product?.note ?? '',
    software_product: product?.software_product ? String(product.software_product.id) : '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))
  const software = useQuery({
    queryKey: softwareKeys.products({ q: form.name, installed: 'false' }),
    queryFn: () => fetchSoftwareProducts({ q: form.name, installed: 'false' }),
    enabled: form.name.trim().length >= 2,
  })
  const options = software.data?.items ?? []
  const linked = product?.software_product
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...form,
        metric: form.metric as LicenseProductDetail['metric'],
        software_product: form.software_product ? Number(form.software_product) : null,
      }
      return product ? updateLicenseProduct(product.id, product.version, body) : createLicenseProduct(body)
    },
    onSuccess: async (saved) => {
      await refresh()
      onSaved?.(saved)
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog
      open
      title={product ? `Edit ${product.name}` : 'New license product'}
      confirmLabel="Save product"
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ name: 'Name', sku: 'Vendor SKU' }}
        />
      )}
      <TextField
        label="Publisher"
        name="lp-publisher"
        value={form.publisher}
        onChange={set('publisher')}
        error={errors.publisher}
      />
      <TextField label="Name" name="lp-name" value={form.name} onChange={set('name')} error={errors.name} required />
      <TextField
        label="Vendor SKU (optional)"
        name="lp-sku"
        value={form.sku}
        onChange={set('sku')}
        error={errors.sku}
      />
      <SelectField
        label="Counted per"
        name="lp-metric"
        value={form.metric}
        onChange={set('metric')}
        options={Object.entries(METRIC).map(([value, label]) => ({
          value,
          label,
        }))}
      />
      <SelectField
        label="Installed software (optional)"
        name="lp-software"
        value={form.software_product}
        onChange={set('software_product')}
        help="Shows how many assets have it installed next to the purchased quantity."
        options={[
          { value: '', label: 'Not linked' },
          ...(linked && !options.some((o) => o.id === linked.id)
            ? [
                {
                  value: String(linked.id),
                  label: `${linked.publisher} ${linked.name}`.trim(),
                },
              ]
            : []),
          ...options.map((o) => ({
            value: String(o.id),
            label: `${o.publisher} ${o.name}`.trim(),
          })),
        ]}
      />
      <TextAreaField label="Note (optional)" name="lp-note" value={form.note} onChange={set('note')} />
    </Dialog>
  )
}

/** Record or edit a purchase: quantity, agreement reference and term. */
export function EntitlementDialog({
  productId,
  entitlement,
  onClose,
}: {
  productId: string
  entitlement?: LicenseEntitlement
  onClose: () => void
}) {
  const refresh = useRefresh()
  const [form, setForm] = useState({
    reference: entitlement?.reference ?? '',
    quantity: entitlement ? String(entitlement.quantity) : '',
    starts_on: entitlement?.starts_on ?? '',
    ends_on: entitlement?.ends_on ?? '',
    supplier: entitlement?.supplier ?? '',
    owner: entitlement?.owner ?? '',
    note: entitlement?.note ?? '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...form,
        quantity: Number(form.quantity),
        starts_on: form.starts_on || null,
        ends_on: form.ends_on || null,
      }
      return entitlement
        ? updateEntitlement(entitlement.id, entitlement.version, body)
        : createEntitlement({ ...body, product: productId })
    },
    onSuccess: async () => {
      await refresh()
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog
      open
      title={entitlement ? `Edit ${entitlement.reference}` : 'Record entitlement'}
      confirmLabel="Save entitlement"
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{
            reference: 'Reference',
            quantity: 'Purchased units',
            ends_on: 'Ends on',
          }}
        />
      )}
      <TextField
        label="Reference"
        name="ent-reference"
        value={form.reference}
        onChange={set('reference')}
        error={errors.reference}
        help="Agreement, order or contract number."
        required
      />
      <TextField
        label="Purchased units"
        name="ent-quantity"
        type="number"
        min={1}
        value={form.quantity}
        onChange={set('quantity')}
        error={errors.quantity}
        required
      />
      <TextField
        label="Starts on (optional)"
        name="ent-starts"
        type="date"
        value={form.starts_on}
        onChange={set('starts_on')}
        error={errors.starts_on}
      />
      <TextField
        label="Ends on (optional)"
        name="ent-ends"
        type="date"
        value={form.ends_on}
        onChange={set('ends_on')}
        error={errors.ends_on}
        help="Leave empty for a perpetual license. The last day is still in term."
      />
      <TextField label="Supplier (optional)" name="ent-supplier" value={form.supplier} onChange={set('supplier')} />
      <TextField
        label="Owner (optional)"
        name="ent-owner"
        value={form.owner}
        onChange={set('owner')}
        help="Responsible person or team."
      />
      <TextAreaField label="Note (optional)" name="ent-note" value={form.note} onChange={set('note')} />
    </Dialog>
  )
}

/** Allocate units of an entitlement to an asset in your sites or to a named user. */
export function AllocateDialog({ entitlement, onClose }: { entitlement: LicenseEntitlement; onClose: () => void }) {
  const refresh = useRefresh()
  const [target, setTarget] = useState<'asset' | 'user'>(entitlement.product.metric === 'device' ? 'asset' : 'user')
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [asset, setAsset] = useState<{ id: string; name: string } | null>(null)
  const [user, setUser] = useState('')
  const [units, setUnits] = useState('1')
  const [note, setNote] = useState('')
  const results = useQuery({
    queryKey: assetKeys.list({ q }),
    queryFn: () => fetchAssets({ q }),
    enabled: q.length > 0,
  })
  const save = useMutation({
    mutationFn: () =>
      allocateEntitlement(entitlement.id, {
        ...(target === 'asset' ? { asset: asset?.id ?? null } : { user_name: user }),
        units: Number(units) || 1,
        note,
      }),
    onSuccess: async () => {
      await refresh()
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  const ready = target === 'asset' ? asset !== null : user.trim().length > 0
  return (
    <Dialog
      open
      title={`Allocate from ${entitlement.reference}`}
      confirmLabel="Allocate"
      busy={save.isPending || !ready}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ asset: 'Asset', user_name: 'User', units: 'Units' }}
        />
      )}
      <p>
        {entitlement.available.toLocaleString('en-GB')} of {entitlement.quantity.toLocaleString('en-GB')} units not
        allocated.
      </p>
      <SelectField
        label="Allocate to"
        name="alloc-target"
        value={target}
        onChange={(e) => setTarget(e.target.value as 'asset' | 'user')}
        options={[
          { value: 'user', label: 'A named user' },
          { value: 'asset', label: 'An asset' },
        ]}
      />
      {target === 'user' ? (
        <TextField
          label="User"
          name="alloc-user"
          value={user}
          onChange={(e) => setUser(e.target.value)}
          help="Name, user principal name or e-mail as your organisation records it."
          error={errors.user_name}
        />
      ) : (
        <>
          <div className="toolbar" role="search">
            <TextField
              label="Find asset"
              name="alloc-q"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  setQ(search.trim())
                }
              }}
              help="Name, tag, serial, hostname or IP. Only assets in your sites."
            />
            <div className="toolbar__actions">
              <Button onClick={() => setQ(search.trim())}>Search</Button>
            </div>
          </div>
          {results.data && (
            <ul className="plain-list" aria-label="Search results">
              {results.data.items.length === 0 && <li>No assets match.</li>}
              {results.data.items.slice(0, 10).map((a) => (
                <li key={a.id}>
                  <label className="checkbox">
                    <input
                      type="radio"
                      name="alloc-asset"
                      checked={asset?.id === a.id}
                      onChange={() => setAsset({ id: a.id, name: a.name })}
                    />
                    {a.name} <span className="cell-secondary mono">{a.site.code}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <TextField
        label="Units"
        name="alloc-units"
        type="number"
        min={1}
        value={units}
        onChange={(e) => setUnits(e.target.value)}
        error={errors.units}
      />
      <TextField label="Note (optional)" name="alloc-note" value={note} onChange={(e) => setNote(e.target.value)} />
    </Dialog>
  )
}
