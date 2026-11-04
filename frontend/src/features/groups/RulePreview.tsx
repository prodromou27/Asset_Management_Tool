import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { isApiError } from '../../shared/api/client'
import { previewGroupRule, previewRule, type RuleNode } from '../../shared/api/groups'
import { ruleComplete } from './ruleUtils'

function useDebounced<T>(value: T, delay = 400): T {
  const [current, setCurrent] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setCurrent(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return current
}

/** Live preview of a rule among the assets the user can see. With `groupId`, also how
 * many current members it would add or remove. */
export function RulePreview({ rule, groupId }: { rule: RuleNode; groupId?: string }) {
  const debounced = useDebounced(rule)
  const key = JSON.stringify(debounced)
  const complete = ruleComplete(debounced)
  const preview = useQuery({
    queryKey: ['groups', 'preview', groupId ?? 'new', key],
    queryFn: () => (groupId ? previewGroupRule(groupId, debounced) : previewRule(debounced)),
    enabled: complete,
    retry: false,
  })
  return (
    <section className="panel rule-preview" aria-live="polite" aria-label="Rule preview">
      {!complete && <p className="field__help">Fill in every condition to see matching assets.</p>}
      {complete && preview.isPending && <p className="field__help">Checking…</p>}
      {preview.isError && (
        <p className="field__error">
          {isApiError(preview.error)
            ? Object.values(preview.error.fieldErrors).flat().join(' ') || preview.error.message
            : 'Could not preview the rule.'}
        </p>
      )}
      {complete && preview.data && (
        <>
          <p>
            <strong>{preview.data.count}</strong> matching {preview.data.count === 1 ? 'asset' : 'assets'} in your
            sites
            {preview.data.would_add !== null &&
              ` · would add ${preview.data.would_add}, remove ${preview.data.would_remove}`}
          </p>
          {preview.data.sample.length > 0 && (
            <ul className="plain-list">
              {preview.data.sample.slice(0, 10).map((a) => (
                <li key={a.id}>
                  <Link to={`/assets/${a.id}`}>{a.name}</Link> <span className="cell-secondary mono">{a.site.code}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
