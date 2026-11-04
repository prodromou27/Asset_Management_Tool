import { fireEvent, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ImportJob, ImportRow, ImportTemplate } from '../../shared/api/types'
import { apiError, makeMe, mockApi, page, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const JOB_ID = '88888888-8888-4888-8888-888888888801'

const TEMPLATES: ImportTemplate[] = [
  {
    code: 'asset',
    label: 'Assets',
    version: 1,
    description: 'Create or update assets.',
    match_help: 'Updates match on id or asset_tag only.',
    columns: [
      { name: 'asset_tag', label: 'Asset tag', required: 'match', help: '', example: 'IT-1' },
      { name: 'name', label: 'Name', required: 'create', help: '', example: 'LT-1' },
      { name: 'site', label: 'Site', required: 'create', help: '', example: 'HQ' },
    ],
    custom_columns: true,
    allowed: true,
  },
  {
    code: 'location',
    label: 'Locations',
    version: 1,
    description: 'Create locations.',
    match_help: '',
    columns: [],
    custom_columns: false,
    allowed: false,
  },
]

function makeJob(overrides: Partial<ImportJob> = {}): ImportJob {
  return {
    id: JOB_ID,
    family: 'asset',
    template_version: 1,
    status: 'uploaded',
    mode: 'create_only',
    filename: 'assets.csv',
    file_format: 'csv',
    size_bytes: 120,
    checksum: 'a'.repeat(64),
    encoding: 'utf-8',
    sheet: '',
    headers: ['Tag', 'Name', 'Where'],
    mapping: { Tag: 'asset_tag', Name: 'name', Where: '' },
    row_count: 3,
    totals: {},
    warnings: [],
    error_message: '',
    progress: 0,
    file_retained: true,
    purge_after: '2027-02-01T00:00:00Z',
    created_by: 'admin.one',
    created_at: '2026-11-04T08:00:00Z',
    previewed_at: null,
    committed_by: null,
    committed_at: null,
    completed_at: null,
    rolled_back_at: null,
    version: 2,
    sample: [['IT-1', 'LT-1', 'HQ']],
    ...overrides,
  }
}

function row(overrides: Partial<ImportRow> = {}): ImportRow {
  return {
    row_number: 1,
    action: 'create',
    key: 'tag:IT-1',
    target_id: '',
    target_label: 'LT-1',
    messages: [],
    values: {},
    changes: {},
    result: '',
    result_message: '',
    ...overrides,
  }
}

describe('Import wizard', () => {
  it('uploads a file for the chosen family', async () => {
    let sent: FormData | null = null
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /imports/templates/': { body: TEMPLATES },
      'POST /imports/': ({ init }) => {
        sent = init.body as FormData
        return { status: 201, body: makeJob() }
      },
      [`GET /imports/${JOB_ID}/`]: { body: makeJob() },
    })
    renderApp('/imports/new?family=asset')

    expect(await screen.findByLabelText(/Locations/)).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Download the CSV template' })).toHaveAttribute(
      'href',
      '/api/v1/imports/templates/asset/csv/',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Upload and continue' }))
    expect(screen.getByText('Choose a .csv or .xlsx file.')).toBeInTheDocument()
    const file = new File(['Tag,Name\nIT-1,LT-1\n'], 'assets.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByLabelText('File'), { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload and continue' }))

    expect(await screen.findByRole('heading', { name: 'assets.csv' })).toBeInTheDocument()
    expect(sent!.get('family')).toBe('asset')
    expect((sent!.get('file') as File).name).toBe('assets.csv')
  })

  it('shows upload errors from the server', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /imports/templates/': { body: TEMPLATES },
      'POST /imports/': apiError(422, 'VALIDATION_ERROR', 'Invalid input.', { file: ['Macro-enabled workbooks are not accepted.'] }),
    })
    renderApp('/imports/new')

    fireEvent.change(await screen.findByLabelText('File'), {
      target: { files: [new File(['x'], 'm.xlsx')] },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Upload and continue' }))
    expect(await screen.findByText('Macro-enabled workbooks are not accepted.')).toBeInTheDocument()
  })

  it('maps columns, picks a mode and runs the dry run', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /imports/templates/': { body: TEMPLATES },
      [`GET /imports/${JOB_ID}/`]: { body: makeJob() },
      [`PATCH /imports/${JOB_ID}/`]: { body: makeJob({ version: 3, mapping: { Tag: 'asset_tag', Name: 'name', Where: 'site' } }) },
      [`POST /imports/${JOB_ID}/preview/`]: {
        status: 202,
        body: makeJob({ status: 'previewed', version: 4, totals: { create: 2, update: 0, skip: 0, conflict: 1, error: 0 } }),
      },
      [`GET /imports/${JOB_ID}/rows/`]: { body: page([row(), row({ row_number: 2, action: 'conflict', messages: ['The same asset is already in row 1.'] })]) },
    })
    renderApp(`/imports/${JOB_ID}`)

    expect(await screen.findByText('IT-1')).toBeInTheDocument() // sample value
    fireEvent.change(screen.getByLabelText('Field for column Where'), { target: { value: 'site' } })
    fireEvent.click(screen.getByLabelText(/Create and update/))
    fireEvent.click(screen.getByRole('button', { name: 'Check rows (dry run)' }))

    const totals = await screen.findByLabelText('Dry-run totals')
    expect(totals).toHaveTextContent('Create2')
    const patch = calls.find((c) => c.method === 'PATCH')!
    expect(patch.headers['If-Match']).toBe('"2"')
    expect(patch.body).toEqual({ mapping: { Tag: 'asset_tag', Name: 'name', Where: 'site' }, mode: 'upsert' })
    expect(calls.find((c) => c.path.endsWith('/preview/'))!.headers['If-Match']).toBe('"3"')
    expect(await screen.findByText('The same asset is already in row 1.')).toBeInTheDocument()
  })

  it('commits with an idempotency key and shows the receipt with rollback', async () => {
    const previewed = makeJob({ status: 'previewed', version: 4, mode: 'upsert', totals: { create: 2, update: 1, skip: 0, conflict: 1, error: 0 } })
    const completed = makeJob({
      status: 'completed',
      version: 6,
      committed_by: 'admin.one',
      committed_at: '2026-11-04T08:05:00Z',
      totals: { create: 2, update: 1, skip: 0, conflict: 1, error: 0, result: { applied: 3, skipped: 1, failed: 0 } },
    })
    let committed = false
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /imports/${JOB_ID}/`]: () => ({ body: committed ? completed : previewed }),
      [`GET /imports/${JOB_ID}/rows/`]: { body: page([row({ result: committed ? 'applied' : '' })]) },
      [`POST /imports/${JOB_ID}/commit/`]: () => {
        committed = true
        return { status: 202, body: completed }
      },
      [`POST /imports/${JOB_ID}/rollback/`]: { body: makeJob({ status: 'rolled_back', version: 7, totals: { ...completed.totals, rollback: { rolled_back: 2, needs_correction: 1 } } }) },
    })
    renderApp(`/imports/${JOB_ID}`)

    fireEvent.click(await screen.findByRole('button', { name: 'Import 3 rows' }))
    expect(await screen.findByRole('heading', { name: 'Receipt' })).toBeInTheDocument()
    const commit = calls.find((c) => c.path.endsWith('/commit/'))!
    expect(commit.headers['If-Match']).toBe('"4"')
    expect(commit.headers['X-Idempotency-Key']).toMatch(/^[0-9a-f-]{36}$/)
    expect(screen.getByLabelText('Import results')).toHaveTextContent('Applied3')

    fireEvent.click(screen.getByRole('button', { name: 'Roll back…' }))
    const dialog = screen.getByRole('dialog', { name: 'Roll back this import?' })
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'Wrong file' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Roll back' }))
    expect(await screen.findByText(/2 rolled back, 1 changed since/)).toBeInTheDocument()
  })
})

describe('Imports list and entry points', () => {
  it('lists imports with results and links from the assets page', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /imports/': {
        body: page([makeJob({ status: 'completed', totals: { result: { applied: 95, skipped: 5, failed: 0 } } })]),
      },
    })
    renderApp('/imports')

    const table = await screen.findByRole('region', { name: 'Import history' })
    expect(await within(table).findByRole('link', { name: 'assets.csv' })).toHaveAttribute('href', `/imports/${JOB_ID}`)
    expect(within(table).getByText('95 applied, 5 not applied, 0 failed')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Imports' })).toHaveAttribute('href', '/imports')
  })

  it('hides imports without the permission', async () => {
    mockApi({ 'GET /auth/me/': { body: makeMe({ permissions: ['assets.view'] }) } })
    renderApp('/')

    expect(await screen.findByRole('link', { name: 'Assets' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Imports' })).not.toBeInTheDocument()
  })
})
