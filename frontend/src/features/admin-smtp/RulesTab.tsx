import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSession } from '../../app/useSession'
import { assetKeys, fetchSites } from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import {
  createRule,
  deleteRule,
  fetchRecipients,
  fetchRules,
  notificationKeys,
  previewRule,
  updateRule,
} from '../../shared/api/notifications'
import { PERMISSIONS, type NotificationRule, type RulePreview } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { CheckboxGroup, SelectField, TextField } from '../../shared/ui/Field'
import { EmptyState, ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'

type Event = NotificationRule['event']

const EVENTS: Record<Event, { label: string; help: string; defaults: number[] }> = {
  certificate_expiry: {
    label: 'TLS certificate expiry',
    help: 'Certificates presented by approved endpoints, or uploaded.',
    defaults: [90, 60, 30, 14, 7],
  },
  domain_expiry: {
    label: 'Domain registration expiry',
    help: 'Only domains whose expiry was recorded with evidence; Unknown is never announced.',
    defaults: [90, 60, 30, 14, 7],
  },
  lifecycle_eol: {
    label: 'Verified end of life / support',
    help: 'Verified lifecycle milestones only. Each recipient gets assets in their own sites.',
    defaults: [365, 180, 90, 30, 7],
  },
  integration_failure: {
    label: 'Integration failures and stale syncs',
    help: 'Repeated failed runs or data older than the integration’s stale limit. Recipients need integration administration rights.',
    defaults: [],
  },
}

export function RulesTab() {
  const { can } = useSession()
  const manage = can(PERMISSIONS.notificationsManage)
  const queryClient = useQueryClient()
  const rules = useQuery({ queryKey: notificationKeys.rules, queryFn: fetchRules })
  const [editing, setEditing] = useState<NotificationRule | 'new' | null>(null)
  const [previewing, setPreviewing] = useState<NotificationRule | null>(null)
  const [deleting, setDeleting] = useState<NotificationRule | null>(null)
  const remove = useMutation({
    mutationFn: (id: string) => deleteRule(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationKeys.rules })
      setDeleting(null)
    },
  })
  return (
    <section aria-label="Notification rules">
      <p className="inline-note">
        Rules decide who is told about what. Each item is announced once per threshold and recipient; a new date or a
        new failure streak is announced again. Rules run hourly and only while mail is enabled.
      </p>
      {manage && (
        <div className="toolbar">
          <div className="toolbar__actions">
            <Button variant="primary" onClick={() => setEditing('new')}>
              New rule
            </Button>
          </div>
        </div>
      )}
      <div className="panel panel--flush" aria-live="polite">
        {rules.isPending && <LoadingState label="Loading rules…" />}
        {rules.isError && <QueryErrorState error={rules.error} what="notification rules" />}
        {rules.data && rules.data.length === 0 && (
          <EmptyState title="No notification rules.">Nobody receives alerts until a rule names recipients.</EmptyState>
        )}
        {rules.data && rules.data.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Rules</caption>
            <thead>
              <tr>
                <th scope="col">Rule</th>
                <th scope="col">When</th>
                <th scope="col">Recipients</th>
                <th scope="col">Last run</th>
                {manage && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rules.data.map((r) => (
                <tr key={r.id}>
                  <td>
                    {r.name}
                    <span className="cell-secondary">
                      {EVENTS[r.event].label}
                      {!r.enabled && ' · paused'}
                    </span>
                  </td>
                  <td>
                    {r.event === 'integration_failure'
                      ? `${r.failure_count} failed runs in a row, or stale`
                      : [
                          r.thresholds.length ? `${r.thresholds.join(', ')} days before` : '',
                          r.include_expired ? 'when expired' : '',
                        ]
                          .filter(Boolean)
                          .join('; ')}
                    {r.sites.length > 0 && (
                      <span className="cell-secondary">Sites: {r.sites.map((s) => s.code).join(', ')}</span>
                    )}
                  </td>
                  <td>
                    {r.recipients.length === 0 ? (
                      <StatusBadge tone="warning" label="No recipients" />
                    ) : (
                      r.recipients.map((u) => u.display_name || u.username).join(', ')
                    )}
                    {r.recipients.some((u) => !u.has_email) && (
                      <span className="cell-secondary">Some recipients have no e-mail address</span>
                    )}
                  </td>
                  <td>
                    {r.last_run_at ? formatDateTime(r.last_run_at) : <span className="cell-muted">Not run yet</span>}
                    {r.last_run_summary && <span className="cell-secondary">{r.last_run_summary}</span>}
                  </td>
                  {manage && (
                    <td>
                      <div className="cell-actions">
                        <Button variant="quiet" onClick={() => setPreviewing(r)}>
                          Preview
                        </Button>
                        <Button variant="quiet" onClick={() => setEditing(r)}>
                          Edit…
                        </Button>
                        <Button variant="quiet" onClick={() => setDeleting(r)}>
                          Delete…
                        </Button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {editing && <RuleDialog rule={editing === 'new' ? undefined : editing} onClose={() => setEditing(null)} />}
      {previewing && <PreviewDialog rule={previewing} onClose={() => setPreviewing(null)} />}
      {deleting && (
        <Dialog
          open
          title={`Delete ${deleting.name}`}
          confirmLabel="Delete rule"
          confirmVariant="danger"
          busy={remove.isPending}
          onClose={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id)}
        >
          <p>Its recipients stop receiving these alerts. Messages already sent stay in the delivery queue.</p>
          {remove.isError && <p className="field__error">{remove.error.message}</p>}
        </Dialog>
      )}
    </section>
  )
}

function RuleDialog({ rule, onClose }: { rule?: NotificationRule; onClose: () => void }) {
  const queryClient = useQueryClient()
  const recipients = useQuery({ queryKey: notificationKeys.recipients, queryFn: fetchRecipients })
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites })
  const [form, setForm] = useState({
    name: rule?.name ?? '',
    event: (rule?.event ?? 'certificate_expiry') as Event,
    enabled: rule?.enabled ?? true,
    thresholds: (rule?.thresholds ?? EVENTS.certificate_expiry.defaults).join(', '),
    include_expired: rule?.include_expired ?? true,
    failure_count: String(rule?.failure_count ?? 3),
    recipients: rule?.recipients.map((u) => u.id) ?? [],
    sites: rule?.sites.map((s) => s.id) ?? [],
  })
  const event = EVENTS[form.event]
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name,
        event: form.event,
        enabled: form.enabled,
        include_expired: form.include_expired,
        failure_count: Number(form.failure_count) || 3,
        thresholds: form.thresholds
          .split(/[\s,;]+/)
          .filter(Boolean)
          .map(Number),
        recipients: form.recipients,
        sites: form.event === 'lifecycle_eol' ? form.sites : [],
      }
      return rule ? updateRule(rule.id, rule.version, body) : createRule(body)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: notificationKeys.rules })
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog
      open
      title={rule ? `Edit ${rule.name}` : 'New notification rule'}
      confirmLabel="Save rule"
      busy={save.isPending}
      onClose={onClose}
      onConfirm={() => save.mutate()}
    >
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{
            name: 'Name',
            thresholds: 'Days before',
            recipients: 'Recipients',
            failure_count: 'Failed runs',
          }}
        />
      )}
      <TextField
        label="Name"
        name="rule-name"
        value={form.name}
        onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
        error={errors.name}
        required
      />
      <SelectField
        label="Alert about"
        name="rule-event"
        value={form.event}
        disabled={Boolean(rule)}
        onChange={(e) => {
          const next = e.target.value as Event
          setForm((f) => ({ ...f, event: next, thresholds: EVENTS[next].defaults.join(', ') }))
        }}
        options={Object.entries(EVENTS).map(([value, e]) => ({ value, label: e.label }))}
        help={event.help}
      />
      {form.event === 'integration_failure' ? (
        <TextField
          label="Failed runs in a row"
          name="rule-failures"
          type="number"
          min={1}
          max={50}
          value={form.failure_count}
          onChange={(e) => setForm((f) => ({ ...f, failure_count: e.target.value }))}
          error={errors.failure_count}
        />
      ) : (
        <>
          <TextField
            label="Days before"
            name="rule-thresholds"
            value={form.thresholds}
            onChange={(e) => setForm((f) => ({ ...f, thresholds: e.target.value }))}
            error={errors.thresholds}
            help="Comma-separated, for example 90, 30, 7. Each threshold is announced once."
          />
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.include_expired}
              onChange={(e) => setForm((f) => ({ ...f, include_expired: e.target.checked }))}
            />{' '}
            Also announce when expired
          </label>
        </>
      )}
      {recipients.data && (
        <CheckboxGroup
          legend="Recipients"
          name="rule-recipients"
          value={form.recipients}
          onChange={(value) => setForm((f) => ({ ...f, recipients: value }))}
          error={errors.recipients}
          options={recipients.data.map((u) => ({
            value: u.id,
            label: `${u.display_name || u.username}${u.has_email ? '' : ' (no e-mail address)'}`,
          }))}
        />
      )}
      {form.event === 'lifecycle_eol' && sites.data && (
        <CheckboxGroup
          legend="Only these sites (optional)"
          name="rule-sites"
          value={form.sites}
          onChange={(value) => setForm((f) => ({ ...f, sites: value }))}
          options={sites.data.map((s) => ({ value: s.id, label: `${s.code} – ${s.name}` }))}
        />
      )}
      <label className="checkbox">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
        />{' '}
        Rule active
      </label>
    </Dialog>
  )
}

function PreviewDialog({ rule, onClose }: { rule: NotificationRule; onClose: () => void }) {
  const preview = useQuery({
    queryKey: ['notifications', 'rule-preview', rule.id],
    queryFn: () => previewRule(rule.id),
  })
  return (
    <Dialog open title={`Preview: ${rule.name}`} confirmLabel="Close" onClose={onClose} onConfirm={onClose}>
      <p>What the next run would announce. Nothing is sent from here.</p>
      {preview.isPending && <LoadingState label="Checking…" />}
      {preview.isError && <QueryErrorState error={preview.error} what="the preview" />}
      {preview.data && <PreviewBody data={preview.data} />}
    </Dialog>
  )
}

function PreviewBody({ data }: { data: RulePreview }) {
  return (
    <>
      {!data.mail_enabled && <p className="field__error">Mail is disabled: rules do not run until it is enabled.</p>}
      {data.recipients.length === 0 && <p>This rule has no recipients.</p>}
      <ul className="plain-list" aria-label="Recipients">
        {data.recipients.map((r) => (
          <li key={r.user.id}>
            <strong>{r.user.display_name || r.user.username}</strong>:{' '}
            {r.eligible ? `${r.pending} new item${r.pending === 1 ? '' : 's'}` : `skipped (${r.reason})`}
            {r.items.length > 0 && (
              <ul>
                {r.items.map((item) => (
                  <li key={`${item.title}-${item.date}-${item.status}`}>
                    {item.title}: {item.status} ({item.date})
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </>
  )
}
