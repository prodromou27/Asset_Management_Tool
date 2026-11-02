import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useSession } from '../../app/useSession'
import {
  fetchSecuritySettings,
  queryKeys,
  updateSecuritySettings,
} from '../../shared/api/accounts'
import { isApiError } from '../../shared/api/client'
import { PERMISSIONS, type SecuritySettings } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'

type FieldKey =
  | 'session_idle_timeout_minutes'
  | 'session_absolute_timeout_hours'
  | 'lockout_threshold'
  | 'lockout_duration_minutes'
  | 'password_min_length'

interface FieldSpec {
  key: FieldKey
  label: string
  min: number
  max: number
  unit: string
  help: string
}

const GROUPS: { title: string; fields: FieldSpec[] }[] = [
  {
    title: 'Sessions',
    fields: [
      {
        key: 'session_idle_timeout_minutes',
        label: 'Idle timeout',
        min: 5,
        max: 480,
        unit: 'minutes',
        help: 'Signs a user out after this long without activity.',
      },
      {
        key: 'session_absolute_timeout_hours',
        label: 'Absolute session lifetime',
        min: 1,
        max: 72,
        unit: 'hours',
        help: 'Maximum session length regardless of activity. Must exceed the idle timeout.',
      },
    ],
  },
  {
    title: 'Sign-in protection',
    fields: [
      {
        key: 'lockout_threshold',
        label: 'Failed attempts before lockout',
        min: 3,
        max: 20,
        unit: 'attempts',
        help: 'Consecutive failed sign-ins that lock the account.',
      },
      {
        key: 'lockout_duration_minutes',
        label: 'Lockout duration',
        min: 1,
        max: 1440,
        unit: 'minutes',
        help: 'How long a locked account stays locked. Admins can unlock sooner.',
      },
    ],
  },
  {
    title: 'Passwords',
    fields: [
      {
        key: 'password_min_length',
        label: 'Minimum password length',
        min: 12,
        max: 128,
        unit: 'characters',
        help: 'Applies to new and changed passwords. Common and numeric-only passwords are always rejected.',
      },
    ],
  },
]

const LABELS = Object.fromEntries(
  GROUPS.flatMap((group) => group.fields.map((field) => [field.key, field.label])),
)

type Draft = Record<FieldKey, string>

function toDraft(settings: SecuritySettings): Draft {
  return {
    session_idle_timeout_minutes: String(settings.session_idle_timeout_minutes),
    session_absolute_timeout_hours: String(settings.session_absolute_timeout_hours),
    lockout_threshold: String(settings.lockout_threshold),
    lockout_duration_minutes: String(settings.lockout_duration_minutes),
    password_min_length: String(settings.password_min_length),
  }
}

export function SecuritySettingsPage() {
  const settings = useQuery({ queryKey: queryKeys.security, queryFn: fetchSecuritySettings })
  // Lives here: a successful save bumps the version, which remounts PolicyForm.
  const [saved, setSaved] = useState(false)

  if (settings.isPending) return <LoadingState label="Loading security policy…" />
  if (settings.isError) return <QueryErrorState error={settings.error} what="security settings" />
  return (
    <PolicyForm
      key={settings.data.version}
      current={settings.data}
      onReload={() => settings.refetch()}
      saved={saved}
      setSaved={setSaved}
    />
  )
}

interface PolicyFormProps {
  current: SecuritySettings
  onReload: () => void
  saved: boolean
  setSaved: (saved: boolean) => void
}

function PolicyForm({ current, onReload, saved, setSaved }: PolicyFormProps) {
  const { can } = useSession()
  const canManage = can(PERMISSIONS.securityManage)
  const queryClient = useQueryClient()
  const [values, setDraft] = useState<Draft>(() => toDraft(current))
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: (changes: Partial<Record<FieldKey, number>>) =>
      updateSecuritySettings(current.version, changes),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.security, updated)
      setSaved(true)
    },
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSaved(false)
    const errors: Record<string, string[]> = {}
    const changes: Partial<Record<FieldKey, number>> = {}
    for (const field of GROUPS.flatMap((group) => group.fields)) {
      const raw = values[field.key].trim()
      const parsed = Number(raw)
      if (!/^\d+$/.test(raw) || parsed < field.min || parsed > field.max) {
        errors[field.key] = [`Enter a whole number from ${field.min} to ${field.max}.`]
      } else if (parsed !== current[field.key]) {
        changes[field.key] = parsed
      }
    }
    setClientErrors(errors)
    if (Object.keys(errors).length > 0) return
    if (Object.keys(changes).length === 0) {
      setSaved(true)
      return
    }
    mutation.mutate(changes)
  }

  const conflict = isApiError(mutation.error, 409)
  const serverErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = Object.keys(clientErrors).length > 0 ? clientErrors : serverErrors

  return (
    <div className="page page--narrow">
      <PageHeader
        title="Security policy"
        meta={
          current.modified_by
            ? `Last changed ${formatDateTime(current.modified_at)} by ${current.modified_by}. Changes are audited.`
            : 'Using defaults. Changes are audited.'
        }
      />
      {!canManage && (
        <p className="inline-note" role="note">
          Read-only. Changing the security policy requires the System Admin role.
        </p>
      )}
      <section className="panel">
        {(Object.keys(errors).length > 0 || mutation.error) && (
          <ErrorSummary
            message={
              Object.keys(errors).length > 0
                ? 'Check the highlighted fields.'
                : (mutation.error?.message ?? 'Could not save the policy.')
            }
            fieldErrors={errors}
            fieldLabels={LABELS}
          />
        )}
        {conflict && (
          <Button
            onClick={() => {
              mutation.reset()
              onReload()
            }}
          >
            Reload latest policy
          </Button>
        )}
        {saved && (
          <p className="inline-success" role="status">
            Security policy saved.
          </p>
        )}
        <form onSubmit={handleSubmit} noValidate className="form-stack">
          {GROUPS.map((group) => (
            <fieldset className="settings-group" key={group.title}>
              <legend className="section-title">{group.title}</legend>
              <div className="form-grid">
                {group.fields.map((field) => (
                  <TextField
                    key={field.key}
                    label={`${field.label} (${field.unit})`}
                    name={field.key}
                    inputMode="numeric"
                    value={values[field.key]}
                    disabled={!canManage}
                    onChange={(event) =>
                      setDraft((d) => ({ ...d, [field.key]: event.target.value }))
                    }
                    error={errors[field.key]}
                    help={`${field.help} Allowed ${field.min}–${field.max}.`}
                  />
                ))}
              </div>
            </fieldset>
          ))}
          <p className="field__help">
            Multi-factor authentication for privileged users will be enforced through the
            identity provider. No identity provider is configured yet.
          </p>
          {canManage && (
            <div className="form-actions">
              <Button type="submit" variant="primary" busy={mutation.isPending}>
                Save policy
              </Button>
            </div>
          )}
        </form>
      </section>
    </div>
  )
}
