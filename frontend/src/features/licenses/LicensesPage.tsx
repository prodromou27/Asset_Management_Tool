import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchSubscriptions, licenseKeys } from '../../shared/api/licenses'
import type { LicenseSubscription } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { CAPABILITY, count } from './labels'

export function LicensesPage() {
  const subscriptions = useQuery({ queryKey: licenseKeys.subscriptions, queryFn: fetchSubscriptions })

  return (
    <div className="page page--wide">
      <PageHeader title="Licenses" meta="Microsoft 365 subscriptions" />
      <p className="inline-note">
        Tenant inventory as reported by Microsoft 365: purchased and consumed units, and the users ITAM counts as
        assigned. This is not a billing agreement and not a license compliance assessment.
      </p>
      <section className="panel panel--flush" aria-label="Microsoft 365 subscriptions" aria-live="polite">
        {subscriptions.isPending && <LoadingState label="Loading subscriptions…" />}
        {subscriptions.isError && <QueryErrorState error={subscriptions.error} what="subscriptions" />}
        {subscriptions.data && subscriptions.data.length === 0 && (
          <EmptyState title="No subscriptions yet. Configure a Microsoft 365 integration to read them." />
        )}
        {subscriptions.data && subscriptions.data.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">SKU</th>
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">
                    Purchased
                  </th>
                  <th scope="col" className="num">
                    Consumed (tenant)
                  </th>
                  <th scope="col" className="num">
                    Assigned users (ITAM)
                  </th>
                  <th scope="col" className="num">
                    Available
                  </th>
                  <th scope="col">Snapshot</th>
                </tr>
              </thead>
              <tbody>
                {subscriptions.data.map((s) => (
                  <Row key={s.id} s={s} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function Row({ s }: { s: LicenseSubscription }) {
  const latest = s.latest
  const status = CAPABILITY[s.capability_status] ?? { label: s.capability_status || 'Unknown', tone: 'neutral' }
  return (
    <tr>
      <td>
        <Link to={`/licenses/subscriptions/${s.id}`}>{s.sku_part_number || s.sku_id}</Link>
        {!s.subscribed && <span className="cell-secondary">Assigned but not in the tenant&apos;s subscriptions</span>}
        {s.missing_since && (
          <span className="cell-secondary">No longer listed since {formatDateTime(s.missing_since)}</span>
        )}
      </td>
      <td>
        {s.instance.name}
        <span className="cell-secondary mono">{s.tenant_id}</span>
      </td>
      <td>
        <StatusBadge tone={status.tone} label={status.label} />
        {latest && (latest.warning_units ?? 0) + (latest.suspended_units ?? 0) > 0 && (
          <span className="cell-secondary">
            {count(latest.warning_units)} in warning, {count(latest.suspended_units)} suspended
          </span>
        )}
      </td>
      <td className="num">{count(latest?.enabled_units)}</td>
      <td className="num">{count(latest?.consumed_units)}</td>
      <td className="num">{count(latest?.assigned_users)}</td>
      <td className="num">{count(latest?.available_units)}</td>
      <td className="nowrap">
        {latest ? formatDateTime(latest.last_confirmed_at) : '—'}
        <span className="cell-secondary">
          <StatusBadge
            tone={s.freshness === 'fresh' ? 'success' : 'warning'}
            label={s.freshness === 'fresh' ? 'Fresh' : 'Stale'}
          />
        </span>
      </td>
    </tr>
  )
}
