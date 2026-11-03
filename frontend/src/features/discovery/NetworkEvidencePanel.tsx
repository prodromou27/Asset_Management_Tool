import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { discoveryKeys, fetchNetworkEvidence } from '../../shared/api/discovery'
import type { NeighborEvidence } from '../../shared/api/types'
import { formatDateTime } from '../../shared/format'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { EVIDENCE_KIND } from './labels'

function AssetRef({ asset, fallback }: { asset: NeighborEvidence['local_asset']; fallback: string }) {
  if (asset) return <Link to={`/assets/${asset.id}?tab=network`}>{asset.name}</Link>
  return <span className="mono">{fallback || <span className="cell-muted">Unknown device</span>}</span>
}

/** FDB / LLDP / CDP observations from network sources. Evidence only: a MAC seen on a
 * port or a neighbour announcement is not a confirmed physical cable. */
export function NetworkEvidencePanel({ assetId }: { assetId: string }) {
  const evidence = useQuery({
    queryKey: discoveryKeys.networkEvidence(assetId),
    queryFn: () => fetchNetworkEvidence(assetId),
  })

  return (
    <section className="panel panel--flush" aria-labelledby="net-evidence" aria-live="polite">
      <h2 className="section-title section-title--inset" id="net-evidence">
        Observed network evidence
      </h2>
      <p className="field__help section-help">
        What network sources reported: MAC addresses seen on switch ports and LLDP/CDP neighbours. Observed, not a
        confirmed cable.
      </p>
      {evidence.isPending && <LoadingState label="Loading network evidence…" />}
      {evidence.isError && <QueryErrorState error={evidence.error} what="network evidence" />}
      {evidence.data && evidence.data.length === 0 && <EmptyState title="No network evidence observed." />}
      {evidence.data && evidence.data.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Type</th>
              <th scope="col">Seen on</th>
              <th scope="col">Port</th>
              <th scope="col">Other side</th>
              <th scope="col">Source</th>
              <th scope="col">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {evidence.data.map((row) => (
              <tr key={row.id}>
                <td>
                  {EVIDENCE_KIND[row.kind] ?? row.kind}
                  {!row.is_active && (
                    <>
                      {' '}
                      <StatusBadge tone="neutral" label="No longer seen" />
                    </>
                  )}
                </td>
                <td>
                  <AssetRef asset={row.local_asset} fallback={`Device ${row.local_external_id}`} />
                </td>
                <td className="mono">
                  {row.local_port}
                  {row.vlan && <span className="cell-secondary">VLAN ref {row.vlan}</span>}
                </td>
                <td>
                  {row.kind === 'fdb' ? (
                    <span className="mono">{row.remote_mac}</span>
                  ) : (
                    <>
                      <AssetRef asset={row.remote_asset} fallback={row.remote_hostname} />
                      {row.remote_port && <span className="cell-secondary mono">{row.remote_port}</span>}
                      {row.remote_platform && <span className="cell-secondary">{row.remote_platform}</span>}
                    </>
                  )}
                </td>
                <td>{row.instance}</td>
                <td className="nowrap">{formatDateTime(row.last_seen_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
