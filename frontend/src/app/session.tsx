import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { DeniedState, LoadingState, QueryErrorState } from '../shared/ui/States'
import { useSession } from './useSession'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { me, isPending, error } = useSession()
  const location = useLocation()

  if (isPending) return <LoadingState label="Checking your session…" />
  if (error) return <QueryErrorState error={error} what="your session" />
  if (!me) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(next)}`} replace />
  }
  if (me.must_change_password && location.pathname !== '/account/password') {
    return <Navigate to="/account/password" replace />
  }
  return children
}

export function RequirePermission({
  permission,
  what,
  children,
}: {
  permission: string
  what: string
  children: ReactNode
}) {
  const { can } = useSession()
  return can(permission) ? children : <DeniedState what={what} />
}
