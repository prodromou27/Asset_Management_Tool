import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AUTH_PROVIDERS, apiError, makeMe, mockApi as rawMockApi, renderApp } from '../../test/api'
import { safeNext } from './safeNext'

afterEach(() => vi.unstubAllGlobals())

const signedOut = apiError(401, 'NOT_AUTHENTICATED', 'Not signed in.')
const providers = AUTH_PROVIDERS
const mockApi = (routes: Parameters<typeof rawMockApi>[0]) => rawMockApi({
  'GET /auth/providers/': { body: providers }, ...routes,
})

function fill(username: string, password: string) {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
}

describe('LoginPage', () => {
  it('starts configured Entra with CSRF and a local destination', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign })
    const url = 'https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize?state=fixture'
    const { calls } = mockApi({
      'GET /auth/me/': signedOut,
      'GET /auth/providers/': { body: providers.map((provider) => ({ ...provider, status: 'available' })) },
      'GET /auth/csrf/': { status: 204 },
      'POST /auth/entra/start/': { body: { authorization_url: url } },
    })
    renderApp('/login?next=%2Fadmin%2Fusers')
    fireEvent.click(await screen.findByRole('button', { name: 'Continue with Microsoft Entra' }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith(url))
    expect(calls.find((call) => call.path === '/auth/entra/start/')?.body).toEqual({ next_path: '/admin/users' })
    expect(calls.findIndex((call) => call.path === '/auth/csrf/')).toBeLessThan(calls.findIndex((call) => call.path === '/auth/entra/start/'))
  })

  it('shows a generic callback failure without reflecting provider query details', async () => {
    mockApi({ 'GET /auth/me/': signedOut })
    renderApp('/login?sso_error=1&error_description=untrusted-value')
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be verified')
    expect(screen.queryByText('untrusted-value')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Continue with Microsoft Entra' })).not.toBeInTheDocument()
  })
  it('validates required fields without calling the API', async () => {
    const { calls } = mockApi({ 'GET /auth/me/': signedOut })
    renderApp('/login')

    fireEvent.click(await screen.findByRole('button', { name: 'Sign in' }))

    expect(screen.getByText('Enter your username.')).toBeInTheDocument()
    expect(screen.getByText('Enter your password.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/auth/local/login/')).toBe(false)
  })

  it('shows the generic failure message and clears the password', async () => {
    mockApi({
      'GET /auth/me/': signedOut,
      'GET /auth/csrf/': { status: 204 },
      'POST /auth/local/login/': apiError(401, 'LOGIN_FAILED', 'Sign-in failed. Check your username and password, or try again later.'),
    })
    renderApp('/login')
    await screen.findByRole('button', { name: 'Sign in' })

    fill('admin.one', 'wrong')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in failed.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    // Still on sign-in: a LOGIN_FAILED 401 must not be treated as session expiry.
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('explains rate limiting', async () => {
    mockApi({
      'GET /auth/me/': signedOut,
      'GET /auth/csrf/': { status: 204 },
      'POST /auth/local/login/': apiError(429, 'TOO_MANY_REQUESTS', 'Throttled.'),
    })
    renderApp('/login')
    await screen.findByRole('button', { name: 'Sign in' })

    fill('admin.one', 'pw')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Too many sign-in attempts')
  })

  it('fetches a CSRF cookie, signs in and continues to a safe next path', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': signedOut,
      'GET /auth/csrf/': { status: 204 },
      'POST /auth/local/login/': { body: makeMe() },
      'GET /users/': { body: { items: [], next_cursor: null, previous_cursor: null, count: 0 } },
      'GET /roles/': { body: [] },
    })
    renderApp('/login?next=%2Fadmin%2Fusers')
    await screen.findByRole('button', { name: 'Sign in' })

    fill('admin.one', 'Correct-Horse-Battery-9')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Users & roles' })).toBeInTheDocument()
    const order = calls.map((c) => `${c.method} ${c.path}`)
    expect(order.indexOf('GET /auth/csrf/')).toBeLessThan(order.indexOf('POST /auth/local/login/'))
    await waitFor(() =>
      expect(calls.find((c) => c.path === '/auth/local/login/')?.body).toEqual({
        username: 'admin.one',
        password: 'Correct-Horse-Battery-9',
      }),
    )
  })
})

describe('safeNext', () => {
  it.each([
    ['/admin/users?status=active', '/admin/users?status=active'],
    [null, '/'],
    ['https://evil.example', '/'],
    ['//evil.example/path', '/'],
    ['/\\evil.example', '/'],
    ['javascript:alert(1)', '/'],
  ])('%s -> %s', (input, expected) => {
    expect(safeNext(input)).toBe(expected)
  })
})
