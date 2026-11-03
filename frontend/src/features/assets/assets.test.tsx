import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ASSET_ID,
  CATEGORIES,
  CAT_LAPTOP,
  CAT_SWITCH,
  DEPT,
  ROOM,
  SITE_BR,
  SITE_HQ,
  apiError,
  assetOperatorMe,
  makeAsset,
  makeField,
  makeMe,
  mockApi,
  operatorMe,
  page,
  readerMe,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const reference = {
  'GET /asset-categories/': { body: CATEGORIES },
  'GET /sites/': { body: [SITE_HQ, SITE_BR] },
}

describe('Assets list', () => {
  it('shows assets with text statuses and honest empty values', async () => {
    mockApi({
      'GET /auth/me/': { body: assetOperatorMe() },
      ...reference,
      'GET /assets/': {
        body: page([
          makeAsset(),
          makeAsset({
            id: 'a2',
            name: 'Reception TV',
            asset_tag: null,
            serial_number: '',
            primary_ip: null,
            primary_hostname: null,
            manufacturer: '',
            model: '',
            support_status: 'eos',
          }),
        ]),
      },
    })

    renderApp('/assets')

    const table = await screen.findByRole('table', { name: 'Assets' })
    expect(within(table).getByRole('link', { name: 'sw-core-01' })).toHaveAttribute(
      'href',
      `/assets/${ASSET_ID}`,
    )
    expect(within(table).getByText('End of support')).toBeInTheDocument()
    expect(within(table).getAllByText('Unknown').length).toBeGreaterThan(0)
    expect(within(table).getByText('Not recorded')).toBeInTheDocument()
    expect(within(table).getByText('None')).toBeInTheDocument()
    expect(screen.getByText('2 assets')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Add asset' })).toBeInTheDocument()
  })

  it('puts filters in the URL and sends them to the API', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: readerMe() },
      ...reference,
      'GET /assets/': { body: page([]) },
    })

    renderApp('/assets?q=core')
    expect(await screen.findByText('No assets match these filters.')).toBeInTheDocument()
    fireEvent.change(await screen.findByLabelText('Site'), { target: { value: SITE_HQ.id } })
    fireEvent.change(screen.getByLabelText('Archived'), { target: { value: 'include' } })

    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/assets/').at(-1)!
      expect(last.search.get('q')).toBe('core')
      expect(last.search.get('site')).toBe(SITE_HQ.id)
      expect(last.search.get('archived')).toBe('include')
    })
    expect(screen.queryByRole('link', { name: 'Add asset' })).not.toBeInTheDocument()
  })

  it('shows the empty state', async () => {
    mockApi({ 'GET /auth/me/': { body: readerMe() }, ...reference, 'GET /assets/': { body: page([]) } })

    renderApp('/assets')

    expect(await screen.findByText('No assets yet.')).toBeInTheDocument()
  })

  it('hides Assets navigation and denies the page without assets.view', async () => {
    mockApi({ 'GET /auth/me/': { body: operatorMe() } })

    renderApp('/assets')

    expect(await screen.findByText(/do not have access to assets/i)).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Primary' })
    expect(within(nav).queryByRole('link', { name: 'Assets' })).not.toBeInTheDocument()
  })

  it('shows 404 from an out-of-scope asset as an error, not data', async () => {
    mockApi({
      'GET /auth/me/': { body: readerMe() },
      [`GET /assets/${ASSET_ID}/`]: apiError(404, 'NOT_FOUND', 'Not found.'),
    })

    renderApp(`/assets/${ASSET_ID}`)

    expect(await screen.findByText('Could not load this asset.')).toBeInTheDocument()
  })
})

describe('Asset detail', () => {
  const detailRoutes = (asset = makeAsset(), me = makeMe()) => ({
    'GET /auth/me/': { body: me },
    [`GET /assets/${ASSET_ID}/`]: { body: asset },
    [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
    [`GET /assets/${ASSET_ID}/network-evidence/`]: { body: [] },
    [`GET /assets/${ASSET_ID}/history/`]: {
      body: page([
        {
          id: 'e1',
          occurred_at: '2026-11-02T09:00:00Z',
          actor_label: 'hq.manager',
          change_type: 'reassigned',
          changes: { site: { before: 'BR1', after: 'HQ' } },
          reason: '',
          version: 3,
          request_id: 'r1',
        },
      ]),
    },
    ...reference,
  })

  it('labels all three status dimensions and shows custom fields', async () => {
    mockApi(detailRoutes())

    renderApp(`/assets/${ASSET_ID}`)

    const strip = await screen.findByLabelText('Status')
    expect(strip).toHaveTextContent('Business')
    expect(strip).toHaveTextContent('Deployed')
    expect(strip).toHaveTextContent('Observation')
    expect(strip).toHaveTextContent('Manual only')
    expect(strip).toHaveTextContent('Support')
    expect(strip).toHaveTextContent('Unknown')
    expect(await screen.findByText('Port count')).toBeInTheDocument()
    expect(screen.getByText('48')).toBeInTheDocument()
  })

  it('switches tabs with the keyboard and shows evidence sources', async () => {
    mockApi(detailRoutes())
    renderApp(`/assets/${ASSET_ID}`)

    const overview = await screen.findByRole('tab', { name: 'Overview' })
    fireEvent.keyDown(overview, { key: 'ArrowRight' })

    const network = screen.getByRole('tab', { name: 'Network' })
    expect(network).toHaveAttribute('aria-selected', 'true')
    expect(network).toHaveFocus()
    const panel = screen.getByRole('tabpanel')
    expect(within(panel).getByText('LibreNMS')).toBeInTheDocument()
    expect(within(panel).getByText('317')).toBeInTheDocument()

    fireEvent.keyDown(network, { key: 'End' })
    expect(await screen.findByText('Reassigned')).toBeInTheDocument()
    expect(screen.getByText(/BR1/)).toHaveTextContent('BR1 → changed to HQ')
  })

  it('archived assets show the reason and no edit action', async () => {
    mockApi(
      detailRoutes(
        makeAsset({
          is_archived: true,
          archived_at: '2026-11-02T10:00:00Z',
          archived_by: 'hq.manager',
          archive_reason: 'Disposed via WEEE',
        }),
      ),
    )

    renderApp(`/assets/${ASSET_ID}`)

    expect(await screen.findByText(/Disposed via WEEE/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument()
  })

  it('read-only users get no actions', async () => {
    mockApi(detailRoutes(makeAsset(), readerMe()))

    renderApp(`/assets/${ASSET_ID}`)

    await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Change category' })).not.toBeInTheDocument()
  })

  it('archive requires a reason and sends If-Match', async () => {
    const { calls } = mockApi({
      ...detailRoutes(),
      [`POST /assets/${ASSET_ID}/archive/`]: { body: makeAsset({ is_archived: true, version: 4 }) },
    })
    renderApp(`/assets/${ASSET_ID}`)

    fireEvent.click(await screen.findByRole('button', { name: 'Archive' }))
    const dialog = screen.getByRole('dialog', { name: 'Archive sw-core-01?' })
    expect(dialog).toHaveTextContent('Affects 1 asset.')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Archive asset' }))
    expect(within(dialog).getByText(/at least 5 characters/)).toBeInTheDocument()

    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Disposed via WEEE' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Archive asset' }))

    expect(await screen.findByText(/sw-core-01 archived/)).toBeInTheDocument()
    const call = calls.find((c) => c.path.endsWith('/archive/'))!
    expect(call.headers['If-Match']).toBe('"3"')
    expect(call.body).toEqual({ reason: 'Disposed via WEEE' })
  })

  it('reclassify previews impact, collects newly required fields and a reason', async () => {
    const screenField = makeField({
      id: 'f2',
      category: CAT_LAPTOP.id,
      key: 'screen_inches',
      label: 'Screen size',
      field_type: 'decimal',
    })
    const { calls } = mockApi({
      ...detailRoutes(),
      [`POST /assets/${ASSET_ID}/classification/preview/`]: {
        body: {
          from_category: 'Networking / Switch',
          to_category: 'Workstations / Laptop',
          fields_added: [{ key: 'screen_inches', label: 'Screen size', required: true }],
          fields_kept: [],
          values_retained_read_only: ['port_count'],
          required_missing: ['screen_inches'],
        },
      },
      [`GET /asset-categories/${CAT_LAPTOP.id}/fields/`]: { body: [screenField] },
      [`POST /assets/${ASSET_ID}/classification/`]: {
        body: makeAsset({ category: { id: CAT_LAPTOP.id, name: 'Laptop', path: 'Workstations / Laptop' }, version: 4 }),
      },
    })
    renderApp(`/assets/${ASSET_ID}`)

    fireEvent.click(await screen.findByRole('button', { name: 'Change category' }))
    const dialog = screen.getByRole('dialog', { name: /Change category of/ })
    await within(dialog).findByRole('option', { name: /Laptop/ })
    fireEvent.change(within(dialog).getByLabelText('New category'), { target: { value: CAT_LAPTOP.id } })

    expect(await within(dialog).findByText(/Retained read-only: port_count/)).toBeInTheDocument()
    fireEvent.change(await within(dialog).findByLabelText('Screen size (required)'), { target: { value: '14' } })
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Mis-registered at intake' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change category' }))

    expect(await screen.findByText('Category changed to Workstations / Laptop.')).toBeInTheDocument()
    const call = calls.find((c) => c.path.endsWith('/classification/') && c.method === 'POST')!
    expect(call.headers['If-Match']).toBe('"3"')
    expect(call.body).toEqual({
      category: CAT_LAPTOP.id,
      reason: 'Mis-registered at intake',
      custom_fields: { screen_inches: '14' },
    })
  })
})

describe('Asset form', () => {
  const formRoutes = {
    'GET /auth/me/': { body: assetOperatorMe() },
    ...reference,
    [`GET /locations/`]: { body: [ROOM] },
    'GET /departments/': { body: [DEPT] },
    'GET /users/lookup/': { body: [{ id: 'u1', username: 'jane.doe', display_name: 'Jane Doe' }] },
    [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
  }

  it('validates required fields and category-required custom fields locally', async () => {
    const { calls } = mockApi(formRoutes)
    renderApp('/assets/new')

    fireEvent.change(await screen.findByLabelText('Category'), { target: { value: CAT_SWITCH.id } })
    await screen.findByLabelText('Port count (required)')
    fireEvent.click(screen.getByRole('button', { name: 'Register asset' }))

    const summary = await screen.findByRole('alert')
    expect(summary).toHaveFocus()
    expect(summary).toHaveTextContent('Name: Enter a name.')
    expect(summary).toHaveTextContent('Site: Choose a site.')
    expect(summary).toHaveTextContent('Port count: Port count is required.')
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('submits a typed payload and maps nested server errors to the row', async () => {
    const { calls } = mockApi({
      ...formRoutes,
      'POST /assets/': apiError(422, 'VALIDATION_ERROR', 'The submitted data is invalid.', {
        'hostnames.0.hostname': ['Enter a valid hostname (letters, digits, hyphens and dots).'],
      }),
    })
    renderApp('/assets/new')

    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'sw-core-02' } })
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: CAT_SWITCH.id } })
    fireEvent.change(screen.getByLabelText('Site'), { target: { value: SITE_HQ.id } })
    fireEvent.change(await screen.findByLabelText('Port count (required)'), { target: { value: '24' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add hostname' }))
    fireEvent.change(screen.getByLabelText('Hostname 1'), { target: { value: 'bad_host!' } })
    fireEvent.click(screen.getByRole('button', { name: 'Register asset' }))

    await waitFor(() => expect(screen.getByLabelText('Hostname 1')).toHaveAttribute('aria-invalid', 'true'))
    expect(screen.getAllByText(/Enter a valid hostname/).length).toBeGreaterThan(0)
    const body = calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>
    expect(body).toMatchObject({
      name: 'sw-core-02',
      category: CAT_SWITCH.id,
      site: SITE_HQ.id,
      asset_tag: null,
      location: null,
      owner: null,
      business_status: 'in_stock',
      custom_fields: { port_count: '24' },
      hostnames: [{ hostname: 'bad_host!', is_primary: true }],
      interfaces: [],
      ip_addresses: [],
    })
  })

  it('edits with If-Match, keeps only manual identifiers, and reports conflicts', async () => {
    const { calls } = mockApi({
      ...formRoutes,
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`PATCH /assets/${ASSET_ID}/`]: apiError(409, 'VERSION_MISMATCH', 'This record was changed by someone else. Reload and try again.'),
    })
    renderApp(`/assets/${ASSET_ID}/edit`)

    fireEvent.change(await screen.findByLabelText('Model'), { target: { value: 'EX-48P' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    expect(await screen.findByText(/Someone else changed this asset/)).toBeInTheDocument()
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.headers['If-Match']).toBe('"3"')
    const body = patch.body as Record<string, unknown>
    expect(body.model).toBe('EX-48P')
    expect(body).not.toHaveProperty('category')
    // The LibreNMS hostname is not sent back; only the manual one is managed here.
    expect(body.hostnames).toEqual([{ hostname: 'sw-core-01.corp.example', is_primary: true }])
  })
})
