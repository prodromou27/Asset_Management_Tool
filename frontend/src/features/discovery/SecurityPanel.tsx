import { useQuery } from '@tanstack/react-query'
import { discoveryKeys, fetchSecurityStates } from '../../shared/api/discovery'
import type { EndpointSecurityState } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge, type StatusTone } from '../../shared/ui/StatusBadge'

// Defender for Endpoint API enum values (healthStatus, onboardingStatus, exposureLevel,
// riskScore). Unknown values are shown as reported.
const HEALTH: Record<string, [string, StatusTone]> = {
  Active: ['Active', 'success'],
  Inactive: ['Inactive', 'neutral'],
  ImpairedCommunication: ['Impaired communication', 'warning'],
  NoSensorData: ['No sensor data', 'warning'],
  NoSensorDataImpairedCommunication: ['No sensor data, impaired communication', 'warning'],
  Unknown: ['Unknown', 'neutral'],
}
const ONBOARDING: Record<string, [string, StatusTone]> = {
  Onboarded: ['Onboarded', 'success'],
  CanBeOnboarded: ['Not onboarded (can be onboarded)', 'warning'],
  Unsupported: ['Unsupported', 'neutral'],
  InsufficientInfo: ['Insufficient information', 'neutral'],
}
const LEVEL: Record<string, StatusTone> = {
  None: 'neutral',
  Informational: 'neutral',
  Low: 'success',
  Medium: 'warning',
  High: 'danger',
}

function Value({ map, value }: { map: Record<string, [string, StatusTone]>; value: string }) {
  if (!value) return <span className="cell-muted">Not reported</span>
  const [label, tone] = map[value] ?? [value, 'neutral' as StatusTone]
  return <StatusBadge tone={tone} label={label} />
}

function Level({ value }: { value: string }) {
  if (!value) return <span className="cell-muted">Not reported</span>
  return <StatusBadge tone={LEVEL[value] ?? 'neutral'} label={value} />
}

function SourceState({ s }: { s: EndpointSecurityState }) {
  return (
    <section className="panel" aria-label={`${s.instance.name} security observation`}>
      <h3 className="subsection-title">
        {s.instance.name}{' '}
        <StatusBadge
          tone={s.freshness === 'fresh' ? 'success' : 'warning'}
          label={s.freshness === 'fresh' ? 'Fresh' : 'Stale'}
        />
      </h3>
      {s.missing_since && (
        <p className="inline-note inline-note--warning">
          Not in the latest complete listing from {s.instance.name} (since {formatDateTime(s.missing_since)}). This
          does not mean the device no longer exists.
        </p>
      )}
      {s.link_status !== 'active' && (
        <p className="inline-note">The link to this source is stale; the values below may be out of date.</p>
      )}
      <dl className="meta-grid meta-grid--two">
        <div className="meta-grid__pair">
          <dt>Onboarding</dt>
          <dd>
            <Value map={ONBOARDING} value={s.onboarding_status} />
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Sensor health</dt>
          <dd>
            <Value map={HEALTH} value={s.health_status} />
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Exposure level</dt>
          <dd>
            <Level value={s.exposure_level} />
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Risk score</dt>
          <dd>
            <Level value={s.risk_score} />
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Device tags</dt>
          <dd>{s.device_tags.length ? s.device_tags.join(', ') : <span className="cell-muted">None</span>}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Device group</dt>
          <dd>{s.machine_group || <span className="cell-muted">Not reported</span>}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>First seen by {s.instance.name}</dt>
          <dd>{formatDateTime(s.first_seen_at)}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Last report received</dt>
          <dd>
            {formatDateTime(s.last_seen_at)}
            <span className="cell-secondary">When the source last received data; not a live online status.</span>
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Last synchronised</dt>
          <dd>
            {formatDateTime(s.last_synced_at)}
            <span className="cell-secondary">
              Source last succeeded {formatDateTime(s.source_last_success_at)}
            </span>
          </dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Last change</dt>
          <dd>{formatDateTime(s.changed_at)}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Machine ID</dt>
          <dd className="mono">{s.external_id}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Entra device ID</dt>
          <dd className="mono">{s.entra_device_id || <span className="cell-muted">Not reported</span>}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>DNS name</dt>
          <dd className="mono">{s.computer_dns_name || <span className="cell-muted">Not reported</span>}</dd>
        </div>
        <div className="meta-grid__pair">
          <dt>Operating system</dt>
          <dd>{[s.os_platform, s.os_version].filter(Boolean).join(' ') || 'Not reported'}</dd>
        </div>
      </dl>
      <details className="cell-secondary">
        <summary>Original source values</summary>
        <pre className="raw-payload" tabIndex={0} aria-label={`Original ${s.instance.name} values`}>
          {JSON.stringify(s.original, null, 2)}
        </pre>
      </details>
    </section>
  )
}

/** Security observations from security sources (Defender for Endpoint). Kept apart from
 * the asset's own fields: they describe what the source reports, never what the asset is. */
export function SecurityPanel({ assetId }: { assetId: string }) {
  const states = useQuery({
    queryKey: discoveryKeys.security(assetId),
    queryFn: () => fetchSecurityStates(assetId),
  })

  return (
    <div className="stack" aria-live="polite">
      <p className="field__help">
        Reported by linked security sources. These are source observations, not asset data; they never change the
        asset&apos;s fields.
      </p>
      {states.isPending && <LoadingState label="Loading security observations…" />}
      {states.isError && <QueryErrorState error={states.error} what="security observations" />}
      {states.data && states.data.length === 0 && (
        <EmptyState title="No security source is linked to this asset." />
      )}
      {states.data?.map((s) => <SourceState key={s.id} s={s} />)}
    </div>
  )
}
