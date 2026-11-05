import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, makeMe, mockApi, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())
const base = { report: 'inventory', label: 'Inventory breakdown', note: 'Current authorized data only.', generated_at: '2026-11-05T12:00:00Z', count: 1, columns: [{ key: 'label', label: 'Breakdown' }, { key: 'total', label: 'Assets' }], rows: [{ label: 'Headquarters', total: 2 }], offset: 0, limit: 50 }
const schedule = { id: 'schedule-1', report: 'lifecycle', filters: { site: 'site-1' }, cadence: 'daily', hour_utc: 7, weekday: 0, enabled: true, version: 1, created_at: '2026-11-05T00:00:00Z', modified_at: '2026-11-05T00:00:00Z' }
function routes(permissions = ['reports.view', 'assets.view', 'groups.view', 'lifecycle.view', 'discovery.view', 'reports.schedule']) {
  return { 'GET /auth/me/': { body: makeMe({ permissions }) }, 'GET /sites/': { body: [{ id: 'site-1', name: 'Headquarters', code: 'HQ' }] }, 'GET /groups/': { body: [] }, 'GET /reports/inventory/': { body: base }, 'GET /reports/schedules/': { body: [] } }
}

describe('Reports', () => {
  it('shows scoped totals and sends site filters to the server', async () => {
    const { calls } = mockApi(routes())
    renderApp('/reports')
    expect(await screen.findByRole('table', { name: 'Report results' })).toHaveTextContent('Headquarters')
    fireEvent.change(screen.getByLabelText('Site'), { target: { value: 'site-1' } })
    await waitFor(() => expect(calls.some((call) => call.path === '/reports/inventory/' && call.search.get('site') === 'site-1')).toBe(true))
    expect(await screen.findByText(/Current authorized data only/)).toBeInTheDocument()
  })

  it('preserves Unknown lifecycle states and offers explicit coverage gaps', async () => {
    mockApi({ ...routes(), 'GET /reports/lifecycle/': { body: { ...base, report: 'lifecycle', columns: [{ key: 'name', label: 'Asset' }, { key: 'status', label: 'Status' }], rows: [{ id: 'asset-1', name: 'Unknown switch', status: 'unknown' }] } }, 'GET /reports/coverage/': { body: { ...base, report: 'coverage', note: 'Not proof of agent absence.' } } })
    renderApp('/reports?report=lifecycle')
    expect(await screen.findByText('Unknown')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Report'), { target: { value: 'coverage' } })
    expect(await screen.findByLabelText('Coverage filter')).toBeInTheDocument()
    expect(await screen.findByText(/Not proof of agent absence/)).toBeInTheDocument()
  })

  it('waits for private saved filters before requesting scheduled report data', async () => {
    const { calls } = mockApi({ ...routes(), 'GET /reports/schedules/schedule-1/': { body: schedule }, 'GET /reports/lifecycle/': { body: { ...base, report: 'lifecycle' } } })
    renderApp('/reports?schedule=schedule-1')
    await screen.findByRole('table', { name: 'Report results' })
    expect(calls.some((call) => call.path === '/reports/inventory/')).toBe(false)
    expect(calls.find((call) => call.path === '/reports/lifecycle/')?.search.get('site')).toBe('site-1')
  })

  it('creates a self-only schedule and disables it with a version guard', async () => {
    let schedules: unknown[] = []
    const { calls } = mockApi({ ...routes(), 'GET /reports/schedules/': () => ({ body: schedules }),
      'POST /reports/schedules/': () => { schedules = [schedule]; return { status: 201, body: schedule } },
      'PATCH /reports/schedules/schedule-1/': { body: { ...schedule, enabled: false, version: 2 } },
    })
    renderApp('/reports')
    fireEvent.click(await screen.findByRole('button', { name: 'Schedule digest' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Schedule digest' })).toBeEnabled())
    // The initial button may render while report data is loading.
    if (!screen.queryByRole('dialog')) fireEvent.click(screen.getByRole('button', { name: 'Schedule digest' }))
    expect(screen.getByText(/No inventory rows or attachments/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Create schedule' }))
    const disable = await screen.findByRole('button', { name: /Disable schedule-1/ })
    fireEvent.click(disable)
    await waitFor(() => expect(calls.some((call) => call.method === 'PATCH')).toBe(true))
    expect(calls.find((call) => call.method === 'PATCH')?.headers['If-Match']).toBe('"1"')
    expect(calls.find((call) => call.method === 'POST')?.body).not.toHaveProperty('recipient')
  })

  it('shows denied and backend error states', async () => {
    mockApi(routes([]))
    const view = renderApp('/reports')
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to reports')
    view.unmount()
    mockApi({ ...routes(), 'GET /reports/inventory/': apiError(503, 'UNAVAILABLE', 'Report unavailable.') })
    renderApp('/reports')
    expect(await screen.findByRole('alert')).toHaveTextContent('Report unavailable.')
  })
})
