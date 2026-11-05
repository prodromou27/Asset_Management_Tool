import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SoftwareInstallation, SoftwareProduct, SoftwareVersion } from '../../shared/api/types'
import {
  ASSET_ID,
  SITE_HQ,
  makeAsset,
  makeIntegration,
  makeMe,
  mockApi,
  page,
  readerMe,
  renderApp,
} from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

function install(overrides: Partial<SoftwareInstallation> = {}): SoftwareInstallation {
  return {
    id: 1,
    product_id: 10,
    publisher: 'Example Software Corp',
    name: 'Example Office Suite',
    version: '16.0.17928.20156',
    version_id: 100,
    lifecycle_status: 'eos',
    raw_publisher: 'Example Software Corp',
    raw_name: 'Example Office Suite',
    raw_version: '16.0.17928.20156',
    source: 'Endpoint Central',
    external_id: '301',
    asset: { id: ASSET_ID, name: 'sw-core-01', site_code: 'HQ' },
    installed_on: null,
    first_seen_at: '2026-11-01T08:00:00Z',
    last_seen_at: '2026-11-04T08:00:00Z',
    removed_at: null,
    removed_reason: '',
    created_by: null,
    note: '',
    ...overrides,
  }
}

function product(overrides: Partial<SoftwareProduct> = {}): SoftwareProduct {
  return { id: 10, publisher: 'Example Software Corp', name: 'Example Office Suite', version_count: 2, installations: 1284, eos_versions: 1, ...overrides }
}

function version(overrides: Partial<SoftwareVersion> = {}): SoftwareVersion {
  return {
    id: 100,
    version: '16.0.17928.20156',
    installations: 12,
    lifecycle_state: 'candidate',
    lifecycle_method: 'none',
    lifecycle_product: null,
    lifecycle_candidates: [
      { product_id: 'p-office-16', label: 'Example Software Corp Example Office Suite 16.0', reason: 'Version is a build or patch of this release' },
    ],
    lifecycle_status: 'unverified',
    lifecycle_milestone_type: '',
    lifecycle_milestone_date: null,
    lifecycle_days_remaining: null,
    lifecycle_evidence_quality: '',
    lifecycle_reasons: ["'Example Office Suite 16.0.17928.20156' is not catalogued exactly."],
    lifecycle_reviewed_by: null,
    lifecycle_reviewed_at: null,
    lifecycle_assessed_at: '2026-11-04T08:00:00Z',
    lifecycle_version: 3,
    ...overrides,
  }
}

const operator = () =>
  makeMe({ ...readerMe(), permissions: ['assets.view', 'assets.edit'] })

describe('Software page', () => {
  it('lists products with observed installation counts and lifecycle flags', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /software/products/': { body: page([product(), product({ id: 11, name: 'Legacy Viewer', publisher: '', eos_versions: 0, installations: 3 })]) },
    })
    renderApp('/software')

    const table = await screen.findByRole('table', { name: 'Software products' })
    expect(within(table).getByRole('link', { name: 'Example Office Suite' })).toHaveAttribute('href', '/software/products/10')
    expect(within(table).getByText('1,284')).toBeInTheDocument()
    expect(within(table).getByText('1 version past end of support')).toBeInTheDocument()
    expect(within(table).getByText('Not reported')).toBeInTheDocument()
    expect(screen.getByText(/not licenses/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Lifecycle'), { target: { value: 'ended' } })
    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/software/products/').at(-1)!
      expect(last.search.get('lifecycle')).toBe('ended')
    })
  })

  it('lists installations with their asset and source', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /software/installations/': { body: page([install()]) },
    })
    renderApp('/software?tab=installations')

    const table = await screen.findByRole('table', { name: /Installations/ })
    expect(within(table).getByRole('link', { name: 'sw-core-01' })).toHaveAttribute('href', `/assets/${ASSET_ID}?tab=software`)
    expect(within(table).getByText('Endpoint Central')).toBeInTheDocument()
    expect(within(table).getByText('End of support')).toBeInTheDocument()
  })
})

describe('Software product page', () => {
  it('approves a version lifecycle match with If-Match', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /software/products/10/': { body: { ...product(), versions: [version()] } },
      'GET /software/installations/': { body: page([install()]) },
      'POST /software/versions/100/lifecycle/approve/': { body: version({ lifecycle_state: 'matched', lifecycle_method: 'manual' }) },
    })
    renderApp('/software/products/10')

    const versions = await screen.findByRole('table', { name: 'Versions' })
    expect(within(versions).getByText('Needs review')).toBeInTheDocument()
    expect(within(versions).getByText(/Suggested: Example Software Corp Example Office Suite 16.0/)).toBeInTheDocument()
    fireEvent.click(within(versions).getByRole('button', { name: 'Approve…' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve match' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.headers['If-Match']).toBe('"3"')
      expect(post.body).toEqual({ product: 'p-office-16', remember_alias: true, note: '' })
    })
  })

  it('does not offer lifecycle decisions without approval rights', async () => {
    mockApi({
      'GET /auth/me/': { body: operator() },
      'GET /software/products/10/': { body: { ...product(), versions: [version()] } },
      'GET /software/installations/': { body: page([]) },
    })
    renderApp('/software/products/10')

    await screen.findByRole('table', { name: 'Versions' })
    expect(screen.queryByRole('button', { name: 'Approve…' })).not.toBeInTheDocument()
  })
})

describe('Asset software tab', () => {
  it('shows discovered and manual software and records a manual entry', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: operator() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /assets/${ASSET_ID}/software/`]: {
        body: [install(), install({ id: 2, name: 'Example CAD', source: 'Manual', created_by: 'hq.operator', lifecycle_status: 'unknown' })],
      },
      [`POST /assets/${ASSET_ID}/software/`]: { status: 201, body: install({ id: 3, source: 'Manual' }) },
    })
    renderApp(`/assets/${ASSET_ID}?tab=software`)

    const table = await screen.findByRole('table', { name: 'Installed software' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(within(rows[0]).queryByRole('button', { name: 'Remove…' })).not.toBeInTheDocument() // discovered
    expect(within(rows[1]).getByRole('button', { name: 'Remove…' })).toBeInTheDocument() // manual
    expect(within(rows[1]).getByText('by hq.operator')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Record software' }))
    const dialog = await screen.findByRole('dialog', { name: 'Record installed software' })
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Example CAD' } })
    fireEvent.change(within(dialog).getByLabelText('Version'), { target: { value: '2025.1' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Record software' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.body).toEqual({ name: 'Example CAD', publisher: '', version: '2025.1', note: '' })
    })
  })

  it('is read-only without edit rights', async () => {
    mockApi({
      'GET /auth/me/': { body: readerMe() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /assets/${ASSET_ID}/software/`]: { body: [install({ source: 'Manual' })] },
    })
    renderApp(`/assets/${ASSET_ID}?tab=software`)

    await screen.findByRole('table', { name: 'Installed software' })
    expect(screen.queryByRole('button', { name: 'Record software' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove…' })).not.toBeInTheDocument()
  })
})

describe('Integration software switch', () => {
  it('offers "Collect installed software" only for Endpoint Central and Intune', async () => {
    const ec = makeIntegration({
      name: 'Endpoint Central',
      source: { code: 'endpoint_central', name: 'Endpoint Central', kind: 'endpoint', availability: 'beta', description: '', instance_count: 1, has_adapter: true, required_permissions: [] },
    })
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /integrations/': { body: [ec, makeIntegration({ id: 'lnms', name: 'LibreNMS HQ' })] },
      'GET /discovery/sources/': { body: [] },
      'GET /discovery/field-authority/': { body: { precedence: {}, version: 1, modified_at: '2026-11-01T00:00:00Z' } },
      'GET /sites/': { body: [SITE_HQ] },
      [`PATCH /integrations/${ec.id}/`]: { body: ec },
    })
    renderApp('/admin/integrations')

    fireEvent.click(await screen.findByRole('button', { name: 'Edit LibreNMS HQ' }))
    let dialog = await screen.findByRole('dialog', { name: 'Edit LibreNMS HQ' })
    expect(within(dialog).queryByLabelText(/Collect installed software/)).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    fireEvent.click(screen.getByRole('button', { name: 'Edit Endpoint Central' }))
    dialog = await screen.findByRole('dialog', { name: 'Edit Endpoint Central' })
    const toggle = within(dialog).getByLabelText(/Collect installed software/)
    expect(toggle).not.toBeChecked()
    fireEvent.click(toggle)
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save integration' }))
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.body).toMatchObject({ collect_software: true })
    })
  })
})
