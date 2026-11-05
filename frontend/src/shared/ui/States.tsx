import { useEffect, useRef, type ReactNode } from 'react'
import { Inbox } from 'lucide-react'
import { isApiError } from '../api/client'

export function LoadingState({ label }: { label: string }) {
  return (
    <p className="state state--loading" role="status">
      {label}
    </p>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state state--empty">
      <span className="state__icon" aria-hidden="true"><Inbox size={18} strokeWidth={1.75} /></span>
      <div>
        <p className="state__title">{title}</p>
        {children && <p className="state__body">{children}</p>}
      </div>
    </div>
  )
}

export function DeniedState({ what }: { what: string }) {
  return (
    <div className="state state--denied" role="alert">
      <p className="state__title">You do not have access to {what}.</p>
      <p className="state__body">Ask a System Admin to review your role if you need it.</p>
    </div>
  )
}

/** Renders the right state for a failed query: denied for 403, otherwise an error. */
export function QueryErrorState({ error, what }: { error: unknown; what: string }) {
  if (isApiError(error, 403)) return <DeniedState what={what} />
  const message = error instanceof Error ? error.message : 'Unknown error'
  const requestId = isApiError(error) ? error.requestId : null
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">Could not load {what}.</p>
      <p className="state__body">
        {message}
        {requestId && (
          <>
            {' '}
            Reference <code>{requestId}</code>.
          </>
        )}
      </p>
    </div>
  )
}

interface ErrorSummaryProps {
  message: string
  fieldErrors: Record<string, string[]>
  fieldLabels: Record<string, string>
}

/** Focused on render so keyboard and screen-reader users land on the problem list. */
export function ErrorSummary({ message, fieldErrors, fieldLabels }: ErrorSummaryProps) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [message, fieldErrors])

  const entries = Object.entries(fieldErrors)
  return (
    <div className="error-summary" role="alert" tabIndex={-1} ref={ref}>
      <p className="error-summary__title">{message}</p>
      {entries.length > 0 && (
        <ul className="error-summary__list">
          {entries.map(([field, messages]) => (
            <li key={field}>
              {fieldLabels[field] ? `${fieldLabels[field]}: ` : ''}
              {messages.join(' ')}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
