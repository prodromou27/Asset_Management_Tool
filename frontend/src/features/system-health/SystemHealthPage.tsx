import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { fetchOutboxStats, notificationKeys } from '../../shared/api/notifications'
import { PERMISSIONS } from '../../shared/api/types'
import { fetchReadiness } from '../../shared/api/health'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { OperationalDiagnostics } from './OperationalDiagnostics'

export function SystemHealthPage() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['health', 'ready'],
    queryFn: fetchReadiness,
    retry: false,
  })

  const dependencies = Object.entries(data?.dependencies ?? {})

  return (
    <div className="page">
      <PageHeader
        title="System health"
        meta={
          data
            ? data.status === 'ok'
              ? 'All required dependencies are reachable.'
              : 'One or more required dependencies are down.'
            : 'API and dependency readiness for this environment.'
        }
      />

      <section className="panel" aria-live="polite">
        {isPending && <LoadingState label="Checking dependency status…" />}
        {isError && <QueryErrorState error={error} what="dependency status" />}
        {data && dependencies.length === 0 && <EmptyState title="No dependencies reported." />}
        {dependencies.length > 0 && (
          <ul className="dependency-list">
            {dependencies.map(([name, dependency]) => (
              <li key={name} className="dependency-list__row">
                <div>
                  <div className="dependency-list__name">{name}</div>
                  {dependency.detail && (
                    <div className="dependency-list__detail">{dependency.detail}</div>
                  )}
                </div>
                <StatusBadge
                  tone={dependency.status === 'up' ? 'success' : 'danger'}
                  label={dependency.status}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
      <MailDelivery />
      <OperationalDiagnostics />
    </div>
  )
}

/** Mail delivery health (docs/14: alert on notification queue backlog). Not part of
 * readiness: a mail outage must not mark the application down. */
function MailDelivery() {
  const { can } = useSession()
  const allowed = can(PERMISSIONS.notificationsView)
  const stats = useQuery({ queryKey: notificationKeys.stats, queryFn: fetchOutboxStats, enabled: allowed })
  if (!allowed || !stats.data) return null
  const s = stats.data
  const tone = s.problems.length ? 'danger' : !s.enabled ? 'warning' : 'success'
  const label = s.problems.length ? 'Needs attention' : !s.configured ? 'Setup incomplete' : s.enabled ? 'OK' : 'Disabled'
  return (
    <section className="panel" aria-label="Mail delivery">
      <ul className="dependency-list">
        <li className="dependency-list__row">
          <div>
            <div className="dependency-list__name">
              <Link to="/admin/smtp?tab=queue">Mail delivery</Link>
            </div>
            <div className="dependency-list__detail">
              {s.problems.length
                ? s.problems.join(' ')
                : `${s.counts.queued + s.counts.retrying} waiting, ${s.counts.sent} sent.`}
            </div>
          </div>
          <StatusBadge tone={tone} label={label} />
        </li>
      </ul>
    </section>
  )
}
