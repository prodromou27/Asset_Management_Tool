import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSession } from '../../app/useSession'
import * as api from '../../shared/api/backups'
import { PERMISSIONS } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { Drawer } from '../../shared/ui/Drawer'
import { isApiError } from '../../shared/api/client'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'

const date = (value?: string | null) => value ? new Date(value).toLocaleString() : 'Not recorded'

export function BackupsPage() {
  const { can } = useSession()
  const manage = can(PERMISSIONS.backupsManage)
  const client = useQueryClient()
  const policy = useQuery({ queryKey: ['backups', 'policy'], queryFn: api.getBackupPolicy })
  const summary = useQuery({ queryKey: ['backups', 'summary'], queryFn: api.getBackupSummary, refetchInterval: 10000 })
  const jobs = useQuery({ queryKey: ['backups', 'jobs'], queryFn: api.getBackupJobs, refetchInterval: 10000 })
  const drills = useQuery({ queryKey: ['backups', 'drills'], queryFn: api.getRestoreDrills })
  const [editing, setEditing] = useState<api.BackupPolicy | null>(null)
  const [recording, setRecording] = useState(false)
  const [selected, setSelected] = useState<api.BackupJob | null>(null)
  const [action, setAction] = useState<string | null>(null)
  const [confirmation, setConfirmation] = useState<'backup' | string | null>(null)
  const refresh = () => client.invalidateQueries({ queryKey: ['backups'] })
  const operation = useMutation({
    mutationFn: (id: string) => id === 'backup' ? api.requestBackup() : api.verifyBackup(id),
    onSuccess: () => { setConfirmation(null); setAction('Operation queued. Follow its progress in the job history.'); void refresh() },
  })
  const save = useMutation({
    mutationFn: (p: api.BackupPolicy) => api.saveBackupPolicy(p, p.version),
    onSuccess: () => { setEditing(null); setAction('Backup policy saved.'); void refresh() },
  })
  const busy = jobs.data?.some((job) => ['queued', 'running'].includes(job.status)) ?? false
  const allowed = summary.data?.execution_allowed ?? false
  const error = policy.error || summary.error || jobs.error || drills.error
  if (error) return <QueryErrorState error={error} what="backups and recovery" />
  if (!policy.data || !summary.data || !jobs.data || !drills.data) return <LoadingState label="Loading backups and recovery…" />
  const p = policy.data
  const s = summary.data

  return (
    <div className="page">
      <PageHeader title="Backups & Recovery" meta="Verified recovery points, backup policy and isolated restore drills." actions={<>
        <a className="button" href="/api/v1/backups/report/">Download summary</a>
        {manage && <Button onClick={() => setEditing({ ...p })}>Edit policy</Button>}
        {manage && <Button variant="primary" disabled={!allowed || busy} onClick={() => setConfirmation('backup')}>Back up now</Button>}
      </>} />
      {action && <p className="state" role="status">{action}</p>}
      {s.problems.length > 0 && <div className="state state--warning" role="status"><p className="state__title">Recovery readiness needs attention</p><ul>{s.problems.map((problem) => <li key={problem}>{problem}</li>)}</ul></div>}
      <section className="panel" aria-label="Backup policy">
        <dl className="detail-grid">
          <div><dt>Schedule</dt><dd>{p.enabled ? `Nightly at ${String(p.hour_utc).padStart(2, '0')}:00 UTC` : 'Disabled'}</dd></div>
          <div><dt>Destination</dt><dd>{s.target_label}</dd></div>
          <div><dt>Recovery objectives</dt><dd>RPO {p.rpo_hours}h / RTO {p.rto_hours}h (validate by drill)</dd></div>
          <div><dt>Retention</dt><dd>{p.retention_enabled ? `${p.keep_daily} daily / ${p.keep_weekly} weekly / ${p.keep_monthly} monthly` : 'Automatic deletion disabled'}</dd></div>
          <div><dt>Last verified recovery point</dt><dd>{date(s.last_backup?.recovery_point)}</dd></div>
          <div><dt>Last verification</dt><dd>{s.last_verification ? `${date(s.last_verification.finished_at)} · ${s.last_verification.verification_result}` : 'Not recorded'}</dd></div>
          <div><dt>Last restore drill</dt><dd>{s.last_drill ? `${date(s.last_drill.finished_at)} · ${s.last_drill.passed ? 'Passed (operator recorded)' : 'Failed'}` : 'Not recorded'}</dd></div>
        </dl>
        <p className="muted">{s.encryption}. {s.off_host}.</p>
      </section>
      <h2 className="section-title">Job history</h2>
      {jobs.data.length === 0 ? (
        <EmptyState title="No backup jobs yet.">
          Provision an approved off-host repository and recovery key, then enable the backup worker.
        </EmptyState>
      ) : (
        <JobTable jobs={jobs.data} manage={manage} disabled={!allowed || busy} onVerify={setConfirmation} onDetails={setSelected} />
      )}
      <section className="panel">
        <div className="page-header">
          <h2 className="section-title">Isolated restore drills</h2>
          {manage && (
            <Button disabled={!jobs.data.some((j) => j.kind === 'backup' && j.status === 'succeeded')}
              onClick={() => setRecording(true)}>Record drill</Button>
          )}
        </div>
        <p>Restore into a new, network-isolated PostgreSQL container with the operator runbook in <code>ops/restore/README.md</code>. Confirm row counts, evidence, audit and encrypted-file recovery before recording the result.</p>
        {drills.data.length === 0 ? (
          <p className="muted">No isolated restore drill recorded.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Finished</th><th>Isolated target</th><th>Result</th><th>Duration</th><th>Notes</th><th>Report</th></tr></thead>
              <tbody>
                {drills.data.map((drill) => (
                  <tr key={drill.id}>
                    <td>{date(drill.finished_at)}</td>
                    <td>{drill.target_label}</td>
                    <td>{drill.passed ? 'Passed (operator recorded)' : 'Failed'}</td>
                    <td>{duration(drill.duration_seconds)}</td>
                    <td>{drill.notes}</td>
                    <td><a href={`/api/v1/backups/drills/${drill.id}/report/`}>Download JSON</a></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <Dialog open={confirmation !== null} title={confirmation === 'backup' ? 'Create encrypted backup' : 'Verify backup'} confirmLabel="Queue operation" busy={operation.isPending} onClose={() => { setConfirmation(null); operation.reset() }} onConfirm={() => confirmation && operation.mutate(confirmation)}>
        <p>{confirmation === 'backup' ? 'Create a consistent database backup and verify its encrypted off-host copy.' : 'Read back the selected backup and verify its database checksum and repository integrity.'} This may take several minutes.</p>
        {operation.error && <p role="alert">{operation.error.message}</p>}
      </Dialog>
      <Dialog open={editing !== null} title="Backup policy" confirmLabel="Save policy" busy={save.isPending} onClose={() => { setEditing(null); save.reset() }} onConfirm={() => editing && save.mutate(editing)}>
        {editing && <div className="form-grid">
          <label className="checkbox"><input type="checkbox" checked={editing.enabled} disabled={!allowed} onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })} />Enable nightly backups</label>
          {POLICY_FIELDS.map(({ key, label, max }) => (
            <TextField key={key} name={key} label={label} type="number"
              value={editing[key]} min={key === 'hour_utc' ? 0 : 1} max={max}
              onChange={(e) => setEditing({ ...editing, [key]: Number(e.target.value) })} />
          ))}
          <label className="checkbox"><input type="checkbox" checked={editing.retention_enabled} onChange={(e) => setEditing({ ...editing, retention_enabled: e.target.checked })} />Apply retention after a verified backup (deletes older ITAM snapshots)</label>
        </div>}
        {save.error && <ErrorSummary message={save.error.message} fieldErrors={isApiError(save.error) ? save.error.fieldErrors : {}} fieldLabels={POLICY_LABELS} />}
      </Dialog>
      {recording && <DrillDialog jobs={jobs.data.filter((j) => j.kind === 'backup' && j.status === 'succeeded')} close={() => setRecording(false)} done={() => { setRecording(false); void refresh() }} />}
      <Drawer open={selected !== null} title="Backup job details" onClose={() => setSelected(null)}>
        {selected && <>
          <dl className="detail-grid">
            <div><dt>Status</dt><dd>{selected.status}</dd></div>
            <div><dt>Verification</dt><dd>{selected.verification_result}</dd></div>
            <div><dt>Destination</dt><dd>{selected.target_label}</dd></div>
            <div><dt>Started</dt><dd>{date(selected.started_at)}</dd></div>
            <div><dt>Finished</dt><dd>{date(selected.finished_at)}</dd></div>
            <div><dt>Duration</dt><dd>{duration(selected.duration_seconds)}</dd></div>
            <div><dt>Recovery point</dt><dd>{date(selected.recovery_point)}</dd></div>
          </dl>
          {(selected.error_message || selected.warning) && <p role="status">{selected.error_message || selected.warning}</p>}
          <a className="button" href={`/api/v1/backups/jobs/${selected.id}/report/`}>Download job report</a>
          <h3>Capture manifest</h3>
          <pre className="pre-wrap">{JSON.stringify(selected.manifest, null, 2)}</pre>
        </>}
      </Drawer>
    </div>
  )
}

function JobTable({ jobs, manage, disabled, onVerify, onDetails }: {
  jobs: api.BackupJob[]
  manage: boolean
  disabled: boolean
  onVerify: (id: string) => void
  onDetails: (job: api.BackupJob) => void
}) {
  const labels = { succeeded: 'Verified', failed: 'Failed', running: 'Running', queued: 'Queued' }
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Requested</th><th>Operation</th><th>Status</th><th>Recovery point</th>
            <th>Size</th><th>Details</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td>{date(job.created_at)}</td>
              <td>{job.kind === 'backup' ? 'Backup' : 'Verify'}</td>
              <td>
                <Button onClick={() => onDetails(job)}>View details</Button>
                <StatusBadge label={labels[job.status]}
                  tone={job.status === 'succeeded' ? 'success' : job.status === 'failed' ? 'danger' : 'neutral'} />
              </td>
              <td>{date(job.recovery_point)}</td>
              <td>{job.size_bytes ? `${(job.size_bytes / 1048576).toFixed(1)} MB` : '—'}</td>
              <td>
                {job.error_message || job.warning || (job.snapshot_id
                  ? <code title={job.snapshot_id}>{job.snapshot_id.slice(0, 12)}</code>
                  : 'Awaiting worker')}
              </td>
              <td>
                {manage && job.kind === 'backup' && job.status === 'succeeded' && (
                  <Button disabled={disabled} onClick={() => onVerify(job.id)}>Verify backup</Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DrillDialog({ jobs, close, done }: { jobs: api.BackupJob[]; close: () => void; done: () => void }) {
  const [backup, setBackup] = useState(jobs[0]?.id ?? '')
  const [target, setTarget] = useState('')
  const [start, setStart] = useState('')
  const [finish, setFinish] = useState('')
  const [notes, setNotes] = useState('')
  const [passed, setPassed] = useState(false)
  const [isolated, setIsolated] = useState(false)
  const [outbound, setOutbound] = useState(false)
  const [error, setError] = useState('')
  const mutation = useMutation({ mutationFn: api.recordDrill, onSuccess: done })
  function submit() {
    if (!backup || !target.trim() || !notes.trim() || !start || !finish || !isolated || !outbound) { setError('Complete all fields and confirm isolation and disabled outgoing actions.'); return }
    mutation.mutate({ backup, target_label: target.trim(), started_at: new Date(start).toISOString(), finished_at: new Date(finish).toISOString(), notes, passed, isolated, outbound_disabled: outbound })
  }
  return <Dialog open title="Record isolated restore drill" confirmLabel="Record result" busy={mutation.isPending} onClose={close} onConfirm={submit}>
    <div className="form-grid">
      <SelectField name="backup" label="Verified backup" value={backup}
        onChange={(e) => setBackup(e.target.value)}
        options={jobs.map((j) => ({ value: j.id, label: `${date(j.recovery_point)} · ${j.snapshot_id.slice(0, 12)}` }))} />
      <TextField name="target" label="Isolated target label" value={target}
        maxLength={120} onChange={(e) => setTarget(e.target.value)} />
      <TextField name="start" label="Started (local time)" type="datetime-local"
        value={start} onChange={(e) => setStart(e.target.value)} />
      <TextField name="finish" label="Finished (local time)" type="datetime-local"
        value={finish} onChange={(e) => setFinish(e.target.value)} />
      <TextAreaField name="notes" label="Recovery checks and notes" value={notes}
        maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
      <label className="checkbox"><input type="checkbox" checked={passed} onChange={(e) => setPassed(e.target.checked)} />All recovery checks passed</label>
      <label className="checkbox"><input type="checkbox" checked={isolated} onChange={(e) => setIsolated(e.target.checked)} />Used a new isolated target</label>
      <label className="checkbox"><input type="checkbox" checked={outbound} onChange={(e) => setOutbound(e.target.checked)} />Outgoing mail and integrations were disabled</label>
    </div>
    {(error || mutation.error) && <ErrorSummary message={error || mutation.error?.message || 'Could not record drill.'} fieldErrors={isApiError(mutation.error) ? mutation.error.fieldErrors : {}} fieldLabels={{ target_label: 'Isolated target', started_at: 'Started', finished_at: 'Finished', notes: 'Recovery checks' }} />}
  </Dialog>
}

const POLICY_FIELDS = [
  { key: 'hour_utc', label: 'Backup hour (UTC, 0–23)', max: 23 },
  { key: 'rpo_hours', label: 'RPO objective (hours)', max: 168 },
  { key: 'rto_hours', label: 'RTO objective (hours)', max: 168 },
  { key: 'keep_daily', label: 'Daily snapshots', max: 365 },
  { key: 'keep_weekly', label: 'Weekly snapshots', max: 104 },
  { key: 'keep_monthly', label: 'Monthly snapshots', max: 120 },
] as const
const POLICY_LABELS = Object.fromEntries(POLICY_FIELDS.map(({ key, label }) => [key, label]))

function duration(seconds?: number | null) {
  return seconds == null ? 'Not recorded' : `${seconds.toFixed(1)} seconds`
}
