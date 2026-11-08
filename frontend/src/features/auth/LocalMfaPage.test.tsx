import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { makeMe, mockApi, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

it('enrolls only after verification and shows recovery codes once', async () => {
  let enabled = false
  const { calls } = mockApi({
    'GET /auth/me/': () => ({ body: makeMe({ mfa_enabled: enabled }) }),
    'POST /auth/mfa/setup/': { body: { secret: 'FIXTURESETUPKEY', provisioning_uri: 'otpauth://totp/fixture' } },
    'POST /auth/mfa/confirm/': () => { enabled = true; return { body: { recovery_codes: ['fixture-one-use-code'] } } },
  })
  renderApp('/account/security')
  fireEvent.change(await screen.findByLabelText('Current local password'), { target: { value: 'fixture-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Set up authenticator' }))
  expect(await screen.findByLabelText('Authenticator setup key')).toHaveValue('FIXTURESETUPKEY')
  expect(calls.some((call) => call.path === '/auth/mfa/confirm/')).toBe(false)
  fireEvent.change(screen.getByLabelText('Authenticator code'), { target: { value: '123456' } })
  fireEvent.click(screen.getByRole('button', { name: 'Verify and enable MFA' }))
  expect(await screen.findByText('fixture-one-use-code')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'I have saved these codes' }))
  expect(screen.queryByText('fixture-one-use-code')).not.toBeInTheDocument()
  await screen.findByRole('button', { name: 'Disable local MFA' })
  expect(calls.find((call) => call.path === '/auth/mfa/confirm/')?.body).toEqual({
    password: 'fixture-password', otp_code: '123456',
  })
})

it('requires password and code to disable enrolled MFA', async () => {
  let enabled = true
  const { calls } = mockApi({
    'GET /auth/me/': () => ({ body: makeMe({ mfa_enabled: enabled }) }),
    'POST /auth/mfa/disable/': () => { enabled = false; return { status: 200 } },
  })
  renderApp('/account/security')
  fireEvent.change(await screen.findByLabelText('Current local password'), { target: { value: 'fixture-password' } })
  fireEvent.change(screen.getByLabelText('Authenticator or recovery code'), { target: { value: 'fixture-recovery' } })
  fireEvent.click(screen.getByRole('button', { name: 'Disable local MFA' }))
  await waitFor(() => expect(calls.find((call) => call.path === '/auth/mfa/disable/')?.body).toEqual({
    password: 'fixture-password', otp_code: 'fixture-recovery',
  }))
  expect(await screen.findByText('Local MFA disabled.')).toBeInTheDocument()
})

it('does not offer local MFA enrollment for a local-disabled account', async () => {
  mockApi({ 'GET /auth/me/': { body: makeMe({ local_login_enabled: false, auth_method: 'entra' }) } })
  renderApp('/account/security')
  expect(await screen.findByText(/Local sign-in is disabled/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Set up authenticator' })).not.toBeInTheDocument()
})
