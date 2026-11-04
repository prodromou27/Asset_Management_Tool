// UTC instants from the API, displayed in the organization timezone (docs/02).
// Admin-selectable timezone arrives with the General settings area.
export const DISPLAY_TIMEZONE = 'Asia/Nicosia'

const dateTimeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: DISPLAY_TIMEZONE,
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
})

export function formatDateTime(iso: string | null | undefined, empty = 'Never'): string {
  if (!iso) return empty
  return dateTimeFormat.format(new Date(iso))
}

const relative = new Intl.RelativeTimeFormat('en-GB', { numeric: 'auto' })

/** "3 hours ago" style text for recency columns; absolute time belongs in a tooltip. */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const abs = Math.abs(seconds)
  if (abs < 60) return relative.format(seconds, 'second')
  if (abs < 3600) return relative.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return relative.format(Math.round(seconds / 3600), 'hour')
  if (abs < 86400 * 60) return relative.format(Math.round(seconds / 86400), 'day')
  return relative.format(Math.round(seconds / (86400 * 30)), 'month')
}

const calendarFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC',
  year: 'numeric',
  month: 'short',
  day: '2-digit',
})
const instantDateFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: DISPLAY_TIMEZONE,
  year: 'numeric',
  month: 'short',
  day: '2-digit',
})

/** Calendar dates ("2026-12-31") are shown as that exact day, never shifted by timezone;
 * full timestamps are shown as the day in the organization timezone. */
export function formatDate(value: string | null | undefined, empty = '–'): string {
  if (!value) return empty
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return calendarFormat.format(new Date(`${value}T00:00:00Z`))
  return instantDateFormat.format(new Date(value))
}
