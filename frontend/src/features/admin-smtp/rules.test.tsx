import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { NotificationRule } from '../../shared/api/types'
import { SITE_HQ, makeMe, mockApi, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const STATS = {
  counts: { queued: 0, sending: 0, retrying: 0, sent: 0, dead: 0, cancelled: 0, expired: 0 },
  oldest_waiting_at: null,
  dead_last_24h: 0,
  problems: [],
  enabled: true,
  configured: true,
}
const OWNER = {
  id: '55555555-5555-4555-8555-555555555501',
  username: 'web.owner',
  display_name: 'Web Owner',
  has_email: true,
}
const NOMAIL = {
  id: '55555555-5555-4555-8555-555555555502',
  username: 'no.mail',
  display_name: 'No Mail',
  has_email: false,
}

function rule(overrides: Partial<NotificationRule> = {}): NotificationRule {
  return {
    id: 'r1',
    name: 'Certificate owners',
    event: 'certificate_expiry',
    enabled: true,
    thresholds: [90, 30, 7],
    include_expired: true,
    failure_count: 3,
    recipients: [OWNER, NOMAIL],
    sites: [],
    version: 2,
    last_run_at: '2026-11-04T09:00:00Z',
    last_run_summary: '1 message(s), 2 new item(s)',
    modified_at: '2026-11-04T09:00:00Z',
    ...overrides,
  }
}

describe('Notification rules', () => {
  it('lists rules and creates a lifecycle rule with recipients and sites', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /notifications/outbox/stats/': { body: STATS },
      'GET /notifications/rules/': { body: [rule()] },
      'GET /notifications/recipients/': { body: [OWNER, NOMAIL] },
      'GET /sites/': { body: [SITE_HQ] },
      'POST /notifications/rules/': { status: 201, body: rule({ id: 'r2', event: 'lifecycle_eol' }) },
    })
    renderApp('/admin/smtp?tab=rules')
    const table = await screen.findByRole('table', { name: 'Rules' })
    expect(within(table).getByText('90, 30, 7 days before; when expired')).toBeInTheDocument()
    expect(within(table).getByText('Some recipients have no e-mail address')).toBeInTheDocument()
    expect(within(table).getByText('1 message(s), 2 new item(s)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'New rule' }))
    const dialog = await screen.findByRole('dialog', { name: 'New notification rule' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'HQ lifecycle' } })
    fireEvent.change(within(dialog).getByLabelText('Alert about'), { target: { value: 'lifecycle_eol' } })
    expect(within(dialog).getByLabelText('Days before')).toHaveValue('365, 180, 90, 30, 7')
    fireEvent.click(await within(dialog).findByLabelText('Web Owner'))
    fireEvent.click(await within(dialog).findByLabelText(/^HQ/))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save rule' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.body).toMatchObject({
        name: 'HQ lifecycle',
        event: 'lifecycle_eol',
        thresholds: [365, 180, 90, 30, 7],
        recipients: [OWNER.id],
        sites: [SITE_HQ.id],
      })
    })
  })

  it('previews without sending and edits with If-Match', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /notifications/outbox/stats/': { body: STATS },
      'GET /notifications/rules/': { body: [rule()] },
      'GET /notifications/recipients/': { body: [OWNER, NOMAIL] },
      'GET /sites/': { body: [SITE_HQ] },
      'POST /notifications/rules/r1/preview/': {
        body: {
          mail_enabled: true,
          recipients: [
            {
              user: OWNER,
              eligible: true,
              reason: '',
              pending: 1,
              items: [{ title: 'vpn.example.test', detail: '', date: '2026-11-20', status: '16 days left' }],
            },
            { user: NOMAIL, eligible: false, reason: 'No e-mail address', pending: 0, items: [] },
          ],
        },
      },
      'PATCH /notifications/rules/r1/': { body: rule({ version: 3 }) },
    })
    renderApp('/admin/smtp?tab=rules')
    const table = await screen.findByRole('table', { name: 'Rules' })
    fireEvent.click(within(table).getByRole('button', { name: 'Preview' }))
    const preview = await screen.findByRole('dialog', { name: 'Preview: Certificate owners' })
    expect(await within(preview).findByText('vpn.example.test: 16 days left (2026-11-20)')).toBeInTheDocument()
    expect(within(preview).getByText(/skipped \(No e-mail address\)/)).toBeInTheDocument()
    fireEvent.click(within(preview).getByRole('button', { name: 'Close' }))

    fireEvent.click(within(table).getByRole('button', { name: 'Edit…' }))
    const dialog = await screen.findByRole('dialog', { name: 'Edit Certificate owners' })
    expect(within(dialog).getByLabelText('Alert about')).toBeDisabled()
    fireEvent.change(within(dialog).getByLabelText('Days before'), { target: { value: '30, 7' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save rule' }))
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.headers['If-Match']).toBe('"2"')
      expect(patch.body).toMatchObject({ thresholds: [30, 7] })
    })
  })

  it('hides changes without notifications.manage', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe({ permissions: ['notifications.view'] }) },
      'GET /notifications/outbox/stats/': { body: STATS },
      'GET /notifications/rules/': { body: [rule()] },
    })
    renderApp('/admin/smtp?tab=rules')
    await screen.findByRole('table', { name: 'Rules' })
    expect(screen.queryByRole('button', { name: 'New rule' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Preview' })).not.toBeInTheDocument()
  })
})
