import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { login, queryKeys } from '../../shared/api/accounts'
import { isApiError } from '../../shared/api/client'
import { Button } from '../../shared/ui/Button'
import { TextField } from '../../shared/ui/Field'
import { ErrorSummary, LoadingState } from '../../shared/ui/States'
import { safeNext } from './safeNext'

export function LoginPage() {
  const { me, isPending } = useSession()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [missing, setMissing] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: () => login(username, password),
    onSuccess: (user) => {
      queryClient.setQueryData(queryKeys.me, user)
      navigate(user.must_change_password ? '/account/password' : next, { replace: true })
    },
    onError: () => setPassword(''),
  })

  if (isPending) return <LoadingState label="Checking your session…" />
  if (me) return <Navigate to={next} replace />

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const errors: Record<string, string[]> = {}
    if (!username.trim()) errors.username = ['Enter your username.']
    if (!password) errors.password = ['Enter your password.']
    setMissing(errors)
    if (Object.keys(errors).length === 0) mutation.mutate()
  }

  const error = mutation.error
  const errorMessage = isApiError(error, 429)
    ? 'Too many sign-in attempts. Wait a minute and try again.'
    : error instanceof Error
      ? error.message
      : null

  return (
    <div className="auth-layout">
      <main className="auth-panel" id="main">
        <p className="auth-panel__product">ITAM</p>
        <h1 className="auth-panel__title">Sign in</h1>
        {errorMessage && <ErrorSummary message={errorMessage} fieldErrors={{}} fieldLabels={{}} />}
        <form onSubmit={handleSubmit} noValidate className="form-stack">
          <TextField
            label="Username"
            name="username"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            error={missing.username}
          />
          <TextField
            label="Password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            error={missing.password}
          />
          <Button type="submit" variant="primary" busy={mutation.isPending}>
            {mutation.isPending ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
        <p className="auth-panel__note">
          Local accounts are issued by a System Admin. Single sign-on is not yet configured.
        </p>
      </main>
    </div>
  )
}
