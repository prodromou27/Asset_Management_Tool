import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useSession } from '../../app/useSession'
import { confirmMfa, disableMfa, queryKeys, setupMfa } from '../../shared/api/accounts'
import type { MfaSetup } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { ErrorSummary } from '../../shared/ui/States'

export function LocalMfaPage() {
  const { me } = useSession()
  const cache = useQueryClient()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [setup, setSetup] = useState<MfaSetup | null>(null)
  const [recovery, setRecovery] = useState<string[]>([])
  const [notice, setNotice] = useState('')
  const mutation = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      if (me?.mfa_enabled) {
        await disableMfa(password, code.trim())
        return { kind: 'disabled' as const }
      }
      if (setup) return { kind: 'confirmed' as const, data: await confirmMfa(password, code.trim()) }
      return { kind: 'setup' as const, data: await setupMfa(password) }
    },
    onSuccess: (result) => {
      if (result.kind === 'setup') setSetup(result.data)
      else {
        setSetup(null)
        setPassword('')
        setCode('')
        if (result.kind === 'confirmed') setRecovery([...result.data.recovery_codes])
        setNotice(result.kind === 'disabled' ? 'Local MFA disabled.' : 'Local MFA enabled.')
        cache.invalidateQueries({ queryKey: queryKeys.me })
      }
    },
    onError: () => { setPassword(''); setCode('') },
  })

  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }

  return (
    <div className="page page--narrow">
      <PageHeader title="Local account MFA" />
      <section className="panel">
        <p className="section-help">
          MFA is optional for local sign-in. Enabling it requires an authenticator or
          one-use recovery code each time you sign in with your local password.
          Microsoft Entra verification is managed by your organization.
        </p>
        {notice && <p role="status" className="inline-success">{notice}</p>}
        {!me?.local_login_enabled ? (
          <p className="section-help">Local sign-in is disabled for this account. Contact a System Admin to enable it.</p>
        ) : recovery.length > 0 ? (
          <div className="form-stack">
            <h2 className="section-title">Save your recovery codes</h2>
            <p>Store these codes securely. Each works once with your password. They cannot be shown again.</p>
            <ul className="mono">{recovery.map((item) => <li key={item}>{item}</li>)}</ul>
            <Button onClick={() => { setRecovery([]); mutation.reset() }}>I have saved these codes</Button>
          </div>
        ) : (
          <form className="form-stack" onSubmit={submit}>
            <h2 className="section-title">{me.mfa_enabled ? 'MFA enabled' : 'MFA not enabled'}</h2>
            {setup && <>
              <p>In your authenticator app, add an account using this setup key (time-based, 6 digits, 30 seconds), then enter its code below. Setup expires in 10 minutes.</p>
              <TextField label="Authenticator setup key" name="setup_key" value={setup.secret} readOnly autoComplete="off" />
            </>}
            <TextField label="Current local password" name="password" type="password"
              autoComplete="current-password" required value={password}
              onChange={(event) => setPassword(event.target.value)} />
            {(setup || me.mfa_enabled) && <TextField
              label={setup ? 'Authenticator code' : 'Authenticator or recovery code'} name="otp_code"
              autoComplete="one-time-code" required value={code} spellCheck={false}
              onChange={(event) => setCode(event.target.value)} />}
            {mutation.error && <ErrorSummary message={mutation.error.message} fieldErrors={{}} fieldLabels={{}} />}
            <Button type="submit" variant="primary" busy={mutation.isPending}>
              {me.mfa_enabled ? 'Disable local MFA' : setup ? 'Verify and enable MFA' : 'Set up authenticator'}
            </Button>
            {setup && <Button variant="quiet" onClick={() => {
              setSetup(null); setPassword(''); setCode(''); mutation.reset()
            }}>Cancel setup</Button>}
          </form>
        )}
      </section>
    </div>
  )
}
