import { useQuery } from '@tanstack/react-query'
import { fetchMe, queryKeys } from '../shared/api/accounts'
import { isApiError } from '../shared/api/client'
import type { Me } from '../shared/api/types'

async function fetchMeOrNull(): Promise<Me | null> {
  try {
    return await fetchMe()
  } catch (error) {
    if (isApiError(error, 401)) return null
    throw error
  }
}

export function useSession() {
  const query = useQuery({ queryKey: queryKeys.me, queryFn: fetchMeOrNull, staleTime: 60_000 })
  const me = query.data ?? null
  return {
    me,
    isPending: query.isPending,
    error: query.error,
    can: (permission: string) => me?.permissions.includes(permission) ?? false,
  }
}
