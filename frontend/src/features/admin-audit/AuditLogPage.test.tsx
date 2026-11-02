import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiError,
  auditorMe,
  makeAuditEvent,
  mockApi,
  page,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

describe('AuditLogPage', () => {
  it('lists events with text outcomes and expandable before/after values', async () => {
    mockApi({
      'GET /auth/me/': { body: auditorMe() },
      'GET /audit/events/': {
        body: page([
          makeAuditEvent(),
          makeAuditEvent({
            id: 'e2',
            action: 'auth.login',
            outcome: 'failure',
            actor_label: 'unknown.user',
            actor_id: null,
            object_label: '',
            object_type: 'user',
            before: null,
            after: null,
            detail: 'invalid credentials',
          }),
        ]),
      },
    })

    renderApp('/admin/audit')

    const table = await screen.findByRole('table', { name: /Audit events/ })
    expect(within(table).getByText('Success')).toBeInTheDocument()
    expect(within(table).getByText('Failure')).toBeInTheDocument()

    const [details] = within(table).getAllByRole('button', { name: 'Details' })
    fireEvent.click(details)
    expect(details).toHaveAttribute('aria-expanded', 'true')
    const changes = screen.getByRole('table', { name: /Recorded values/ })
    const rolesRow = within(changes).getByRole('row', { name: /roles/ })
    expect(rolesRow).toHaveTextContent('asset_operator, auditor')
    expect(rolesRow).toHaveTextContent('(changed)')
    expect(screen.getByText('req-abc-123456')).toBeInTheDocument()
  })

  it('applies filters from the URL, including object scope from a user page', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: auditorMe() },
      'GET /audit/events/': { body: page([]) },
    })

    renderApp('/admin/audit?object_id=abc&outcome=failure')

    expect(await screen.findByText('No events match these filters.')).toBeInTheDocument()
    expect(screen.getByText(/Showing events for object/)).toBeInTheDocument()
    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/audit/events/').at(-1)!
      expect(last.search.get('object_id')).toBe('abc')
      expect(last.search.get('outcome')).toBe('failure')
    })
  })

  it('shows denied when the API refuses', async () => {
    mockApi({
      'GET /auth/me/': { body: auditorMe() },
      'GET /audit/events/': apiError(403, 'PERMISSION_DENIED', 'No.'),
    })

    renderApp('/admin/audit')

    expect(await screen.findByText(/do not have access to the audit log/i)).toBeInTheDocument()
  })
})
