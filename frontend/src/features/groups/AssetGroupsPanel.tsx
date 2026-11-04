import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchAssetGroups, groupKeys } from '../../shared/api/groups'
import { formatDateTime } from '../../shared/format'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'

/** Groups the asset currently belongs to, and why (manual or rule version). */
export function AssetGroupsPanel({ assetId }: { assetId: string }) {
  const groups = useQuery({ queryKey: groupKeys.forAsset(assetId), queryFn: () => fetchAssetGroups(assetId) })
  return (
    <section className="panel panel--flush" aria-label="Asset groups" aria-live="polite">
      {groups.isPending && <LoadingState label="Loading groups…" />}
      {groups.isError && <QueryErrorState error={groups.error} what="groups" />}
      {groups.data && groups.data.length === 0 && <EmptyState title="Not in any group." />}
      {groups.data && groups.data.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Group</th>
              <th scope="col">Why</th>
              <th scope="col">Since</th>
            </tr>
          </thead>
          <tbody>
            {groups.data.map((g) => (
              <tr key={g.id}>
                <td>
                  <Link to={`/groups/${g.id}`}>{g.name}</Link>
                  <span className="cell-secondary">{g.kind === 'dynamic' ? 'Dynamic' : 'Static'}</span>
                </td>
                <td>{g.source === 'evaluated' ? `Matches rule version ${g.rule_version}` : 'Added manually'}</td>
                <td className="nowrap">{formatDateTime(g.added_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
