import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  assetKeys,
  createDepartment,
  createLocation,
  createSite,
  fetchDepartments,
  fetchLocations,
  fetchSites,
  updateDepartment,
  updateLocation,
  updateSite,
} from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import type { Department, Location, Site } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { CheckboxGroup, SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'

const KINDS = [
  { value: 'building', label: 'Building' },
  { value: 'floor', label: 'Floor' },
  { value: 'room', label: 'Room' },
  { value: 'rack', label: 'Rack' },
  { value: 'other', label: 'Other' },
]
const KIND_LABEL = Object.fromEntries(KINDS.map((k) => [k.value, k.label]))

type Editing =
  | { kind: 'site'; record: Site | null }
  | { kind: 'location'; record: Location | null }
  | { kind: 'department'; record: Department | null }
  | null

function ActiveBadge({ active }: { active: boolean }) {
  return <StatusBadge tone={active ? 'success' : 'neutral'} label={active ? 'Active' : 'Inactive'} />
}

/** Depth-first order with depth, for indented display of parent/child records. */
function ordered<T extends { id: string; parent: string | null }>(rows: T[], label: (r: T) => string) {
  const out: { row: T; depth: number }[] = []
  const walk = (parent: string | null, depth: number) =>
    rows
      .filter((r) => r.parent === parent)
      .sort((a, b) => label(a).localeCompare(label(b)))
      .forEach((r) => {
        out.push({ row: r, depth })
        walk(r.id, depth + 1)
      })
  walk(null, 0)
  // Rows whose parent is outside the visible set still appear (at top level).
  rows.filter((r) => !out.some((o) => o.row.id === r.id)).forEach((r) => out.push({ row: r, depth: 0 }))
  return out
}

export function SitesPage() {
  const [params, setParams] = useSearchParams()
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites })
  const siteId = params.get('site') ?? sites.data?.[0]?.id ?? ''
  const locations = useQuery({
    queryKey: assetKeys.locations(siteId),
    queryFn: () => fetchLocations(siteId),
    enabled: Boolean(siteId),
  })
  const departments = useQuery({ queryKey: assetKeys.departments, queryFn: fetchDepartments })
  const [editing, setEditing] = useState<Editing>(null)
  const selectedSite = sites.data?.find((s) => s.id === siteId)

  return (
    <div className="page page--wide">
      <PageHeader
        title="Sites, locations & departments"
        meta="Site access is granted per user under Users & roles. A grant on a site includes its child sites."
      />

      <section className="panel panel--flush" aria-labelledby="sites-heading">
        <div className="section-header section-header--inset">
          <h2 className="section-title" id="sites-heading">
            Sites
          </h2>
          <Button onClick={() => setEditing({ kind: 'site', record: null })}>Add site</Button>
        </div>
        {sites.isPending && <LoadingState label="Loading sites…" />}
        {sites.isError && <QueryErrorState error={sites.error} what="sites" />}
        {sites.data && sites.data.length === 0 && (
          <EmptyState title="No sites yet.">Add the first site to start registering assets.</EmptyState>
        )}
        {sites.data && sites.data.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Code</th>
                <th scope="col">Name</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {ordered(sites.data, (s) => s.code).map(({ row, depth }) => (
                <tr key={row.id} className={row.id === siteId ? 'row--selected' : undefined}>
                  <td className="mono" style={{ paddingLeft: `${12 + depth * 20}px` }}>
                    {row.code}
                  </td>
                  <td>{row.name}</td>
                  <td>
                    <ActiveBadge active={row.is_active} />
                  </td>
                  <td className="cell-actions">
                    <Button
                      variant="quiet"
                      aria-current={row.id === siteId ? 'true' : undefined}
                      onClick={() => setParams({ site: row.id }, { replace: true })}
                    >
                      Locations<span className="visually-hidden"> for {row.code}</span>
                    </Button>
                    <Button variant="quiet" onClick={() => setEditing({ kind: 'site', record: row })}>
                      Edit<span className="visually-hidden"> {row.code}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {selectedSite && (
        <section className="panel panel--flush" aria-labelledby="loc-heading">
          <div className="section-header section-header--inset">
            <h2 className="section-title" id="loc-heading">
              Locations in {selectedSite.code}
            </h2>
            <Button onClick={() => setEditing({ kind: 'location', record: null })}>Add location</Button>
          </div>
          {locations.isPending && <LoadingState label="Loading locations…" />}
          {locations.isError && <QueryErrorState error={locations.error} what="locations" />}
          {locations.data && locations.data.length === 0 && (
            <EmptyState title="No locations in this site." />
          )}
          {locations.data && locations.data.length > 0 && (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Type</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {ordered(locations.data, (l) => l.name).map(({ row, depth }) => (
                  <tr key={row.id}>
                    <td style={{ paddingLeft: `${12 + depth * 20}px` }}>{row.name}</td>
                    <td>{KIND_LABEL[row.kind]}</td>
                    <td>
                      <ActiveBadge active={row.is_active} />
                    </td>
                    <td>
                      <Button
                        variant="quiet"
                        onClick={() => setEditing({ kind: 'location', record: row })}
                      >
                        Edit<span className="visually-hidden"> {row.name}</span>
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      <section className="panel panel--flush" aria-labelledby="dept-heading">
        <div className="section-header section-header--inset">
          <h2 className="section-title" id="dept-heading">
            Departments
          </h2>
          <Button onClick={() => setEditing({ kind: 'department', record: null })}>
            Add department
          </Button>
        </div>
        {departments.isPending && <LoadingState label="Loading departments…" />}
        {departments.isError && <QueryErrorState error={departments.error} what="departments" />}
        {departments.data && departments.data.length === 0 && <EmptyState title="No departments yet." />}
        {departments.data && departments.data.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Code</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {departments.data.map((row) => (
                <tr key={row.id}>
                  <td>{row.name}</td>
                  <td className="mono">{row.code || <span className="cell-muted">None</span>}</td>
                  <td>
                    <ActiveBadge active={row.is_active} />
                  </td>
                  <td>
                    <Button
                      variant="quiet"
                      onClick={() => setEditing({ kind: 'department', record: row })}
                    >
                      Edit<span className="visually-hidden"> {row.name}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {editing && (
        <RecordDialog
          editing={editing}
          sites={sites.data ?? []}
          site={selectedSite}
          locations={locations.data ?? []}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

function RecordDialog({
  editing,
  sites,
  site,
  locations,
  onClose,
}: {
  editing: NonNullable<Editing>
  sites: Site[]
  site?: Site
  locations: Location[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const record = editing.record as (Site & Location & Department) | null
  const [code, setCode] = useState(record?.code ?? '')
  const [name, setName] = useState(record?.name ?? '')
  const [parent, setParent] = useState(record?.parent ?? '')
  const [kind, setKind] = useState(record?.kind ?? 'room')
  const [active, setActive] = useState(record?.is_active ?? true)
  const [client, setClient] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: (): Promise<unknown> => {
      const status = record ? { is_active: active } : {}
      if (editing.kind === 'site') {
        const body = { code: code.trim(), name: name.trim(), parent: parent || null, ...status }
        return record ? updateSite(record.id, record.version, body) : createSite(body)
      }
      if (editing.kind === 'location') {
        const body = { name: name.trim(), parent: parent || null, kind, ...status }
        return record
          ? updateLocation(record.id, record.version, body)
          : createLocation({ ...body, site: site!.id })
      }
      const body = { name: name.trim(), code: code.trim(), ...status }
      return record ? updateDepartment(record.id, record.version, body) : createDepartment(body)
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: assetKeys.sites }),
        queryClient.invalidateQueries({ queryKey: ['locations'] }),
        queryClient.invalidateQueries({ queryKey: assetKeys.departments }),
      ])
      onClose()
    },
  })
  const server = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = { ...server, ...client }
  const summary = mutation.error && Object.keys(server).length === 0 ? mutation.error.message : null
  const noun = { site: 'site', location: 'location', department: 'department' }[editing.kind]
  const parentOptions =
    editing.kind === 'site'
      ? sites.filter((s) => s.id !== record?.id).map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` }))
      : locations.filter((l) => l.id !== record?.id).map((l) => ({ value: l.id, label: l.name }))

  return (
    <Dialog
      open
      title={record ? `Edit ${noun} ${record.code || record.name}` : `Add ${noun}${editing.kind === 'location' && site ? ` to ${site.code}` : ''}`}
      confirmLabel={record ? `Save ${noun}` : `Add ${noun}`}
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        const errs: Record<string, string[]> = {}
        if (!name.trim()) errs.name = ['Enter a name.']
        if (editing.kind === 'site' && !code.trim()) errs.code = ['Enter a site code.']
        setClient(errs)
        if (!Object.keys(errs).length) mutation.mutate()
      }}
    >
      {summary && <p className="field__error">{summary}</p>}
      {editing.kind !== 'location' && (
        <TextField
          label={editing.kind === 'site' ? 'Code' : 'Code (optional)'}
          name="record_code"
          className="field__control mono"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          error={errors.code}
          help={editing.kind === 'site' ? 'Short unique code, e.g. LIM-HQ. Stored in uppercase.' : undefined}
          autoFocus
        />
      )}
      <TextField
        label="Name"
        name="record_name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={errors.name}
        autoFocus={editing.kind === 'location'}
      />
      {editing.kind !== 'department' && (
        <SelectField
          label={editing.kind === 'site' ? 'Parent site' : 'Inside location'}
          name="record_parent"
          options={[{ value: '', label: 'None' }, ...parentOptions]}
          value={parent}
          onChange={(e) => setParent(e.target.value)}
          error={errors.parent}
        />
      )}
      {editing.kind === 'location' && (
        <SelectField
          label="Type"
          name="record_kind"
          options={KINDS}
          value={kind}
          onChange={(e) => setKind(e.target.value as Location['kind'])}
          error={errors.kind}
        />
      )}
      {record && (
        <CheckboxGroup
          legend="Status"
          name="record_active"
          options={[
            {
              value: 'active',
              label: 'Active',
              description: 'Inactive records stay on existing assets but cannot be newly assigned.',
            },
          ]}
          value={active ? ['active'] : []}
          onChange={(v) => setActive(v.includes('active'))}
        />
      )}
    </Dialog>
  )
}
