import { screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, makeMe, mockApi, operatorMe, renderApp } from '../test/api'

const readyOk = { body: { status: 'ok', dependencies: {} } }

afterEach(() => vi.unstubAllGlobals())

describe('session guards and navigation', () => {
  it('redirects unauthenticated users to sign in', async () => {
    mockApi({ 'GET /auth/me/': apiError(401, 'NOT_AUTHENTICATED', 'Not signed in.') })

    renderApp('/admin/users')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('forces a temporary-password user to the change-password page with no navigation', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe({ must_change_password: true }) } })

    renderApp('/admin/users')

    expect(await screen.findByRole('heading', { name: 'Change password' })).toBeInTheDocument()
    expect(screen.getByText(/temporary password/i)).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(within(nav).queryByRole('link')).not.toBeInTheDocument()
  })

  it('shows administration links only for granted permissions', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe() }, 'GET /health/ready/': readyOk })

    renderApp('/')

    const nav = await screen.findByRole('navigation', { name: 'Primary' })
    expect(within(nav).getByRole('link', { name: 'Users & roles' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Audit log' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Security policy' })).toBeInTheDocument()
  })

  it('hides administration for a role without admin permissions and denies direct URLs', async () => {
    mockApi({ 'GET /auth/me/': { body: operatorMe() } })

    renderApp('/admin/users')

    expect(await screen.findByText(/do not have access to user accounts/i)).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(within(nav).queryByText('Administration')).not.toBeInTheDocument()
  })

  it('returns to sign-in when the session expires mid-use', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /users/': apiError(401, 'NOT_AUTHENTICATED', 'Session expired.'),
    })

    renderApp('/admin/users')

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })
})
