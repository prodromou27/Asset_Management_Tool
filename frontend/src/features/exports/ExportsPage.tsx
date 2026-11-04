import { useInfiniteQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { exportDownloadUrl, exportKeys, fetchExports, isActive } from '../../shared/api/exports'
import { formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { EXPORT_STATUS, FAMILY_LABEL, FORMAT_LABEL, SCOPE_LABEL, formatBytes } from './labels'

const POLL_MS = 2000

/** docs/07: long jobs have a durable progress panel; this page is it for exports. */
export function ExportsPage() {
  const [params] = useSearchParams()
  const highlight = params.get('job')
  const jobs = useInfiniteQuery({
    queryKey: exportKeys.list,
    queryFn: ({ pageParam }) => fetchExports(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: (query) =>
      query.state.data?.pages.some((p) => p.items.some(isActive)) ? POLL_MS : false,
  })
  const items = jobs.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="page page--wide">
      <PageHeader
        title="Exports"
        meta="Start an export from the Assets list or a group. Files are kept encrypted and can be downloaded by their creator for 24 hours."
      />
      <section className="panel panel--flush" aria-label="Export history" aria-live="polite">
        {jobs.isPending && <LoadingState label="Loading exports…" />}
        {jobs.isError && <QueryErrorState error={jobs.error} what="exports" />}
        {jobs.isSuccess && items.length === 0 && (
          <EmptyState title="No exports yet.">
            Use the Export button on the Assets list or on a group page.
          </EmptyState>
        )}
        {items.length > 0 && (
          <table className="data-table">
            <caption className="visually-hidden">Exports</caption>
            <thead>
              <tr>
                <th scope="col">Data</th>
                <th scope="col">Status</th>
                <th scope="col">Records</th>
                <th scope="col">Created</th>
                <th scope="col">Available until</th>
                <th scope="col">
                  <span className="visually-hidden">Download</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((job) => {
                const status = EXPORT_STATUS[job.status]
                const related = Object.entries(job.related_counts)
                return (
                  <tr key={job.id} className={job.id === highlight ? 'row--highlight' : undefined}>
                    <td>
                      {FAMILY_LABEL[job.family] ?? job.family} · {FORMAT_LABEL[job.file_format]}
                      <span className="cell-secondary">
                        {SCOPE_LABEL[job.scope]}
                        {job.scope === 'selected' && ` (${job.selected_count})`}
                        {job.related.length > 0 && ` · with ${job.related.join(', ')}`}
                      </span>
                    </td>
                    <td>
                      <StatusBadge tone={status.tone} label={status.label} />
                      {job.status === 'failed' && (
                        <span className="cell-secondary">{job.error_message}</span>
                      )}
                      {job.masked_columns.length > 0 && job.status === 'completed' && (
                        <span className="cell-secondary">Personal data left out</span>
                      )}
                    </td>
                    <td className="nowrap">
                      {job.status === 'completed' || job.status === 'expired'
                        ? job.row_count.toLocaleString('en-GB')
                        : '–'}
                      {related.length > 0 && (
                        <span className="cell-secondary">
                          {related
                            .map(([name, n]) => `${n.toLocaleString('en-GB')} ${name.replace('_', ' ')}`)
                            .join(', ')}
                        </span>
                      )}
                    </td>
                    <td className="nowrap">
                      {formatDateTime(job.created_at)}
                      <span className="cell-secondary">{job.created_by}</span>
                    </td>
                    <td className="nowrap">
                      {job.status === 'completed' ? formatDateTime(job.expires_at) : '–'}
                    </td>
                    <td className="nowrap">
                      {job.downloadable && (
                        <a
                          className="button button--secondary"
                          href={exportDownloadUrl(job.id)}
                          download={job.filename}
                        >
                          <Download size={16} aria-hidden="true" />
                          Download
                          <span className="visually-hidden">
                            {' '}
                            {job.filename}
                          </span>
                        </a>
                      )}
                      {job.downloadable && (
                        <span className="cell-secondary">{formatBytes(job.size_bytes)}</span>
                      )}
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
