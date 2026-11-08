import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { changePassword, queryKeys } from '../../shared/api/accounts'
import { isApiError } from '../../shared/api/client'
import { Button } from '../../shared/ui/Button'
import { TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary } from '../../shared/ui/States'

const LABELS = {
  current_password: 'Current password',
  new_password: 'New password',
  confirm_password: 'Confirm new password',
}

export function ChangePasswordPage() {
  const { me } = useSession()
  const forced = me?.must_change_password ?? false
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [values, setValues] = useState({
    current_password: '',
    new_password: '',
    confirm_password: '',
  })
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({})
  const [done, setDone] = useState(false)

  const mutation = useMutation({
    mutationFn: () => changePassword(values.current_password, values.new_password),
    onSuccess: async () => {
      setValues({ current_password: '', new_password: '', confirm_password: '' })
      await queryClient.invalidateQueries({ queryKey: queryKeys.me })
      if (forced) navigate('/', { replace: true })
      else setDone(true)
    },
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setDone(false)
    const errors: Record<string, string[]> = {}
    if (!values.current_password) errors.current_password = ['Enter your current password.']
    if (!values.new_password) errors.new_password = ['Enter a new password.']
    if (values.new_password !== values.confirm_password) {
      errors.confirm_password = ['The new passwords do not match.']
    }
    setClientErrors(errors)
    if (Object.keys(errors).length === 0) mutation.mutate()
  }

  const serverErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = { ...serverErrors, ...clientErrors }
  const set = (field: keyof typeof values) => (event: { target: { value: string } }) =>
    setValues((current) => ({ ...current, [field]: event.target.value }))

  if (me?.auth_method === 'entra') return (
    <div className="page page--narrow">
      <PageHeader title="Change password" />
      <p className="section-help">Your sign-in password is managed by Microsoft Entra. Use your organization’s Microsoft account password settings.</p>
    </div>
  )

  return (
    <div className="page page--narrow">
      <PageHeader
        title="Change password"
        meta={
          forced
            ? 'Your account uses a temporary password. Choose a new one to continue.'
            : 'Changing your password signs out your other sessions.'
        }
      />
      <section className="panel">
        {(Object.keys(errors).length > 0 || mutation.error) && (
          <ErrorSummary
            message={
              Object.keys(errors).length > 0
                ? 'Check the highlighted fields.'
                : (mutation.error?.message ?? 'Could not change the password.')
            }
            fieldErrors={errors}
            fieldLabels={LABELS}
          />
        )}
        {done && (
          <p className="inline-success" role="status">
            Password changed.
          </p>
        )}
        <form onSubmit={handleSubmit} noValidate className="form-stack">
          <TextField
            label={LABELS.current_password}
            name="current_password"
            type="password"
            autoComplete="current-password"
            value={values.current_password}
            onChange={set('current_password')}
            error={errors.current_password}
          />
          <TextField
            label={LABELS.new_password}
            name="new_password"
            type="password"
            autoComplete="new-password"
            value={values.new_password}
            onChange={set('new_password')}
            error={errors.new_password}
            help="At least 12 characters (or the configured minimum). Avoid common or personal words."
          />
          <TextField
            label={LABELS.confirm_password}
            name="confirm_password"
            type="password"
            autoComplete="new-password"
            value={values.confirm_password}
            onChange={set('confirm_password')}
            error={errors.confirm_password}
          />
          <div className="form-actions">
            <Button type="submit" variant="primary" busy={mutation.isPending}>
              Change password
            </Button>
          </div>
        </form>
      </section>
    </div>
  )
}
