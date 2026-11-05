import { apiGet, apiRequest } from './client'
import type { components } from './schema'

export type GeneralSettings = components['schemas']['GeneralSettings']
export const generalKey = ['settings', 'general'] as const
export const fetchGeneralSettings = () => apiGet<GeneralSettings>('/settings/general/')
export const saveGeneralSettings = (settings: GeneralSettings) => {
  const { version, modified_at: _at, modified_by: _by, ...body } = settings
  return apiRequest<GeneralSettings>('PATCH', '/settings/general/', { body, ifMatch: version })
}
