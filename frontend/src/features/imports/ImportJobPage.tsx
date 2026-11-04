import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { isApiError } from '../../shared/api/client'
import {
  commitImport,
  errorsUrl,
  fetchImport,
  fetchImportRows,
  fetchTemplates,
  importKeys,
  previewImport,
  rollbackImport,
  templateUrl,
  updateImport,
  uploadImport,
  type ImportMode,
} from '../../shared/api/imports'
import type { ImportJob, ImportTemplate } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { PageHeader } from '../../shared/ui/PageHeader'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { ReasonDialog } from '../discovery/ReasonDialog'
import { ACTION, FAMILY_LABEL, JOB_STATUS, MODE, RESULT } from './labels'

const STEPS = ['Choose file', 'Map columns', 'Check rows', 'Import']

function Steps({ current }: { current: number }) {
  return (
    <ol className="wizard-steps" aria-label="Import steps">
      {STEPS.map((label, n) => (
        <li key={label} className={n === current ? 'wizard-steps__item wizard-steps__item--current' : 'wizard-steps__item'}
          aria-current={n === current ? 'step' : undefined}>
          {n + 1}. {label}
        </li>
      ))}
    </ol>
  )
}

/** docs/08 §10 import wizard: template → upload → map → preview → confirm → background. */
export function ImportJobPage() {
  const { id } = useParams()
  return id ? <ExistingJob id={id} /> : <NewImport />
}

// --- Step 1: family, template and file ------------------------------------------------------------

function NewImport() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const templates = useQuery({ queryKey: importKeys.templates, queryFn: fetchTemplates })
  const [family, setFamily] = useState(params.get('family') ?? 'asset')
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const upload = useMutation({
    mutationFn: () => uploadImport(family, file!),
    onSuccess: (job) => navigate(`/imports/${job.id}`, { replace: true }),
  })
  const chosen = templates.data?.find((t) => t.code === family)
  const serverError = isApiError(upload.error)
    ? Object.values(upload.error.fieldErrors).flat().join(' ') || upload.error.message
    : null
  return (
    <div className="page">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/imports">Imports</Link>
      </nav>
      <PageHeader title="New import" />
      <Steps current={0} />
      {templates.isPending && <LoadingState label="Loading templates…" />}
      {templates.isError && <QueryErrorState error={templates.error} what="import templates" />}
      {templates.data && (
        <form
          className="panel form-stack"
          onSubmit={(e) => {
            e.preventDefault()
            if (!file) return setError('Choose a .csv or .xlsx file.')
            setError(null)
            upload.mutate()
          }}
        >
          <fieldset className="fieldset">
            <legend className="field__label">What are you importing?</legend>
            <div className="radio-list">
              {templates.data.map((t) => (
                <label key={t.code} className="radio">
                  <input
                    type="radio"
                    name="family"
                    value={t.code}
                    checked={family === t.code}
                    disabled={!t.allowed}
                    onChange={() => setFamily(t.code)}
                  />
                  {t.label}
                  <span className="field__help">{t.allowed ? t.description : 'You do not have permission to import these.'}</span>
                </label>
              ))}
            </div>
          </fieldset>
          {chosen && <TemplateHelp template={chosen} />}
          <div className="field">
            <label className="field__label" htmlFor="import_file">
              File
            </label>
            <input
              id="import_file"
              className="field__control"
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <p className="field__help">CSV (UTF-8 or Windows-1252) or XLSX, up to 5 MB and 10,000 rows.</p>
          </div>
          {(error || serverError) && <p className="field__error">{error ?? serverError}</p>}
          <div className="form-actions">
            <Button type="submit" variant="primary" busy={upload.isPending} disabled={!chosen?.allowed}>
              Upload and continue
            </Button>
          </div>
        </form>
      )}
    </div>
  )
}

function TemplateHelp({ template }: { template: ImportTemplate }) {
  return (
    <section aria-label={`${template.label} template`} className="template-help">
      <p>
        Template version {template.version}.{' '}
        <a href={templateUrl(template.code)} download>
          Download the CSV template
        </a>
        . {template.match_help}
      </p>
      <ul className="plain-list">
        {template.columns.map((c) => (
          <li key={c.name}>
            <span className="mono">{c.name}</span>
            {c.required === 'always' && ' (required)'}
            {c.required === 'create' && ' (required for new records)'}
            {c.required === 'match' && ' (match key)'}
            {c.help && <span className="cell-secondary">{c.help}</span>}
          </li>
        ))}
        {template.custom_columns && (
          <li>
            <span className="mono">cf.&lt;key&gt;</span>
            <span className="cell-secondary">Custom fields of the category, for example cf.battery_model.</span>
          </li>
        )}
      </ul>
    </section>
  )
}

// --- Steps 2–4 ------------------------------------------------------------------------------------

function ExistingJob({ id }: { id: string }) {
  const job = useQuery({
    queryKey: importKeys.job(id),
    queryFn: () => fetchImport(id),
    refetchInterval: (q) => (q.state.data && ['previewing', 'committing'].includes(q.state.data.status) ? 2000 : false),
  })
  if (job.isPending) return <LoadingState label="Loading import…" />
  if (job.isError)
    return (
      <div className="page">
        <QueryErrorState error={job.error} what="this import" />
      </div>
    )
  const j = job.data
  const step = j.status === 'uploaded' ? 1 : j.status === 'previewed' || j.status === 'previewing' ? 2 : 3
  return (
    <div className="page page--wide">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/imports">Imports</Link>
      </nav>
      <PageHeader
        title={j.filename}
        meta={`${FAMILY_LABEL[j.family] ?? j.family} · ${j.row_count} rows · ${j.file_format.toUpperCase()}${j.encoding ? ` (${j.encoding})` : ''}`}
        actions={<StatusBadge tone={JOB_STATUS[j.status].tone} label={JOB_STATUS[j.status].label} />}
      />
      <Steps current={step} />
      {j.warnings.map((w) => (
        <p key={w} className="inline-note inline-note--warning">
          {w}
        </p>
      ))}
      {j.error_message && <p className="field__error">{j.error_message}</p>}
      {j.status === 'uploaded' && <Mapping job={j} />}
      {j.status === 'previewing' && <LoadingState label="Checking every row…" />}
      {j.status === 'previewed' && <Preview job={j} />}
      {j.status === 'committing' && (
        <div className="run-progress" role="status">
          <p>
            Importing · {j.progress} of {j.row_count} rows
          </p>
          <progress max={j.row_count || 1} value={j.progress} aria-label="Import progress" />
        </div>
      )}
      {['completed', 'rolled_back', 'failed'].includes(j.status) && <Receipt job={j} />}
    </div>
  )
}

function Mapping({ job }: { job: ImportJob }) {
  const queryClient = useQueryClient()
  const templates = useQuery({ queryKey: importKeys.templates, queryFn: fetchTemplates })
  const template = templates.data?.find((t) => t.code === job.family)
  const [mapping, setMapping] = useState<Record<string, string>>(job.mapping)
  const [mode, setMode] = useState<ImportMode>(job.mode)
  const check = useMutation({
    mutationFn: async () => {
      const updated = await updateImport(job.id, job.version, { mapping, mode })
      return previewImport(updated.id, updated.version)
    },
    onSuccess: (updated) => queryClient.setQueryData(importKeys.job(job.id), updated),
  })
  const fieldErrors = isApiError(check.error) ? check.error.fieldErrors : {}
  if (!template) return <LoadingState label="Loading template…" />
  const options = [
    { value: '', label: 'Ignore this column' },
    ...template.columns.map((c) => ({ value: c.name, label: `${c.label} (${c.name})` })),
    ...Object.values(mapping)
      .filter((v) => v.startsWith('cf.'))
      .map((v) => ({ value: v, label: `Custom field ${v.slice(3)}` })),
  ]
  return (
    <section className="panel" aria-labelledby="mapping-heading">
      <h2 className="section-title" id="mapping-heading">
        Map columns
      </h2>
      {check.error && (
        <ErrorSummary
          message={Object.keys(fieldErrors).length ? 'Check the mapping.' : check.error.message}
          fieldErrors={fieldErrors}
          fieldLabels={{ mapping: 'Mapping' }}
        />
      )}
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Column in your file</th>
            <th scope="col">Imports into</th>
            <th scope="col">First values</th>
          </tr>
        </thead>
        <tbody>
          {job.headers.map((header, n) => (
            <tr key={header}>
              <td className="mono">{header}</td>
              <td>
                <select
                  className="field__control"
                  aria-label={`Field for column ${header}`}
                  value={mapping[header] ?? ''}
                  onChange={(e) => setMapping((m) => ({ ...m, [header]: e.target.value }))}
                >
                  {options.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </td>
              <td className="cell-secondary">
                {job.sample
                  .map((row) => row[n])
                  .filter(Boolean)
                  .slice(0, 3)
                  .join(' · ')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <fieldset className="fieldset">
        <legend className="field__label">How should matching records be handled?</legend>
        <div className="radio-list">
          {Object.entries(MODE).map(([value, m]) => (
            <label key={value} className="radio">
              <input type="radio" name="mode" checked={mode === value} onChange={() => setMode(value as ImportMode)} />
              {m.label}
              <span className="field__help">{m.help}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="form-actions">
        <Button variant="primary" busy={check.isPending} onClick={() => check.mutate()}>
          Check rows (dry run)
        </Button>
      </div>
    </section>
  )
}

function Totals({ totals }: { totals: Record<string, number> }) {
  return (
    <dl className="status-strip" aria-label="Dry-run totals">
      {(['create', 'update', 'skip', 'conflict', 'error'] as const).map((a) => (
        <div key={a}>
          <dt>{ACTION[a].label}</dt>
          <dd>{totals[a] ?? 0}</dd>
        </div>
      ))}
    </dl>
  )
}

function Preview({ job }: { job: ImportJob }) {
  const queryClient = useQueryClient()
  const [key] = useState(() => crypto.randomUUID())
  const totals = job.totals as Record<string, number>
  const changes = (totals.create ?? 0) + (totals.update ?? 0)
  const commit = useMutation({
    mutationFn: () => commitImport(job.id, job.version, key),
    onSuccess: (updated) => {
      queryClient.setQueryData(importKeys.job(job.id), updated)
      queryClient.invalidateQueries({ queryKey: importKeys.list })
    },
  })
  const back = useMutation({
    mutationFn: () => updateImport(job.id, job.version, {}),
    onSuccess: (updated) => queryClient.setQueryData(importKeys.job(job.id), updated),
  })
  return (
    <>
      <section className="panel" aria-labelledby="preview-heading">
        <h2 className="section-title" id="preview-heading">
          Dry run · {MODE[job.mode].label}
        </h2>
        <Totals totals={totals} />
        <p className="field__help">
          Nothing has changed yet. Conflicts and errors are never imported;{' '}
          <a href={errorsUrl(job.id)} download>
            download the rows that will not be imported
          </a>
          .
        </p>
        {commit.error && <p className="field__error">{commit.error.message}</p>}
        <div className="form-actions">
          <Button variant="quiet" busy={back.isPending} onClick={() => back.mutate()}>
            Change mapping or mode
          </Button>
          <Button variant="primary" busy={commit.isPending} disabled={changes === 0} onClick={() => commit.mutate()}>
            Import {changes} {changes === 1 ? 'row' : 'rows'}
          </Button>
        </div>
      </section>
      <Rows job={job} />
    </>
  )
}

function Rows({ job }: { job: ImportJob }) {
  const [action, setAction] = useState('')
  const rows = useInfiniteQuery({
    queryKey: importKeys.rows(job.id, `${action}:${job.version}`),
    queryFn: ({ pageParam }) => fetchImportRows(job.id, action, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = rows.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section className="panel panel--flush" aria-label="Rows" aria-live="polite">
      <div className="toolbar toolbar--inset">
        <div className="field">
          <label className="field__label" htmlFor="row_action">
            Show
          </label>
          <select id="row_action" className="field__control" value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All rows</option>
            {Object.entries(ACTION).map(([value, a]) => (
              <option key={value} value={value}>
                {a.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      {rows.isPending && <LoadingState label="Loading rows…" />}
      {items.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col" className="num">
                Row
              </th>
              <th scope="col">Action</th>
              <th scope="col">Record</th>
              <th scope="col">Details</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={r.row_number}>
                <td className="num">{r.row_number}</td>
                <td>
                  <StatusBadge tone={ACTION[r.action].tone} label={ACTION[r.action].label} />
                  {r.result && <span className="cell-secondary">{RESULT[r.result] ?? r.result}</span>}
                </td>
                <td>
                  {r.target_label || <span className="cell-muted">New</span>}
                  {r.key && <span className="cell-secondary mono">{r.key}</span>}
                </td>
                <td>
                  {r.messages.join(' ')}
                  {r.result_message && r.result !== 'skipped' && <span className="cell-secondary">{r.result_message}</span>}
                  {Object.keys(r.changes).length > 0 && r.action === 'update' && (
                    <span className="cell-secondary">
                      {Object.entries(r.changes as Record<string, { before: unknown; after: unknown }>)
                        .map(([f, c]) => `${f}: ${String(c.before ?? '—')} → ${String(c.after ?? '—')}`)
                        .join('; ')}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {rows.hasNextPage && (
        <div className="table-footer">
          <Button onClick={() => rows.fetchNextPage()} busy={rows.isFetchingNextPage}>
            Load more
          </Button>
        </div>
      )}
    </section>
  )
}

function Receipt({ job }: { job: ImportJob }) {
  const queryClient = useQueryClient()
  const [rollingBack, setRollingBack] = useState(false)
  const totals = job.totals as { result?: Record<string, number>; rollback?: Record<string, number> }
  const rollback = useMutation({
    mutationFn: (reason: string) => rollbackImport(job.id, job.version, reason),
    onSuccess: (updated) => {
      setRollingBack(false)
      queryClient.setQueryData(importKeys.job(job.id), updated)
      queryClient.invalidateQueries({ queryKey: ['imports', 'rows', job.id] })
    },
  })
  return (
    <>
      <section className="panel" aria-labelledby="receipt-heading">
        <h2 className="section-title" id="receipt-heading">
          Receipt
        </h2>
        {totals.result && (
          <dl className="status-strip" aria-label="Import results">
            <div>
              <dt>Applied</dt>
              <dd>{totals.result.applied}</dd>
            </div>
            <div>
              <dt>Not applied</dt>
              <dd>{totals.result.skipped}</dd>
            </div>
            <div>
              <dt>Failed</dt>
              <dd>{totals.result.failed}</dd>
            </div>
          </dl>
        )}
        <dl className="meta-grid meta-grid--two">
          <div className="meta-grid__pair">
            <dt>Imported by</dt>
            <dd>
              {job.committed_by ?? '—'} · {formatDateTime(job.committed_at)}
            </dd>
          </div>
          <div className="meta-grid__pair">
            <dt>File checksum (SHA-256)</dt>
            <dd className="mono">{job.checksum.slice(0, 16)}…</dd>
          </div>
          <div className="meta-grid__pair">
            <dt>Original file</dt>
            <dd>{job.file_retained ? `Kept encrypted until ${formatDateTime(job.purge_after)}` : 'Deleted after retention'}</dd>
          </div>
          {totals.rollback && (
            <div className="meta-grid__pair">
              <dt>Rollback</dt>
              <dd>
                {totals.rollback.rolled_back} rolled back, {totals.rollback.needs_correction} changed since and need
                correction by hand
              </dd>
            </div>
          )}
        </dl>
        <div className="form-actions">
          <a className="button button--quiet" href={errorsUrl(job.id)} download>
            Download rows not applied
          </a>
          {job.status === 'completed' && (
            <Button variant="danger" onClick={() => setRollingBack(true)}>
              Roll back…
            </Button>
          )}
        </div>
      </section>
      <Rows job={job} />
      {rollingBack && (
        <ReasonDialog
          title="Roll back this import?"
          confirmLabel="Roll back"
          help="Records created by the import are archived and updated records get their previous values back, unless someone changed them afterwards; those are listed for correction by hand."
          busy={rollback.isPending}
          error={rollback.error ? rollback.error.message : null}
          onClose={() => setRollingBack(false)}
          onConfirm={(reason) => rollback.mutate(reason)}
        />
      )}
    </>
  )
}
