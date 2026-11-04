import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ExportFamily, ExportJob } from '../../shared/api/types'
import { CATEGORIES, SITE_HQ, makeMe, mockApi, page, readerMe, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const JOB_ID = '99999999-9999-4999-8999-999999999901'

function family(overrides: Partial<ExportFamily> = {}): ExportFamily {
  return {
    code: 'assets',
    label: 'Assets',
    description: 'Assets in your sites',
    allowed: true,
    filter_keys: ['q', 'site', 'category', 'archived'],
    columns: [
      { key: 'id', label: 'Asset ID', personal: false, allowed: true },
      { key: 'name', label: 'Name', personal: false, allowed: true },
      { key: 'owner', label: 'Owner username', personal: true, allowed: true },
    ],
    related: [
      { key: 'hostnames', label: 'Hostnames' },
      { key: 'groups', label: 'Group memberships' },
    ],
    personal_data_allowed: true,
    ...overrides,
  }
}

function job(overrides: Partial<ExportJob> = {}): ExportJob {
  return {
    id: JOB_ID,
    family: 'assets',
    file_format: 'xlsx',
    scope: 'filtered',
    filters: { q: 'core' },
    selected_count: 0,
    columns: [],
    related: [],
    status: 'completed',
    row_count: 1284,
    related_counts: {},
    masked_columns: [],
    filename: 'itam-assets-20261104-101500.xlsx',
    size_bytes: 52_430,
    checksum: 'abc',
    error_message: '',
    created_by: 'admin.one',
    created_at: '2026-11-04T10:15:00Z',
    completed_at: '2026-11-04T10:15:02Z',
    expires_at: '2026-11-05T10:15:02Z',
    download_count: 0,
    last_downloaded_at: null,
    downloadable: true,
    ...overrides,
  }
}

const assetsPage = {
  'GET /asset-categories/': { body: CATEGORIES },
  'GET /sites/': { body: [SITE_HQ] },
  'GET /assets/': { body: page([]) },
}

const exporter = () =>
  makeMe({ ...readerMe(), permissions: ['assets.view', 'exports.run'] })

describe('Export dialog on the assets list', () => {
  it('exports the current filters with the chosen format and related data', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...assetsPage,
      'GET /exports/families/': { body: [family()] },
      'POST /exports/': { status: 202, body: job({ status: 'queued', downloadable: false }) },
      'GET /exports/': { body: page([job({ status: 'queued', downloadable: false })]) },
    })
    renderApp('/assets?q=core&site=' + SITE_HQ.id)

    fireEvent.click(await screen.findByRole('button', { name: 'Export' }))
    const dialog = await screen.findByRole('dialog', { name: 'Export assets' })
    expect(await within(dialog).findByLabelText('Current filters')).toBeChecked()
    fireEvent.click(within(dialog).getByLabelText('CSV'))
    fireEvent.click(within(dialog).getByLabelText('Hostnames'))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Start export' }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/exports/')!
      expect(post.body).toEqual({
        family: 'assets',
        format: 'csv',
        scope: 'filtered',
        filters: { q: 'core', site: SITE_HQ.id },
        ids: [],
        columns: [],
        related: ['hostnames'],
      })
    })
    expect(await screen.findByRole('heading', { name: 'Exports' })).toBeInTheDocument()
  })

  it('sends a column subset and explains masked personal data', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: exporter() },
      ...assetsPage,
      'GET /exports/families/': {
        body: [
          family({
            personal_data_allowed: false,
            columns: [
              { key: 'id', label: 'Asset ID', personal: false, allowed: true },
              { key: 'name', label: 'Name', personal: false, allowed: true },
              { key: 'owner', label: 'Owner username', personal: true, allowed: false },
            ],
          }),
        ],
      },
      'POST /exports/': { status: 202, body: job() },
      'GET /exports/': { body: page([job()]) },
    })
    renderApp('/assets')

    fireEvent.click(await screen.findByRole('button', { name: 'Export' }))
    const dialog = await screen.findByRole('dialog', { name: 'Export assets' })
    expect(await within(dialog).findByText(/Personal data \(Owner username\) is left out/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Everything you can see')).toBeChecked()
    expect(within(dialog).queryByLabelText('Current filters')).not.toBeInTheDocument()
    fireEvent.click(within(dialog).getByLabelText('Name'))
    expect(within(dialog).getByText('Columns (1 of 2)')).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Start export' }))

    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/exports/')!
      expect(post.body).toMatchObject({ scope: 'all', format: 'xlsx', columns: ['id'] })
    })
  })

  it('shows field errors from the server', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      ...assetsPage,
      'GET /exports/families/': { body: [family()] },
      'POST /exports/': {
        status: 429,
        body: { error: { code: 'EXPORT_LIMIT', message: 'You already have 3 exports in progress.', request_id: 'r', field_errors: {} } },
      },
    })
    renderApp('/assets')

    fireEvent.click(await screen.findByRole('button', { name: 'Export' }))
    const dialog = await screen.findByRole('dialog', { name: 'Export assets' })
    await within(dialog).findByLabelText('Everything you can see')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Start export' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('3 exports in progress')
  })

  it('hides the Export button without the export permission', async () => {
    mockApi({ 'GET /auth/me/': { body: readerMe() }, ...assetsPage })
    renderApp('/assets')

    await screen.findByRole('link', { name: 'Assets' })
    await screen.findByText(/No assets/)
    expect(screen.queryByRole('button', { name: 'Export' })).not.toBeInTheDocument()
  })
})

describe('Exports page', () => {
  it('lists exports with status, download link, expiry and failures', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /exports/': {
        body: page([
          job({ related: ['hostnames'], related_counts: { hostnames: 2400 }, masked_columns: ['owner'] }),
          job({
            id: 'j2',
            status: 'failed',
            downloadable: false,
            error_message: 'This export would contain more than 100,000 records. Narrow the filters.',
          }),
          job({ id: 'j3', status: 'expired', downloadable: false }),
        ]),
      },
    })
    renderApp(`/exports?job=${JOB_ID}`)

    const table = await screen.findByRole('table', { name: 'Exports' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows[0]).toHaveClass('row--highlight')
    expect(within(rows[0]).getByText('Ready')).toBeInTheDocument()
    expect(within(rows[0]).getByText('1,284')).toBeInTheDocument()
    expect(within(rows[0]).getByText('2,400 hostnames')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Personal data left out')).toBeInTheDocument()
    expect(within(rows[0]).getByRole('link', { name: /Download/ })).toHaveAttribute(
      'href',
      `/api/v1/exports/${JOB_ID}/download/`,
    )
    expect(within(rows[1]).getByText(/more than 100,000 records/)).toBeInTheDocument()
    expect(within(rows[1]).queryByRole('link', { name: /Download/ })).not.toBeInTheDocument()
    expect(within(rows[2]).getByText('Expired')).toBeInTheDocument()
  })

  it('polls while an export is being prepared', async () => {
    let polls = 0
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /exports/': () => {
        polls += 1
        return {
          body: page([polls < 2 ? job({ status: 'running', downloadable: false }) : job()]),
        }
      },
    })
    renderApp('/exports')

    expect(await screen.findByText('Preparing')).toBeInTheDocument()
    expect(await screen.findByText('Ready', {}, { timeout: 4000 })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Download/ })).toBeInTheDocument()
  })

  it('denies the page without the export permission', async () => {
    mockApi({ 'GET /auth/me/': { body: readerMe() } })
    renderApp('/exports')

    expect(await screen.findByText(/do not have access to exports/i)).toBeInTheDocument()
  })
})
