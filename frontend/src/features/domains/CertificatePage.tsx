import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { domainKeys, fetchAssetCertificates, fetchCertificate } from '../../shared/api/domains'
import { formatDateTime } from '../../shared/format'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { EndpointsTable } from './DomainsPage'
import { expiryBadge, fingerprint } from './labels'

/** docs/08 §7 detail: identifiers, validity and where the certificate was observed (rotation
 * history per endpoint). */
export function CertificatePage() {
  const { id = '' } = useParams()
  const cert = useQuery({ queryKey: domainKeys.certificate(id), queryFn: () => fetchCertificate(id) })
  const crumb = (
    <nav aria-label="Breadcrumb" className="breadcrumb">
      <Link to="/domains">Domains &amp; Certificates</Link>
    </nav>
  )
  if (cert.isPending) return <LoadingState label="Loading certificate…" />
  if (cert.isError)
    return (
      <div className="page">
        {crumb}
        <QueryErrorState error={cert.error} what="this certificate" />
      </div>
    )
  const c = cert.data
  const badge = expiryBadge(c.expiry)
  return (
    <div className="page page--wide">
      {crumb}
      <PageHeader
        title={c.common_name || c.sans[0] || 'Certificate'}
        meta={c.source === 'uploaded' ? 'Uploaded certificate' : 'Read from an approved endpoint'}
      />
      <dl className="kpi-strip" aria-label="Validity">
        <div className="kpi-strip__item">
          <dt>Expiry</dt>
          <dd>
            <StatusBadge tone={badge.tone} label={badge.label} />
          </dd>
        </div>
        <div className="kpi-strip__item">
          <dt>Not after</dt>
          <dd>{formatDateTime(c.not_after)}</dd>
        </div>
        <div className="kpi-strip__item">
          <dt>Not before</dt>
          <dd>{formatDateTime(c.not_before)}</dd>
        </div>
        <div className="kpi-strip__item">
          <dt>Presented by</dt>
          <dd>
            {c.endpoints} {c.endpoints === 1 ? 'endpoint' : 'endpoints'}
          </dd>
        </div>
      </dl>
      <section className="panel" aria-labelledby="cert-ids">
        <h2 className="section-title" id="cert-ids">
          Identifiers
        </h2>
        <dl className="meta-grid">
          <dt>Subject</dt>
          <dd className="mono">{c.subject || '–'}</dd>
          <dt>Issuer</dt>
          <dd className="mono">
            {c.issuer}
            {c.self_signed && ' (self-signed)'}
          </dd>
          <dt>SHA-256 fingerprint</dt>
          <dd className="mono">{fingerprint(c.fingerprint_sha256, true)}</dd>
          <dt>Serial number</dt>
          <dd className="mono">{c.serial_number}</dd>
          <dt>Key / signature</dt>
          <dd>
            {c.public_key} · {c.signature_algorithm}
          </dd>
          <dt>Subject alternative names</dt>
          <dd className="mono">{c.sans.length ? c.sans.join(', ') : 'None'}</dd>
        </dl>
      </section>
      <h2 className="section-title">Where it was seen</h2>
      <div className="panel panel--flush">
        {c.deployments.length === 0 ? (
          <EmptyState title="Not seen on an approved endpoint." />
        ) : (
          <table className="data-table data-table--nowrap">
            <caption className="visually-hidden">Deployments</caption>
            <thead>
              <tr>
                <th scope="col">Endpoint</th>
                <th scope="col">First seen</th>
                <th scope="col">Last seen</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {c.deployments.map((d) => (
                <tr key={d.id}>
                  <td>
                    <span className="mono">{d.endpoint.label}</span>
                    {d.endpoint.service && <span className="cell-secondary">{d.endpoint.service}</span>}
                  </td>
                  <td>{formatDateTime(d.first_seen_at)}</td>
                  <td>{formatDateTime(d.last_seen_at)}</td>
                  <td>
                    {d.current ? (
                      <StatusBadge tone="success" label="Presented now" />
                    ) : (
                      <StatusBadge
                        tone="neutral"
                        label={d.replaced_at ? `Replaced ${formatDateTime(d.replaced_at)}` : 'Endpoint retired'}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <details className="panel">
        <summary>Public certificate (PEM)</summary>
        <pre className="mono pre-wrap">{c.pem}</pre>
      </details>
    </div>
  )
}

/** Asset detail "Certificates" tab (docs/04 /assets/{id}/certificates). */
export function AssetCertificatesPanel({ assetId }: { assetId: string }) {
  const rows = useQuery({ queryKey: domainKeys.asset(assetId), queryFn: () => fetchAssetCertificates(assetId) })
  if (rows.isPending) return <LoadingState label="Loading certificates…" />
  if (rows.isError) return <QueryErrorState error={rows.error} what="certificates" />
  return (
    <div className="panel panel--flush">
      {rows.data.length === 0 ? (
        <EmptyState title="No approved TLS endpoints are linked to this asset.">
          Link one under Domains &amp; Certificates → TLS endpoints.
        </EmptyState>
      ) : (
        <EndpointsTable items={rows.data} manage={false} />
      )}
    </div>
  )
}
