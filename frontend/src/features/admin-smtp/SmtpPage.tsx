import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { isApiError } from '../../shared/api/client'
import {
  cancelMessage,
  fetchOutbox,
  fetchOutboxStats,
  fetchSmtp,
  fetchTemplates,
  notificationKeys,
  previewTemplate,
  retryMessage,
  sendTestEmail,
  testSmtp,
  updateSmtp,
  updateTemplate,
} from '../../shared/api/notifications'
import { PERMISSIONS, type NotificationTemplate, type SmtpProfile, type TemplatePreview } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge, type StatusTone } from '../../shared/ui/StatusBadge'
import { Tabs } from '../../shared/ui/Tabs'

const OUTBOX_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  queued: { label: 'Queued', tone: 'neutral' },
  sending: { label: 'Sending', tone: 'neutral' },
  retrying: { label: 'Waiting to retry', tone: 'warning' },
  sent: { label: 'Sent', tone: 'success' },
  dead: { label: 'Failed', tone: 'danger' },
  cancelled: { label: 'Cancelled', tone: 'neutral' },
  expired: { label: 'Expired', tone: 'warning' },
}

const SECURITY = [
  { value: 'starttls', label: 'STARTTLS (port 587)' },
  { value: 'tls', label: 'Implicit TLS (port 465)' },
  { value: 'none', label: 'None (internal relay, no sign-in)' },
]

const PASSWORD_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  not_set: { label: 'No password', tone: 'neutral' },
  configured: { label: 'Password available', tone: 'success' },
  missing: { label: 'Reference not found on the server', tone: 'danger' },
  invalid: { label: 'Invalid reference', tone: 'danger' },
}

export function SmtpPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') ?? 'settings'
  return (
    <div className="page page--wide">
      <PageHeader
        title="SMTP & notifications"
        meta="Outgoing mail settings, message templates and the delivery queue."
      />
      <DeliveryAlert />
      <Tabs
        label="SMTP and notification sections"
        selected={tab}
        onSelect={(next) => {
          const search = new URLSearchParams(params)
          if (next === 'settings') search.delete('tab')
          else search.set('tab', next)
          setParams(search, { replace: true })
        }}
        tabs={[
          { id: 'settings', label: 'Settings', content: <Settings /> },
          { id: 'templates', label: 'Templates', content: <Templates /> },
          { id: 'queue', label: 'Delivery queue', content: <Queue /> },
        ]}
      />
    </div>
  )
}

/** Operational alert: failed or long-waiting mail (docs/10 production gate). */
export function DeliveryAlert() {
  const stats = useQuery({ queryKey: notificationKeys.stats, queryFn: fetchOutboxStats })
  if (!stats.data || stats.data.problems.length === 0) return null
  return (
    <div className="error-summary" role="alert">
      <p className="error-summary__title">Mail delivery needs attention</p>
      <ul className="error-summary__list">
        {stats.data.problems.map((p) => (
          <li key={p}>{p}</li>
        ))}
      </ul>
    </div>
  )
}

// --- Settings -------------------------------------------------------------------------------

type Draft = {
  host: string
  port: string
  security: string
  username: string
  password_ref: string
  ca_bundle_ref: string
  from_address: string
  from_name: string
  reply_to: string
  timeout_seconds: string
  max_per_minute: string
}

const toDraft = (p: SmtpProfile): Draft => ({
  host: p.host,
  port: String(p.port),
  security: p.security,
  username: p.username,
  password_ref: p.password_ref,
  ca_bundle_ref: p.ca_bundle_ref,
  from_address: p.from_address,
  from_name: p.from_name,
  reply_to: p.reply_to,
  timeout_seconds: String(p.timeout_seconds),
  max_per_minute: String(p.max_per_minute),
})

function Settings() {
  const profile = useQuery({ queryKey: notificationKeys.smtp, queryFn: fetchSmtp })
  if (profile.isPending) return <LoadingState label="Loading mail settings…" />
  if (profile.isError) return <QueryErrorState error={profile.error} what="mail settings" />
  return <SettingsForm key={profile.data.version} current={profile.data} />
}

function SettingsForm({ current }: { current: SmtpProfile }) {
  const { can, me } = useSession()
  const manage = can(PERMISSIONS.notificationsManage)
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>(() => toDraft(current))
  const [notice, setNotice] = useState<string | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: notificationKeys.all })
  const set = (key: keyof Draft) => (e: { target: { value: string } }) =>
    setDraft((d) => ({ ...d, [key]: e.target.value }))
  const save = useMutation({
    mutationFn: (extra: { enabled?: boolean }) =>
      updateSmtp(current.version, {
        ...draft,
        port: Number(draft.port) || 587,
        timeout_seconds: Number(draft.timeout_seconds) || 15,
        max_per_minute: Number(draft.max_per_minute) || 60,
        security: draft.security as SmtpProfile['security'],
        ...extra,
      }),
    onSuccess: async (_, extra) => {
      setNotice(
        extra.enabled === true ? 'Mail enabled.' : extra.enabled === false ? 'Mail disabled.' : 'Settings saved.',
      )
      await refresh()
    },
  })
  const test = useMutation({
    mutationFn: testSmtp,
    onSuccess: (saved) => queryClient.setQueryData(notificationKeys.smtp, saved),
  })
  const sendTest = useMutation({ mutationFn: sendTestEmail, onSuccess: refresh })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(current))
  const configured = Boolean(current.host && current.from_address)
  const pw = PASSWORD_STATUS[current.password_status] ?? PASSWORD_STATUS.invalid

  function submit(event: FormEvent) {
    event.preventDefault()
    setNotice(null)
    save.mutate({})
  }

  return (
    <section className="panel" aria-label="Mail settings">
      <dl className="kpi-strip" aria-label="Mail status">
        <div className="kpi-strip__item">
          <dt>Mail</dt>
          <dd>
            {current.enabled ? (
              <StatusBadge tone="success" label="Enabled" />
            ) : (
              <StatusBadge
                tone={configured ? 'neutral' : 'warning'}
                label={configured ? 'Disabled' : 'Setup incomplete'}
              />
            )}
          </dd>
        </div>
        <div className="kpi-strip__item">
          <dt>Last connection test</dt>
          <dd>
            {current.last_test_at ? (
              <StatusBadge
                tone={current.last_test_ok ? 'success' : 'danger'}
                label={`${current.last_test_ok ? 'Passed' : 'Failed'} ${formatDateTime(current.last_test_at)}`}
              />
            ) : (
              <span className="cell-muted">Not tested</span>
            )}
          </dd>
        </div>
        <div className="kpi-strip__item">
          <dt>Last test message</dt>
          <dd>
            {current.last_test_email_at ? (
              formatDateTime(current.last_test_email_at)
            ) : (
              <span className="cell-muted">None</span>
            )}
          </dd>
        </div>
        <div className="kpi-strip__item">
          <dt>Password</dt>
          <dd>
            <StatusBadge tone={pw.tone} label={pw.label} />
          </dd>
        </div>
      </dl>
      {current.last_test_ok === false && current.last_test_error && (
        <p className="field__error" role="alert">
          Connection test: {current.last_test_error}
        </p>
      )}
      {notice && (
        <p className="inline-success" role="status">
          {notice}
        </p>
      )}
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ host: 'Host', security: 'Security', password_ref: 'Password reference', enabled: 'Mail' }}
        />
      )}
      <form onSubmit={submit} noValidate className="form-stack">
        <fieldset className="settings-group" disabled={!manage}>
          <legend className="section-title">Server</legend>
          <div className="form-grid">
            <TextField
              label="Host"
              name="smtp-host"
              value={draft.host}
              onChange={set('host')}
              error={errors.host}
              help="Host name or IP of the approved relay."
            />
            <TextField
              label="Port"
              name="smtp-port"
              type="number"
              min={1}
              max={65535}
              value={draft.port}
              onChange={set('port')}
              error={errors.port}
            />
            <SelectField
              label="Security"
              name="smtp-security"
              value={draft.security}
              onChange={set('security')}
              options={SECURITY}
              error={errors.security}
              help="Encryption is never dropped: if STARTTLS is not offered, sending stops."
            />
            <TextField
              label="CA bundle (optional)"
              name="smtp-ca"
              value={draft.ca_bundle_ref}
              onChange={set('ca_bundle_ref')}
              error={errors.ca_bundle_ref}
              help="file:<name> in the server's secrets directory, for an internal CA. Empty: system CAs."
            />
          </div>
        </fieldset>
        <fieldset className="settings-group" disabled={!manage}>
          <legend className="section-title">Sign-in</legend>
          <div className="form-grid">
            <TextField
              label="Username (optional)"
              name="smtp-user"
              value={draft.username}
              onChange={set('username')}
              error={errors.username}
              autoComplete="off"
            />
            <TextField
              label="Password reference"
              name="smtp-password-ref"
              value={draft.password_ref}
              onChange={set('password_ref')}
              error={errors.password_ref}
              autoComplete="off"
              help="env:ITAM_SMTP_PASSWORD or file:<name>. The password itself is set on the server, never here."
            />
          </div>
        </fieldset>
        <fieldset className="settings-group" disabled={!manage}>
          <legend className="section-title">Sender</legend>
          <div className="form-grid">
            <TextField
              label="From address"
              name="smtp-from"
              type="email"
              value={draft.from_address}
              onChange={set('from_address')}
              error={errors.from_address}
            />
            <TextField label="From name" name="smtp-from-name" value={draft.from_name} onChange={set('from_name')} />
            <TextField
              label="Reply-To (optional)"
              name="smtp-reply"
              type="email"
              value={draft.reply_to}
              onChange={set('reply_to')}
              error={errors.reply_to}
            />
          </div>
        </fieldset>
        <fieldset className="settings-group" disabled={!manage}>
          <legend className="section-title">Delivery</legend>
          <div className="form-grid">
            <TextField
              label="Timeout (seconds)"
              name="smtp-timeout"
              type="number"
              min={3}
              max={120}
              value={draft.timeout_seconds}
              onChange={set('timeout_seconds')}
              error={errors.timeout_seconds}
            />
            <TextField
              label="Messages per minute"
              name="smtp-rate"
              type="number"
              min={1}
              max={1000}
              value={draft.max_per_minute}
              onChange={set('max_per_minute')}
              error={errors.max_per_minute}
            />
          </div>
        </fieldset>
        {manage && (
          <div className="form-actions">
            <Button type="submit" variant="primary" busy={save.isPending} disabled={!dirty}>
              Save
            </Button>
            {current.enabled ? (
              <Button variant="danger" onClick={() => save.mutate({ enabled: false })} disabled={dirty}>
                Disable mail
              </Button>
            ) : (
              <Button onClick={() => save.mutate({ enabled: true })} disabled={dirty || !configured}>
                Enable mail
              </Button>
            )}
            <Button onClick={() => test.mutate()} busy={test.isPending} disabled={dirty || !configured}>
              Test connection
            </Button>
            <Button
              onClick={() => sendTest.mutate()}
              busy={sendTest.isPending}
              disabled={dirty || !current.enabled || !me?.email}
            >
              Send test email
            </Button>
          </div>
        )}
        {manage && (
          <p className="field__help">
            Test connection signs in without sending. The test email goes only to you
            {me?.email ? ` (${me.email})` : ' (your account has no e-mail address)'}.
          </p>
        )}
        {test.isError && <p className="field__error">{test.error.message}</p>}
        {sendTest.isError && <p className="field__error">{sendTest.error.message}</p>}
        {sendTest.data && (
          <p className={sendTest.data.status === 'sent' ? 'inline-success' : 'field__error'} role="status">
            {sendTest.data.status === 'sent'
              ? `Test message sent to ${sendTest.data.to_address}.`
              : `Test message not sent: ${sendTest.data.last_error || OUTBOX_STATUS[sendTest.data.status].label}`}
          </p>
        )}
      </form>
    </section>
  )
}

// --- Templates ------------------------------------------------------------------------------

function Templates() {
  const templates = useQuery({ queryKey: notificationKeys.templates, queryFn: fetchTemplates })
  const [selected, setSelected] = useState<string | null>(null)
  if (templates.isPending) return <LoadingState label="Loading templates…" />
  if (templates.isError) return <QueryErrorState error={templates.error} what="templates" />
  const current = templates.data.find((t) => t.code === selected) ?? templates.data[0]
  if (!current) return <EmptyState title="No templates." />
  return (
    <div className="template-layout">
      <ul className="plain-list" aria-label="Templates">
        {templates.data.map((t) => (
          <li key={t.code}>
            <Button variant={t.code === current.code ? 'secondary' : 'quiet'} onClick={() => setSelected(t.code)}>
              {t.name}
            </Button>
          </li>
        ))}
      </ul>
      <TemplateEditor key={`${current.code}:${current.version}`} template={current} />
    </div>
  )
}

function TemplateEditor({ template }: { template: NotificationTemplate }) {
  const { can } = useSession()
  const manage = can(PERMISSIONS.notificationsManage)
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState({
    subject: template.subject,
    body_text: template.body_text,
    body_html: template.body_html,
  })
  const [preview, setPreview] = useState<TemplatePreview | null>(null)
  const set = (key: keyof typeof draft) => (e: { target: { value: string } }) =>
    setDraft((d) => ({ ...d, [key]: e.target.value }))
  const render = useMutation({ mutationFn: () => previewTemplate(template.code, draft), onSuccess: setPreview })
  const save = useMutation({
    mutationFn: () => updateTemplate(template.code, template.version, draft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: notificationKeys.templates }),
  })
  const error = save.error ?? render.error
  const errors = isApiError(error) ? error.fieldErrors : {}
  return (
    <section className="panel" aria-label={`Template ${template.name}`}>
      <h2 className="section-title">{template.name}</h2>
      <p className="field__help">
        {template.description} Version {template.version}
        {template.modified_by && `, last changed by ${template.modified_by}`}.
      </p>
      {template.variables.length > 0 && (
        <p className="field__help">
          Values:{' '}
          {template.variables.map((v, i) => (
            <span key={v.name}>
              {i > 0 && ', '}
              <code>{`{{ ${v.name} }}`}</code> {v.description}
            </span>
          ))}
          . Values are escaped; tags are limited to if, for and with.
        </p>
      )}
      {error && (
        <ErrorSummary
          message={error.message}
          fieldErrors={errors}
          fieldLabels={{ subject: 'Subject', body_text: 'Plain text', body_html: 'HTML' }}
        />
      )}
      <fieldset className="form-stack plain-fieldset" disabled={!manage}>
        <TextField
          label="Subject"
          name="tpl-subject"
          value={draft.subject}
          onChange={set('subject')}
          error={errors.subject}
        />
        <TextAreaField
          label="Plain text"
          name="tpl-text"
          value={draft.body_text}
          onChange={set('body_text')}
          rows={8}
          className="mono"
          error={errors.body_text}
        />
        <TextAreaField
          label="HTML (optional)"
          name="tpl-html"
          value={draft.body_html}
          onChange={set('body_html')}
          rows={8}
          className="mono"
          error={errors.body_html}
        />
      </fieldset>
      <div className="form-actions">
        <Button onClick={() => render.mutate()} busy={render.isPending}>
          Preview
        </Button>
        {manage && (
          <Button variant="primary" onClick={() => save.mutate()} busy={save.isPending}>
            Save template
          </Button>
        )}
      </div>
      {preview && (
        <div className="template-preview" aria-label="Preview">
          <p>
            <strong>Subject:</strong> {preview.subject}
          </p>
          <pre className="mono pre-wrap">{preview.body_text}</pre>
          {preview.body_html && (
            <iframe title="HTML preview" sandbox="" srcDoc={preview.body_html} className="template-preview__html" />
          )}
        </div>
      )}
    </section>
  )
}

// --- Queue ----------------------------------------------------------------------------------

function Queue() {
  const { can } = useSession()
  const manage = can(PERMISSIONS.notificationsManage)
  const queryClient = useQueryClient()
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const filters = { status: status || undefined, q: q || undefined }
  const rows = useInfiniteQuery({
    queryKey: notificationKeys.outbox(filters),
    queryFn: ({ pageParam }) => fetchOutbox(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: notificationKeys.all })
  const retry = useMutation({ mutationFn: retryMessage, onSuccess: refresh })
  const cancel = useMutation({ mutationFn: cancelMessage, onSuccess: refresh })
  const items = rows.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <section aria-label="Delivery queue">
      <div className="toolbar">
        <TextField
          label="Search"
          name="outbox-q"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          help="Recipient or subject."
        />
        <SelectField
          label="Status"
          name="outbox-status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { value: '', label: 'Any' },
            { value: 'queued,retrying,sending', label: 'Waiting' },
            { value: 'dead', label: 'Failed' },
            { value: 'sent', label: 'Sent' },
            { value: 'expired,cancelled', label: 'Expired or cancelled' },
          ]}
        />
      </div>
      {(retry.isError || cancel.isError) && <p className="field__error">{(retry.error ?? cancel.error)?.message}</p>}
      <div className="panel panel--flush" aria-live="polite">
        {rows.isPending && <LoadingState label="Loading the queue…" />}
        {rows.isError && <QueryErrorState error={rows.error} what="the delivery queue" />}
        {rows.isSuccess && items.length === 0 && <EmptyState title="No messages." />}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Messages</caption>
            <thead>
              <tr>
                <th scope="col">Message</th>
                <th scope="col">Recipient</th>
                <th scope="col">Status</th>
                <th scope="col">Queued</th>
                {manage && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((m) => {
                const s = OUTBOX_STATUS[m.status]
                return (
                  <tr key={m.id}>
                    <td>
                      {m.subject}
                      <span className="cell-secondary">
                        {m.template_code} v{m.template_version}
                        {m.message_id && ` · ${m.message_id}`}
                      </span>
                    </td>
                    <td>{m.to_address}</td>
                    <td>
                      <StatusBadge tone={s.tone} label={s.label} />
                      <span className="cell-secondary">
                        {m.attempts} of {m.max_attempts} attempts
                        {m.status === 'retrying' && ` · next ${formatDateTime(m.next_attempt_at)}`}
                        {m.sent_at && ` · sent ${formatDateTime(m.sent_at)}`}
                      </span>
                      {m.last_error && <span className="cell-secondary">{m.last_error}</span>}
                    </td>
                    <td>{formatDateTime(m.queued_at)}</td>
                    {manage && (
                      <td>
                        <div className="cell-actions">
                          {['dead', 'expired', 'cancelled'].includes(m.status) && (
                            <Button variant="quiet" onClick={() => retry.mutate(m.id)}>
                              Retry
                            </Button>
                          )}
                          {['queued', 'retrying'].includes(m.status) && (
                            <Button variant="quiet" onClick={() => cancel.mutate(m.id)}>
                              Cancel
                            </Button>
                          )}
                        </div>
                      </td>
                    )}
                  </tr>
                )
              })}
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
      </div>
    </section>
  )
}
