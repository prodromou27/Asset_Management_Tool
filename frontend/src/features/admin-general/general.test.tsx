import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiError, makeMe, mockApi, renderApp } from '../../test/api'
import { configureDisplay, formatDate, formatDateTime, getDisplayTimezoneWarning } from '../../shared/format'

afterEach(() => { vi.unstubAllGlobals(); configureDisplay() })
const settings = { organization_name: 'ITAM', timezone: 'Asia/Nicosia', date_format: 'day_month_year', language: 'en', support_contact: '', version: 1, modified_by: null, modified_at: '2026-11-05T00:00:00Z' }
const routes = (permissions = ['settings.general.view', 'settings.general.manage']) => ({
  'GET /auth/me/': { body: makeMe({ permissions }) },
  'GET /settings/general/': { body: settings },
})

describe('General settings', () => {
  it('saves with If-Match, excludes response metadata, and updates organization branding', async () => {
    let display = makeMe().display_preferences
    const { calls } = mockApi({ ...routes(),
      'GET /auth/me/': () => ({ body: makeMe({ display_preferences: display }) }),
      'PATCH /settings/general/': ({ body }) => {
        display = { ...display, ...body as object }
        return { body: { ...settings, ...body as object, version: 2 } }
      },
    })
    renderApp('/admin/general')
    fireEvent.change(await screen.findByLabelText('Organization name'), { target: { value: 'Fixture Operations' } })
    fireEvent.change(screen.getByLabelText('Display timezone'), { target: { value: 'UTC' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save general settings' }))
    expect(await screen.findByText('General settings saved.')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTitle('Fixture Operations')).toBeInTheDocument())
    const request = calls.find((call) => call.method === 'PATCH')!
    expect(request.headers['If-Match']).toBe('"1"')
    expect(request.body).not.toHaveProperty('version')
    expect(request.body).not.toHaveProperty('modified_at')
  })

  it('keeps auditor settings read-only and denies unauthorized users', async () => {
    mockApi(routes(['settings.general.view']))
    const view = renderApp('/admin/general')
    expect(await screen.findByLabelText('Organization name')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save general settings' })).not.toBeInTheDocument()
    view.unmount()
    mockApi(routes([]))
    renderApp('/admin/general')
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to general settings')
  })

  it('shows field validation and keeps the entered draft', async () => {
    mockApi({ ...routes(), 'PATCH /settings/general/': apiError(422, 'VALIDATION_ERROR', 'Check the settings.', { timezone: ['Invalid IANA timezone.'] }) })
    renderApp('/admin/general')
    fireEvent.change(await screen.findByLabelText('Display timezone'), { target: { value: 'Invalid/Zone' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save general settings' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid IANA timezone.')
    expect(screen.getByLabelText('Display timezone')).toHaveValue('Invalid/Zone')
  })

  it('offers explicit reload on a stale edit', async () => {
    mockApi({ ...routes(), 'PATCH /settings/general/': apiError(409, 'CONFLICT', 'Settings changed. Reload before saving.') })
    renderApp('/admin/general')
    fireEvent.click(await screen.findByRole('button', { name: 'Save general settings' }))
    expect(await screen.findByRole('button', { name: 'Reload current settings' })).toBeInTheDocument()
  })
})

describe('Organization display formatting', () => {
  it('keeps dates usable with an explicit UTC warning for unsupported browser zones', () => {
    configureDisplay({ timezone: 'Fixture/UnsupportedZone', date_format: 'iso' })
    expect(formatDateTime('2026-11-05T00:30:00Z')).toBe('2026-11-05 00:30')
    expect(getDisplayTimezoneWarning()).toContain('shown in UTC')
  })
  it('uses the selected timezone/ISO format while preserving calendar dates', () => {
    configureDisplay({ timezone: 'America/Los_Angeles', date_format: 'iso' })
    expect(formatDateTime('2026-11-05T00:30:00Z')).toBe('2026-11-04 16:30')
    expect(formatDate('2026-11-05')).toBe('2026-11-05')
    expect(formatDate('2026-11-05T00:30:00Z')).toBe('2026-11-04')
  })
})
