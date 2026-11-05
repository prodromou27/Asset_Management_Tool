import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CAT_LAPTOP, CAT_WS, CATEGORIES, SITE_HQ, makeMe, mockApi, page, readerMe, renderApp } from '../test/api'

afterEach(() => vi.unstubAllGlobals())
const server = { ...CAT_WS, id: '77777777-7777-4777-8777-777777777701', code: 'servers', name: 'Servers', path: 'Servers' }
const printer = { ...server, id: '77777777-7777-4777-8777-777777777702', code: 'printers', name: 'Printers', path: 'Printers' }
const roots = [...CATEGORIES, server, printer, { ...server, id: 'lab', code: 'lab-equipment', name: 'Lab equipment' }, { ...server, id: 'inactive', name: 'Inactive type', is_active: false }]
const routes = {
  'GET /auth/me/': { body: readerMe() },
  'GET /asset-categories/': { body: roots },
  'GET /sites/': { body: [SITE_HQ] },
  'GET /assets/': { body: page([]) },
  'GET /saved-views/': { body: [] },
}

describe('asset type navigation', () => {
  it('uses active root categories and opens the existing category-filtered list', async () => {
    const { calls } = mockApi(routes)
    renderApp('/assets')
    const link = await screen.findByRole('link', { name: 'Workstations' })
    expect(screen.getByRole('link', { name: 'Servers' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Printers' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Lab equipment' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(within(nav).queryByRole('link', { name: 'Laptop' })).not.toBeInTheDocument()
    expect(within(nav).queryByText('Inactive type')).not.toBeInTheDocument()
    fireEvent.click(link)
    expect(await screen.findByRole('heading', { name: 'Workstations', level: 1 })).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((call) => call.path === '/assets/').at(-1)?.search.get('category')).toBe(CAT_WS.id))
    expect(screen.getByRole('link', { name: 'Workstations' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Assets' })).not.toHaveAttribute('aria-current')
  })

  it('highlights the parent type for a child filter and returns to all assets', async () => {
    const { calls } = mockApi(routes)
    renderApp(`/assets?category=${CAT_LAPTOP.id}`)
    expect(await screen.findByRole('heading', { name: 'Laptop', level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Workstations' })).toHaveAttribute('aria-current', 'page')
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Primary' })).getByRole('link', { name: 'Assets' }))
    expect(await screen.findByRole('heading', { name: 'Assets', level: 1 })).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((call) => call.path === '/assets/').at(-1)?.search.has('category')).toBe(false))
  })

  it('does not request or expose types without asset-view permission', async () => {
    const { calls } = mockApi({ 'GET /auth/me/': { body: makeMe({ permissions: [] }) }, 'GET /health/ready/': { body: { status: 'ok', dependencies: {} } } })
    renderApp('/')
    await screen.findByRole('navigation', { name: 'Primary' })
    expect(screen.queryByText('Asset types')).not.toBeInTheDocument()
    expect(calls.some((call) => call.path === '/asset-categories/')).toBe(false)
  })

  it('shows a retryable metadata error without inventing categories', async () => {
    let attempts = 0
    mockApi({ ...routes, 'GET /asset-categories/': () => ++attempts === 1 ? { status: 503, body: { error: { message: 'Unavailable' } } } : { body: roots } })
    renderApp('/assets')
    expect(await screen.findByText(/Asset types unavailable/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Servers' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findByRole('link', { name: 'Servers' })).toBeInTheDocument()
  })
})
