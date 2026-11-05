import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { fetchSites } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import { fetchGroups } from '../../shared/api/groups'
import * as api from '../../shared/api/reports'
import { PERMISSIONS } from '../../shared/api/types'
import { formatDate, formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { DeniedState, EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { ExportDialog } from '../exports/ExportDialog'

const REPORTS = [
  { value: 'inventory', label: 'Inventory breakdown', permission: 'assets.view' },
  { value: 'lifecycle', label: 'Lifecycle evidence', permission: 'lifecycle.view' },
  { value: 'coverage', label: 'Observed source coverage', permission: 'discovery.view' },
  { value: 'groups', label: 'Group replacement and ownership', permission: 'groups.view' },
] as const
const HIDDEN = new Set(['id', 'assessment_id', 'product_id', 'milestone_ids'])

export function ReportsPage() {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const scheduleId = params.get('schedule')
  const selected = params.get('report') ?? 'inventory'
  const kind = (REPORTS.some((report) => report.value === selected) ? selected : 'inventory') as api.ReportKind
  const filters = Object.fromEntries(['site', 'group', 'q', 'breakdown', 'dimension', 'status', 'coverage'].flatMap((key) => params.get(key) ? [[key, params.get(key)!]] : []))
  const offsetValue = Number(params.get('offset') ?? '0')
  const offset = Number.isInteger(offsetValue) && offsetValue >= 0 ? offsetValue : 0
  function setOffset(value: number) {
    const next = new URLSearchParams(params)
    next.set('offset', String(value))
    setParams(next, { replace: true })
  }
  const [exporting, setExporting] = useState(false)
  const [scheduling, setScheduling] = useState(false)
  const sites = useQuery({ queryKey: ['assets', 'sites'], queryFn: fetchSites })
  const groups = useQuery({ queryKey: ['groups', 'list'], queryFn: fetchGroups, enabled: can(PERMISSIONS.groupsView) })
  const report = useQuery({ queryKey: ['reports', kind, filters, offset], queryFn: () => api.fetchReport(kind, filters, offset), enabled: !scheduleId })
  const linked = useQuery({ queryKey: ['report-schedule', scheduleId], queryFn: () => api.fetchSchedule(scheduleId!), enabled: !!scheduleId && can(PERMISSIONS.reportsSchedule) })
  useEffect(() => {
    if (!linked.data) return
    setParams({ report: linked.data.report, ...linked.data.filters }, { replace: true })
  }, [linked.data, setParams])
  if (scheduleId && !can(PERMISSIONS.reportsSchedule)) return <DeniedState what="scheduled reports" />
  if (scheduleId && linked.error) return <QueryErrorState error={linked.error} what="scheduled report" />
  if (scheduleId) return <LoadingState label="Loading scheduled report filters…" />
  function change(key: string, value: string) {
    const next = new URLSearchParams(params)
    next.delete('schedule')
    if (value) next.set(key, value); else next.delete(key)
    if (key === 'report') { next.delete('dimension'); next.delete('status'); next.delete('breakdown'); next.delete('coverage') }
    next.delete('offset'); setParams(next, { replace: true })
  }
  const columns = report.data?.columns.filter((column) => !HIDDEN.has(column.key)) ?? []
  return <div className="page page--wide">
    <PageHeader title="Reports" meta="Current authorized inventory, lifecycle, source coverage and group evidence." actions={<>
      {can(PERMISSIONS.exportsRun) && <Button disabled={!report.data || report.isFetching} onClick={() => setExporting(true)}>Export report</Button>}
      {can(PERMISSIONS.reportsSchedule) && <Button disabled={!report.data} onClick={() => setScheduling(true)}>Schedule digest</Button>}
    </>} />
    <div className="toolbar">
      <SelectField label="Report" name="report" value={kind} onChange={(e) => change('report', e.target.value)} options={REPORTS.filter((entry) => can(entry.permission)).map(({ value, label }) => ({ value, label }))} />
      <SelectField label="Site" name="site" value={filters.site ?? ''} onChange={(e) => change('site', e.target.value)} options={[{ value: '', label: 'All authorized sites' }, ...(sites.data ?? []).map((site) => ({ value: site.id, label: site.name }))]} />
      {can(PERMISSIONS.groupsView) && <SelectField label="Group" name="group" value={filters.group ?? ''} onChange={(e) => change('group', e.target.value)} options={[{ value: '', label: 'All groups' }, ...(groups.data ?? []).map((group) => ({ value: group.id, label: group.name }))]} />}
      {kind === 'inventory' && <SelectField label="Break down by" name="breakdown" value={filters.breakdown ?? 'site'} onChange={(e) => change('breakdown', e.target.value)} options={[{ value: 'site', label: 'Site' }, { value: 'category', label: 'Category' }, { value: 'manufacturer', label: 'Vendor' }, ...(can(PERMISSIONS.exportsPersonal) ? [{ value: 'owner', label: 'Owner' }] : [])]} />}
      {kind === 'lifecycle' && <SelectField label="Dimension" name="dimension" value={filters.dimension ?? 'hardware'} onChange={(e) => change('dimension', e.target.value)} options={['hardware', 'os', 'firmware'].map((value) => ({ value, label: value === 'os' ? 'Operating system' : value[0].toUpperCase() + value.slice(1) }))} />}
      {kind === 'coverage' && <SelectField label="Coverage filter" name="coverage" value={filters.coverage ?? ''} onChange={(e) => change('coverage', e.target.value)} options={[{ value: '', label: 'All recorded states' }, { value: 'any_gap', label: 'Any missing active link' }, { value: 'endpoint_central_gap', label: 'No active Endpoint Central link' }, { value: 'defender_gap', label: 'No active Defender link' }]} />}
      <ReportSearch key={filters.q ?? ''} initial={filters.q ?? ''} submit={(value) => change('q', value)} />
    </div>
    {(sites.error || groups.error) && <QueryErrorState error={sites.error || groups.error} what="report filter options" />}
    {linked.error && <QueryErrorState error={linked.error} what="scheduled report" />}
    {report.isPending ? <LoadingState label="Loading report…" /> : report.error ? <QueryErrorState error={report.error} what="report" /> : report.data && <>
      <p className="field__help">{report.data.note} Generated {formatDateTime(report.data.generated_at)}. Evidence IDs are included in exports; open asset details for full evidence.</p>
      {!report.data.count ? <EmptyState title="No report rows match your current scope and filters." /> : <div className="table-scroll"><table className="data-table" aria-label="Report results">
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>{report.data.rows.map((row, index) => <tr key={String(row.id ?? index)}>{columns.map((column) => <td key={column.key}>
          {column.key === 'name' && row.id ? <Link to={kind === 'groups' ? `/groups/${row.id}` : `/assets/${row.id}`}>{String(row.name)}</Link> : cell(row[column.key], column.key)}
        </td>)}</tr>)}</tbody>
      </table></div>}
      <div className="form-actions"><span>{report.data.count} rows · {offset + (report.data.count ? 1 : 0)}–{Math.min(offset + 50, report.data.count)}</span><Button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</Button><Button disabled={offset + 50 >= report.data.count} onClick={() => setOffset(offset + 50)}>Next</Button></div>
    </>}
    <ExportDialog open={exporting} onClose={() => setExporting(false)} family={`report_${kind}`} filters={filters} />
    {scheduling && <ScheduleDialog kind={kind} filters={filters} close={() => setScheduling(false)} />}
    {can(PERMISSIONS.reportsSchedule) && <Schedules />}
  </div>
}

function ReportSearch({ initial, submit }: { initial: string; submit: (value: string) => void }) {
  const [draft, setDraft] = useState(initial)
  const search = (event: FormEvent) => { event.preventDefault(); submit(draft.trim()) }
  return <form className="report-search" onSubmit={search}>
    <TextField label="Search" name="q" type="search" maxLength={200} value={draft} onChange={(e) => setDraft(e.target.value)} />
    <Button type="submit">Search report</Button>
  </form>
}

function cell(value: unknown, key: string) {
  if (value === null || value === undefined || value === '') return 'Not recorded'
  if (key === 'date') return formatDate(String(value))
  if (key === 'assessed_at') return formatDateTime(String(value))
  if (key === 'status' || key === 'base_status') return String(value).replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

function ScheduleDialog({ kind, filters, close }: { kind: api.ReportKind; filters: Record<string, string>; close: () => void }) {
  const { me } = useSession()
  const client = useQueryClient()
  const [cadence, setCadence] = useState<'daily' | 'weekly'>('daily')
  const [hour, setHour] = useState('7')
  const [weekday, setWeekday] = useState('0')
  const mutation = useMutation({ mutationFn: () => api.createSchedule({ report: kind, filters, cadence, hour_utc: Number(hour), weekday: Number(weekday), enabled: true }), onSuccess: () => { void client.invalidateQueries({ queryKey: ['report-schedules'] }); close() } })
  return <Dialog open title="Schedule report digest" confirmLabel="Create schedule" busy={mutation.isPending} onClose={close} onConfirm={() => mutation.mutate()}>
    <p>Send one authenticated report link to your account address ({me?.email || 'No email configured'}). No inventory rows or attachments are emailed. Times are UTC; a new schedule starts at its next due slot.</p>
    <SelectField name="cadence" label="Frequency" value={cadence} onChange={(e) => setCadence(e.target.value as 'daily' | 'weekly')} options={[{ value: 'daily', label: 'Daily' }, { value: 'weekly', label: 'Weekly' }]} />
    <TextField name="hour" label="Hour (UTC)" type="number" min={0} max={23} value={hour} onChange={(e) => setHour(e.target.value)} />
    {cadence === 'weekly' && <SelectField name="weekday" label="Day" value={weekday} onChange={(e) => setWeekday(e.target.value)} options={['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map((label, value) => ({ value: String(value), label }))} />}
    {mutation.error && <ErrorSummary message={mutation.error.message} fieldErrors={isApiError(mutation.error) ? mutation.error.fieldErrors : {}} fieldLabels={{ hour_utc: 'Hour (UTC)', weekday: 'Day' }} />}
  </Dialog>
}

function Schedules() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['report-schedules'], queryFn: api.fetchSchedules })
  const update = useMutation({ mutationFn: (schedule: api.DigestSchedule) => api.updateSchedule(schedule.id, schedule.version, { enabled: !schedule.enabled }), onSuccess: () => { void client.invalidateQueries({ queryKey: ['report-schedules'] }) } })
  return <section className="panel"><h2 className="section-title">My scheduled digests</h2>
    {query.isPending && <LoadingState label="Loading schedules…" />}
    {query.error && <QueryErrorState error={query.error} what="report schedules" />}
    {update.error && <p role="alert">{update.error.message} Reload the page if the schedule changed.</p>}
    {!query.data?.length ? <p className="muted">No scheduled digests.</p> : <div className="table-scroll"><table className="data-table" aria-label="My scheduled digests"><thead><tr><th>Report</th><th>Schedule (UTC)</th><th>State</th><th>Actions</th></tr></thead><tbody>{query.data.map((schedule) => <tr key={schedule.id}>
      <td><Link to={`/reports?schedule=${schedule.id}`}>{REPORTS.find((report) => report.value === schedule.report)?.label}</Link></td><td>{schedule.cadence === 'weekly' ? ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][schedule.weekday] : 'Daily'} {String(schedule.hour_utc).padStart(2, '0')}:00</td><td>{schedule.enabled ? 'Enabled' : 'Disabled'}</td><td><Button busy={update.isPending} onClick={() => update.mutate(schedule)}>{schedule.enabled ? 'Disable' : 'Enable'}<span className="visually-hidden"> {schedule.id}</span></Button></td>
    </tr>)}</tbody></table></div>}
  </section>
}
