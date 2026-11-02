import { useQuery } from '@tanstack/react-query'
import { fetchReadiness } from '../../shared/api/health'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'

export function SystemHealthPage() {
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['health', 'ready'],
    queryFn: fetchReadiness,
    retry: false,
  })

  const dependencies = Object.entries(data?.dependencies ?? {})

  return (
    <div className="page">
      <PageHeader
        title="System health"
        meta={
          data
            ? data.status === 'ok'
              ? 'All required dependencies are reachable.'
              : 'One or more required dependencies are down.'
            : 'API and dependency readiness for this environment.'
        }
      />

      <section className="panel" aria-live="polite">
        {isPending && <LoadingState label="Checking dependency status…" />}
        {isError && <QueryErrorState error={error} what="dependency status" />}
        {data && dependencies.length === 0 && <EmptyState title="No dependencies reported." />}
        {dependencies.length > 0 && (
          <ul className="dependency-list">
            {dependencies.map(([name, dependency]) => (
              <li key={name} className="dependency-list__row">
                <div>
                  <div className="dependency-list__name">{name}</div>
                  {dependency.detail && (
                    <div className="dependency-list__detail">{dependency.detail}</div>
                  )}
                </div>
                <StatusBadge
                  tone={dependency.status === 'up' ? 'success' : 'danger'}
                  label={dependency.status}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
