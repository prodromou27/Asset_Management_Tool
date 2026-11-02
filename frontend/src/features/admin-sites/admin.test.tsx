import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  CATEGORIES,
  CAT_SWITCH,
  DEPT,
  ROOM,
  ROLES,
  SITE_BR,
  SITE_HQ,
  apiError,
  makeField,
  makeMe,
  makeUser,
  mockApi,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const admin = { 'GET /auth/me/': { body: makeMe() } }

describe('Categories & fields', () => {
  it('lists the hierarchy and creates a child category', async () => {
    const { calls } = mockApi({
      ...admin,
      'GET /asset-categories/': { body: CATEGORIES },
      'POST /asset-categories/': { status: 201, body: CATEGORIES[1] },
    })
    renderApp('/admin/categories')

    expect(await screen.findByRole('button', { name: 'Switch' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add category' }))
    const dialog = screen.getByRole('dialog', { name: 'Add category' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'SD-WAN Edge' } })
    fireEvent.change(within(dialog).getByLabelText('Parent'), { target: { value: CATEGORIES[0].id } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add category' }))

    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
        name: 'SD-WAN Edge',
        parent: CATEGORIES[0].id,
        description: '',
      }),
    )
  })

  it('shows own and inherited fields and validates a choice field', async () => {
    const { calls } = mockApi({
      ...admin,
      'GET /asset-categories/': { body: CATEGORIES },
      [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: ({ url }) => ({
        body:
          url.searchParams.get('effective') === 'true'
            ? [makeField(), makeField({ id: 'inh', category: CATEGORIES[0].id, key: 'rack_units', label: 'Rack units', required: false })]
            : [makeField()],
      }),
      [`POST /asset-categories/${CAT_SWITCH.id}/fields/`]: { status: 201, body: makeField({ id: 'n' }) },
    })
    renderApp(`/admin/categories?category=${CAT_SWITCH.id}`)

    expect(await screen.findByRole('heading', { name: 'Fields for Networking / Switch' })).toBeInTheDocument()
    expect(await screen.findByText('Inherited from parent categories')).toBeInTheDocument()
    expect(screen.getByText('Rack units')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add field' }))
    const dialog = screen.getByRole('dialog', { name: /Add field to Switch/ })
    fireEvent.change(within(dialog).getByLabelText('Label'), { target: { value: 'Tier' } })
    fireEvent.change(within(dialog).getByLabelText('Key'), { target: { value: 'tier' } })
    fireEvent.change(within(dialog).getByLabelText('Type'), { target: { value: 'choice' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add field' }))
    expect(within(dialog).getByText('Add at least one choice.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'POST')).toBe(false)

    fireEvent.change(within(dialog).getByLabelText('Choices (one per line)'), { target: { value: 'core\naccess\n' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add field' }))
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
        key: 'tier',
        label: 'Tier',
        field_type: 'choice',
        choices: ['core', 'access'],
        required: false,
      }),
    )
  })

  it('is denied without categories.manage', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe({ permissions: ['assets.view'] }) } })

    renderApp('/admin/categories')

    expect(await screen.findByText(/do not have access to category administration/i)).toBeInTheDocument()
  })
})

describe('Sites, locations & departments', () => {
  it('lists sites with locations and creates a site', async () => {
    const { calls } = mockApi({
      ...admin,
      'GET /sites/': { body: [SITE_HQ, { ...SITE_BR, is_active: false }] },
      'GET /locations/': { body: [ROOM] },
      'GET /departments/': { body: [DEPT] },
      'POST /sites/': apiError(422, 'VALIDATION_ERROR', 'The submitted data is invalid.', {
        code: ['This site code is already in use.'],
      }),
    })
    renderApp('/admin/sites')

    expect(await screen.findByRole('heading', { name: 'Locations in HQ' })).toBeInTheDocument()
    expect(await screen.findByRole('cell', { name: 'Server room' })).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add site' }))
    const dialog = screen.getByRole('dialog', { name: 'Add site' })
    fireEvent.change(within(dialog).getByLabelText('Code'), { target: { value: 'hq' } })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Duplicate' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add site' }))

    expect(await within(dialog).findByText('This site code is already in use.')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ code: 'hq', name: 'Duplicate', parent: null })
  })
})

describe('User site access', () => {
  it('grants specific sites with If-Match', async () => {
    const user = makeUser()
    const { calls } = mockApi({
      ...admin,
      'GET /roles/': { body: ROLES },
      'GET /sites/': { body: [SITE_HQ, SITE_BR] },
      [`GET /users/${user.id}/`]: { body: user },
      [`PATCH /users/${user.id}/`]: {
        body: makeUser({ version: 2, sites: [{ id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' }] }),
      },
    })
    renderApp(`/admin/users/${user.id}`)

    const panel = (await screen.findByRole('heading', { name: 'Site access' })).closest('section')!
    expect(within(panel).getByText('With no sites, this user cannot see any assets.')).toBeInTheDocument()
    fireEvent.click(await within(panel).findByRole('checkbox', { name: /HQ — Headquarters/ }))
    fireEvent.click(within(panel).getByRole('button', { name: 'Save site access' }))

    expect(await screen.findByText(/Site access saved/)).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.headers['If-Match']).toBe('"1"')
    expect(patch.body).toEqual({ all_sites: false, site_ids: [SITE_HQ.id] })
  })
})
