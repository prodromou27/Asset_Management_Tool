import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { queryKeys } from '../../shared/api/accounts'
import { isApiError } from '../../shared/api/client'
import { fetchGeneralSettings, generalKey, saveGeneralSettings, type GeneralSettings } from '../../shared/api/general'
import { PERMISSIONS } from '../../shared/api/types'
import { configureDisplay, previewDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'

export function GeneralSettingsPage() {
  const [saved, setSaved] = useState(false)
  const query = useQuery({ queryKey: generalKey, queryFn: fetchGeneralSettings })
  if (query.isPending) return <LoadingState label="Loading organization settings…" />
  if (query.error) return <QueryErrorState error={query.error} what="organization settings" />
  return <SettingsForm key={query.data.version} initial={query.data} saved={saved} setSaved={setSaved} />
}

function SettingsForm({ initial, saved, setSaved }: { initial: GeneralSettings; saved: boolean; setSaved: (value: boolean) => void }) {
  const { can } = useSession()
  const manage = can(PERMISSIONS.generalManage)
  const client = useQueryClient()
  const [draft, setDraft] = useState(initial)
  const mutation = useMutation({ mutationFn: saveGeneralSettings, onSuccess: async (data) => {
    configureDisplay(data)
    setSaved(true)
    client.setQueryData(generalKey, data)
    await client.invalidateQueries({ queryKey: queryKeys.me })
  } })
  const errors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const update = (key: keyof GeneralSettings, value: string) => { setSaved(false); setDraft({ ...draft, [key]: value }) }
  let preview = 'Enter a valid timezone to preview the display.'
  try { preview = previewDateTime('2026-11-05T12:30:00Z', draft) } catch { /* Server validates IANA zones. */ }
  const submit = (event: FormEvent) => { event.preventDefault(); if (manage && !mutation.isPending) mutation.mutate(draft) }
  return <div className="page">
    <PageHeader title="General settings" meta="Organization identity and shared display preferences. Timestamps remain stored in UTC." />
    <section className="panel">
      <form onSubmit={submit}>
        {mutation.error && <ErrorSummary message={mutation.error.message} fieldErrors={errors} fieldLabels={{ organization_name: 'Organization name', timezone: 'Timezone', support_contact: 'Support contact' }} />}
        {isApiError(mutation.error, 409) && <Button onClick={() => { void client.invalidateQueries({ queryKey: generalKey }) }}>Reload current settings</Button>}
        {saved && <p className="inline-success" role="status">General settings saved.</p>}
        <fieldset disabled={!manage || mutation.isPending} className="form-fieldset">
          <div className="form-grid">
            <TextField label="Organization name" name="organization_name" value={draft.organization_name} required maxLength={100} onChange={(e) => update('organization_name', e.target.value)} error={errors.organization_name} help="Shown in the navigation sidebar." />
            <TextField label="Display timezone" name="timezone" value={draft.timezone} required maxLength={64} onChange={(e) => update('timezone', e.target.value)} error={errors.timezone} help="IANA timezone, for example Asia/Nicosia, Europe/London or UTC." />
            <SelectField label="Date format" name="date_format" value={draft.date_format} options={[{ value: 'day_month_year', label: 'Day month year' }, { value: 'month_day_year', label: 'Month day year' }, { value: 'iso', label: 'ISO 8601' }]} onChange={(e) => update('date_format', e.target.value)} />
            <SelectField label="Language" name="language" value="en" options={[{ value: 'en', label: 'English' }]} onChange={() => {}} help="English is the supported application language." />
            <TextField label="Support contact" name="support_contact" type="email" value={draft.support_contact ?? ''} maxLength={254} onChange={(e) => update('support_contact', e.target.value)} error={errors.support_contact} help="Optional internal support email. This does not configure outgoing mail." />
          </div>
        </fieldset>
        <p className="field__help">Display preview for 5 November 2026, 12:30 UTC: <output>{preview}</output>. Calendar dates keep their original day.</p>
        {manage && <div className="form-actions"><Button type="submit" variant="primary" busy={mutation.isPending}>Save general settings</Button></div>}
      </form>
    </section>
    <section className="panel">
      <h2 className="section-title">Configuration ownership</h2>
      <p>Business policies are stored in the database. Deployment configuration and secrets stay with the operator; this page never displays credentials.</p>
      <ul className="plain-list">
        {can(PERMISSIONS.securityView) && <li><Link to="/admin/security">Session and password policy</Link></li>}
        {can(PERMISSIONS.notificationsView) && <li><Link to="/admin/smtp">SMTP, notification rules and delivery queue</Link></li>}
        {can(PERMISSIONS.backupsView) && <li><Link to="/admin/backups">Backup schedule, retention and recovery objectives</Link></li>}
        {can(PERMISSIONS.healthView) && <li><Link to="/">Operational diagnostics and production checklist</Link></li>}
      </ul>
      <p className="field__help">Import/export expiry, storage paths and quotas, worker concurrency and protected audit retention are deployment-controlled. External SSO/MFA is planned pending approved identity-provider design. No retention deletion or credential reset is available here.</p>
    </section>
  </div>
}
