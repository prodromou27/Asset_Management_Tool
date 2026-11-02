import { useInfiniteQuery } from '@tanstack/react-query'
import { Fragment, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchAuditEvents, queryKeys, type AuditFilters } from '../../shared/api/accounts'
import type { AuditEvent } from '../../shared/api/types'
import { DISPLAY_TIMEZONE, formatDateTime } from '../../shared/format'
import { Button } from '../../shared/ui/Button'
import { SelectField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge, type StatusTone } from '../../shared/ui/StatusBadge'

const OUTCOME_TONE: Record<AuditEvent['outcome'], StatusTone> = {
  success: 'success',
  failure: 'danger',
  denied: 'warning',
}

const FILTER_KEYS = ['action', 'actor', 'outcome', 'object_id'] as const
type Filters = AuditFilters & { object_id?: string }

export function AuditLogPage() {
  const [params, setParams] = useSearchParams()
  const filters: Filters = Object.fromEntries(
    FILTER_KEYS.map((key) => [key, params.get(key) ?? undefined]),
  )
  const [draft, setDraft] = useState({ action: filters.action ?? '', actor: filters.actor ?? '' })
  const [expanded, setExpanded] = useState<string | null>(null)

  const events = useInfiniteQuery({
    queryKey: queryKeys.audit(filters),
    queryFn: ({ pageParam }) => fetchAuditEvents(filters, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  })

  function apply(next: Partial<Filters>) {
    const merged = { ...filters, ...next }
    const search = new URLSearchParams()
    for (const [key, value] of Object.entries(merged)) if (value) search.set(key, value)
    setParams(search, { replace: true })
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    apply({ action: draft.action.trim() || undefined, actor: draft.actor.trim() || undefined })
  }

  const items = events.data?.pages.flatMap((page) => page.items) ?? []
  const total = events.data?.pages[0]?.count
  const filtered = FILTER_KEYS.some((key) => filters[key])

  return (
    <div className="page">
      <PageHeader
        title="Audit log"
        meta={`Append-only record of sign-ins and administrative changes. Times in ${DISPLAY_TIMEZONE}.${
          total === undefined ? '' : ` ${total} ${total === 1 ? 'event' : 'events'}.`
        }`}
      />
      <form className="toolbar" role="search" onSubmit={handleSubmit}>
        <TextField
          label="Action"
          name="action"
          placeholder="e.g. users.disable"
          spellCheck={false}
          value={draft.action}
          onChange={(event) => setDraft((d) => ({ ...d, action: event.target.value }))}
        />
        <TextField
          label="Actor username"
          name="actor"
          spellCheck={false}
          value={draft.actor}
          onChange={(event) => setDraft((d) => ({ ...d, actor: event.target.value }))}
        />
        <SelectField
          label="Outcome"
          name="outcome"
          options={[
            { value: '', label: 'Any outcome' },
            { value: 'success', label: 'Success' },
            { value: 'failure', label: 'Failure' },
            { value: 'denied', label: 'Denied' },
          ]}
          value={filters.outcome ?? ''}
          onChange={(event) => apply({ outcome: event.target.value || undefined })}
        />
        <div className="toolbar__actions">
          <Button type="submit">Apply</Button>
          {filtered && (
            <Button
              variant="quiet"
              onClick={() => {
                setDraft({ action: '', actor: '' })
                setParams(new URLSearchParams(), { replace: true })
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
      </form>
      {filters.object_id && (
        <p className="filter-note">
          Showing events for object <code>{filters.object_id}</code>.{' '}
          <button type="button" className="link-button" onClick={() => apply({ object_id: undefined })}>
            Show all objects
          </button>
        </p>
      )}

      <section className="panel panel--flush" aria-live="polite">
        {events.isPending && <LoadingState label="Loading audit events…" />}
        {events.isError && <QueryErrorState error={events.error} what="the audit log" />}
        {events.isSuccess && items.length === 0 && (
          <EmptyState title={filtered ? 'No events match these filters.' : 'No audit events yet.'} />
        )}
        {items.length > 0 && (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Audit events, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Action</th>
                  <th scope="col">Object</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">
                    <span className="visually-hidden">Details</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((event) => (
                  <Fragment key={event.id}>
                    <tr>
                      <td className="nowrap">{formatDateTime(event.occurred_at)}</td>
                      <td>
                        <span className="mono">{event.actor_label}</span>
                        {event.source !== 'api' && (
                          <span className="cell-secondary">via {event.source}</span>
                        )}
                      </td>
                      <td className="mono">{event.action}</td>
                      <td>
                        {event.object_label || event.object_type || (
                          <span className="cell-muted">Not applicable</span>
                        )}
                      </td>
                      <td>
                        <StatusBadge
                          tone={OUTCOME_TONE[event.outcome]}
                          label={event.outcome[0].toUpperCase() + event.outcome.slice(1)}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          aria-expanded={expanded === event.id}
                          aria-controls={`audit-${event.id}`}
                          onClick={() => setExpanded(expanded === event.id ? null : event.id)}
                        >
                          {expanded === event.id ? 'Hide' : 'Details'}
                        </button>
                      </td>
                    </tr>
                    {expanded === event.id && (
                      <tr className="detail-row" id={`audit-${event.id}`}>
                        <td colSpan={6}>
                          <AuditDetail event={event} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {events.hasNextPage && (
          <div className="table-footer">
            <Button onClick={() => events.fetchNextPage()} busy={events.isFetchingNextPage}>
              Load more
            </Button>
          </div>
        )}
      </section>
    </div>
  )
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function show(value: unknown): string {
  if (value === undefined) return '—'
  if (Array.isArray(value)) return value.join(', ') || '(none)'
  if (value === '' || value === null) return '(empty)'
  return String(value)
}

function AuditDetail({ event }: { event: AuditEvent }) {
  const before = asRecord(event.before)
  const after = asRecord(event.after)
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])]
  return (
    <div className="audit-detail">
      <dl className="meta-grid">
        {event.detail && (
          <>
            <dt>Detail</dt>
            <dd>{event.detail}</dd>
          </>
        )}
        <dt>Object ID</dt>
        <dd className="mono">{event.object_id || 'Not applicable'}</dd>
        <dt>Request ID</dt>
        <dd className="mono">{event.request_id || 'Not recorded'}</dd>
        <dt>Source address</dt>
        <dd className="mono">{event.ip_address ?? 'Not recorded'}</dd>
      </dl>
      {keys.length > 0 && (
        <table className="data-table data-table--compact">
          <caption className="audit-detail__caption">Recorded values (secrets redacted)</caption>
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Before</th>
              <th scope="col">After</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => {
              const changed = show(before[key]) !== show(after[key])
              return (
                <tr key={key} className={changed ? 'row--changed' : undefined}>
                  <th scope="row" className="mono">
                    {key}
                  </th>
                  <td>{show(before[key])}</td>
                  <td>
                    {show(after[key])}
                    {changed && <span className="visually-hidden"> (changed)</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
