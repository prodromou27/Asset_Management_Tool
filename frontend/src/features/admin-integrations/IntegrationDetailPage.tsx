import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { isApiError } from '../../shared/api/client'
import {
  discoveryKeys,
  fetchIntegration,
  fetchRuns,
  setLiveAccess,
  syncNow,
  testConnection,
  updateIntegration,
} from '../../shared/api/discovery'
import type {
  ConnectionTest,
  IntegrationInstance,
  IntegrationWrite,
  Paginated,
  SyncRun,
} from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { CheckboxGroup, SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import {
  AVAILABILITY_LABEL,
  CREDENTIAL_STATUS,
  FRESHNESS,
  INSTANCE_STATUS,
  RUN_PHASE,
  RUN_STATUS,
} from '../discovery/labels'

const CAPABILITY_LABEL: Record<string, string> = {
  devices: 'Device list',
  device_ip: 'IP addresses per device',
  device_ports: 'Ports per device',
  inventory: 'Hardware inventory',
  fdb: 'MAC table (FDB)',
  computers: 'Computer list',
  computer_details: 'Hardware, OS and network details',
  software: 'Installed software (not collected yet)',
  route_dcapi: 'Inventory API: dcapi (current)',
  route_api_1_4: 'Inventory API: api/1.4 (older builds)',
  links: 'LLDP/CDP neighbours',
  route_listing: 'API route listing',
  managed_devices: 'Managed device inventory (Graph v1.0)',
  detected_apps: 'Detected apps (not collected yet)',
  permission_read_all: 'Required read permission granted',
  machines: 'Machines API (Defender for Endpoint)',
  advanced_hunting: 'Advanced Hunting (not used)',
  device_actions: 'Device actions (never used)',
}
// Shown in the permissions panel instead (a "yes" here is a problem, not a feature).
const HIDDEN_CAPABILITIES = new Set(['excess_permissions'])

const ACTIVE: SyncRun['status'][] = ['queued', 'running']

const AUTH_LABEL: Record<string, string> = {
  bearer: 'Authorization: Bearer <token>',
  x_auth_token: 'X-Auth-Token: <token>',
  authorization: 'Authorization: <token>',
  client_certificate: 'OAuth client certificate (recommended)',
  client_secret: 'OAuth client secret',
}

interface SourceProfile {
  url: string
  token: string
  api: string
  schemeHelp?: string
  credentialLabel?: string
  credentialHelp?: string
  schemeLabel?: string
  accountHint?: string
}

const PROFILES: Record<string, SourceProfile> = {
  librenms: {
    url: 'https://librenms.example',
    token: 'env:ITAM_INTEGRATION_LIBRENMS_TOKEN',
    api: 'The connector only sends GET requests to /api/v0.',
    schemeHelp: 'Use X-Auth-Token if your LibreNMS version rejects Bearer.',
  },
  endpoint_central: {
    url: 'https://endpointcentral.example:8383',
    token: 'env:ITAM_INTEGRATION_ENDPOINT_CENTRAL_KEY',
    api: 'Use the verified HTTPS listener and port. The connector only sends GET requests to the inventory API (dcapi or api/1.4, detected automatically).',
    schemeHelp: 'On-premises API keys are normally sent as the raw Authorization header value.',
  },
  intune: {
    url: 'https://graph.microsoft.com',
    token: 'file:intune-app.pem',
    api: 'The connector only sends GET requests to Microsoft Graph v1.0 managedDevices.',
    credentialLabel: 'Credential reference',
    credentialHelp:
      'Certificate: file:<name> holding the private key and certificate (PEM). Secret: env:ITAM_INTEGRATION_<NAME>. The credential itself is never entered or shown here.',
    schemeLabel: 'Authentication method',
    schemeHelp: 'Prefer a certificate uploaded to the app registration; use a client secret only if a certificate is not possible.',
    accountHint: 'Use a dedicated app registration with read-only application permissions.',
  },
  defender: {
    url: 'https://api.security.microsoft.com',
    token: 'file:defender-app.pem',
    api: 'The connector only sends GET requests to /api/machines (Defender for Endpoint API, its own token audience).',
    credentialLabel: 'Certificate reference',
    credentialHelp:
      'file:<name> holding the private key and the certificate (PEM) uploaded to the app registration. The certificate is never entered or shown here.',
    schemeLabel: 'Authentication method',
    schemeHelp: 'Defender integrations use certificate credentials only.',
    accountHint:
      'Use a dedicated app registration with only the WindowsDefenderATP application permission Machine.Read.All; never grant device actions.',
  },
}
const GENERIC: SourceProfile = {
  url: 'https://',
  token: 'env:ITAM_INTEGRATION_<NAME>',
  api: 'The connector only sends GET requests.',
}

export function IntegrationDetailPage() {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const instance = useQuery({
    queryKey: discoveryKeys.integration(id),
    queryFn: () => fetchIntegration(id),
    // Follow an active run until it finishes.
    refetchInterval: (query) => {
      const status = query.state.data?.last_run?.status
      return status && ACTIVE.includes(status) ? 3000 : false
    },
  })
  const runActive = Boolean(instance.data?.last_run && ACTIVE.includes(instance.data.last_run.status))
  const runs = useQuery({
    queryKey: discoveryKeys.runs(id),
    queryFn: () => fetchRuns(id),
    refetchInterval: runActive ? 3000 : false,
  })
  const [saved, setSaved] = useState(false)
  const [test, setTest] = useState<ConnectionTest | null>(null)

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: discoveryKeys.integration(id) }),
      queryClient.invalidateQueries({ queryKey: discoveryKeys.runs(id) }),
      queryClient.invalidateQueries({ queryKey: discoveryKeys.integrations, exact: true }),
    ])
  }
  const testMutation = useMutation({
    mutationFn: () => testConnection(id),
    onSuccess: async (result) => {
      setTest(result)
      await refresh()
    },
  })
  const syncMutation = useMutation({ mutationFn: () => syncNow(id, 'full'), onSuccess: refresh })

  const crumb = (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <Link to="/admin/integrations">Integrations</Link>
    </nav>
  )
  if (instance.isPending) return <LoadingState label="Loading integration…" />
  if (instance.isError) {
    return (
      <div className="page">
        {crumb}
        <QueryErrorState error={instance.error} what="this integration" />
      </div>
    )
  }
  const i = instance.data
  const blocked = gateMessage(i)

  return (
    <div className="page page--wide">
      {crumb}
      <PageHeader
        title={i.name}
        meta={`${i.source.name} · ${AVAILABILITY_LABEL[i.source.availability] ?? i.source.availability}`}
        actions={
          i.has_adapter && (
            <>
              <Button busy={testMutation.isPending} disabled={!i.base_url} onClick={() => testMutation.mutate()}>
                Test connection
              </Button>
              <Button
                variant="primary"
                busy={syncMutation.isPending}
                disabled={Boolean(blocked) || runActive}
                onClick={() => syncMutation.mutate()}
              >
                Sync now
              </Button>
            </>
          )
        }
      />
      {!i.has_adapter && (
        <p className="inline-note">
          This source has no adapter yet. It can be configured, but it cannot connect or synchronise.
        </p>
      )}
      {i.has_adapter && blocked && <p className="inline-note inline-note--warning">{blocked}</p>}
      {i.source.availability === 'beta' && (
        <p className="inline-note">
          Beta: tested against sanitized fixtures only. Validate against your {i.source.name} version with a
          read-only account before relying on scheduled synchronisation.
        </p>
      )}
      {syncMutation.error && <p className="field__error">{syncMutation.error.message}</p>}
      {testMutation.error && <p className="field__error">{testMutation.error.message}</p>}
      {test && (
        <p className={test.ok ? 'inline-success' : 'field__error'} role="status">
          {test.message}
          {test.ok && test.version && ` ${i.source.name} ${test.version}.`}
        </p>
      )}

      <dl className="status-strip" aria-label="Integration status">
        <div>
          <dt>Status</dt>
          <dd>
            <StatusBadge tone={INSTANCE_STATUS[i.status].tone} label={INSTANCE_STATUS[i.status].label} />
          </dd>
        </div>
        <div>
          <dt>Freshness</dt>
          <dd>
            <StatusBadge tone={FRESHNESS[i.freshness].tone} label={FRESHNESS[i.freshness].label} />
          </dd>
        </div>
        <div>
          <dt>Connection test</dt>
          <dd>
            <StatusBadge
              tone={i.last_test_ok === null ? 'neutral' : i.last_test_ok ? 'success' : 'danger'}
              label={i.last_test_ok === null ? 'Not tested' : i.last_test_ok ? 'Passed' : 'Failed'}
            />
          </dd>
        </div>
        <div>
          <dt>Credential</dt>
          <dd>
            <StatusBadge
              tone={(CREDENTIAL_STATUS[i.credential_status] ?? CREDENTIAL_STATUS.not_set).tone}
              label={(CREDENTIAL_STATUS[i.credential_status] ?? CREDENTIAL_STATUS.not_set).label}
            />
          </dd>
        </div>
        <div>
          <dt>Live access</dt>
          <dd>
            <StatusBadge
              tone={i.live_access_approved ? 'success' : 'neutral'}
              label={i.live_access_approved ? 'Approved' : 'Not approved'}
            />
          </dd>
        </div>
      </dl>

      <div className="detail-layout">
        <div className="stack">
          <Health instance={i} />
          <RunHistory runs={runs} />
          <ConfigurationForm
            key={i.version}
            instance={i}
            saved={saved}
            onSaved={async () => {
              setSaved(true)
              await refresh()
            }}
          />
        </div>
        <div className="detail-layout__side">
          {i.has_adapter && <LiveAccessPanel instance={i} onChanged={refresh} />}
          {i.has_adapter && Boolean(i.connector?.permissions.length) && <Permissions instance={i} />}
          {i.has_adapter && <Capabilities instance={i} />}
        </div>
      </div>
    </div>
  )
}

function gateMessage(i: IntegrationInstance): string | null {
  if (!i.live_integrations_enabled) {
    return `Live integrations are disabled for this deployment (ITAM_ALLOW_LIVE_INTEGRATIONS). Nothing will contact ${i.source.name} until an operator enables them on the host.`
  }
  if (!i.live_access_approved) return 'Record live-access approval before the first connection.'
  if (!i.is_enabled) return 'The integration is disabled.'
  if (!i.base_url) return 'Set the base URL before synchronising.'
  if (missingSettings(i).length) return `Set the ${missingSettings(i).join(' and ')} before synchronising.`
  if (i.credential_status !== 'configured') return 'The credential is not available to the server.'
  return null
}

const SETTING_LABEL: Record<string, string> = {
  tenant_id: 'tenant ID',
  client_id: 'application (client) ID',
}

function missingSettings(i: IntegrationInstance): string[] {
  return (i.connector?.required_settings ?? [])
    .filter((key) => !i[key as 'tenant_id' | 'client_id'])
    .map((key) => SETTING_LABEL[key] ?? key)
}

function Health({ instance: i }: { instance: IntegrationInstance }) {
  const run = i.last_run
  const active = run && ACTIVE.includes(run.status)
  return (
    <section className="panel" aria-labelledby="health-heading">
      <h2 className="section-title" id="health-heading">
        Health
      </h2>
      {active && run && (
        <div className="run-progress" role="status">
          <p>
            {RUN_PHASE[run.phase] ?? run.phase}
            {run.devices_total > 0 && ` · ${run.devices_processed} of ${run.devices_total} devices`}
          </p>
          <progress
            max={run.devices_total || 1}
            value={run.devices_total ? run.devices_processed : undefined}
            aria-label="Synchronisation progress"
          />
        </div>
      )}
      {i.last_error && <p className="field__error">Last error: {i.last_error}</p>}
      <dl className="meta-grid meta-grid--two">
        <div className="meta-grid__pair">
          <dt>Last successful sync</dt>
          <dd>{formatDateTime(i.last_success_at)}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Next scheduled sync</dt>
          <dd>{i.next_sync_at ? formatDateTime(i.next_sync_at) : 'Not scheduled'}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Devices discovered</dt>
          <dd>{run ? run.devices_total : '—'}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Assets matched</dt>
          <dd>
            {i.active_links}
            {i.stale_links > 0 && ` (${i.stale_links} stale)`}
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>New candidates</dt>
          <dd>
            {i.open_candidates > 0 ? (
              <Link to={`/discovery?instance=${i.id}`}>{i.open_candidates} awaiting review</Link>
            ) : (
              0
            )}
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Errors / warnings</dt>
          <dd>{run ? `${run.errors} / ${run.warnings} in last run` : '—'}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Consecutive failures</dt>
          <dd>{i.consecutive_failures}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>{i.source.name} version</dt>
          <dd>{i.source_software_version || 'Unknown (run a connection test)'}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Last connection test</dt>
          <dd>
            {formatDateTime(i.last_test_at)}
            {i.last_test_message && <span className="cell-secondary">{i.last_test_message}</span>}
          </dd>
        </div>
        {i.connector?.supports_evidence && (
          <div className="meta-grid__pair">
            <dt>Last FDB/neighbour pass</dt>
            <dd>{formatDateTime(i.last_evidence_at)}</dd>
          </div>
        )}
      </dl>
    </section>
  )
}

function RunHistory({ runs }: { runs: UseQueryResult<Paginated<SyncRun>> }) {
  return (
    <section className="panel panel--flush" aria-labelledby="history-heading" aria-live="polite">
      <h2 className="section-title section-title--inset" id="history-heading">
        Sync history
      </h2>
      {runs.isPending && <LoadingState label="Loading sync history…" />}
      {runs.isError && <QueryErrorState error={runs.error} what="sync history" />}
      {runs.data && runs.data.items.length === 0 && <EmptyState title="No sync runs yet." />}
      {runs.data && runs.data.items.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Started</th>
              <th scope="col">Trigger</th>
              <th scope="col">Result</th>
              <th scope="col">Devices</th>
              <th scope="col">New candidates</th>
              <th scope="col">Stale</th>
              <th scope="col">Errors / warnings</th>
              <th scope="col">API requests</th>
            </tr>
          </thead>
          <tbody>
            {runs.data.items.map((run) => (
              <tr key={run.id}>
                <td className="nowrap">
                  {formatDateTime(run.started_at)}
                  <span className="cell-secondary">{run.mode === 'full' ? 'Full' : 'Incremental'}</span>
                </td>
                <td>{run.triggered_by}</td>
                <td>
                  <StatusBadge tone={RUN_STATUS[run.status].tone} label={RUN_STATUS[run.status].label} />
                  {ACTIVE.includes(run.status) && (
                    <span className="cell-secondary">{RUN_PHASE[run.phase] ?? run.phase}</span>
                  )}
                  {run.error_message && <span className="cell-secondary">{run.error_message}</span>}
                </td>
                <td>
                  {run.devices_processed} / {run.devices_total}
                  <span className="cell-secondary">{run.devices_enriched} re-read</span>
                </td>
                <td>{run.candidates_opened}</td>
                <td>{run.links_marked_stale}</td>
                <td>
                  {run.errors} / {run.warnings}
                  {[...run.error_samples, ...run.warning_samples].length > 0 && (
                    <details className="cell-secondary">
                      <summary>Details</summary>
                      <ul className="plain-list">
                        {run.error_samples.map((s, n) => (
                          <li key={`e${n}`}>
                            {s.external_id ? `Device ${String(s.external_id)}: ` : ''}
                            {String(s.error)}
                          </li>
                        ))}
                        {run.warning_samples.map((s, n) => (
                          <li key={`w${n}`}>
                            {s.external_id ? `Device ${String(s.external_id)}: ` : ''}
                            {String(s.warning)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </td>
                <td>{run.api_requests}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function LiveAccessPanel({ instance: i, onChanged }: { instance: IntegrationInstance; onChanged: () => Promise<void> }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string[] | undefined>()
  const mutation = useMutation({
    mutationFn: () => setLiveAccess(i.id, !i.live_access_approved, reason.trim()),
    onSuccess: async () => {
      setReason('')
      await onChanged()
    },
  })
  const server = isApiError(mutation.error) ? mutation.error.fieldErrors.reason : undefined

  return (
    <section className="panel" aria-labelledby="live-heading">
      <h2 className="section-title" id="live-heading">
        Live access
      </h2>
      {i.live_access_approved ? (
        <dl className="meta-grid meta-grid--stacked">
          <dt>Approved by</dt>
          <dd>{i.live_access_approved_by ?? 'Unknown'}</dd>
          <dt>Approved</dt>
          <dd>{formatDateTime(i.live_access_approved_at)}</dd>
          <dt>Reason</dt>
          <dd>{i.live_access_reason}</dd>
        </dl>
      ) : (
        <p className="field__help">
          No request reaches {i.source.name} until access is approved here and live integrations are enabled on
          the host. {(PROFILES[i.source.code] ?? GENERIC).accountHint ?? `Use a read-only ${i.source.name} API account.`}
        </p>
      )}
      <TextAreaField
        label={i.live_access_approved ? 'Reason for revoking' : 'Approval reference'}
        name="live_reason"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        error={error ?? server}
        help={i.live_access_approved ? undefined : 'For example the change or approval ticket.'}
      />
      {mutation.error && !server && <p className="field__error">{mutation.error.message}</p>}
      <div className="form-actions">
        <Button
          variant={i.live_access_approved ? 'danger' : 'primary'}
          busy={mutation.isPending}
          onClick={() => {
            if (reason.trim().length < 5) {
              setError(['Enter at least 5 characters.'])
              return
            }
            setError(undefined)
            mutation.mutate()
          }}
        >
          {i.live_access_approved ? 'Revoke live access' : 'Approve live access'}
        </Button>
      </div>
    </section>
  )
}

function Permissions({ instance: i }: { instance: IntegrationInstance }) {
  const excess = i.capabilities.excess_permissions === true
  return (
    <section className="panel" aria-labelledby="perm-heading">
      <h2 className="section-title" id="perm-heading">
        Required permissions
      </h2>
      <ul className="plain-list">
        {(i.connector?.permissions ?? []).map((name) => (
          <li key={name} className="mono">
            {name}
          </li>
        ))}
      </ul>
      <p className="field__help">
        Application permission with admin consent. Do not grant write, device-action or privileged permissions: the
        connector only reads.
      </p>
      {excess && (
        <p className="inline-note inline-note--warning" role="status">
          The last connection test found write or privileged permissions on the app registration. Remove them; see
          the connection test message for the list.
        </p>
      )}
    </section>
  )
}

function Capabilities({ instance: i }: { instance: IntegrationInstance }) {
  const entries = Object.entries(i.capabilities).filter(([key]) => !HIDDEN_CAPABILITIES.has(key))
  return (
    <section className="panel" aria-labelledby="caps-heading">
      <h2 className="section-title" id="caps-heading">
        API capabilities
      </h2>
      {entries.length === 0 ? (
        <p className="field__help">Detected on the first connection test or sync.</p>
      ) : (
        <ul className="plain-list">
          {entries.map(([key, available]) => (
            <li key={key}>
              <StatusBadge tone={available ? 'success' : 'neutral'} label={available ? 'Available' : 'Not available'} />{' '}
              {CAPABILITY_LABEL[key] ?? key}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const TENANT = /^([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|([a-z0-9-]{1,63}\.)+[a-z]{2,63})$/i

const NUMBER_RULES: Record<string, [number, number, string]> = {
  timeout_seconds: [5, 120, 'Enter 5 to 120 seconds.'],
  max_retries: [0, 6, 'Enter 0 to 6 retries.'],
  requests_per_second: [1, 20, 'Enter 1 to 20 requests per second.'],
  sync_interval_minutes: [15, 10080, 'Enter 15 to 10080 minutes.'],
  evidence_interval_hours: [1, 168, 'Enter 1 to 168 hours.'],
  enrichment_max_age_hours: [1, 720, 'Enter 1 to 720 hours.'],
}

type NumberKey = keyof typeof NUMBER_RULES

function ConfigurationForm({
  instance: i,
  saved,
  onSaved,
}: {
  instance: IntegrationInstance
  saved: boolean
  onSaved: () => Promise<void>
}) {
  const profile = PROFILES[i.source.code] ?? GENERIC
  const [baseUrl, setBaseUrl] = useState(i.base_url)
  const [credential, setCredential] = useState(i.credential_ref)
  const [scheme, setScheme] = useState(i.auth_scheme)
  const [caBundle, setCaBundle] = useState(i.ca_bundle_ref)
  const [tenantId, setTenantId] = useState(i.tenant_id)
  const [clientId, setClientId] = useState(i.client_id)
  const fixedUrl = i.connector?.fixed_base_url ?? null
  const required = new Set(i.connector?.required_settings ?? [])
  const [timezone, setTimezone] = useState(i.source_timezone)
  const [enabled, setEnabled] = useState(i.is_enabled)
  const [numbers, setNumbers] = useState<Record<NumberKey, string>>(
    () =>
      Object.fromEntries(
        Object.keys(NUMBER_RULES).map((k) => [k, String(i[k as keyof IntegrationInstance])]),
      ) as Record<NumberKey, string>,
  )
  const [client, setClient] = useState<Record<string, string[]>>({})
  const mutation = useMutation({
    mutationFn: () => {
      const body: Partial<IntegrationWrite> = {
        base_url: baseUrl.trim(),
        credential_ref: credential.trim(),
        auth_scheme: scheme,
        ca_bundle_ref: caBundle.trim(),
        ...(required.size ? { tenant_id: tenantId.trim(), client_id: clientId.trim() } : {}),
        source_timezone: timezone.trim(),
        is_enabled: enabled,
        ...Object.fromEntries(Object.entries(numbers).map(([k, v]) => [k, Number(v)])),
      }
      return updateIntegration(i.id, i.version, body)
    },
    onSuccess: onSaved,
  })
  const server = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = { ...server, ...client }
  const summary = mutation.error && !Object.keys(server).length ? mutation.error.message : null
  const numberField = (key: NumberKey, label: string, help?: string) => (
    <TextField
      label={label}
      name={key}
      inputMode="numeric"
      value={numbers[key]}
      onChange={(e) => setNumbers((current) => ({ ...current, [key]: e.target.value }))}
      error={errors[key]}
      help={help}
    />
  )

  return (
    <section className="panel" aria-labelledby="config-heading">
      <h2 className="section-title" id="config-heading">
        Configuration
      </h2>
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault()
          const errs: Record<string, string[]> = {}
          for (const [key, [min, max, message]] of Object.entries(NUMBER_RULES)) {
            const value = Number(numbers[key])
            if (!Number.isInteger(value) || value < min || value > max) errs[key] = [message]
          }
          if (baseUrl.trim() && !baseUrl.trim().startsWith('https://')) errs.base_url = ['Use an https:// URL.']
          if (required.has('tenant_id') && tenantId.trim() && !TENANT.test(tenantId.trim()))
            errs.tenant_id = ['Use the directory (tenant) ID GUID or a verified domain.']
          if (required.has('client_id') && clientId.trim() && !GUID.test(clientId.trim()))
            errs.client_id = ['Use the application (client) ID GUID.']
          setClient(errs)
          if (!Object.keys(errs).length) mutation.mutate()
        }}
      >
        {summary && <p className="field__error">{summary}</p>}
        <h3 className="subsection-title">Connection</h3>
        {/* Profile texts are per source; unknown sources get generic wording. */}
        {fixedUrl ? (
          <p className="field__help">
            Endpoint: <span className="mono">{fixedUrl}</span> (fixed). {profile.api}
          </p>
        ) : (
          <TextField
            label="Base URL"
            name="cfg_url"
            className="field__control mono"
            placeholder={profile.url}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            error={errors.base_url}
            help={`HTTPS with a valid certificate. ${profile.api}`}
          />
        )}
        {required.size > 0 && (
          <div className="form-grid">
            <TextField
              label="Tenant ID"
              name="cfg_tenant"
              className="field__control mono"
              placeholder="00000000-0000-0000-0000-000000000000"
              value={tenantId}
              onChange={(e) => setTenantId(e.target.value)}
              error={errors.tenant_id}
              help="Directory (tenant) ID or verified domain of the Microsoft Entra tenant."
            />
            <TextField
              label="Application (client) ID"
              name="cfg_client"
              className="field__control mono"
              placeholder="00000000-0000-0000-0000-000000000000"
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              error={errors.client_id}
              help="From the app registration's overview page."
            />
          </div>
        )}
        <div className="form-grid">
          <TextField
            label={profile.credentialLabel ?? 'API token reference'}
            name="cfg_credential"
            className="field__control mono"
            placeholder={profile.token}
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
            error={errors.credential_ref}
            help={
              profile.credentialHelp ??
              'env:ITAM_INTEGRATION_<NAME> or file:<name> in the server secrets directory. The token itself is never entered or shown here.'
            }
          />
          <SelectField
            label={profile.schemeLabel ?? 'Authentication header'}
            name="cfg_scheme"
            options={(i.connector?.auth_schemes ?? [i.auth_scheme]).map((value) => ({
              value,
              label: AUTH_LABEL[value] ?? value,
            }))}
            value={scheme}
            onChange={(e) => setScheme(e.target.value as IntegrationInstance['auth_scheme'])}
            error={errors.auth_scheme}
            help={profile.schemeHelp}
          />
        </div>
        <TextField
          label="Private CA bundle (optional)"
          name="cfg_ca"
          className="field__control mono"
          placeholder="file:librenms-ca.pem"
          value={caBundle}
          onChange={(e) => setCaBundle(e.target.value)}
          error={errors.ca_bundle_ref}
          help={`Only needed when ${i.source.name} uses an internal CA. Certificate validation cannot be turned off.`}
        />
        <div className="form-grid">
          {numberField('timeout_seconds', 'Timeout (seconds)')}
          {numberField('max_retries', 'Retries')}
          {numberField('requests_per_second', 'Requests per second', `Rate limit towards ${i.source.name}.`)}
        </div>
        <h3 className="subsection-title">Schedule</h3>
        <div className="form-grid">
          {numberField('sync_interval_minutes', 'Sync every (minutes)')}
          {i.connector?.supports_evidence && numberField('evidence_interval_hours', 'FDB/neighbours every (hours)')}
          {(i.connector?.uses_detail_refresh ?? true) &&
            numberField('enrichment_max_age_hours', 'Re-read device details after (hours)')}
        </div>
        {(i.connector?.uses_source_timezone ?? true) && (
          <TextField
            label="Source server time zone"
            name="cfg_tz"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            error={errors.source_timezone}
            help="Used for times the source reports without a zone; for example UTC or Europe/Nicosia."
          />
        )}
        <CheckboxGroup
          legend="State"
          name="cfg_enabled"
          options={[{ value: 'enabled', label: 'Enabled', description: 'Disabled integrations are never scheduled.' }]}
          value={enabled ? ['enabled'] : []}
          onChange={(v) => setEnabled(v.includes('enabled'))}
        />
        {saved && !mutation.isPending && (
          <p className="inline-success" role="status">
            Configuration saved.
          </p>
        )}
        <div className="form-actions">
          <Button type="submit" variant="primary" busy={mutation.isPending}>
            Save configuration
          </Button>
        </div>
      </form>
    </section>
  )
}
