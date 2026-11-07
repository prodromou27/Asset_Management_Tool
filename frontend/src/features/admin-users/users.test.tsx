import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ROLES,
  apiError,
  auditorMe,
  makeMe,
  makeUser,
  mockApi,
  page,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const admin = { 'GET /auth/me/': { body: makeMe() }, 'GET /roles/': { body: ROLES } }
const USER_ID = '11111111-1111-4111-8111-111111111111'

describe('Users list', () => {
  it('shows a loading state, then rows with text statuses', async () => {
    mockApi({
      ...admin,
      'GET /users/': {
        body: page([
          makeUser(),
          makeUser({ id: 'u2', username: 'old.user', display_name: 'Old User', is_active: false }),
          makeUser({ id: 'u3', username: 'locked.user', display_name: 'Lock Test', is_locked: true }),
        ]),
      },
    })

    renderApp('/admin/users')

    expect(await screen.findByText(/loading users/i)).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'User accounts' })
    expect(within(table).getByRole('link', { name: 'Jane Doe' })).toHaveAttribute(
      'href',
      `/admin/users/${USER_ID}`,
    )
    expect(within(table).getByText('Active')).toBeInTheDocument()
    expect(within(table).getByText('Disabled')).toBeInTheDocument()
    expect(within(table).getByText('Locked')).toBeInTheDocument()
    expect(screen.getByText('3 accounts')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add user' })).toBeInTheDocument()
  })

  it('shows an empty state', async () => {
    mockApi({ ...admin, 'GET /users/': { body: page([]) } })

    renderApp('/admin/users')

    expect(await screen.findByText('No user accounts yet.')).toBeInTheDocument()
  })

  it('shows an error state with the request reference', async () => {
    mockApi({ ...admin, 'GET /users/': apiError(500, 'ERROR', 'Server error.') })

    renderApp('/admin/users')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load user accounts.')
    expect(alert).toHaveTextContent('req-test-0001')
  })

  it('shows a denied state when the API refuses access', async () => {
    mockApi({ ...admin, 'GET /users/': apiError(403, 'PERMISSION_DENIED', 'No.') })

    renderApp('/admin/users')

    expect(await screen.findByText(/do not have access to user accounts/i)).toBeInTheDocument()
  })

  it('sends filters to the API from the URL and the status control', async () => {
    const { calls } = mockApi({ ...admin, 'GET /users/': { body: page([]) } })

    renderApp('/admin/users?q=jane')
    await screen.findByText('No users match these filters.')
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'disabled' } })

    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/users/').at(-1)!
      expect(last.search.get('q')).toBe('jane')
      expect(last.search.get('status')).toBe('disabled')
    })
  })

  it('hides Add user for read-only auditors', async () => {
    mockApi({
      'GET /auth/me/': { body: auditorMe() },
      'GET /roles/': { body: ROLES },
      'GET /users/': { body: page([makeUser()]) },
    })

    renderApp('/admin/users')

    await screen.findByRole('table', { name: 'User accounts' })
    expect(screen.queryByRole('link', { name: 'Add user' })).not.toBeInTheDocument()
  })
})

describe('Add user', () => {
  it('validates locally before calling the API', async () => {
    const { calls } = mockApi(admin)
    renderApp('/admin/users/new')

    await screen.findByRole('heading', { name: 'Add user' })
    fireEvent.change(screen.getByLabelText('Temporary password'), { target: { value: 'a' } })
    fireEvent.change(screen.getByLabelText('Confirm temporary password'), {
      target: { value: 'b' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    const summary = await screen.findByRole('alert')
    expect(summary).toHaveFocus()
    expect(summary).toHaveTextContent('Username: Enter a username.')
    expect(summary).toHaveTextContent('Roles: Select at least one role.')
    expect(screen.getAllByText('The passwords do not match.').length).toBeGreaterThan(0)
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('shows server field errors inline and links them to the input', async () => {
    mockApi({
      ...admin,
      'POST /users/': apiError(422, 'VALIDATION_ERROR', 'The submitted data is invalid.', {
        username: ['This username is already in use.'],
      }),
    })
    renderApp('/admin/users/new')
    await screen.findByRole('heading', { name: 'Add user' })

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'jane.doe' } })
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Jane' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /Asset Operator/ }))
    for (const label of ['Temporary password', 'Confirm temporary password']) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: 'Temporary-Pass-001' } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    const input = screen.getByLabelText('Username')
    await waitFor(() => expect(input).toHaveAttribute('aria-invalid', 'true'))
    expect(input).toHaveAccessibleDescription(/already in use/)
  })

  it('creates the account and opens its detail page', async () => {
    const created = makeUser({ must_change_password: true })
    const { calls } = mockApi({
      ...admin,
      'POST /users/': { status: 201, body: created },
      [`GET /users/${USER_ID}/`]: { body: created },
    })
    renderApp('/admin/users/new')
    await screen.findByRole('heading', { name: 'Add user' })

    fireEvent.change(screen.getByLabelText('Username'), { target: { value: ' jane.doe ' } })
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: 'Jane Doe' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /Auditor/ }))
    for (const label of ['Temporary password', 'Confirm temporary password']) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: 'Temporary-Pass-001' } })
    }
    fireEvent.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByText('Account jane.doe created.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST' && c.path === '/users/')?.body).toEqual({
      username: 'jane.doe',
      display_name: 'Jane Doe',
      email: '',
      roles: ['auditor'],
      password: 'Temporary-Pass-001',
    })
    expect(screen.getByText('Password change pending')).toBeInTheDocument()
  })
})

describe('User detail', () => {
  it('saves an explicit Entra binding with the current account version', async () => {
    const tenant = '22222222-2222-4222-8222-222222222222'
    const objectId = '33333333-3333-4333-8333-333333333333'
    const { calls } = mockApi({
      ...admin,
      [`GET /users/${USER_ID}/`]: { body: makeUser({ version: 4 }) },
      [`PATCH /users/${USER_ID}/entra/`]: {
        body: makeUser({ version: 5, entra_tenant_id: tenant, entra_object_id: objectId }),
      },
    })
    renderApp(`/admin/users/${USER_ID}`)
    fireEvent.change(await screen.findByLabelText('Entra tenant ID'), { target: { value: tenant } })
    fireEvent.change(screen.getByLabelText('Entra user object ID'), { target: { value: objectId } })
    fireEvent.click(screen.getByRole('button', { name: 'Save sign-in binding' }))
    expect(await screen.findByText('Entra sign-in binding saved.')).toBeInTheDocument()
    const patch = calls.find((call) => call.path.endsWith('/entra/'))!
    expect(patch.headers['If-Match']).toBe('"4"')
    expect(patch.body).toEqual({ tenant_id: tenant, object_id: objectId })
  })

  it('sends If-Match with the record version and reports a conflict', async () => {
    const { calls } = mockApi({
      ...admin,
      [`GET /users/${USER_ID}/`]: { body: makeUser({ version: 4 }) },
      [`PATCH /users/${USER_ID}/`]: apiError(
        409,
        'VERSION_MISMATCH',
        'This record was changed by someone else. Reload and try again.',
      ),
    })
    renderApp(`/admin/users/${USER_ID}`)

    const name = await screen.findByLabelText('Display name')
    fireEvent.change(name, { target: { value: 'Jane Q. Doe' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText(/changed by someone else/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reload latest version' })).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.headers['If-Match']).toBe('"4"')
    expect(patch.body).toMatchObject({ display_name: 'Jane Q. Doe' })
  })

  it('requires a reason before disabling and then reports the result', async () => {
    const { calls } = mockApi({
      ...admin,
      [`GET /users/${USER_ID}/`]: { body: makeUser() },
      [`POST /users/${USER_ID}/disable/`]: {
        body: makeUser({ is_active: false, disabled_by: 'admin.one', version: 2 }),
      },
    })
    renderApp(`/admin/users/${USER_ID}`)

    fireEvent.click(await screen.findByRole('button', { name: 'Disable account' }))
    const dialog = screen.getByRole('dialog', { name: 'Disable jane.doe?' })
    expect(dialog).toHaveTextContent('Affects 1 account.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disable account' }))
    expect(within(dialog).getByText(/at least 5 characters/)).toBeInTheDocument()
    expect(calls.some((c) => c.path.endsWith('/disable/'))).toBe(false)

    fireEvent.change(within(dialog).getByLabelText('Reason'), {
      target: { value: 'Left the organization' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disable account' }))

    expect(await screen.findByText(/jane.doe disabled/)).toBeInTheDocument()
    expect(calls.find((c) => c.path.endsWith('/disable/'))?.body).toEqual({
      reason: 'Left the organization',
    })
  })

  it('does not offer self-disable', async () => {
    const self = makeUser({ id: makeMe().id, username: 'admin.one' })
    mockApi({ ...admin, [`GET /users/${self.id}/`]: { body: self } })

    renderApp(`/admin/users/${self.id}`)

    await screen.findByRole('button', { name: 'Set temporary password' })
    expect(screen.queryByRole('button', { name: 'Disable account' })).not.toBeInTheDocument()
  })

  it('is read-only for auditors', async () => {
    mockApi({
      'GET /auth/me/': { body: auditorMe() },
      [`GET /users/${USER_ID}/`]: { body: makeUser() },
    })

    renderApp(`/admin/users/${USER_ID}`)

    expect(await screen.findByRole('heading', { name: 'Profile' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Account actions' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save sign-in binding' })).not.toBeInTheDocument()
  })
})
