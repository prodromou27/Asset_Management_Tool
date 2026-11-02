import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  assetKeys,
  createAsset,
  fetchAsset,
  fetchCategories,
  fetchCategoryFields,
  fetchDepartments,
  fetchLocations,
  fetchSites,
  fetchUserLookup,
  updateAsset,
} from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import { PERMISSIONS, type AssetDetail, type BusinessStatus } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { CustomFieldInputs } from './CustomFieldInputs'
import { toApiValues, toFormValue, type CustomValues } from './customValues'
import { BUSINESS_STATUS, categoryOptions, options } from './labels'
import { NetworkEditor, type NetworkRows } from './NetworkEditor'

const LABELS: Record<string, string> = {
  name: 'Name',
  asset_tag: 'Asset tag',
  category: 'Category',
  manufacturer: 'Manufacturer',
  model: 'Model',
  serial_number: 'Serial number',
  os_name: 'Operating system',
  os_version: 'OS version',
  firmware_version: 'Firmware version',
  site: 'Site',
  location: 'Location',
  department: 'Department',
  owner: 'Owner',
  business_status: 'Business status',
  notes: 'Notes',
  hostnames: 'Hostnames',
  interfaces: 'Interfaces',
  ip_addresses: 'IP addresses',
}

type Scalars = {
  name: string
  asset_tag: string
  category: string
  manufacturer: string
  model: string
  serial_number: string
  os_name: string
  os_version: string
  firmware_version: string
  site: string
  location: string
  department: string
  owner: string
  business_status: BusinessStatus
  notes: string
}

function initialScalars(asset?: AssetDetail): Scalars {
  return {
    name: asset?.name ?? '',
    asset_tag: asset?.asset_tag ?? '',
    category: asset?.category.id ?? '',
    manufacturer: asset?.manufacturer ?? '',
    model: asset?.model ?? '',
    serial_number: asset?.serial_number ?? '',
    os_name: asset?.os_name ?? '',
    os_version: asset?.os_version ?? '',
    firmware_version: asset?.firmware_version ?? '',
    site: asset?.site.id ?? '',
    location: asset?.location?.id ?? '',
    department: asset?.department?.id ?? '',
    owner: asset?.owner?.id ?? '',
    business_status: (asset?.business_status ?? 'in_stock') as BusinessStatus,
    notes: asset?.notes ?? '',
  }
}

function initialNetwork(asset?: AssetDetail): NetworkRows {
  const manual = <T extends { source: string }>(rows: readonly T[] = []) =>
    rows.filter((row) => row.source === 'manual')
  return {
    hostnames: manual(asset?.hostnames).map((h) => ({
      hostname: h.hostname,
      is_primary: h.is_primary,
    })),
    interfaces: manual(asset?.interfaces).map((i) => ({ name: i.name, mac_address: i.mac_address })),
    ip_addresses: manual(asset?.ip_addresses).map((a) => ({
      address: a.address,
      interface_name: a.interface_name ?? '',
      is_primary: a.is_primary,
    })),
  }
}

export function AssetFormPage() {
  const { id } = useParams()
  const asset = useQuery({
    queryKey: assetKeys.detail(id ?? ''),
    queryFn: () => fetchAsset(id!),
    enabled: Boolean(id),
  })
  if (id && asset.isPending) return <LoadingState label="Loading asset…" />
  if (id && asset.isError) return <QueryErrorState error={asset.error} what="this asset" />
  // Keyed by version: a reload after a conflict starts from the latest record.
  return <AssetForm key={asset.data?.version ?? 'new'} asset={asset.data} />
}

function AssetForm({ asset }: { asset?: AssetDetail }) {
  const editing = asset !== undefined
  const { can } = useSession()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [values, setValues] = useState<Scalars>(() => initialScalars(asset))
  const [custom, setCustom] = useState<CustomValues>(() =>
    Object.fromEntries(
      Object.entries(asset?.custom_fields ?? {}).map(([k, v]) => [k, toFormValue(v)]),
    ),
  )
  const [network, setNetwork] = useState<NetworkRows>(() => initialNetwork(asset))
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({})

  const categories = useQuery({ queryKey: assetKeys.categories, queryFn: fetchCategories })
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites })
  const locations = useQuery({
    queryKey: assetKeys.locations(values.site),
    queryFn: () => fetchLocations(values.site),
    enabled: Boolean(values.site),
  })
  const departments = useQuery({ queryKey: assetKeys.departments, queryFn: fetchDepartments })
  const owners = useQuery({ queryKey: assetKeys.userLookup, queryFn: fetchUserLookup })
  const fields = useQuery({
    queryKey: assetKeys.fields(values.category, true),
    queryFn: () => fetchCategoryFields(values.category, true),
    enabled: Boolean(values.category),
  })
  const definitions = fields.data ?? []

  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        name: values.name.trim(),
        asset_tag: values.asset_tag.trim() || null,
        manufacturer: values.manufacturer.trim(),
        model: values.model.trim(),
        serial_number: values.serial_number.trim(),
        os_name: values.os_name.trim(),
        os_version: values.os_version.trim(),
        firmware_version: values.firmware_version.trim(),
        site: values.site,
        location: values.location || null,
        department: values.department || null,
        owner: values.owner || null,
        business_status: values.business_status,
        notes: values.notes,
        custom_fields: toApiValues(definitions, custom),
        hostnames: network.hostnames.map((h) => ({ ...h, hostname: h.hostname.trim() })),
        interfaces: network.interfaces.map((i) => ({
          name: i.name.trim(),
          mac_address: i.mac_address.trim(),
        })),
        ip_addresses: network.ip_addresses.map((a) => ({ ...a, address: a.address.trim() })),
      }
      return editing
        ? updateAsset(asset.id, asset.version, body)
        : createAsset({ ...body, category: values.category })
    },
    onSuccess: async (saved) => {
      queryClient.setQueryData(assetKeys.detail(saved.id), saved)
      await queryClient.invalidateQueries({ queryKey: ['assets', 'list'] })
      navigate(`/assets/${saved.id}`, {
        state: { notice: editing ? 'Changes saved.' : `Asset ${saved.name} registered.` },
      })
    },
  })

  function set<K extends keyof Scalars>(key: K, value: Scalars[K]) {
    setValues((current) => {
      const next = { ...current, [key]: value }
      if (key === 'site') next.location = ''
      return next
    })
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const errors: Record<string, string[]> = {}
    if (!values.name.trim()) errors.name = ['Enter a name.']
    if (!editing && !values.category) errors.category = ['Choose a category.']
    if (!values.site) errors.site = ['Choose a site.']
    for (const definition of definitions) {
      if (definition.required && !(custom[definition.key] ?? '').trim()) {
        errors[`custom_fields.${definition.key}`] = [`${definition.label} is required.`]
      }
    }
    setClientErrors(errors)
    if (Object.keys(errors).length === 0) mutation.mutate()
  }

  const serverErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = Object.keys(clientErrors).length > 0 ? clientErrors : serverErrors
  const conflict = isApiError(mutation.error, 409) && mutation.error.code === 'VERSION_MISMATCH'
  const labels = {
    ...LABELS,
    ...Object.fromEntries(definitions.map((d) => [`custom_fields.${d.key}`, d.label])),
  }

  if (!can(editing ? PERMISSIONS.assetsEdit : PERMISSIONS.assetsCreate)) return null
  const loading = categories.isPending || sites.isPending
  if (loading) return <LoadingState label="Loading form…" />
  if (categories.isError) return <QueryErrorState error={categories.error} what="categories" />
  if (sites.isError) return <QueryErrorState error={sites.error} what="sites" />

  const activeSites = (sites.data ?? []).filter((s) => s.is_active || s.id === values.site)

  return (
    <div className="page page--form">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/assets">Assets</Link>
        {editing && (
          <>
            {' / '}
            <Link to={`/assets/${asset.id}`}>{asset.name}</Link>
          </>
        )}
      </nav>
      <PageHeader
        title={editing ? `Edit ${asset.name}` : 'Add asset'}
        meta={
          editing
            ? `Record version ${asset.version}. Changes are recorded in the asset history.`
            : 'Only name, category and site are required. IP, MAC, serial and hostname are optional.'
        }
      />
      {(Object.keys(errors).length > 0 || mutation.error) && (
        <ErrorSummary
          message={
            Object.keys(errors).length > 0
              ? 'Check the highlighted fields.'
              : (mutation.error?.message ?? 'Could not save the asset.')
          }
          fieldErrors={errors}
          fieldLabels={labels}
        />
      )}
      {conflict && (
        <p className="inline-note">
          Someone else changed this asset.{' '}
          <button
            type="button"
            className="link-button"
            onClick={() => queryClient.invalidateQueries({ queryKey: assetKeys.detail(asset!.id) })}
          >
            Reload the latest version
          </button>{' '}
          and re-apply your edits.
        </p>
      )}
      <form onSubmit={handleSubmit} noValidate className="form-stack">
        <section className="panel" aria-labelledby="identity-heading">
          <h2 className="section-title" id="identity-heading">
            Identity
          </h2>
          <div className="form-grid">
            <TextField
              label={LABELS.name}
              name="name"
              value={values.name}
              onChange={(e) => set('name', e.target.value)}
              error={errors.name}
              help="Display name, e.g. hostname or 'Reception TV'."
            />
            <TextField
              label={LABELS.asset_tag}
              name="asset_tag"
              className="field__control mono"
              value={values.asset_tag}
              onChange={(e) => set('asset_tag', e.target.value)}
              error={errors.asset_tag}
              help="Optional. Unique; stored in uppercase."
            />
            {editing ? (
              <div className="field">
                <span className="field__label">Category</span>
                <p className="field__static">{asset.category.path}</p>
                <p className="field__help">Use Change category on the asset page.</p>
              </div>
            ) : (
              <SelectField
                label={LABELS.category}
                name="category"
                options={[
                  { value: '', label: 'Choose a category' },
                  ...categoryOptions(categories.data ?? [], { activeOnly: true }),
                ]}
                value={values.category}
                onChange={(e) => set('category', e.target.value)}
                error={errors.category}
              />
            )}
            <SelectField
              label={LABELS.business_status}
              name="business_status"
              options={options(BUSINESS_STATUS)}
              value={values.business_status}
              onChange={(e) => set('business_status', e.target.value as BusinessStatus)}
              error={errors.business_status}
            />
          </div>
        </section>

        <section className="panel" aria-labelledby="hardware-heading">
          <h2 className="section-title" id="hardware-heading">
            Hardware and software
          </h2>
          <div className="form-grid">
            {(
              [
                'manufacturer',
                'model',
                'serial_number',
                'os_name',
                'os_version',
                'firmware_version',
              ] as const
            ).map((key) => (
              <TextField
                key={key}
                label={LABELS[key]}
                name={key}
                className={key === 'serial_number' ? 'field__control mono' : undefined}
                value={values[key]}
                onChange={(e) => set(key, e.target.value)}
                error={errors[key]}
              />
            ))}
          </div>
        </section>

        <section className="panel" aria-labelledby="ownership-heading">
          <h2 className="section-title" id="ownership-heading">
            Site, location and ownership
          </h2>
          <div className="form-grid">
            <SelectField
              label={LABELS.site}
              name="site"
              options={[
                { value: '', label: 'Choose a site' },
                ...activeSites.map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` })),
              ]}
              value={values.site}
              onChange={(e) => set('site', e.target.value)}
              error={errors.site}
              help={activeSites.length === 0 ? 'You have no site access. Ask a System Admin.' : undefined}
            />
            <SelectField
              label={LABELS.location}
              name="location"
              options={[
                { value: '', label: values.site ? 'No location' : 'Choose a site first' },
                ...(locations.data ?? [])
                  .filter((l) => l.is_active || l.id === values.location)
                  .map((l) => ({ value: l.id, label: l.name })),
              ]}
              value={values.location}
              disabled={!values.site}
              onChange={(e) => set('location', e.target.value)}
              error={errors.location}
            />
            <SelectField
              label={LABELS.department}
              name="department"
              options={[
                { value: '', label: 'No department' },
                ...(departments.data ?? [])
                  .filter((d) => d.is_active || d.id === values.department)
                  .map((d) => ({ value: d.id, label: d.name })),
              ]}
              value={values.department}
              onChange={(e) => set('department', e.target.value)}
              error={errors.department}
            />
            <SelectField
              label={LABELS.owner}
              name="owner"
              options={[
                { value: '', label: 'Unassigned' },
                ...(owners.data ?? []).map((u) => ({
                  value: u.id,
                  label: `${u.display_name} (${u.username})`,
                })),
                ...(asset?.owner && !(owners.data ?? []).some((u) => u.id === asset.owner?.id)
                  ? [{ value: asset.owner.id, label: `${asset.owner.display_name} (disabled)` }]
                  : []),
              ]}
              value={values.owner}
              onChange={(e) => set('owner', e.target.value)}
              error={errors.owner}
            />
          </div>
        </section>

        <section className="panel" aria-labelledby="custom-heading">
          <h2 className="section-title" id="custom-heading">
            Category fields
          </h2>
          {!values.category && <p className="field__help">Choose a category to see its fields.</p>}
          {values.category && fields.isPending && <LoadingState label="Loading fields…" />}
          {values.category && fields.isError && (
            <QueryErrorState error={fields.error} what="category fields" />
          )}
          {fields.data && (
            <CustomFieldInputs
              definitions={definitions}
              values={custom}
              errors={errors}
              onChange={(key, value) => setCustom((c) => ({ ...c, [key]: value }))}
            />
          )}
        </section>

        <section className="panel" aria-labelledby="network-heading">
          <h2 className="section-title" id="network-heading">
            Network identifiers
          </h2>
          <NetworkEditor value={network} onChange={setNetwork} errors={errors} />
        </section>

        <section className="panel" aria-labelledby="notes-heading">
          <h2 className="section-title visually-hidden" id="notes-heading">
            Notes
          </h2>
          <TextAreaField
            label={LABELS.notes}
            name="notes"
            rows={4}
            value={values.notes}
            onChange={(e) => set('notes', e.target.value)}
            error={errors.notes}
          />
        </section>

        <div className="form-actions">
          <Button type="submit" variant="primary" busy={mutation.isPending}>
            {editing ? 'Save changes' : 'Register asset'}
          </Button>
          <Link className="button button--quiet" to={editing ? `/assets/${asset.id}` : '/assets'}>
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
