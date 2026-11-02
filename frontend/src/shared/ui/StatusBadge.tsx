export type StatusTone = 'success' | 'warning' | 'danger' | 'neutral'

interface StatusBadgeProps {
  tone: StatusTone
  label: string
}

/** Text always carries the meaning; colour only reinforces it. */
export function StatusBadge({ tone, label }: StatusBadgeProps) {
  return <span className={`status-badge status-badge--${tone}`}>{label}</span>
}
