import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EntitlementAllocation, LicenseEntitlement, LicenseProductDetail } from '../../shared/api/types'
import { ASSET_ID, makeMe, mockApi, page, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const PRODUCT = '11111111-1111-4111-8111-111111111101'
const ENT = '22222222-2222-4222-8222-222222222201'
const ALLOC = '33333333-3333-4333-8333-333333333301'

function product(overrides: Partial<LicenseProductDetail> = {}): LicenseProductDetail {
  return {
    id: PRODUCT,
    publisher: 'Example Software Corp',
    name: 'Example CAD',
    sku: 'ECAD-1Y',
    metric: 'user',
    software_product: { id: 10, publisher: 'Example Software Corp', name: 'Example CAD' },
    note: '',
    is_active: true,
    purchased: 25,
    allocated: 27,
    available: -2,
    entitlements_in_term: 1,
    observed_assets: 31,
    version: 1,
    modified_at: '2026-11-04T08:00:00Z',
    entitlements: [],
    ...overrides,
  }
}

function entitlement(overrides: Partial<LicenseEntitlement> = {}): LicenseEntitlement {
  return {
    id: ENT,
    product: { id: PRODUCT, label: 'Example Software Corp Example CAD (ECAD-1Y)', metric: 'user' },
    reference: 'PO-1001',
    quantity: 25,
    starts_on: '2026-01-01',
    ends_on: '2026-12-31',
    supplier: 'Example Reseller Ltd',
    owner: 'Engineering',
    note: '',
    source: 'manual',
    status: 'active',
    allocated: 27,
    available: -2,
    retired_at: null,
    retired_by: null,
    retired_reason: '',
    version: 3,
    created_by: 'admin.one',
    created_at: '2026-11-01T08:00:00Z',
    modified_at: '2026-11-01T08:00:00Z',
    ...overrides,
  }
}

function allocation(overrides: Partial<EntitlementAllocation> = {}): EntitlementAllocation {
  return {
    id: ALLOC,
    entitlement: {
      id: ENT,
      reference: 'PO-1001',
      product_id: PRODUCT,
      product_label: 'Example Software Corp Example CAD (ECAD-1Y)',
    },
    target: 'asset',
    asset: { id: ASSET_ID, name: 'ws-hq-01', site_code: 'HQ' },
    user_name: '',
    units: 1,
    note: '',
    allocated_at: '2026-11-02T08:00:00Z',
    allocated_by: 'admin.one',
    ended_at: null,
    ended_by: null,
    ended_reason: '',
    ...overrides,
  }
}

const viewer = () => makeMe({ permissions: ['assets.view', 'licenses.view'] })

describe('Entitlements tab', () => {
  it('keeps purchased, allocated, available and installed totals apart', async () => {
    const { entitlements: _, ...listed } = product()
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /licenses/products/': {
        body: page([
          listed,
          { ...listed, id: 'p2', name: 'Viewer', software_product: null, observed_assets: null, available: 3 },
        ]),
      },
    })
    renderApp('/software?tab=entitlements')

    const table = await screen.findByRole('table', { name: 'License products' })
    const cad = within(table).getByRole('link', { name: 'Example CAD' }).closest('tr')!
    expect(within(cad).getByText('25')).toBeInTheDocument()
    expect(within(cad).getByText('27')).toBeInTheDocument()
    expect(within(cad).getByText('2 more allocated than purchased')).toBeInTheDocument()
    expect(within(cad).getByText('31')).toBeInTheDocument()
    const viewerRow = within(table).getByRole('link', { name: 'Viewer' }).closest('tr')!
    expect(within(viewerRow).getByText('Not linked')).toBeInTheDocument()
    expect(screen.getByText(/does not judge license compliance/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New license product' })).toBeInTheDocument()
  })

  it('offers no changes without licenses.manage', async () => {
    mockApi({
      'GET /auth/me/': { body: viewer() },
      'GET /licenses/products/': { body: page([]) },
    })
    renderApp('/software?tab=entitlements')
    await screen.findByText('No license products recorded.')
    expect(screen.queryByRole('button', { name: 'New license product' })).not.toBeInTheDocument()
  })
})

describe('License product page', () => {
  it('records an entitlement, allocates to a named user and retires with If-Match', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /licenses/products/${PRODUCT}/`]: { body: product({ entitlements: [entitlement()] }) },
      'GET /licenses/entitlement-allocations/': { body: page([allocation()]) },
      'POST /licenses/entitlements/': { status: 201, body: entitlement({ id: 'new', reference: 'PO-2002' }) },
      [`POST /licenses/entitlements/${ENT}/allocations/`]: {
        status: 201,
        body: allocation({ target: 'user', asset: null, user_name: 'a.user@example.test' }),
      },
      [`POST /licenses/entitlements/${ENT}/retire/`]: { body: entitlement({ status: 'retired' }) },
    })
    renderApp(`/software/licenses/${PRODUCT}`)

    const totals = await screen.findByLabelText('Totals')
    expect(within(totals).getByText('2 more allocated than purchased')).toBeInTheDocument()
    expect(within(totals).getByRole('link', { name: '31' })).toHaveAttribute('href', '/software/products/10')

    fireEvent.click(screen.getByRole('button', { name: 'Record entitlement' }))
    let dialog = await screen.findByRole('dialog', { name: 'Record entitlement' })
    fireEvent.change(within(dialog).getByLabelText('Reference'), { target: { value: 'PO-2002' } })
    fireEvent.change(within(dialog).getByLabelText('Purchased units'), { target: { value: '10' } })
    fireEvent.change(within(dialog).getByLabelText('Ends on (optional)'), { target: { value: '2027-06-30' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save entitlement' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/licenses/entitlements/')!
      expect(post.body).toMatchObject({
        product: PRODUCT,
        reference: 'PO-2002',
        quantity: 10,
        starts_on: null,
        ends_on: '2027-06-30',
      })
    })

    const ents = screen.getByRole('table', { name: 'Entitlements' })
    fireEvent.click(within(ents).getByRole('button', { name: 'Allocate…' }))
    dialog = await screen.findByRole('dialog', { name: 'Allocate from PO-1001' })
    fireEvent.change(within(dialog).getByLabelText('User'), { target: { value: 'a.user@example.test' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Allocate' }))
    await waitFor(() => {
      const post = calls.find((c) => c.path === `/licenses/entitlements/${ENT}/allocations/`)!
      expect(post.body).toEqual({ user_name: 'a.user@example.test', units: 1, note: '' })
    })

    fireEvent.click(within(ents).getByRole('button', { name: 'Retire…' }))
    dialog = await screen.findByRole('dialog', { name: 'Retire PO-1001' })
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Contract cancelled' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Retire entitlement' }))
    await waitFor(() => {
      const post = calls.find((c) => c.path === `/licenses/entitlements/${ENT}/retire/`)!
      expect(post.headers['If-Match']).toBe('"3"')
      expect(post.body).toEqual({ reason: 'Contract cancelled' })
    })
  })
})

describe('Allocations tab', () => {
  it('lists asset and named-user allocations and ends one with a reason', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /licenses/entitlement-allocations/': {
        body: page([
          allocation(),
          allocation({ id: 'a2', target: 'user', asset: null, user_name: 'b.user@example.test' }),
        ]),
      },
      [`POST /licenses/entitlement-allocations/${ALLOC}/end/`]: {
        body: allocation({ ended_at: '2026-11-04T09:00:00Z' }),
      },
    })
    renderApp('/software?tab=allocations')

    const table = await screen.findByRole('table', { name: 'Allocations' })
    expect(within(table).getByRole('link', { name: 'ws-hq-01' })).toHaveAttribute('href', `/assets/${ASSET_ID}`)
    expect(within(table).getByText('b.user@example.test')).toBeInTheDocument()
    fireEvent.click(within(table).getAllByRole('button', { name: 'End…' })[0])
    const dialog = await screen.findByRole('dialog', { name: 'End allocation' })
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: 'Asset retired' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'End allocation' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.path).toBe(`/licenses/entitlement-allocations/${ALLOC}/end/`)
      expect(post.body).toEqual({ reason: 'Asset retired' })
    })
  })
})
