import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Certificate, CertificateDetail, Domain, TlsEndpoint } from '../../shared/api/types'
import { ASSET_ID, apiError, makeAsset, makeMe, mockApi, page, renderApp } from '../../test/api'

afterEach(() => vi.unstubAllGlobals())

const CERT = '11111111-1111-4111-8111-111111111111'
const EP = '22222222-2222-4222-8222-222222222222'
const FP = 'ab'.repeat(32)

function cert(overrides: Partial<Certificate> = {}): Certificate {
  return {
    id: CERT,
    fingerprint_sha256: FP,
    subject: 'CN=intranet.example.test',
    common_name: 'intranet.example.test',
    issuer: 'CN=Example Internal CA',
    serial_number: '1a2b',
    sans: ['intranet.example.test', 'www.intranet.example.test'],
    not_before: '2026-01-01T00:00:00Z',
    not_after: '2026-11-20T12:00:00Z',
    expiry: { status: 'expiring', days_remaining: 16, threshold: 30 },
    signature_algorithm: 'ecdsa-with-SHA256',
    public_key: 'EC secp256r1',
    self_signed: false,
    is_ca: false,
    source: 'observed',
    first_seen_at: '2026-11-01T00:00:00Z',
    endpoints: 2,
    note: '',
    ...overrides,
  }
}

function endpoint(overrides: Partial<TlsEndpoint> = {}): TlsEndpoint {
  return {
    id: EP,
    host: 'intranet.example.test',
    port: 443,
    sni: 'intranet.example.test',
    asset: { id: ASSET_ID, name: 'web-hq-01', site_code: 'HQ' },
    asset_hidden: false,
    service: 'Intranet',
    owner: 'Web team',
    enabled: true,
    note: '',
    certificate: {
      id: CERT,
      common_name: 'intranet.example.test',
      fingerprint_sha256: FP,
      not_after: '2026-11-20T12:00:00Z',
      expiry: { status: 'expiring', days_remaining: 16, threshold: 30 },
    },
    hostname_matches: true,
    last_checked_at: '2026-11-04T06:00:00Z',
    last_success_at: '2026-11-04T06:00:00Z',
    last_status: 'ok',
    last_error: '',
    last_address: '10.0.0.10',
    tls_version: 'TLSv1.3',
    retired_at: null,
    retired_reason: '',
    version: 2,
    created_at: '2026-11-01T00:00:00Z',
    modified_at: '2026-11-01T00:00:00Z',
    ...overrides,
  }
}

function domain(overrides: Partial<Domain> = {}): Domain {
  return {
    id: 'd1',
    fqdn: 'example.org',
    owner: 'Web team',
    registrar: '',
    expires_on: null,
    expiry_evidence: '',
    expiry_verified_by: null,
    expiry_verified_at: null,
    expiry: { status: 'unknown', days_remaining: null, threshold: null },
    auto_renew: null,
    note: '',
    retired_at: null,
    retired_reason: '',
    version: 1,
    created_at: '2026-11-01T00:00:00Z',
    modified_at: '2026-11-01T00:00:00Z',
    ...overrides,
  }
}

const reader = () => makeMe({ permissions: ['assets.view', 'certificates.view'] })

describe('Certificates', () => {
  it('lists certificates with expiry, fingerprint and endpoint count', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /certificates/': {
        body: page([
          cert(),
          cert({
            id: 'c2',
            common_name: 'old.example.test',
            sans: [],
            self_signed: true,
            endpoints: 0,
            expiry: { status: 'expired', days_remaining: -3, threshold: null },
          }),
        ]),
      },
    })
    renderApp('/domains')
    const table = await screen.findByRole('table', { name: 'Certificates' })
    const row = within(table).getByRole('link', { name: 'intranet.example.test' }).closest('tr')!
    expect(within(row).getByText('16 days left')).toBeInTheDocument()
    expect(within(row).getByText(/\+1 more/)).toBeInTheDocument()
    expect(within(row).getByText('AB:AB:AB:AB:AB:AB:AB:AB…')).toBeInTheDocument()
    const old = within(table).getByRole('link', { name: 'old.example.test' }).closest('tr')!
    expect(within(old).getByText('Expired 3 days ago')).toBeInTheDocument()
    expect(within(old).getByText('Self-signed')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Domains & Certificates' })).toHaveAttribute('href', '/domains')
  })

  it('shows the private-key refusal when uploading', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /certificates/': { body: page([]) },
      'POST /certificates/': apiError(422, 'VALIDATION_ERROR', 'This contains a private key.', {
        pem: ['This contains a private key.'],
      }),
    })
    renderApp('/domains')
    fireEvent.click(await screen.findByRole('button', { name: 'Upload certificate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Upload certificate' })
    fireEvent.change(within(dialog).getByLabelText('Certificate (PEM)'), {
      target: { value: '-----BEGIN PRIVATE KEY-----' },
    })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Upload' }))
    expect(await within(dialog).findAllByText(/private key/)).not.toHaveLength(0)
  })

  it('shows where a certificate was seen', async () => {
    const detail: CertificateDetail = {
      ...cert(),
      pem: '-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----',
      deployments: [
        {
          id: 1,
          endpoint: { id: EP, label: 'intranet.example.test:443', service: 'Intranet', retired: false },
          certificate: endpoint().certificate!,
          first_seen_at: '2026-11-01T00:00:00Z',
          last_seen_at: '2026-11-04T06:00:00Z',
          replaced_at: null,
          current: true,
        },
        {
          id: 2,
          endpoint: { id: 'e2', label: 'vpn.example.test:8443', service: '', retired: false },
          certificate: endpoint().certificate!,
          first_seen_at: '2026-10-01T00:00:00Z',
          last_seen_at: '2026-10-20T06:00:00Z',
          replaced_at: '2026-10-21T06:00:00Z',
          current: false,
        },
      ],
    }
    mockApi({ 'GET /auth/me/': { body: reader() }, [`GET /certificates/${CERT}/`]: { body: detail } })
    renderApp(`/certificates/${CERT}`)
    const table = await screen.findByRole('table', { name: 'Deployments' })
    expect(within(table).getByText('Presented now')).toBeInTheDocument()
    expect(within(table).getByText(/^Replaced/)).toBeInTheDocument()
    expect(screen.getByText(FP.toUpperCase().match(/.{2}/g)!.join(':'))).toBeInTheDocument()
  })
})

describe('TLS endpoints', () => {
  it('approves an endpoint and checks it now', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /tls-endpoints/': {
        body: page([
          endpoint(),
          endpoint({
            id: 'e2',
            host: 'br.example.test',
            asset: null,
            asset_hidden: true,
            last_status: 'blocked',
            last_error: 'resolves to 169.254.169.254',
            certificate: null,
          }),
        ]),
      },
      'POST /tls-endpoints/': { status: 201, body: endpoint({ id: 'e3' }) },
      [`POST /tls-endpoints/${EP}/check/`]: { body: endpoint() },
    })
    renderApp('/domains?tab=endpoints')
    const table = await screen.findByRole('table', { name: 'TLS endpoints' })
    expect(within(table).getByText('Asset outside your sites')).toBeInTheDocument()
    expect(within(table).getByText('Target not allowed')).toBeInTheDocument()
    fireEvent.click(within(table).getAllByRole('button', { name: 'Check now' })[0])
    await waitFor(() => expect(calls.some((c) => c.path === `/tls-endpoints/${EP}/check/`)).toBe(true))

    fireEvent.click(screen.getByRole('button', { name: 'Approve endpoint' }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve TLS endpoint' })
    fireEvent.change(within(dialog).getByLabelText('Host'), { target: { value: 'mail.example.test' } })
    fireEvent.change(within(dialog).getByLabelText('Port'), { target: { value: '8443' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve endpoint' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.path === '/tls-endpoints/')!
      expect(post.body).toMatchObject({ host: 'mail.example.test', port: 8443, sni: '', asset: null, enabled: true })
    })
  })

  it('is read-only without certificates.manage', async () => {
    mockApi({ 'GET /auth/me/': { body: reader() }, 'GET /tls-endpoints/': { body: page([endpoint()]) } })
    renderApp('/domains?tab=endpoints')
    await screen.findByRole('table', { name: 'TLS endpoints' })
    expect(screen.queryByRole('button', { name: 'Check now' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve endpoint' })).not.toBeInTheDocument()
  })
})

describe('Domains', () => {
  it('shows Unknown expiry and needs evidence with a date', async () => {
    const { calls } = mockApi({
      'GET /auth/me/': { body: makeMe() },
      'GET /domains/': { body: page([domain()]) },
      'POST /domains/': { status: 201, body: domain({ id: 'd2', fqdn: 'example.net' }) },
    })
    renderApp('/domains?tab=domains')
    const table = await screen.findByRole('table', { name: 'Domains' })
    expect(within(table).getAllByText('Unknown').length).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole('button', { name: 'Add domain' }))
    const dialog = await screen.findByRole('dialog', { name: 'Add domain' })
    expect(within(dialog).queryByLabelText('Expiry evidence')).not.toBeInTheDocument()
    fireEvent.change(within(dialog).getByLabelText('Domain'), { target: { value: 'example.net' } })
    fireEvent.change(within(dialog).getByLabelText('Registration expires (optional)'), {
      target: { value: '2027-03-31' },
    })
    fireEvent.change(within(dialog).getByLabelText('Expiry evidence'), { target: { value: 'Registrar portal' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save domain' }))
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST')!
      expect(post.body).toMatchObject({
        fqdn: 'example.net',
        expires_on: '2027-03-31',
        expiry_evidence: 'Registrar portal',
        auto_renew: null,
      })
    })
  })
})

describe('Asset certificates tab', () => {
  it('lists endpoints linked to the asset', async () => {
    mockApi({
      'GET /auth/me/': { body: makeMe() },
      [`GET /assets/${ASSET_ID}/`]: { body: makeAsset() },
      [`GET /assets/${ASSET_ID}/certificates/`]: { body: [endpoint()] },
    })
    renderApp(`/assets/${ASSET_ID}?tab=certificates`)
    const table = await screen.findByRole('table', { name: 'TLS endpoints' })
    expect(within(table).getByRole('link', { name: 'intranet.example.test' })).toHaveAttribute(
      'href',
      `/certificates/${CERT}`,
    )
  })
})
