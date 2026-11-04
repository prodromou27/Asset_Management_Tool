import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { NotificationTemplate, OutboxMessage, OutboxStats, SmtpProfile } from '../../shared/api/types'
import { apiError, auditorMe, makeMe, mockApi, page, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

function profile(overrides: Partial<SmtpProfile> = {}): SmtpProfile {
  return {
    enabled: false,
    host: 'smtp.internal.example',
    port: 587,
    security: 'starttls',
    username: 'itam',
    password_ref: 'env:ITAM_SMTP_PASSWORD',
    password_status: 'configured',
    ca_bundle_ref: '',
    from_address: 'itam-alerts@example.test',
    from_name: 'ITAM',
    reply_to: '',
    timeout_seconds: 15,
    max_per_minute: 60,
    last_test_at: null,
    last_test_ok: null,
    last_test_error: '',
    last_test_email_at: null,
    version: 4,
    modified_by: 'admin.one',
    modified_at: '2026-11-04T08:00:00Z',
    ...overrides,
  }
}

function stats(overrides: Partial<OutboxStats> = {}): OutboxStats {
  return {
    counts: { queued: 0, sending: 0, retrying: 0, sent: 3, dead: 0, cancelled: 0, expired: 0 },
    oldest_waiting_at: null,
    dead_last_24h: 0,
    problems: [],
    enabled: true,
    configured: true,
    ...overrides,
  }
}

function message(overrides: Partial<OutboxMessage> = {}): OutboxMessage {
  return {
    id: 'm1',
    event_type: 'smtp.test',
    template_code: 'smtp_test',
    template_version: 1,
    to_address: 'admin.one@example.test',
    subject: 'ITAM test message',
    message_id: '<1@example.test>',
    status: 'sent',
    attempts: 1,
    max_attempts: 6,
    next_attempt_at: '2026-11-04T08:00:00Z',
    last_error: '',
    queued_at: '2026-11-04T08:00:00Z',
    sent_at: '2026-11-04T08:00:01Z',
    finished_at: '2026-11-04T08:00:01Z',
    expires_at: '2026-11-07T08:00:00Z',
    ...overrides,
  }
}

const template: NotificationTemplate = {
  id: 1,
  code: 'smtp_test',
  name: 'SMTP test message',
  description: 'Sent by Send test email.',
  variables: [{ name: 'requested_by', description: 'Administrator', example: 'Admin One' }],
  subject: '{{ app_name }} test message',
  body_text: 'Hello {{ requested_by }}',
  body_html: '',
  version: 1,
  modified_by: null,
  modified_at: '2026-11-04T08:00:00Z',
}

describe('SMTP settings', () => {
  it('saves with If-Match, never shows a password and tests the connection', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /settings/smtp/': { body: profile() },
      'GET /notifications/outbox/stats/': { body: stats() },
      'PATCH /settings/smtp/': { body: profile({ version: 5, port: 465, security: 'tls' }) },
      'POST /smtp/test/': {
        body: profile({
          last_test_at: '2026-11-04T09:00:00Z',
          last_test_ok: false,
          last_test_error: '535 Authentication failed',
        }),
      },
    })
    renderApp('/admin/smtp')
    const form = await screen.findByRole('region', { name: 'Mail settings' })
    expect(within(form).getByText('Password available')).toBeInTheDocument()
    expect(within(form).getByText('Disabled')).toBeInTheDocument()
    fireEvent.click(within(form).getByRole('button', { name: 'Test connection' }))
    expect(await within(form).findByText(/535 Authentication failed/)).toBeInTheDocument()

    fireEvent.change(within(form).getByLabelText('Port'), { target: { value: '465' } })
    fireEvent.change(within(form).getByLabelText('Security'), { target: { value: 'tls' } })
    expect(within(form).getByRole('button', { name: 'Test connection' })).toBeDisabled() // unsaved
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.headers['If-Match']).toBe('"4"')
      expect(patch.body).toMatchObject({ port: 465, security: 'tls', password_ref: 'env:ITAM_SMTP_PASSWORD' })
      expect(patch.body).not.toHaveProperty('password')
    })
  })

  it('sends the test email only to the signed-in admin and shows the result', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /settings/smtp/': { body: profile({ enabled: true }) },
      'GET /notifications/outbox/stats/': { body: stats() },
      'POST /smtp/test-email/': { body: message() },
    })
    renderApp('/admin/smtp')
    const form = await screen.findByRole('region', { name: 'Mail settings' })
    expect(within(form).getByText(/goes only to you \(admin\.one@example\.test\)/)).toBeInTheDocument()
    fireEvent.click(within(form).getByRole('button', { name: 'Send test email' }))
    expect(await within(form).findByText('Test message sent to admin.one@example.test.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')!.body).toBeUndefined()
  })

  it('is read-only for the auditor and shows delivery problems', async () => {
    mockApi({
      'GET /auth/me/': {
        body: makeMe({ ...auditorMe(), permissions: [...auditorMe().permissions, 'notifications.view'] }),
      },
      'GET /settings/smtp/': { body: profile({ enabled: true }) },
      'GET /notifications/outbox/stats/': {
        body: stats({ problems: ['2 message(s) failed permanently in the last 24 hours.'] }),
      },
    })
    renderApp('/admin/smtp')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('failed permanently')
    await screen.findByRole('region', { name: 'Mail settings' })
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Host')).toBeDisabled()
  })

  it('shows the save error from the server', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /settings/smtp/': { body: profile() },
      'GET /notifications/outbox/stats/': { body: stats() },
      'PATCH /settings/smtp/': apiError(
        422,
        'VALIDATION_ERROR',
        'Credentials are only sent over STARTTLS or implicit TLS; choose one.',
        {
          security: ['Credentials are only sent over STARTTLS or implicit TLS; choose one.'],
        },
      ),
    })
    renderApp('/admin/smtp')
    const form = await screen.findByRole('region', { name: 'Mail settings' })
    fireEvent.change(within(form).getByLabelText('Security'), { target: { value: 'none' } })
    fireEvent.click(within(form).getByRole('button', { name: 'Save' }))
    expect((await within(form).findAllByText(/only sent over STARTTLS/)).length).toBeGreaterThan(0)
  })
})

describe('Templates and queue', () => {
  it('previews a draft and saves it with If-Match', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /notifications/outbox/stats/': { body: stats() },
      'GET /notifications/templates/': { body: [template] },
      'POST /notifications/templates/smtp_test/preview/': {
        body: { subject: 'ITAM check', body_text: 'Hello Admin One\n', body_html: '' },
      },
      'PATCH /notifications/templates/smtp_test/': { body: { ...template, version: 2 } },
    })
    renderApp('/admin/smtp?tab=templates')
    const editor = await screen.findByRole('region', { name: 'Template SMTP test message' })
    fireEvent.change(within(editor).getByLabelText('Subject'), { target: { value: '{{ app_name }} check' } })
    fireEvent.click(within(editor).getByRole('button', { name: 'Preview' }))
    expect(await within(editor).findByText('ITAM check')).toBeInTheDocument()
    fireEvent.click(within(editor).getByRole('button', { name: 'Save template' }))
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.headers['If-Match']).toBe('"1"')
      expect(patch.body).toMatchObject({ subject: '{{ app_name }} check' })
    })
  })

  it('lists the queue and retries a failed message', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /notifications/outbox/stats/': { body: stats() },
      'GET /notifications/outbox/': {
        body: page([
          message({ id: 'dead1', status: 'dead', attempts: 6, last_error: '550 5.1.1 No such user', sent_at: null }),
          message({ id: 'wait1', status: 'retrying', attempts: 2, last_error: 'Connection refused', sent_at: null }),
        ]),
      },
      'POST /notifications/outbox/dead1/retry/': { body: message({ id: 'dead1', status: 'queued' }) },
    })
    renderApp('/admin/smtp?tab=queue')
    const table = await screen.findByRole('table', { name: 'Messages' })
    expect(within(table).getByText('550 5.1.1 No such user')).toBeInTheDocument()
    expect(within(table).getByText('Waiting to retry')).toBeInTheDocument()
    expect(within(table).getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    fireEvent.click(within(table).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/notifications/outbox/dead1/retry/')).toBe(true))
  })
})
