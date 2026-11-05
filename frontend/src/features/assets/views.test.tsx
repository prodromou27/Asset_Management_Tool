import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AssetEvidence, SavedView } from '../../shared/api/types'
import {
  ASSET_ID,
  CATEGORIES,
  CAT_SWITCH,
  SITE_HQ,
  assetOperatorMe,
  makeAsset,
  makeField,
  makeMe,
  mockApi,
  page,
  readerMe,
  renderApp,
} from '../../test/api'

beforeEach(() => window.localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

const VIEW: SavedView = {
  id: 'cccccccc-cccc-4ccc-8ccc-ccccccccccc1',
  resource: 'assets',
  name: 'Stale switches',
  is_shared: true,
  filters: { q: 'sw', observation_status: 'stale' },
  columns: ['name', 'site', 'last_seen'],
  ordering: 'name',
  owner: 'admin.one',
  is_mine: true,
  created_at: '2026-11-02T09:00:00Z',
  modified_at: '2026-11-02T09:00:00Z',
  version: 1,
}

const listRoutes = (views: SavedView[] = []) => ({
  'GET /asset-categories/': { body: CATEGORIES },
  'GET /sites/': { body: [SITE_HQ] },
  'GET /integrations/': { body: [] },
  'GET /saved-views/': { body: views },
  'GET /assets/': {
    body: page([
      makeAsset({ last_seen_at: new Date(Date.now() - 3 * 3600_000).toISOString(), source_count: 2 }),
    ]),
  },
})

const headers = () => within(screen.getByRole('table', { name: 'Assets' })).getAllByRole('columnheader').map((h) => h.textContent)

describe('Asset list columns and saved views', () => {
  it('shows last seen as relative time and the source count', async () => {
    mockApi({ 'GET /auth/me/': { body: readerMe() }, ...listRoutes() })

    renderApp('/assets')

    const table = await screen.findByRole('table', { name: 'Assets' })
    expect(within(table).getByText(/3 hours ago/)).toBeInTheDocument()
    expect(within(table).getByRole('columnheader', { name: 'Sources' })).toBeInTheDocument()
    expect(within(table).getByText('2')).toBeInTheDocument()
  })

  it('chooses columns and remembers them for the user', async () => {
    mockApi({ 'GET /auth/me/': { body: readerMe() }, ...listRoutes() })
    const { unmount } = renderApp('/assets')
    await screen.findByRole('table', { name: 'Assets' })

    fireEvent.click(screen.getByRole('button', { name: /Columns/ }))
    const dialog = screen.getByRole('dialog', { name: 'Choose columns' })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Serial' }))
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Observation/ }))
    expect(within(dialog).getByRole('checkbox', { name: /Name \/ hostname/ })).toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Apply columns' }))

    expect(headers()).not.toContain('Serial')
    expect(headers()).toContain('Observation')
    unmount()

    renderApp('/assets')
    await screen.findByRole('table', { name: 'Assets' })
    expect(headers()).not.toContain('Serial')
  })

  it('applies a saved view to the URL filters and its columns', async () => {
    const { calls } = mockApi({ 'GET /auth/me/': { body: makeMe() }, ...listRoutes([VIEW]) })
    renderApp('/assets')
    await screen.findByRole('table', { name: 'Assets' })

    fireEvent.change(await screen.findByLabelText('Saved view'), { target: { value: VIEW.id } })

    await waitFor(() => {
      const last = calls.filter((c) => c.path === '/assets/').at(-1)!
      expect(last.search.get('q')).toBe('sw')
      expect(last.search.get('observation_status')).toBe('stale')
      expect(last.search.get('ordering')).toBe('name')
    })
    await waitFor(() => expect(headers()).toEqual(['', 'Name / hostname', 'Site / location', 'Last seen']))
    expect(screen.getByText(/view “Stale switches”/)).toBeInTheDocument()
  })

  it('saves the current filters as a new view', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...listRoutes(),
      'POST /saved-views/': { status: 201, body: { ...VIEW, is_shared: false } },
    })
    renderApp('/assets?q=core&business_status=deployed&ordering=-name')
    await screen.findByRole('table', { name: 'Assets' })

    fireEvent.click(screen.getByRole('button', { name: 'Save as new view' }))
    const dialog = screen.getByRole('dialog', { name: 'Save view' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save view' }))
    expect(within(dialog).getByText('Enter a name.')).toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Deployed core' } })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: /Share with other users/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save view' }))

    await waitFor(() =>
      expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
        name: 'Deployed core',
        filters: { q: 'core', business_status: 'deployed' },
        ordering: '-name',
        is_shared: true,
      }),
    )
  })

  it('offers sharing only to users with edit rights and update only to the owner', async () => {
    mockApi({
      'GET /auth/me/': { body: readerMe() },
      ...listRoutes([{ ...VIEW, is_mine: false }]),
    })
    renderApp(`/assets?q=other&view=${VIEW.id}`)
    await screen.findByRole('table', { name: 'Assets' })
    await screen.findByRole('option', { name: /shared by admin.one/ })

    expect(screen.queryByRole('button', { name: /Update/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete view' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save as new view' }))
    expect(within(screen.getByRole('dialog', { name: 'Save view' })).queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('updates an owned view with changed filters using If-Match', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...listRoutes([VIEW]),
      [`PATCH /saved-views/${VIEW.id}/`]: { body: { ...VIEW, version: 2 } },
    })
    renderApp(`/assets?q=sw&observation_status=stale&ordering=name&business_status=deployed&view=${VIEW.id}`)

    fireEvent.click(await screen.findByRole('button', { name: 'Update “Stale switches”' }))

    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.headers['If-Match']).toBe('"1"')
      expect(patch.body).toMatchObject({
        filters: { q: 'sw', observation_status: 'stale', business_status: 'deployed' },
        ordering: 'name',
      })
    })
  })
})

describe('Source evidence drawer', () => {
  const evidence: AssetEvidence = {
    field_evidence: [
      {
        field: 'serial_number',
        value: 'SN-TEST-0001',
        provenance: { kind: 'discovery', instance: { id: 'i1', name: 'NMS HQ', source: 'fixture' }, observed_at: '2026-11-02T08:00:00Z', recorded_at: '2026-11-02T08:00:00Z', recorded_by: null },
        lock: null,
        sources: [
          { instance: { id: 'i1', name: 'NMS HQ', source: 'fixture' }, external_id: '317', value: 'SN-TEST-0001', observed_at: '2026-11-02T08:00:00Z', link_status: 'active', differs: false },
          { instance: { id: 'i2', name: 'Endpoint Central', source: 'endpoint_central' }, external_id: 'ec-9', value: 'SN-OTHER', observed_at: '2026-11-01T08:00:00Z', link_status: 'stale', differs: true },
        ],
        open_conflicts: [],
      },
    ],
    links: [],
    merges: [],
  }
  const routes = (me = makeMe()) => ({
    'GET /auth/me/': { body: me },
    [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
    [`GET /asset-categories/${CAT_SWITCH.id}/fields/`]: { body: [makeField()] },
    [`GET /assets/${ASSET_ID}/evidence/`]: { body: evidence },
  })

  it('opens from a field, shows each source, closes on Escape and restores focus', async () => {
    mockApi(routes())
    renderApp(`/assets/${ASSET_ID}`)

    const trigger = await screen.findByRole('button', { name: 'Evidence for Serial number' })
    trigger.focus()
    fireEvent.click(trigger)

    const drawer = await screen.findByRole('dialog', { name: 'Evidence: Serial number' })
    expect(await within(drawer).findByText(/NMS HQ, observed/)).toBeInTheDocument()
    expect(within(drawer).getByText('Differs')).toBeInTheDocument()
    expect(within(drawer).getByText(/ec-9 · stale/)).toBeInTheDocument()
    expect(within(drawer).getByRole('button', { name: 'Close' })).toHaveFocus()

    fireEvent.keyDown(drawer, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Evidence: Serial number' })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('is not offered without discovery.view', async () => {
    mockApi(routes(assetOperatorMe()))
    renderApp(`/assets/${ASSET_ID}`)

    await screen.findByRole('tab', { name: 'Overview' })
    expect(screen.queryByRole('button', { name: /Evidence for/ })).not.toBeInTheDocument()
  })
})
