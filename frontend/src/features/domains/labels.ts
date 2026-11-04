import type { Expiry } from '../../shared/api/types'
import type { StatusTone } from '../../shared/ui/StatusBadge'

/** Expiry badge text and tone: Unknown is its own state, never guessed (docs/15 A12). */
export function expiryBadge(expiry: Expiry): { label: string; tone: StatusTone } {
  const days = expiry.days_remaining ?? 0
  switch (expiry.status) {
    case 'expired':
      return { label: `Expired ${-days} ${-days === 1 ? 'day' : 'days'} ago`, tone: 'danger' }
    case 'expiring':
      return {
        label: days === 0 ? 'Expires today' : `${days} ${days === 1 ? 'day' : 'days'} left`,
        tone: (expiry.threshold ?? 90) <= 14 ? 'danger' : 'warning',
      }
    case 'ok':
      return { label: `${days.toLocaleString('en-GB')} days left`, tone: 'success' }
    default:
      return { label: 'Unknown', tone: 'neutral' }
  }
}

export const CHECK_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  never: { label: 'Not checked yet', tone: 'neutral' },
  ok: { label: 'Certificate read', tone: 'success' },
  failed: { label: 'Check failed', tone: 'danger' },
  blocked: { label: 'Target not allowed', tone: 'danger' },
}

/** Fingerprint in colon-separated pairs, shortened unless full. */
export function fingerprint(hex: string, full = false): string {
  const pairs = hex.toUpperCase().match(/.{2}/g) ?? []
  return full ? pairs.join(':') : `${pairs.slice(0, 8).join(':')}…`
}
