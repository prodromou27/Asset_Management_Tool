import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useSession } from '../../app/useSession'
import { fetchAuthProviders, login, queryKeys, startEntra } from '../../shared/api/accounts'
import { isApiError } from '../../shared/api/client'
import { Button } from '../../shared/ui/Button'
import { TextField } from '../../shared/ui/Field'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { safeNext } from './safeNext'
import { ThemeToggle } from '../../app/theme'

export function LoginPage() {
  const { me, isPending } = useSession()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [missing, setMissing] = useState<Record<string, string[]>>({})
  const providers = useQuery({ queryKey: ['auth', 'providers'], queryFn: fetchAuthProviders, enabled: !me && !isPending })
  const entra = useMutation({
    mutationFn: () => startEntra(next),
    onSuccess: ({ authorization_url }) => globalThis.location.assign(authorization_url),
  })

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
  if (providers.isPending) return <LoadingState label="Loading sign-in options…" />
  if (providers.isError) return <main className="auth-panel"><QueryErrorState error={providers.error} what="sign-in options" /></main>
  const sso = providers.data.find((provider) => provider.id === 'entra' && provider.status === 'available')
  const local = providers.data.find((provider) => provider.id === 'local')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const errors: Record<string, string[]> = {}
    if (!username.trim()) errors.username = ['Enter your username.']
    if (!password) errors.password = ['Enter your password.']
    setMissing(errors)
    if (Object.keys(errors).length === 0) mutation.mutate()
  }

  const error = mutation.error ?? entra.error
  const errorMessage = isApiError(error, 429)
    ? 'Too many sign-in attempts. Wait a minute and try again.'
    : error instanceof Error
      ? error.message
      : null

  return (
    <div className="auth-layout">
      <div className="auth-appearance"><ThemeToggle /></div>
      <main className="auth-panel" id="main">
        <p className="auth-panel__product">ITAM</p>
        <h1 className="auth-panel__title">Sign in</h1>
        {params.has('sso_error') && <ErrorSummary message="Microsoft Entra sign-in could not be verified. Try again or contact your administrator." fieldErrors={{}} fieldLabels={{}} />}
        {errorMessage && <ErrorSummary message={errorMessage} fieldErrors={{}} fieldLabels={{}} />}
        {sso && <div className="form-stack">
          <Button variant="primary" onClick={() => entra.mutate()} busy={entra.isPending}>
            Continue with Microsoft Entra
          </Button>
          <p className="auth-panel__note">Use your organization account and complete its sign-in verification.</p>
          <h2 className="section-title">{local?.label ?? 'Local account'}</h2>
        </div>}
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
          {local?.label === 'Local emergency access'
            ? 'Emergency access requires a named administrator account and a one-use recovery window opened by your authorized operator.'
            : 'Local accounts are issued by a System Admin.'}
        </p>
      </main>
    </div>
  )
}
