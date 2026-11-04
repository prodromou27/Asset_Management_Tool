import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type {
  AssetLifecycle,
  LifecycleAssessment,
  LifecycleMatch,
  LifecycleProductDetail,
} from '../../shared/api/types'
import { ASSET_ID, SITE_HQ, makeAsset, makeMe, mockApi, page, readerMe, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const PRODUCT_ID = '88888888-8888-4888-8888-888888888801'
const MILESTONE_ID = '88888888-8888-4888-8888-888888888802'
const SOURCE = {
  id: '88888888-8888-4888-8888-888888888803',
  publisher: 'Example vendor',
  title: 'EOL bulletin EX-1 (fictitious)',
  url: 'https://vendor.example/eol/ex-1',
  source_type: 'vendor' as const,
  collected_on: '2026-10-01',
  last_verified_on: null,
}
const assetRef = {
  id: ASSET_ID,
  name: 'sw-core-01',
  site: { id: SITE_HQ.id, code: 'HQ', name: 'Headquarters' },
  manufacturer: 'Example Networks',
  model: 'EX-48',
  os_name: 'ExOS',
  os_version: '9.1',
  firmware_version: '',
}
const productRef = { id: PRODUCT_ID, kind: 'hardware' as const, vendor: 'Example Networks', name: 'EX-48', release: '', label: 'Example Networks EX-48' }

function assessment(overrides: Partial<LifecycleAssessment> = {}): LifecycleAssessment {
  return {
    id: 'a1',
    asset: assetRef,
    dimension: 'hardware',
    status: 'eos',
    effective_status: 'eos',
    product: productRef,
    support_level: 'ended',
    milestone_type: 'end_of_standard_support',
    milestone_date: '2026-10-31',
    days_remaining: -4,
    threshold_days: null,
    evidence_quality: 'vendor',
    milestone_ids: [MILESTONE_ID],
    reasons: ['Exact match: Example Networks EX-48.', 'End of standard support was 2026-10-31.'],
    exception: null,
    assessed_at: '2026-11-04T08:00:00Z',
    ...overrides,
  }
}

const milestone = {
  id: MILESTONE_ID,
  milestone_type: 'end_of_standard_support' as const,
  date: '2026-10-31',
  source: SOURCE,
  verification: 'verified' as const,
  reviewed_by: 'admin.one',
  reviewed_at: '2026-11-01T09:00:00Z',
  notes: '',
  created_by: 'admin.one',
  created_at: '2026-11-01T08:00:00Z',
  version: 2,
}

function match(overrides: Partial<LifecycleMatch> = {}): LifecycleMatch {
  return {
    id: 'm1',
    asset: assetRef,
    dimension: 'hardware',
    state: 'matched',
    method: 'exact',
    product: productRef,
    observed: { manufacturer: { value: 'Example Networks', source: null }, model: { value: 'EX-48', source: null } },
    candidates: [],
    reason: 'Matched model.',
    rejected_products: [],
    reviewed_by: null,
    reviewed_at: null,
    review_note: '',
    modified_at: '2026-11-04T08:00:00Z',
    version: 1,
    ...overrides,
  }
}

function assetLifecycle(overrides: Partial<AssetLifecycle> = {}): AssetLifecycle {
  return {
    assessments: [
      assessment(),
      assessment({
        id: 'a2',
        dimension: 'os',
        status: 'unknown',
        effective_status: 'unknown',
        product: null,
        support_level: '',
        milestone_type: '',
        milestone_date: null,
        days_remaining: null,
        evidence_quality: '',
        milestone_ids: [],
        reasons: ["Operating system 'ExOS' is not in the catalogue."],
      }),
    ],
    matches: [match()],
    exceptions: [],
    history: [],
    evidence: [milestone],
    ...overrides,
  }
}

const lifecycleReader = () => makeMe({ ...readerMe(), permissions: ['assets.view', 'lifecycle.view'] })

describe('Asset lifecycle tab', () => {
  it('shows status, governing date, evidence and Unknown dimensions', async () => {
    mockApi({
      'GET /auth/me/': { body: lifecycleReader() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /assets/${ASSET_ID}/lifecycle/`]: { body: assetLifecycle() },
    })
    renderApp(`/assets/${ASSET_ID}?tab=lifecycle`)

    const panel = await screen.findByRole('region', { name: 'Lifecycle' })
    expect(within(panel).getByText('End of support')).toBeInTheDocument()
    expect(within(panel).getByText('Unknown')).toBeInTheDocument()
    expect(within(panel).getByText(/31 Oct 2026 \(4 days ago\)/)).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: SOURCE.title })).toHaveAttribute('href', SOURCE.url)
    expect(within(panel).getByText(/not in the catalogue/)).toBeInTheDocument()
    expect(within(panel).getByText(/does not reflect your maintenance contract/)).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Record exception…' })).not.toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Reassess' })).not.toBeInTheDocument()
  })

  it('records an exception that keeps the vendor evidence visible', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /assets/${ASSET_ID}/lifecycle/`]: { body: assetLifecycle() },
      'GET /lifecycle/policy/': {
        body: { warning_days: [180, 90], count_extended_support: false, max_exception_days: 365, today: '2026-11-04' },
      },
      [`POST /assets/${ASSET_ID}/lifecycle/exceptions/`]: { status: 201, body: { id: 'x1' } },
    })
    renderApp(`/assets/${ASSET_ID}?tab=lifecycle`)

    const panel = await screen.findByRole('region', { name: 'Lifecycle' })
    fireEvent.click(within(panel).getAllByRole('button', { name: 'Record exception…' })[0])
    const dialog = await screen.findByRole('dialog', { name: 'Lifecycle exception: Hardware' })
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Isolated lab switch' } })
    fireEvent.change(within(dialog).getByLabelText('Expires on'), { target: { value: '2026-12-31' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve exception' }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.body).toEqual({
        dimension: 'hardware',
        status: 'supported',
        reason: 'Isolated lab switch',
        compensating_controls: '',
        expires_on: '2026-12-31',
      })
    })
  })

  it('shows an overridden status next to what the evidence says', async () => {
    mockApi({
      'GET /auth/me/': { body: lifecycleReader() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /assets/${ASSET_ID}/lifecycle/`]: {
        body: assetLifecycle({
          assessments: [
            assessment({
              effective_status: 'supported',
              exception: { id: 'x1', status: 'supported', expires_on: '2026-12-31', approved_by: 'hq.manager' },
            }),
          ],
        }),
      },
    })
    renderApp(`/assets/${ASSET_ID}?tab=lifecycle`)

    const panel = await screen.findByRole('region', { name: 'Lifecycle' })
    expect(within(panel).getByText('Supported')).toBeInTheDocument()
    expect(within(panel).getByText('Evidence says: End of support')).toBeInTheDocument()
    expect(within(panel).getByText(/until 31 Dec 2026, approved by hq.manager/)).toBeInTheDocument()
  })

  it('hides the tab without lifecycle access', async () => {
    mockApi({
      'GET /auth/me/': { body: readerMe() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
    })
    renderApp(`/assets/${ASSET_ID}`)

    await screen.findByRole('tablist', { name: 'Asset sections' })
    expect(screen.queryByRole('tab', { name: 'Lifecycle' })).not.toBeInTheDocument()
  })
})

const lifecycleHome = {
  'GET /lifecycle/policy/': {
    body: { warning_days: [180, 90], count_extended_support: false, max_exception_days: 365, today: '2026-11-04' },
  },
  'GET /lifecycle/summary/': {
    body: [
      { dimension: 'hardware', effective_status: 'eos', count: 3 },
      { dimension: 'os', effective_status: 'unknown', count: 7 },
    ],
  },
}

describe('Lifecycle page', () => {
  it('lists findings with totals and sends filters', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: lifecycleReader() },
      ...lifecycleHome,
      'GET /lifecycle/findings/': { body: page([assessment()]) },
    })
    renderApp('/lifecycle')

    const table = await screen.findByRole('table', { name: /Lifecycle findings/ })
    expect(within(table).getByRole('link', { name: 'sw-core-01' })).toHaveAttribute('href', `/assets/${ASSET_ID}?tab=lifecycle`)
    expect(within(table).getByText('End of standard support')).toBeInTheDocument()
    expect(within(table).getByText('4 days ago')).toBeInTheDocument()
    const kpis = screen.getByLabelText(/Lifecycle totals/)
    expect(within(kpis).getByText('3')).toBeInTheDocument()
    expect(within(kpis).getByText('7')).toBeInTheDocument()
    expect(screen.getByText(/Missing evidence is Unknown, never Supported/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reassess all' })).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'eos,security_maintenance_ended' } })
    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/lifecycle/findings/').at(-1)!
      expect(last.search.get('status')).toBe('eos,security_maintenance_ended')
    })
  })

  it('approves a suggested match and remembers the alias', async () => {
    const candidate = match({
      state: 'candidate',
      method: 'none',
      product: null,
      version: 4,
      reason: 'No exact catalogue entry.',
      candidates: [{ product_id: PRODUCT_ID, label: 'Example Networks EX-48', reason: 'Model differs by a revision or suffix' }],
    })
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...lifecycleHome,
      'GET /lifecycle/matches/': { body: page([candidate]) },
      'POST /lifecycle/matches/m1/approve/': { body: match() },
    })
    renderApp('/lifecycle?tab=review')

    const table = await screen.findByRole('table', { name: 'Review queue' })
    expect(within(table).getByText(/Model differs by a revision/)).toBeInTheDocument()
    fireEvent.click(within(table).getByRole('button', { name: 'Approve…' }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve match for sw-core-01' })
    expect(within(dialog).getByLabelText(/Example Networks EX-48/)).toBeChecked()
    expect(within(dialog).getByLabelText(/Remember as an approved alias/)).toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve match' }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.headers['If-Match']).toBe('"4"')
      expect(post.body).toEqual({ product: PRODUCT_ID, remember_alias: true, note: '' })
    })
  })

  it('denies the page without lifecycle access', async () => {
    mockApi({ 'GET /auth/me/': { body: readerMe() } })
    renderApp('/lifecycle')
    expect(await screen.findByText(/do not have access to lifecycle/i)).toBeInTheDocument()
  })
})

function product(overrides: Partial<LifecycleProductDetail> = {}): LifecycleProductDetail {
  return {
    id: PRODUCT_ID,
    kind: 'hardware',
    dimension: 'hardware',
    vendor: 'Example Networks',
    name: 'EX-48',
    release: '',
    family: 'EX',
    description: '',
    support_statement: '',
    is_active: true,
    milestones_verified: 0,
    milestones_pending: 1,
    alias_count: 0,
    matched_assets: 1,
    modified_at: '2026-11-04T08:00:00Z',
    version: 3,
    statement_source: null,
    statement_verified_by: null,
    statement_verified_at: null,
    aliases: [],
    milestones: [{ ...milestone, verification: 'pending', reviewed_by: null, reviewed_at: null, version: 1 }],
    created_by: 'hq.engineer',
    created_at: '2026-11-04T08:00:00Z',
    modified_by: 'hq.engineer',
    ...overrides,
  }
}

const productRoutes = {
  [`GET /lifecycle/products/${PRODUCT_ID}/`]: { body: product() },
  [`GET /lifecycle/products/${PRODUCT_ID}/assets/`]: { body: page([assessment()]) },
  [`GET /lifecycle/products/${PRODUCT_ID}/revisions/`]: {
    body: [{ number: 1, action: 'product.create', summary: 'Created', snapshot: {}, actor: 'hq.engineer', created_at: '2026-11-04T08:00:00Z' }],
  },
  'GET /lifecycle/sources/': { body: [SOURCE] },
}

describe('Catalogue product page', () => {
  it('verifies a pending date with If-Match', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...productRoutes,
      [`POST /lifecycle/milestones/${MILESTONE_ID}/review/`]: { body: milestone },
    })
    renderApp(`/lifecycle/catalogue/${PRODUCT_ID}`)

    const table = await screen.findByRole('table', { name: 'Lifecycle milestones' })
    expect(within(table).getByText('Awaiting verification')).toBeInTheDocument()
    expect(within(table).getByRole('link', { name: SOURCE.title })).toHaveAttribute('href', SOURCE.url)
    fireEvent.click(within(table).getByRole('button', { name: 'Verify' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.headers['If-Match']).toBe('"1"')
      expect(post.body).toEqual({ decision: 'verified', note: '' })
    })
    expect(screen.getByText(/#1/)).toBeInTheDocument()
  })

  it('lets an engineer add dates but not verify them', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': {
        body: makeMe({ permissions: ['assets.view', 'lifecycle.view', 'lifecycle.manage'] }),
      },
      ...productRoutes,
      [`POST /lifecycle/products/${PRODUCT_ID}/milestones/`]: { status: 201, body: product() },
    })
    renderApp(`/lifecycle/catalogue/${PRODUCT_ID}`)

    const table = await screen.findByRole('table', { name: 'Lifecycle milestones' })
    expect(within(table).queryByRole('button', { name: 'Verify' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Add date' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add lifecycle date' })
    fireEvent.change(within(dialog).getByLabelText('Milestone'), { target: { value: 'end_of_sale' } })
    fireEvent.change(within(dialog).getByLabelText('Date'), { target: { value: '2027-01-31' } })
    fireEvent.change(await within(dialog).findByLabelText('Source'), { target: { value: SOURCE.id } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add date' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.body).toEqual({ milestone_type: 'end_of_sale', date: '2027-01-31', source: SOURCE.id, notes: '' })
    })
  })

  it('only offers catalogue changes to authorised roles', async () => {
    mockApi({ 'GET /auth/me/': { body: lifecycleReader() }, ...productRoutes })
    renderApp(`/lifecycle/catalogue/${PRODUCT_ID}`)

    await screen.findByRole('table', { name: 'Lifecycle milestones' })
    for (const name of ['Add date', 'Edit details', 'Reassess assets', 'Verify', 'Add alias']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
  })
})
