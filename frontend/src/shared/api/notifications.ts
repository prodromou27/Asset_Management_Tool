import { apiGet, apiRequest } from './client'
import type {
  NotificationRecipient,
  NotificationRule,
  NotificationRuleWrite,
  NotificationTemplate,
  RulePreview,
  OutboxMessage,
  OutboxStats,
  Paginated,
  SmtpProfile,
  SmtpProfileWrite,
  TemplatePreview,
} from './types'

type Query = Record<string, string | undefined>
type TemplateDraft = { subject?: string; body_text?: string; body_html?: string }

export const notificationKeys = {
  all: ['notifications'] as const,
  smtp: ['notifications', 'smtp'] as const,
  stats: ['notifications', 'stats'] as const,
  outbox: (q: Query) => ['notifications', 'outbox', q] as const,
  templates: ['notifications', 'templates'] as const,
  rules: ['notifications', 'rules'] as const,
  recipients: ['notifications', 'recipients'] as const,
}

export const fetchSmtp = () => apiGet<SmtpProfile>('/settings/smtp/')
export const updateSmtp = (version: number, body: SmtpProfileWrite) =>
  apiRequest<SmtpProfile>('PATCH', '/settings/smtp/', { body, ifMatch: version })
export const testSmtp = () => apiRequest<SmtpProfile>('POST', '/smtp/test/')
export const sendTestEmail = () => apiRequest<OutboxMessage>('POST', '/smtp/test-email/')

export const fetchOutboxStats = () => apiGet<OutboxStats>('/notifications/outbox/stats/')
export const fetchOutbox = (query: Query, cursor?: string) =>
  apiGet<Paginated<OutboxMessage>>('/notifications/outbox/', { ...query, cursor })
export const retryMessage = (id: string) => apiRequest<OutboxMessage>('POST', `/notifications/outbox/${id}/retry/`)
export const cancelMessage = (id: string) => apiRequest<OutboxMessage>('POST', `/notifications/outbox/${id}/cancel/`)

export const fetchTemplates = () => apiGet<NotificationTemplate[]>('/notifications/templates/')
export const updateTemplate = (code: string, version: number, body: TemplateDraft) =>
  apiRequest<NotificationTemplate>('PATCH', `/notifications/templates/${code}/`, { body, ifMatch: version })
export const previewTemplate = (code: string, body: TemplateDraft) =>
  apiRequest<TemplatePreview>('POST', `/notifications/templates/${code}/preview/`, { body })

// Notification rules (Task 018b).
export const fetchRules = () => apiGet<NotificationRule[]>('/notifications/rules/')
export const createRule = (body: NotificationRuleWrite) =>
  apiRequest<NotificationRule>('POST', '/notifications/rules/', { body })
export const updateRule = (id: string, version: number, body: Partial<NotificationRuleWrite>) =>
  apiRequest<NotificationRule>('PATCH', `/notifications/rules/${id}/`, { body, ifMatch: version })
export const deleteRule = (id: string) => apiRequest<void>('DELETE', `/notifications/rules/${id}/`)
export const previewRule = (id: string) => apiRequest<RulePreview>('POST', `/notifications/rules/${id}/preview/`)
export const fetchRecipients = () => apiGet<NotificationRecipient[]>('/notifications/recipients/')
