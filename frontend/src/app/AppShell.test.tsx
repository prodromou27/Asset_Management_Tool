import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CATEGORIES, SITE_HQ, makeMe, mockApi, operatorMe, page, readerMe, renderApp } from '../test/api'
import { locate } from './navigation'

const readyOk = { body: { status: 'ok', dependencies: {} } }

afterEach(() => vi.unstubAllGlobals())

describe('locate', () => {
  it.each([
    ['/', 'System', 'System health'],
    ['/assets', 'Inventory', 'Assets'],
    ['/assets/123/edit', 'Inventory', 'Assets'],
    ['/imports/new', 'Sources', 'Imports'],
    ['/admin/users/42', 'Administration', 'Users & roles'],
    ['/account/password', 'Account', 'Change password'],
  ])('places %s under %s / %s', (path, section, pageLabel) => {
    expect(locate(path)).toEqual({ section, page: pageLabel })
  })

  it('does not treat a shared prefix as a match', () => {
    expect(locate('/assetsx')).toEqual({})
  })
})

describe('application shell', () => {
  it('moves focus into the account panel and restores it on Escape', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe() }, 'GET /health/ready/': readyOk })
    renderApp('/')
    const trigger = await screen.findByRole('button', { expanded: false, name: /admin/i })
    fireEvent.click(trigger)
    expect(screen.getByRole('link', { name: 'Change password' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(trigger).toHaveFocus()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('System health')
  })
  it('keeps the session visible when sign out fails and allows a retry', async () => {
    let attempts = 0
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /health/ready/': readyOk,
      'GET /health/operations/': { body: { checked_at: '2026-11-05T12:00:00Z', production_readiness: 'incomplete', components: [], integrations: [], queues: [], checklist: [] } },
      'POST /auth/logout/': () => ++attempts === 1
        ? { status: 503, body: { error: { message: 'Fixture network failure' } } }
        : { status: 204 },
      'GET /auth/providers/': { body: [] },
      'GET /auth/csrf/': { body: {} },
    })
    renderApp('/')
    fireEvent.click(await screen.findByRole('button', { name: /admin/i, expanded: false }))
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Your session may still be active')
    expect(screen.getByRole('heading', { level: 1, name: 'System health' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'System health' })).not.toBeInTheDocument())
    expect(attempts).toBe(2)
  })
  it('keeps the sidebar selected on certificate detail routes', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /certificates/fixture/': { status: 404, body: { error: { message: 'Not found' } } },
    })
    renderApp('/certificates/fixture')
    const nav = await screen.findByRole('navigation', { name: 'Primary' })
    expect(within(nav).getByRole('link', { name: 'Domains & Certificates' })).toHaveClass('nav-link--active')
    expect(within(nav).getByRole('link', { name: 'Domains & Certificates' })).toHaveAttribute('aria-current', 'page')
  })
  it('groups navigation into labelled sections and shows where the user is', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe() }, 'GET /health/ready/': readyOk })

    renderApp('/')

    const nav = await screen.findByRole('navigation', { name: 'Primary' })
    for (const label of ['Inventory', 'Sources', 'Administration', 'System']) {
      expect(within(nav).getByText(label)).toBeInTheDocument()
    }
    expect(within(nav).getByRole('link', { name: 'System health' })).toHaveClass('nav-link--active')
    expect(screen.getByText('System', { selector: '.top-bar__section' })).toBeInTheDocument()
    expect(screen.getByText('System health', { selector: '.top-bar__page' })).toBeInTheDocument()
  })

  it('shows initials and roles in the user menu', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe() }, 'GET /health/ready/': readyOk })

    renderApp('/')

    const trigger = await screen.findByRole('button', { expanded: false, name: /admin/i })
    expect(trigger.querySelector('.avatar')?.textContent).toMatch(/^[A-Z]{1,2}$/)
    fireEvent.click(trigger)
    expect(screen.getByRole('link', { name: 'Change password' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('searches assets from the top bar', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: readerMe() },
      'GET /health/ready/': readyOk,
      'GET /asset-categories/': { body: CATEGORIES },
      'GET /sites/': { body: [SITE_HQ] },
      'GET /assets/': { body: page([]) },
    })

    renderApp('/')

    const search = await screen.findByRole('searchbox', { name: 'Search assets' })
    fireEvent.change(search, { target: { value: '  sw-core ' } })
    fireEvent.submit(screen.getByRole('search'))

    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/assets/').at(-1)
      expect(last?.search.get('q')).toBe('sw-core')
    })
  })

  it('hides the asset search from users who cannot view assets', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe({ permissions: [] }) },
      'GET /health/ready/': readyOk,
    })

    renderApp('/')

    await screen.findByRole('navigation', { name: 'Primary' })
    expect(screen.queryByRole('searchbox', { name: 'Search assets' })).not.toBeInTheDocument()
  })

  it('opens and closes the navigation drawer on small screens', async () => {
    mockApi({ 'GET /auth/me/': { body: operatorMe() }, 'GET /health/ready/': readyOk })

    renderApp('/')

    const toggle = await screen.findByRole('button', { name: 'Open navigation' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    toggle.focus()
    fireEvent.click(toggle)
    expect(screen.getByRole('button', { name: 'Close navigation' })).toHaveFocus()
    expect(document.querySelector<HTMLElement>('.app-shell__body')?.inert).toBe(true)
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(screen.getByRole('link', { name: 'System health' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(screen.getByRole('button', { name: 'Close navigation' })).toHaveFocus()
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(document.querySelector<HTMLElement>('.app-shell__body')?.inert).toBe(false)
    expect(toggle).toHaveFocus()
    fireEvent.click(toggle)
    fireEvent.click(screen.getByRole('button', { name: 'Close navigation' }))
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })
})

describe('nested navigation entries', () => {
  it('highlights only the catalogue on catalogue pages', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /lifecycle/products/': { body: page([]) },
    })

    renderApp('/lifecycle/catalogue')

    const nav = await screen.findByRole('navigation', { name: 'Primary' })
    expect(within(nav).getByRole('link', { name: 'Lifecycle catalogue' })).toHaveClass('nav-link--active')
    expect(within(nav).getByRole('link', { name: 'Lifecycle' })).not.toHaveClass('nav-link--active')
  })
})
