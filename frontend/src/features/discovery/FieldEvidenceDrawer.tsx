import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { discoveryKeys, fetchEvidence } from '../../shared/api/discovery'
import { formatDateTime } from '../../shared/format'
import { Drawer } from '../../shared/ui/Drawer'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { FIELD_LABEL } from './labels'

interface Props {
  assetId: string
  field: string | null
  onClose: () => void
}

/** docs/07 SourceEvidenceDrawer: value, source, time, lock, every source's report and conflicts. */
export function FieldEvidenceDrawer({ assetId, field, onClose }: Props) {
  const evidence = useQuery({
    queryKey: discoveryKeys.evidence(assetId),
    queryFn: () => fetchEvidence(assetId),
    enabled: field !== null,
  })
  const label = field ? (FIELD_LABEL[field] ?? field) : ''
  const row = evidence.data?.field_evidence.find((r) => r.field === field)

  return (
    <Drawer open={field !== null} title={`Evidence: ${label}`} onClose={onClose}>
      {evidence.isPending && <LoadingState label="Loading evidence…" />}
      {evidence.isError && <QueryErrorState error={evidence.error} what="source evidence" />}
      {row && (
        <div className="stack">
          <dl className="meta-grid meta-grid--stacked">
            <dt>Current value</dt>
            <dd className="mono">{row.value || 'Unknown'}</dd>
            <dt>Set by</dt>
            <dd>
              {row.provenance === null
                ? 'Not recorded'
                : row.provenance.kind === 'manual'
                  ? `Manual entry by ${row.provenance.recorded_by ?? 'unknown'}, ${formatDateTime(row.provenance.recorded_at)}`
                  : `${row.provenance.instance?.name ?? 'Source'}, observed ${formatDateTime(row.provenance.observed_at)}`}
            </dd>
            <dt>Lock</dt>
            <dd>
              {row.lock ? (
                <>
                  <StatusBadge tone="warning" label="Locked" /> by {row.lock.locked_by ?? 'unknown'} —{' '}
                  {row.lock.reason || 'no reason'}
                </>
              ) : (
                'Unlocked: the highest-authority fresh source may update it'
              )}
            </dd>
          </dl>
          <section aria-labelledby="drawer-sources">
            <h3 className="subsection-title" id="drawer-sources">
              Reported by linked sources
            </h3>
            {row.sources.length === 0 ? (
              <EmptyState title="No linked source reports this field." />
            ) : (
              <table className="data-table data-table--compact">
                <thead>
                  <tr>
                    <th scope="col">Source</th>
                    <th scope="col">Value</th>
                    <th scope="col">Observed</th>
                  </tr>
                </thead>
                <tbody>
                  {row.sources.map((s) => (
                    <tr key={`${s.instance.id}-${s.external_id}`}>
                      <td>
                        {s.instance.name}
                        <span className="cell-secondary mono">
                          {s.external_id}
                          {s.link_status === 'stale' ? ' · stale' : ''}
                        </span>
                      </td>
                      <td className="mono">
                        {s.value ?? <span className="cell-muted">Not reported</span>}
                        {s.differs && (
                          <>
                            {' '}
                            <StatusBadge tone="warning" label="Differs" />
                          </>
                        )}
                      </td>
                      <td className="nowrap">{formatDateTime(s.observed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
          {row.open_conflicts.length > 0 && (
            <p className="inline-note inline-note--warning" role="note">
              {row.open_conflicts.length} open conflict(s) for this field. Resolve them on the Source evidence tab.
            </p>
          )}
          <Link to={`/assets/${assetId}?tab=evidence`} onClick={onClose}>
            Open the Source evidence tab
          </Link>
        </div>
      )}
    </Drawer>
  )
}
