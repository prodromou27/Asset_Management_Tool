import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { queryKeys } from '../shared/api/accounts'
import { isApiError } from '../shared/api/client'

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (count, error) => !isApiError(error) && count < 2,
      },
    },
    // Any 401 means the session ended (timeout, revocation); drop identity so guards redirect.
    queryCache: new QueryCache({ onError: (error) => handleUnauthenticated(client, error) }),
    mutationCache: new MutationCache({
      onError: (error) => handleUnauthenticated(client, error),
    }),
  })
  return client
}

function handleUnauthenticated(client: QueryClient, error: unknown) {
  if (isApiError(error, 401) && error.code !== 'LOGIN_FAILED') {
    client.setQueryData(queryKeys.me, null)
  }
}
