import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeMe, mockApi, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const policy = { enabled: false, hour_utc: 2, rpo_hours: 24, rto_hours: 4, keep_daily: 30, keep_weekly: 8, keep_monthly: 12, retention_enabled: false, version: 1, modified_at: '2026-11-05T00:00:00Z' }
const summary = { execution_allowed: false, target_label: 'Not configured', encryption: 'Restic encryption', off_host: 'SFTP required', last_backup: null, last_drill: null, problems: ['Setup incomplete (DEC-09).'] }
function routes(permissions = ['backups.view', 'backups.manage']) {
  return {
    'GET /auth/me/': { body: makeMe({ permissions }) },
    'GET /backups/policy/': { body: policy },
    'GET /backups/summary/': { body: summary },
    'GET /backups/jobs/': { body: [] },
    'GET /backups/drills/': { body: [] },
  }
}

describe('backups and recovery', () => {
  it('shows incomplete setup without fabricated backup success', async () => {
    mockApi(routes())
    renderApp('/admin/backups')
    expect(await screen.findByRole('heading', { name: 'Backups & Recovery', level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back up now' })).toBeDisabled()
    expect(screen.getByText('Setup incomplete (DEC-09).')).toBeInTheDocument()
    expect(screen.getByText('No backup jobs yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download summary' })).toHaveAttribute('href', '/api/v1/backups/report/')
  })

  it('allows policy edits with optimistic locking', async () => {
    const { calls } = mockApi({ ...routes(), 'PATCH /backups/policy/': { body: { ...policy, version: 2 } } })
    renderApp('/admin/backups')
    fireEvent.click(await screen.findByRole('button', { name: 'Edit policy' }))
    fireEvent.change(screen.getByLabelText('RPO objective (hours)'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }))
    await screen.findByText('Backup policy saved.')
    expect(calls.find((c) => c.method === 'PATCH')?.headers['If-Match']).toBe('"1"')
  })

  it('keeps auditor access read-only and denies users without permission', async () => {
    mockApi(routes(['backups.view']))
    const view = renderApp('/admin/backups')
    await screen.findByRole('heading', { level: 1 })
    expect(screen.queryByRole('button', { name: 'Edit policy' })).not.toBeInTheDocument()
    view.unmount()
    mockApi(routes([]))
    renderApp('/admin/backups')
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to backups and recovery')
  })

  it('requires confirmation, queues a backup and shows durable progress', async () => {
    const { calls } = mockApi({ ...routes(), 'GET /backups/summary/': { body: { ...summary, execution_allowed: true } }, 'POST /backups/jobs/': { status: 202, body: { id: 'job', status: 'queued' } } })
    renderApp('/admin/backups')
    fireEvent.click(await screen.findByRole('button', { name: 'Back up now' }))
    const dialog = screen.getByRole('dialog', { name: 'Create encrypted backup' })
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Queue operation' }))
    await waitFor(() => expect(screen.getByText(/Operation queued/)).toBeInTheDocument())
  })
})
