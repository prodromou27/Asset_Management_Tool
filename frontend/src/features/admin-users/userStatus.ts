import type { User } from '../../shared/api/types'
import type { StatusTone } from '../../shared/ui/StatusBadge'

export function userStatus(user: User): { tone: StatusTone; label: string } {
  if (!user.is_active) return { tone: 'neutral', label: 'Disabled' }
  if (user.is_locked) return { tone: 'warning', label: 'Locked' }
  if (user.must_change_password) return { tone: 'warning', label: 'Password change pending' }
  return { tone: 'success', label: 'Active' }
}
