import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import {
  checkEndpoint,
  domainKeys,
  fetchCertificates,
  fetchDomains,
  fetchEndpoints,
  retireDomain,
  retireEndpoint,
} from '../../shared/api/domains'
import { PERMISSIONS, type Domain, type TlsEndpoint } from '../../shared/api/types'
import { formatDate, formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { Tabs } from '../../shared/ui/Tabs'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { DomainDialog, EndpointDialog, UploadDialog } from './dialogs'
import { CHECK_STATUS, expiryBadge, fingerprint } from './labels'

const EXPIRY_OPTIONS = [
  { value: '', label: 'Any' },
  { value: 'expired', label: 'Expired' },
  { value: 'expiring', label: 'Expiring within 90 days' },
  { value: 'ok', label: 'Later' },
]

export function DomainsPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'certificates'
  return (
    <div className="page page--wide">
      <PageHeader
        title="Domains & Certificates"
        meta="Owned domains with their registration expiry, TLS certificates and the approved endpoints ITAM reads them from."
      />
      <Tabs
        label="Domains and certificates sections"
        selected={tab}
        onSelect={(next) => {
          const search = new URLSearchParams(params)
          if (next === 'certificates') search.delete('tab')
          else search.set('tab', next)
          setParams(search, { replace: true })
        }}
        tabs={[
          { id: 'certificates', label: 'Certificates', content: <Certificates /> },
          { id: 'endpoints', label: 'TLS endpoints', content: <Endpoints /> },
          { id: 'domains', label: 'Domains', content: <Domains /> },
        ]}
      />
    </div>
  )
}

function usePaged<T>(
  key: readonly unknown[],
  fetcher: (cursor?: string) => Promise<{ items: T[]; next_cursor?: string | null }>,
) {
  const query = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) => fetcher(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  return { query, items: query.data?.pages.flatMap((p) => p.items) ?? [] }
}

function More({
  query,
}: {
  query: { hasNextPage: boolean; isFetchingNextPage: boolean; fetchNextPage: () => unknown }
}) {
  if (!query.hasNextPage) return null
  return (
    <div className="table-footer">
      <Button onClick={() => query.fetchNextPage()} busy={query.isFetchingNextPage}>
        Load more
      </Button>
    </div>
  )
}

function Panel({
  pending,
  error,
  what,
  empty,
  children,
}: {
  pending: boolean
  error: unknown
  what: string
  empty: ReactNode
  children: ReactNode
}) {
  return (
    <div className="panel panel--flush" aria-live="polite">
      {pending && <LoadingState label={`Loading ${what}…`} />}
      {Boolean(error) && <QueryErrorState error={error} what={what} />}
      {!pending && !error && empty}
      {children}
    </div>
  )
}

// --- Certificates -------------------------------------------------------------------------

function Certificates() {
  const { can } = useSession()
  const [q, setQ] = useState('')
  const [expiry, setExpiry] = useState('')
  const [deployed, setDeployed] = useState(false)
  const [uploading, setUploading] = useState(false)
  const filters = { q: q || undefined, expiry: expiry || undefined, deployed: deployed ? 'true' : undefined }
  const { query, items } = usePaged(domainKeys.certificates(filters), (cursor) => fetchCertificates(filters, cursor))
  return (
    <section aria-label="Certificates">
      <div className="toolbar">
        <TextField
          label="Search"
          name="cert-q"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          help="Name, SAN, issuer or fingerprint."
        />
        <SelectField
          label="Expiry"
          name="cert-expiry"
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          options={EXPIRY_OPTIONS}
        />
        <label className="checkbox">
          <input type="checkbox" checked={deployed} onChange={(e) => setDeployed(e.target.checked)} /> Only on an
          endpoint
        </label>
        {can(PERMISSIONS.certificatesManage) && (
          <div className="toolbar__actions">
            <Button onClick={() => setUploading(true)}>Upload certificate</Button>
          </div>
        )}
      </div>
      <Panel
        pending={query.isPending}
        error={query.error}
        what="certificates"
        empty={
          query.isSuccess &&
          items.length === 0 && (
            <EmptyState title="No certificates.">
              Approve a TLS endpoint so ITAM can read its certificate, or upload a public certificate.
            </EmptyState>
          )
        }
      >
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table data-table--nowrap">
              <caption className="visually-hidden">Certificates</caption>
              <thead>
                <tr>
                  <th scope="col">Certificate</th>
                  <th scope="col">Issuer</th>
                  <th scope="col">Fingerprint (SHA-256)</th>
                  <th scope="col">Not after</th>
                  <th scope="col">Expiry</th>
                  <th scope="col" className="num">
                    Endpoints
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => {
                  const badge = expiryBadge(c.expiry)
                  const extra = c.sans.length > 1 ? ` +${c.sans.length - 1} more` : ''
                  return (
                    <tr key={c.id}>
                      <td>
                        <Link className="table-link" to={`/certificates/${c.id}`}>
                          {c.common_name || c.sans[0] || 'No common name'}
                        </Link>
                        <span className="cell-secondary">
                          {c.sans.length ? `${c.sans[0]}${extra}` : 'No subject alternative names'}
                        </span>
                      </td>
                      <td>{c.self_signed ? <StatusBadge tone="neutral" label="Self-signed" /> : c.issuer}</td>
                      <td className="mono">{fingerprint(c.fingerprint_sha256)}</td>
                      <td>{formatDateTime(c.not_after)}</td>
                      <td>
                        <StatusBadge tone={badge.tone} label={badge.label} />
                      </td>
                      <td className="num">{c.endpoints}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <More query={query} />
      </Panel>
      {uploading && <UploadDialog onClose={() => setUploading(false)} />}
    </section>
  )
}

// --- Endpoints ----------------------------------------------------------------------------

export function EndpointsTable({ items, manage }: { items: TlsEndpoint[]; manage: boolean }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<TlsEndpoint | null>(null)
  const [retiring, setRetiring] = useState<TlsEndpoint | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: domainKeys.all })
  const check = useMutation({ mutationFn: (id: string) => checkEndpoint(id), onSettled: refresh })
  const retire = useMutation({
    mutationFn: ({ e, reason }: { e: TlsEndpoint; reason: string }) => retireEndpoint(e.id, e.version, reason),
    onSuccess: async () => {
      await refresh()
      setRetiring(null)
    },
  })
  return (
    <>
      {check.isError && (
        <p className="field__error panel__note" role="alert">
          {check.error.message}
        </p>
      )}
      <div className="table-scroll">
        <table className="data-table">
          <caption className="visually-hidden">TLS endpoints</caption>
          <thead>
            <tr>
              <th scope="col">Endpoint</th>
              <th scope="col">Service / asset</th>
              <th scope="col">Certificate</th>
              <th scope="col">Last check</th>
              {manage && (
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {items.map((e) => {
              const status = CHECK_STATUS[e.last_status]
              const badge = e.certificate ? expiryBadge(e.certificate.expiry) : null
              return (
                <tr key={e.id}>
                  <td>
                    <span className="mono">
                      {e.host}:{e.port}
                    </span>
                    <span className="cell-secondary">
                      {e.sni && e.sni !== e.host ? `SNI ${e.sni}` : e.sni ? 'SNI = host' : 'No SNI'}
                      {!e.enabled && ' · not checked'}
                    </span>
                  </td>
                  <td>
                    {e.service || <span className="cell-muted">–</span>}
                    <span className="cell-secondary">
                      {e.asset ? (
                        <Link to={`/assets/${e.asset.id}`}>{e.asset.name}</Link>
                      ) : e.asset_hidden ? (
                        'Asset outside your sites'
                      ) : (
                        'No asset linked'
                      )}
                    </span>
                  </td>
                  <td>
                    {e.certificate && badge ? (
                      <>
                        <Link className="table-link" to={`/certificates/${e.certificate.id}`}>
                          {e.certificate.common_name || fingerprint(e.certificate.fingerprint_sha256)}
                        </Link>{' '}
                        <StatusBadge tone={badge.tone} label={badge.label} />
                        {e.hostname_matches === false && (
                          <span className="cell-secondary">Name does not match the certificate</span>
                        )}
                      </>
                    ) : (
                      <span className="cell-muted">None read yet</span>
                    )}
                  </td>
                  <td>
                    <StatusBadge tone={status.tone} label={status.label} />
                    <span className="cell-secondary">
                      {e.last_checked_at ? formatDateTime(e.last_checked_at) : 'Never'}
                      {e.last_error && ` · ${e.last_error}`}
                    </span>
                  </td>
                  {manage && (
                    <td>
                      <div className="cell-actions">
                        {e.enabled && !e.retired_at && (
                          <Button
                            variant="quiet"
                            busy={check.isPending && check.variables === e.id}
                            onClick={() => check.mutate(e.id)}
                          >
                            Check now
                          </Button>
                        )}
                        {!e.retired_at && (
                          <>
                            <Button variant="quiet" onClick={() => setEditing(e)}>
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
      {editing && <EndpointDialog endpoint={editing} onClose={() => setEditing(null)} />}
      {retiring && (
        <ReasonDialog
          title={`Retire ${retiring.host}:${retiring.port}`}
          confirmLabel="Retire endpoint"
          help="ITAM stops checking it. Its certificate history stays."
          busy={retire.isPending}
          error={retire.error?.message}
          onClose={() => setRetiring(null)}
          onConfirm={(reason) => retire.mutate({ e: retiring, reason })}
        />
      )}
    </>
  )
}

function Endpoints() {
  const { can } = useSession()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [creating, setCreating] = useState(false)
  const filters = { q: q || undefined, status: status || undefined }
  const { query, items } = usePaged(domainKeys.endpoints(filters), (cursor) => fetchEndpoints(filters, cursor))
  const manage = can(PERMISSIONS.certificatesManage)
  return (
    <section aria-label="TLS endpoints">
      <p className="inline-note">
        ITAM connects only to the hosts and ports approved here, reads the certificate they present and stores nothing
        else. Checks run daily; metadata and link-local addresses are always refused.
      </p>
      <div className="toolbar">
        <TextField label="Search" name="ep-q" value={q} onChange={(e) => setQ(e.target.value)} />
        <SelectField
          label="Last check"
          name="ep-status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { value: '', label: 'Any' },
            ...Object.entries(CHECK_STATUS).map(([value, s]) => ({ value, label: s.label })),
          ]}
        />
        {manage && (
          <div className="toolbar__actions">
            <Button variant="primary" onClick={() => setCreating(true)}>
              Approve endpoint
            </Button>
          </div>
        )}
      </div>
      <Panel
        pending={query.isPending}
        error={query.error}
        what="TLS endpoints"
        empty={query.isSuccess && items.length === 0 && <EmptyState title="No approved TLS endpoints." />}
      >
        {items.length > 0 && <EndpointsTable items={items} manage={manage} />}
        <More query={query} />
      </Panel>
      {creating && <EndpointDialog onClose={() => setCreating(false)} />}
    </section>
  )
}

// --- Domains ------------------------------------------------------------------------------

function Domains() {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const [q, setQ] = useState('')
  const [expiry, setExpiry] = useState('')
  const [editing, setEditing] = useState<Domain | 'new' | null>(null)
  const [retiring, setRetiring] = useState<Domain | null>(null)
  const filters = { q: q || undefined, expiry: expiry || undefined }
  const { query, items } = usePaged(domainKeys.domains(filters), (cursor) => fetchDomains(filters, cursor))
  const retire = useMutation({
    mutationFn: ({ d, reason }: { d: Domain; reason: string }) => retireDomain(d.id, d.version, reason),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: domainKeys.all })
      setRetiring(null)
    },
  })
  const manage = can(PERMISSIONS.certificatesManage)
  return (
    <section aria-label="Domains">
      <p className="inline-note">
        Registration expiry is Unknown until someone records it with its evidence. It is never taken from a TLS
        certificate.
      </p>
      <div className="toolbar">
        <TextField label="Search" name="dom-q" value={q} onChange={(e) => setQ(e.target.value)} />
        <SelectField
          label="Registration expiry"
          name="dom-expiry"
          value={expiry}
          onChange={(e) => setExpiry(e.target.value)}
          options={[...EXPIRY_OPTIONS, { value: 'unknown', label: 'Unknown' }]}
        />
        {manage && (
          <div className="toolbar__actions">
            <Button variant="primary" onClick={() => setEditing('new')}>
              Add domain
            </Button>
          </div>
        )}
      </div>
      <Panel
        pending={query.isPending}
        error={query.error}
        what="domains"
        empty={query.isSuccess && items.length === 0 && <EmptyState title="No domains recorded." />}
      >
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table data-table--nowrap">
              <caption className="visually-hidden">Domains</caption>
              <thead>
                <tr>
                  <th scope="col">Domain</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Registrar</th>
                  <th scope="col">Registration expiry</th>
                  <th scope="col">Renewal status</th>
                  {manage && (
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((d) => {
                  const badge = expiryBadge(d.expiry)
                  return (
                    <tr key={d.id}>
                      <td className="mono">{d.fqdn}</td>
                      <td>{d.owner || <span className="cell-muted">–</span>}</td>
                      <td>{d.registrar || <span className="cell-muted">Unknown</span>}</td>
                      <td>
                        {d.expires_on ? formatDate(d.expires_on) : <span className="cell-muted">Unknown</span>}
                        {d.expires_on && (
                          <span className="cell-secondary">
                            {d.expiry_evidence}
                            {d.expiry_verified_by && ` · ${d.expiry_verified_by}`}
                          </span>
                        )}
                      </td>
                      <td>
                        <StatusBadge tone={badge.tone} label={badge.label} />
                        {d.auto_renew !== null && (
                          <span className="cell-secondary">{d.auto_renew ? 'Auto-renews' : 'Manual renewal'}</span>
                        )}
                      </td>
                      {manage && (
                        <td>
                          <div className="cell-actions">
                            <Button variant="quiet" onClick={() => setEditing(d)}>
                              Edit…
                            </Button>
                            <Button variant="quiet" onClick={() => setRetiring(d)}>
                              Retire…
                            </Button>
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
        <More query={query} />
      </Panel>
      {editing && <DomainDialog domain={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      {retiring && (
        <ReasonDialog
          title={`Retire ${retiring.fqdn}`}
          confirmLabel="Retire domain"
          help="Use this when the domain is no longer owned. It stays in the history."
          busy={retire.isPending}
          error={retire.error?.message}
          onClose={() => setRetiring(null)}
          onConfirm={(reason) => retire.mutate({ d: retiring, reason })}
        />
      )}
    </section>
  )
}
