import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { assetKeys, fetchSites } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import {
  createIntegration,
  discoveryKeys,
  fetchFieldAuthority,
  fetchIntegrations,
  fetchSources,
  updateFieldAuthority,
  updateIntegration,
} from '../../shared/api/discovery'
import type { DiscoverySource, FieldAuthorityPolicy, IntegrationInstance } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { CheckboxGroup, SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { AVAILABILITY_LABEL, FIELD_LABEL, FRESHNESS, INSTANCE_STATUS } from '../discovery/labels'

export function IntegrationsPage() {
  const integrations = useQuery({ queryKey: discoveryKeys.integrations, queryFn: fetchIntegrations })
  const sources = useQuery({ queryKey: discoveryKeys.sources, queryFn: fetchSources })
  const [editing, setEditing] = useState<IntegrationInstance | 'new' | null>(null)

  return (
    <div className="page page--wide">
      <PageHeader
        title="Integrations"
        meta="Read-only source connections. Planned sources have no adapter yet; Beta adapters are fixture-tested and need live validation."
        actions={
          <Button variant="primary" onClick={() => setEditing('new')}>
            Add integration
          </Button>
        }
      />
      <section className="panel panel--flush" aria-live="polite">
        {integrations.isPending && <LoadingState label="Loading integrations…" />}
        {integrations.isError && <QueryErrorState error={integrations.error} what="integrations" />}
        {integrations.data?.length === 0 && <EmptyState title="No integrations configured." />}
        {integrations.data && integrations.data.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Source</th>
                <th scope="col">Status</th>
                <th scope="col">Freshness</th>
                <th scope="col">Default site</th>
                <th scope="col">Automatic strong matches</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {integrations.data.map((i) => (
                <tr key={i.id}>
                  <td>
                    <Link to={`/admin/integrations/${i.id}`}>{i.name}</Link>
                    {!i.is_enabled && <span className="cell-secondary">Disabled</span>}
                  </td>
                  <td>
                    {i.source.name}
                    {i.source.availability !== 'available' && (
                      <>
                        {' '}
                        <StatusBadge
                          tone={i.source.availability === 'beta' ? 'warning' : 'neutral'}
                          label={AVAILABILITY_LABEL[i.source.availability]}
                        />
                      </>
                    )}
                    {i.has_adapter && !i.live_access_approved && (
                      <span className="cell-secondary">Live access not approved</span>
                    )}
                  </td>
                  <td>
                    <StatusBadge tone={INSTANCE_STATUS[i.status].tone} label={INSTANCE_STATUS[i.status].label} />
                  </td>
                  <td>
                    <StatusBadge tone={FRESHNESS[i.freshness].tone} label={FRESHNESS[i.freshness].label} />
                    {i.last_success_at && (
                      <span className="cell-secondary">{formatDateTime(i.last_success_at)}</span>
                    )}
                  </td>
                  <td className="mono">
                    {i.default_site.code}
                    {i.default_vrf && <span className="cell-secondary">VRF {i.default_vrf}</span>}
                  </td>
                  <td>{i.auto_link_strong_matches ? 'On' : 'Off (review all)'}</td>
                  <td>
                    <Button variant="quiet" onClick={() => setEditing(i)}>
                      Edit<span className="visually-hidden"> {i.name}</span>
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <FieldAuthorityEditor sources={sources.data ?? []} />
      {editing && sources.data && (
        <IntegrationDialog
          instance={editing === 'new' ? null : editing}
          sources={sources.data}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

// Cloud sources whose endpoint is fixed by the connector (the server enforces it too).
const FIXED_ENDPOINT: Record<string, string> = {
  intune: 'https://graph.microsoft.com',
  defender: 'https://api.security.microsoft.com',
  m365: 'https://graph.microsoft.com',
}
// Per-source default for "stale after"; Intune devices are often offline for days.
const STALE_DEFAULT: Record<string, number> = { intune: 168, defender: 168 }

function IntegrationDialog({
  instance,
  sources,
  onClose,
}: {
  instance: IntegrationInstance | null
  sources: DiscoverySource[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites })
  const [source, setSource] = useState(instance?.source.code ?? '')
  const [name, setName] = useState(instance?.name ?? '')
  const [site, setSite] = useState(instance?.default_site.id ?? '')
  const [vrf, setVrf] = useState(instance?.default_vrf ?? '')
  const [baseUrl, setBaseUrl] = useState(instance?.base_url ?? '')
  const [staleHours, setStaleHours] = useState(String(instance?.stale_after_hours ?? 48))
  const [flags, setFlags] = useState<string[]>([
    ...((instance?.is_enabled ?? true) ? ['enabled'] : []),
    ...(instance?.auto_link_strong_matches ? ['auto_link'] : []),
  ])
  const [disconnected, setDisconnected] = useState(instance?.status === 'disconnected')
  const [client, setClient] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: (): Promise<unknown> => {
      const body = {
        name: name.trim(),
        default_site: site,
        default_vrf: vrf.trim(),
        base_url: baseUrl.trim(),
        stale_after_hours: Number(staleHours),
        is_enabled: flags.includes('enabled'),
        auto_link_strong_matches: flags.includes('auto_link'),
      }
      if (instance) {
        const status = disconnected ? 'disconnected' : instance.status === 'disconnected' ? 'configured' : undefined
        return updateIntegration(instance.id, instance.version, { ...body, ...(status ? { status } : {}) })
      }
      return createIntegration({ ...body, source })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: discoveryKeys.integrations })
      onClose()
    },
  })
  const server = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = { ...server, ...client }
  const summary = mutation.error && !Object.keys(server).length ? mutation.error.message : null
  const chosen = sources.find((s) => s.code === source)
  const fixedUrl = FIXED_ENDPOINT[source] ?? instance?.connector?.fixed_base_url ?? null

  return (
    <Dialog
      open
      title={instance ? `Edit ${instance.name}` : 'Add integration'}
      confirmLabel={instance ? 'Save integration' : 'Add integration'}
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        const errs: Record<string, string[]> = {}
        if (!instance && !source) errs.source = ['Choose a source type.']
        if (!name.trim()) errs.name = ['Enter a name.']
        if (!site) errs.default_site = ['Choose the default site.']
        const hours = Number(staleHours)
        if (!Number.isInteger(hours) || hours < 1 || hours > 720) errs.stale_after_hours = ['Enter 1 to 720 hours.']
        setClient(errs)
        if (!Object.keys(errs).length) mutation.mutate()
      }}
    >
      {summary && <p className="field__error">{summary}</p>}
      {!instance && (
        <SelectField
          label="Source type"
          name="int_source"
          options={[
            { value: '', label: 'Choose a source' },
            ...sources.map((s) => ({
              value: s.code,
              label: `${s.name}${s.availability === 'available' ? '' : ` (${s.availability})`}`,
            })),
          ]}
          value={source}
          onChange={(e) => {
            setSource(e.target.value)
            setStaleHours(String(STALE_DEFAULT[e.target.value] ?? 48))
          }}
          error={errors.source}
          help={chosen?.availability === 'planned' ? 'No adapter yet: the integration can be configured but will not synchronise.' : chosen?.description}
        />
      )}
      <TextField label="Name" name="int_name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
      <SelectField
        label="Default site"
        name="int_site"
        options={[{ value: '', label: 'Choose a site' }, ...(sites.data ?? []).map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` }))]}
        value={site}
        onChange={(e) => setSite(e.target.value)}
        error={errors.default_site}
        help="New devices are proposed in this site; IP addresses are interpreted in this site."
      />
      <div className="form-grid">
        <TextField label="Default VRF" name="int_vrf" value={vrf} onChange={(e) => setVrf(e.target.value)} error={errors.default_vrf} help="Leave empty for the global table." />
        <TextField label="Stale after (hours)" name="int_stale" inputMode="numeric" value={staleHours} onChange={(e) => setStaleHours(e.target.value)} error={errors.stale_after_hours} />
      </div>
      {fixedUrl ? (
        <p className="field__help">
          Endpoint: <span className="mono">{fixedUrl}</span> (fixed for this source).
        </p>
      ) : (
        <TextField
          label="Base URL"
          name="int_url"
          className="field__control mono"
          placeholder="https://"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          error={errors.base_url}
          help="HTTPS only, no credentials in the URL. Tokens are referenced as server secrets on the integration page, never entered here."
        />
      )}
      <CheckboxGroup
        legend="Options"
        name="int_flags"
        options={[
          { value: 'enabled', label: 'Enabled' },
          {
            value: 'auto_link',
            label: 'Link strong matches automatically',
            description:
              'Only a verified serial or hardware UUID with the same manufacturer and category and no conflicting identifier. IP, hostname, MAC or serial alone never auto-link.',
          },
        ]}
        value={flags}
        onChange={setFlags}
      />
      {instance && (
        <CheckboxGroup
          legend="Connection"
          name="int_disconnected"
          options={[{ value: 'disconnected', label: 'Mark as disconnected', description: 'Keeps links and history; stops treating the source as current.' }]}
          value={disconnected ? ['disconnected'] : []}
          onChange={(v) => setDisconnected(v.includes('disconnected'))}
        />
      )}
    </Dialog>
  )
}

function FieldAuthorityEditor({ sources }: { sources: DiscoverySource[] }) {
  const policy = useQuery({ queryKey: discoveryKeys.authority, queryFn: fetchFieldAuthority })
  // Lives here: saving bumps the version, which remounts AuthorityForm.
  const [saved, setSaved] = useState(false)
  if (policy.isPending) return <LoadingState label="Loading field authority…" />
  if (policy.isError) return <QueryErrorState error={policy.error} what="field authority" />
  return (
    <AuthorityForm
      key={policy.data.version}
      policy={policy.data}
      sources={sources}
      saved={saved}
      onSaved={() => setSaved(true)}
    />
  )
}

function AuthorityForm({
  policy,
  sources,
  saved,
  onSaved,
}: {
  policy: FieldAuthorityPolicy
  sources: DiscoverySource[]
  saved: boolean
  onSaved: () => void
}) {
  const queryClient = useQueryClient()
  const [precedence, setPrecedence] = useState<Record<string, string[]>>(policy.precedence)
  const names = Object.fromEntries(sources.map((s) => [s.code, s.name]))
  const mutation = useMutation({
    mutationFn: () => updateFieldAuthority(policy.version, precedence),
    onSuccess: (updated) => {
      onSaved()
      queryClient.setQueryData(discoveryKeys.authority, updated)
    },
  })

  function move(field: string, index: number, delta: number) {
    setPrecedence((current) => {
      const list = [...current[field]]
      const [item] = list.splice(index, 1)
      list.splice(index + delta, 0, item)
      return { ...current, [field]: list }
    })
  }

  return (
    <section className="panel" aria-labelledby="authority-heading">
      <h2 className="section-title" id="authority-heading">
        Field authority
      </h2>
      <p className="field__help">
        When sources disagree, the first source in each list sets the value while it is fresh. Manually locked values
        always win over every source. Business fields (owner, site, category, tag) are never set by sources.
      </p>
      <div className="authority-grid">
        {Object.entries(precedence).map(([field, order]) => (
          <div key={field} className="authority-grid__item">
            <h3 className="subsection-title">{FIELD_LABEL[field] ?? field}</h3>
            <ol className="authority-list">
              {order.map((code, index) => (
                <li key={code}>
                  <span>{names[code] ?? code}</span>
                  <span className="authority-list__actions">
                    <Button variant="quiet" disabled={index === 0} onClick={() => move(field, index, -1)}>
                      Up<span className="visually-hidden"> {names[code]} for {FIELD_LABEL[field]}</span>
                    </Button>
                    <Button variant="quiet" disabled={index === order.length - 1} onClick={() => move(field, index, 1)}>
                      Down<span className="visually-hidden"> {names[code]} for {FIELD_LABEL[field]}</span>
                    </Button>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      {mutation.error && <p className="field__error">{mutation.error.message}</p>}
      {saved && (
        <p className="inline-success" role="status">
          Field authority saved.
        </p>
      )}
      <div className="form-actions">
        <Button variant="primary" busy={mutation.isPending} onClick={() => mutation.mutate()}>
          Save field authority
        </Button>
      </div>
    </section>
  )
}
