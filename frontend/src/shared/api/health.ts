import { ApiError, apiGet } from './client'
import type { components } from './schema'

export type ReadinessResponse = components['schemas']['Readiness']
export type LivenessResponse = components['schemas']['Liveness']
export type OperationalHealth = components['schemas']['OperationalHealth']
export const fetchOperationalHealth = () => apiGet<OperationalHealth>('/health/operations/')

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export function fetchLiveness(): Promise<LivenessResponse> {
  return apiGet<LivenessResponse>('/health/live/')
}

/** 503 still carries the per-dependency body ("degraded"), so it is data, not an error. */
export async function fetchReadiness(): Promise<ReadinessResponse> {
  const response = await fetch(`${API_BASE_URL}/health/ready/`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
  })
  if (response.status !== 200 && response.status !== 503) {
    throw new ApiError(`Readiness check failed with status ${response.status}`, response.status)
  }
  return (await response.json()) as ReadinessResponse
}
