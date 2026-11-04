import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { assetKeys, fetchAssets } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import {
  createDomain,
  createEndpoint,
  domainKeys,
  updateDomain,
  updateEndpoint,
  uploadCertificates,
} from '../../shared/api/domains'
import type { Domain, TlsEndpoint } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { ErrorSummary } from '../../shared/ui/States'

function useRefresh() {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: domainKeys.all })
}

const AUTO_RENEW = [
  { value: '', label: 'Unknown' },
  { value: 'true', label: 'Yes' },
  { value: 'false', label: 'No' },
]

export function DomainDialog({ domain, onClose }: { domain?: Domain; onClose: () => void }) {
  const refresh = useRefresh()
  const [form, setForm] = useState({
    fqdn: domain?.fqdn ?? '',
    owner: domain?.owner ?? '',
    registrar: domain?.registrar ?? '',
    expires_on: domain?.expires_on ?? '',
    expiry_evidence: domain?.expiry_evidence ?? '',
    auto_renew: domain?.auto_renew === null || domain?.auto_renew === undefined ? '' : String(domain.auto_renew),
    note: domain?.note ?? '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...form,
        expires_on: form.expires_on || null,
        expiry_evidence: form.expires_on ? form.expiry_evidence : '',
        auto_renew: form.auto_renew === '' ? null : form.auto_renew === 'true',
      }
      return domain ? updateDomain(domain.id, domain.version, body) : createDomain(body)
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
      title={domain ? `Edit ${domain.fqdn}` : 'Add domain'}
      confirmLabel="Save domain"
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ fqdn: 'Domain', expiry_evidence: 'Expiry evidence' }}
        />
      )}
      <TextField
        label="Domain"
        name="dom-fqdn"
        value={form.fqdn}
        onChange={set('fqdn')}
        error={errors.fqdn}
        required
        help="Name only, for example example.org."
      />
      <TextField
        label="Owner (optional)"
        name="dom-owner"
        value={form.owner}
        onChange={set('owner')}
        help="Responsible person or team."
      />
      <TextField label="Registrar (optional)" name="dom-registrar" value={form.registrar} onChange={set('registrar')} />
      <TextField
        label="Registration expires (optional)"
        name="dom-expires"
        type="date"
        value={form.expires_on}
        onChange={set('expires_on')}
        help="Leave empty when not confirmed: the expiry stays Unknown."
      />
      {form.expires_on && (
        <TextField
          label="Expiry evidence"
          name="dom-evidence"
          value={form.expiry_evidence}
          onChange={set('expiry_evidence')}
          error={errors.expiry_evidence}
          help="Where the date comes from: registrar portal, invoice, WHOIS record. You are recorded as the verifier."
          required
        />
      )}
      <SelectField
        label="Auto-renew"
        name="dom-auto"
        value={form.auto_renew}
        onChange={set('auto_renew')}
        options={AUTO_RENEW}
      />
      <TextAreaField label="Note (optional)" name="dom-note" value={form.note} onChange={set('note')} />
    </Dialog>
  )
}

export function EndpointDialog({ endpoint, onClose }: { endpoint?: TlsEndpoint; onClose: () => void }) {
  const refresh = useRefresh()
  const [form, setForm] = useState({
    host: endpoint?.host ?? '',
    port: String(endpoint?.port ?? 443),
    sni: endpoint?.sni ?? '',
    service: endpoint?.service ?? '',
    owner: endpoint?.owner ?? '',
    enabled: endpoint?.enabled ?? true,
    note: endpoint?.note ?? '',
  })
  const [asset, setAsset] = useState<{ id: string; name: string } | null>(endpoint?.asset ?? null)
  const [assetTouched, setAssetTouched] = useState(false)
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const results = useQuery({
    queryKey: assetKeys.list({ q }),
    queryFn: () => fetchAssets({ q }),
    enabled: q.length > 0,
  })
  const set = (key: 'host' | 'port' | 'sni' | 'service' | 'owner' | 'note') => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...form,
        port: Number(form.port) || 443,
        ...(endpoint && !assetTouched ? {} : { asset: asset?.id ?? null }),
      }
      return endpoint ? updateEndpoint(endpoint.id, endpoint.version, body) : createEndpoint(body)
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
      title={endpoint ? `Edit ${endpoint.host}:${endpoint.port}` : 'Approve TLS endpoint'}
      confirmLabel={endpoint ? 'Save endpoint' : 'Approve endpoint'}
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ host: 'Host', port: 'Port', sni: 'SNI' }}
        />
      )}
      <p>ITAM will connect to this host and port to read the certificate it presents. Approve only services you own.</p>
      <TextField
        label="Host"
        name="ep-host"
        value={form.host}
        onChange={set('host')}
        error={errors.host}
        required
        help="Host name or IP address, no URL."
      />
      <TextField
        label="Port"
        name="ep-port"
        type="number"
        min={1}
        max={65535}
        value={form.port}
        onChange={set('port')}
        error={errors.port}
      />
      <TextField
        label="SNI (optional)"
        name="ep-sni"
        value={form.sni}
        onChange={set('sni')}
        error={errors.sni}
        help="Server name to present. Empty: the host name (none for IP addresses)."
      />
      <TextField label="Service (optional)" name="ep-service" value={form.service} onChange={set('service')} />
      <TextField label="Owner (optional)" name="ep-owner" value={form.owner} onChange={set('owner')} />
      <div className="toolbar" role="search">
        <TextField
          label="Asset (optional)"
          name="ep-asset-q"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              setQ(search.trim())
            }
          }}
          help={asset ? `Linked: ${asset.name}` : 'Find the asset that serves it (in your sites).'}
        />
        <div className="toolbar__actions">
          <Button onClick={() => setQ(search.trim())}>Search</Button>
          {asset && (
            <Button
              variant="quiet"
              onClick={() => {
                setAsset(null)
                setAssetTouched(true)
              }}
            >
              Unlink
            </Button>
          )}
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
                  name="ep-asset"
                  checked={asset?.id === a.id}
                  onChange={() => {
                    setAsset({ id: a.id, name: a.name })
                    setAssetTouched(true)
                  }}
                />
                {a.name} <span className="cell-secondary mono">{a.site.code}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
        />{' '}
        Check daily
      </label>
      <TextAreaField label="Note (optional)" name="ep-note" value={form.note} onChange={set('note')} />
    </Dialog>
  )
}

export function UploadDialog({ onClose }: { onClose: () => void }) {
  const refresh = useRefresh()
  const [pem, setPem] = useState('')
  const [note, setNote] = useState('')
  const save = useMutation({
    mutationFn: () => uploadCertificates(pem, note),
    onSuccess: async () => {
      await refresh()
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog
      open
      title="Upload certificate"
      confirmLabel="Upload"
      busy={save.isPending || !pem.trim()}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary message={save.error.message} fieldErrors={errors} fieldLabels={{ pem: 'Certificate' }} />
      )}
      <p>
        For certificates ITAM cannot read from an endpoint. Paste the public certificate only; private keys are refused
        and never stored.
      </p>
      <TextAreaField
        label="Certificate (PEM)"
        name="cert-pem"
        value={pem}
        onChange={(e) => setPem(e.target.value)}
        error={errors.pem}
        rows={10}
        className="mono"
      />
      <TextField label="Note (optional)" name="cert-note" value={note} onChange={(e) => setNote(e.target.value)} />
    </Dialog>
  )
}
