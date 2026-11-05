import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { makeMe, mockApi, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())
const operations = {
  checked_at: '2026-11-05T12:00:00Z', production_readiness: 'incomplete',
  components: [{ id: 'workers', label: 'Workers and scheduler', status: 'unknown', detail: 'No worker heartbeat available.', href: '/' }],
  integrations: [{ id: 'fixture', label: 'Synthetic source', status: 'disabled', detail: 'Disabled; no successful sync implied.', href: '/admin/integrations/fixture' }],
  queues: [{ name: 'Imports', queued: 0, running: 1, failed: 2, worker_status: 'unknown' }],
  checklist: [{ id: 'https', label: 'Trusted HTTPS', status: 'unknown', detail: 'Verify on staging.', href: '/admin/security' }],
}
const ready = { status: 'ok', dependencies: { database: { status: 'up', detail: '' }, redis: { status: 'up', detail: '' } } }

describe('Operational diagnostics', () => {
  it('distinguishes infrastructure reachability from incomplete production readiness', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe({ permissions: ['health.view'] }) },
      'GET /health/ready/': { body: ready },
      'GET /health/operations/': { body: operations },
    })
    renderApp('/')
    const panel = await screen.findByRole('region', { name: 'Production readiness' })
    expect(within(panel).getByText('Incomplete')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Synthetic source' })).not.toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Durable jobs' })).getByText('Unknown')).toBeInTheDocument()
    fireEvent.click(within(panel).getByRole('button', { name: 'Refresh diagnostics' }))
    expect(calls.filter((call) => call.path === '/health/operations/').length).toBeGreaterThanOrEqual(1)
  })

  it('does not request protected diagnostics without health permission', async () => {
    const { calls } = mockApi({ 'GET /auth/me/': { body: makeMe({ permissions: [] }) }, 'GET /health/ready/': { body: ready } })
    renderApp('/')
    await screen.findByText('database')
    expect(calls.some((call) => call.path === '/health/operations/')).toBe(false)
    expect(screen.queryByRole('region', { name: 'Production readiness' })).not.toBeInTheDocument()
  })
})
