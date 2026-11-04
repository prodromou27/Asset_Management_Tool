export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
const CSRF_COOKIE = 'itam_csrftoken'
const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

export type FieldErrors = Record<string, string[]>

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fieldErrors: FieldErrors
  readonly requestId: string | null

  constructor(
    message: string,
    status: number,
    code = 'ERROR',
    fieldErrors: FieldErrors = {},
    requestId: string | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fieldErrors = fieldErrors
    this.requestId = requestId
  }
}

export function isApiError(error: unknown, status?: number): error is ApiError {
  return error instanceof ApiError && (status === undefined || error.status === status)
}

function readCookie(name: string): string | null {
  const match = document.cookie.split('; ').find((part) => part.startsWith(`${name}=`))
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null
}

interface RequestOptions {
  body?: unknown
  ifMatch?: number
  query?: Record<string, string | undefined>
  /** Extra request headers (for example X-Idempotency-Key). */
  headers?: Record<string, string>
}

export async function apiRequest<T>(
  method: string,
  path: string,
  { body, ifMatch, query, headers: extra }: RequestOptions = {},
): Promise<T> {
  const multipart = body instanceof FormData
  const headers: Record<string, string> = { Accept: 'application/json', ...extra }
  // FormData sets its own multipart boundary.
  if (body !== undefined && !multipart) headers['Content-Type'] = 'application/json'
  if (UNSAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE)
    if (token) headers['X-CSRFToken'] = token
  }
  if (ifMatch !== undefined) headers['If-Match'] = `"${ifMatch}"`

  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value) params.set(key, value)
  }
  const search = params.size > 0 ? `?${params.toString()}` : ''

  const response = await fetch(`${API_BASE_URL}${path}${search}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
  })

  if (response.status === 204) return undefined as T

  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = (payload as { error?: Record<string, unknown> } | null)?.error
    throw new ApiError(
      typeof error?.message === 'string'
        ? error.message
        : `Request failed with status ${response.status}`,
      response.status,
      typeof error?.code === 'string' ? error.code : 'ERROR',
      (error?.field_errors as FieldErrors | undefined) ?? {},
      typeof error?.request_id === 'string' ? error.request_id : null,
    )
  }
  return payload as T
}

export const apiGet = <T>(path: string, query?: RequestOptions['query']) =>
  apiRequest<T>('GET', path, { query })
