import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { createUser, fetchRoles, queryKeys } from '../../shared/api/accounts'
import { isApiError } from '../../shared/api/client'
import { Button } from '../../shared/ui/Button'
import { CheckboxGroup, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'

const LABELS: Record<string, string> = {
  username: 'Username',
  display_name: 'Display name',
  email: 'Email',
  roles: 'Roles',
  password: 'Temporary password',
  confirm_password: 'Confirm temporary password',
  non_field_errors: '',
}

const EMPTY = {
  username: '',
  display_name: '',
  email: '',
  password: '',
  confirm_password: '',
}

export function UserCreatePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const roles = useQuery({ queryKey: queryKeys.roles, queryFn: fetchRoles })
  const [values, setValues] = useState(EMPTY)
  const [selectedRoles, setSelectedRoles] = useState<string[]>([])
  const [clientErrors, setClientErrors] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: () =>
      createUser({
        username: values.username.trim(),
        display_name: values.display_name.trim(),
        email: values.email.trim(),
        roles: selectedRoles,
        password: values.password,
      }),
    onSuccess: async (user) => {
      await queryClient.invalidateQueries({ queryKey: ['users'] })
      navigate(`/admin/users/${user.id}`, { state: { notice: `Account ${user.username} created.` } })
    },
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const errors: Record<string, string[]> = {}
    if (!values.username.trim()) errors.username = ['Enter a username.']
    if (!values.display_name.trim()) errors.display_name = ['Enter a display name.']
    if (selectedRoles.length === 0) errors.roles = ['Select at least one role.']
    if (!values.password) errors.password = ['Enter a temporary password.']
    if (values.password !== values.confirm_password) {
      errors.confirm_password = ['The passwords do not match.']
    }
    setClientErrors(errors)
    if (Object.keys(errors).length === 0) mutation.mutate()
  }

  const serverErrors = isApiError(mutation.error) ? mutation.error.fieldErrors : {}
  const errors = Object.keys(clientErrors).length > 0 ? clientErrors : serverErrors
  const set = (field: keyof typeof EMPTY) => (event: { target: { value: string } }) =>
    setValues((current) => ({ ...current, [field]: event.target.value }))

  if (roles.isPending) return <LoadingState label="Loading roles…" />
  if (roles.isError) return <QueryErrorState error={roles.error} what="roles" />

  return (
    <div className="page page--narrow">
      <nav aria-label="Breadcrumb" className="breadcrumb">
        <Link to="/admin/users">Users &amp; roles</Link>
      </nav>
      <PageHeader
        title="Add user"
        meta="Creates a local account. The user must replace the temporary password at first sign-in."
      />
      <section className="panel">
        {(Object.keys(errors).length > 0 || mutation.error) && (
          <ErrorSummary
            message={
              Object.keys(errors).length > 0
                ? 'Check the highlighted fields.'
                : (mutation.error?.message ?? 'Could not create the account.')
            }
            fieldErrors={errors}
            fieldLabels={LABELS}
          />
        )}
        <form onSubmit={handleSubmit} noValidate className="form-stack">
          <div className="form-grid">
            <TextField
              label={LABELS.username}
              name="username"
              autoComplete="off"
              spellCheck={false}
              value={values.username}
              onChange={set('username')}
              error={errors.username}
              help="Lowercase letters, digits, dots, hyphens or underscores."
            />
            <TextField
              label={LABELS.display_name}
              name="display_name"
              autoComplete="off"
              value={values.display_name}
              onChange={set('display_name')}
              error={errors.display_name}
            />
            <TextField
              label={LABELS.email}
              name="email"
              type="email"
              autoComplete="off"
              value={values.email}
              onChange={set('email')}
              error={errors.email}
              help="Optional. Used for notifications once SMTP is configured."
            />
          </div>
          <CheckboxGroup
            legend={LABELS.roles}
            name="roles"
            options={roles.data.map((role) => ({
              value: role.code,
              label: role.name,
              description: role.description,
            }))}
            value={selectedRoles}
            onChange={setSelectedRoles}
            error={errors.roles}
          />
          <div className="form-grid">
            <TextField
              label={LABELS.password}
              name="password"
              type="password"
              autoComplete="new-password"
              value={values.password}
              onChange={set('password')}
              error={errors.password}
              help="Share it with the user through an approved channel. It is never shown again."
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
          </div>
          <div className="form-actions">
            <Button type="submit" variant="primary" busy={mutation.isPending}>
              Create account
            </Button>
            <Link className="button button--quiet" to="/admin/users">
              Cancel
            </Link>
          </div>
        </form>
      </section>
    </div>
  )
}
