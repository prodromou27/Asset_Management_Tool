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
    fireEvent.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    fireEvent.click(screen.getByRole('button', { name: 'Close navigation' }))
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })
})
