import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as healthApi from '../../shared/api/health'
import { SystemHealthPage } from './SystemHealthPage'

function renderWithQueryClient(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
  )
}

describe('SystemHealthPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a loading state before the response arrives', () => {
    vi.spyOn(healthApi, 'fetchReadiness').mockReturnValue(new Promise(() => {}))

    renderWithQueryClient(<SystemHealthPage />)

    expect(screen.getByText(/checking dependency status/i)).toBeInTheDocument()
  })

  it('shows dependency statuses on success', async () => {
    vi.spyOn(healthApi, 'fetchReadiness').mockResolvedValue({
      status: 'ok',
      dependencies: {
        database: { status: 'up', detail: '' },
        redis: { status: 'up', detail: '' },
      },
    })

    renderWithQueryClient(<SystemHealthPage />)

    expect(await screen.findByText('database')).toBeInTheDocument()
    expect(await screen.findByText('redis')).toBeInTheDocument()
    expect(screen.getAllByText('up')).toHaveLength(2)
  })

  it('shows an error state when the API call fails', async () => {
    vi.spyOn(healthApi, 'fetchReadiness').mockRejectedValue(new Error('network down'))

    renderWithQueryClient(<SystemHealthPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent('network down')
  })
})

describe('fetchReadiness', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('treats a 503 degraded response as data so the failed dependency is shown', async () => {
    const body = {
      status: 'degraded',
      dependencies: {
        database: { status: 'down', detail: 'Unreachable. See API logs for details.' },
        redis: { status: 'up', detail: '' },
      },
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status: 503 })))
    const { fetchReadiness } = await vi.importActual<typeof healthApi>('../../shared/api/health')

    await expect(fetchReadiness()).resolves.toEqual(body)
  })
})
