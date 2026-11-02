import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { auditorMe, makeMe, makeSecurity, mockApi, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

describe('SecuritySettingsPage', () => {
  it('is read-only without the manage permission', async () => {
    mockApi({
      'GET /auth/me/': { body: auditorMe() },
      'GET /settings/security/': { body: makeSecurity() },
    })

    renderApp('/admin/security')

    expect(await screen.findByLabelText('Idle timeout (minutes)')).toBeDisabled()
    expect(screen.getByRole('note')).toHaveTextContent('Read-only')
    expect(screen.queryByRole('button', { name: 'Save policy' })).not.toBeInTheDocument()
  })

  it('rejects out-of-range values locally', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /settings/security/': { body: makeSecurity() },
    })
    renderApp('/admin/security')

    const field = await screen.findByLabelText('Minimum password length (characters)')
    fireEvent.change(field, { target: { value: '8' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('from 12 to 128')
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
  })

  it('sends only changed fields with If-Match and confirms the save', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /settings/security/': { body: makeSecurity({ version: 3 }) },
      'PATCH /settings/security/': {
        body: makeSecurity({ lockout_threshold: 4, version: 4, modified_by: 'admin.one' }),
      },
    })
    renderApp('/admin/security')

    const field = await screen.findByLabelText('Failed attempts before lockout (attempts)')
    fireEvent.change(field, { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save policy' }))

    expect(await screen.findByText('Security policy saved.')).toBeInTheDocument()
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.body).toEqual({ lockout_threshold: 4 })
      expect(patch.headers['If-Match']).toBe('"3"')
    })
    expect(screen.getByText(/by admin\.one/)).toBeInTheDocument()
  })
})
