import { useInfiniteQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchImports, importKeys } from '../../shared/api/imports'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { FAMILY_LABEL, JOB_STATUS } from './labels'

export function ImportsPage() {
  const jobs = useInfiniteQuery({
    queryKey: importKeys.list,
    queryFn: ({ pageParam }) => fetchImports(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })
  const items = jobs.data?.pages.flatMap((p) => p.items) ?? []
  return (
    <div className="page page--wide">
      <PageHeader
        title="Imports"
        meta="CSV or XLSX files are checked in a dry run before anything changes. Missing rows never delete or archive records."
        actions={
          <Link className="button button--primary" to="/imports/new">
            New import
          </Link>
        }
      />
      <section className="panel panel--flush" aria-label="Import history" aria-live="polite">
        {jobs.isPending && <LoadingState label="Loading imports…" />}
        {jobs.isError && <QueryErrorState error={jobs.error} what="imports" />}
        {jobs.isSuccess && items.length === 0 && <EmptyState title="No imports yet." />}
        {items.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Data</th>
                <th scope="col">Status</th>
                <th scope="col">Rows</th>
                <th scope="col">Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => {
                const result = (j.totals as { result?: Record<string, number> }).result
                return (
                  <tr key={j.id}>
                    <td>
                      <Link to={`/imports/${j.id}`}>{j.filename}</Link>
                      <span className="cell-secondary mono">{j.file_format.toUpperCase()}</span>
                    </td>
                    <td>{FAMILY_LABEL[j.family] ?? j.family}</td>
                    <td>
                      <StatusBadge tone={JOB_STATUS[j.status].tone} label={JOB_STATUS[j.status].label} />
                    </td>
                    <td>
                      {j.row_count}
                      {result && (
                        <span className="cell-secondary">
                          {result.applied} applied, {result.skipped} not applied, {result.failed} failed
                        </span>
                      )}
                    </td>
                    <td className="nowrap">
                      {formatDateTime(j.created_at)}
                      <span className="cell-secondary">{j.created_by}</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {jobs.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => jobs.fetchNextPage()} busy={jobs.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}
