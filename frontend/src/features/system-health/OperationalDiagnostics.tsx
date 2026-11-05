import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { fetchOperationalHealth, type OperationalHealth } from '../../shared/api/health'
import { PERMISSIONS } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge, type StatusTone } from '../../shared/ui/StatusBadge'

const LABELS = {
  up: 'Recorded OK', down: 'Failed', unknown: 'Unknown',
  disabled: 'Disabled', needs_attention: 'Needs attention',
} as const
type Check = OperationalHealth['components'][number]
const TONES: Record<Check['status'], StatusTone> = {
  up: 'success', down: 'danger', unknown: 'neutral', disabled: 'neutral', needs_attention: 'warning',
}
const LINK_PERMISSIONS = [
  ['/admin/integrations', PERMISSIONS.integrationsManage],
  ['/admin/backups', PERMISSIONS.backupsView],
  ['/admin/smtp', PERMISSIONS.notificationsView],
  ['/admin/users', PERMISSIONS.usersView],
  ['/admin/security', PERMISSIONS.securityView],
  ['/lifecycle', PERMISSIONS.lifecycleView],
] as const

export function OperationalDiagnostics() {
  const { can } = useSession()
  const client = useQueryClient()
  const allowed = can(PERMISSIONS.healthView)
  const query = useQuery({ queryKey: ['health', 'operations'], queryFn: fetchOperationalHealth, enabled: allowed, retry: false })
  if (!allowed) return null
  if (query.isPending) return <LoadingState label="Loading operational diagnostics…" />
  if (query.error) return <QueryErrorState error={query.error} what="operational diagnostics" />
  const data = query.data
  function checks(title: string, rows: Check[]) {
    return <section className="panel panel--flush" aria-label={title}>
      <div className="section-header section-header--inset"><h2 className="section-title">{title}</h2></div>
      {!rows.length ? <p className="state">No recorded data.</p> : <div className="table-scroll"><table className="data-table" aria-label={title}>
        <thead><tr><th>Check</th><th>State</th><th>Evidence and next action</th></tr></thead>
        <tbody>{rows.map((row) => {
          const permission = LINK_PERMISSIONS.find(([prefix]) => row.href.startsWith(prefix))?.[1]
          return (
            <tr key={row.id}>
              <td>{permission && can(permission) ? <Link to={row.href}>{row.label}</Link> : row.label}</td>
              <td><StatusBadge tone={TONES[row.status]} label={LABELS[row.status]} /></td>
              <td>{row.detail}</td>
            </tr>
          )
        })}</tbody>
      </table></div>}
    </section>
  }
  return <>
    <section className="panel" aria-label="Production readiness">
      <div className="section-header"><h2 className="section-title">Production readiness</h2><StatusBadge tone="warning" label="Incomplete" /><Button busy={query.isFetching} onClick={() => { void client.invalidateQueries({ queryKey: ['health'] }) }}>Refresh diagnostics</Button></div>
      <p>Checked {formatDateTime(data.checked_at)}. Infrastructure reachability is separate from production acceptance. Unknown checks require target-host verification; disabled sources do not imply a successful sync.</p>
    </section>
    {checks('Operational services', data.components)}
    {checks('Integration health', data.integrations)}
    <section className="panel panel--flush" aria-label="Durable jobs">
      <div className="section-header section-header--inset"><h2 className="section-title">Durable jobs</h2></div>
      <p className="field__help panel__note">Stored job states, not broker depth or worker heartbeats. Failed totals include historical failures.</p>
      <div className="table-scroll"><table className="data-table" aria-label="Durable jobs"><thead><tr><th>Job family</th><th className="num">Queued</th><th className="num">Running</th><th className="num">Failed</th><th>Worker health</th></tr></thead><tbody>{data.queues.map((queue) => <tr key={queue.name}><td>{queue.name}</td><td className="num">{queue.queued}</td><td className="num">{queue.running}</td><td className="num">{queue.failed}</td><td>Unknown</td></tr>)}</tbody></table></div>
    </section>
    {checks('First-run checklist', data.checklist)}
  </>
}
