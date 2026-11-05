// UTC instants from the API, displayed in the organization timezone (docs/02).
export const DISPLAY_TIMEZONE = 'Asia/Nicosia'

export interface DisplayPreferences {
  timezone: string
  date_format: 'day_month_year' | 'month_day_year' | 'iso'
}
let display: DisplayPreferences = { timezone: DISPLAY_TIMEZONE, date_format: 'day_month_year' }
let timezoneWarning: string | null = null

/** One organization per browser session. Auth responses apply validated policy before render. */
export function configureDisplay(preferences?: DisplayPreferences) {
  display = preferences ?? { timezone: DISPLAY_TIMEZONE, date_format: 'day_month_year' }
  timezoneWarning = null
  try {
    new Intl.DateTimeFormat('en-GB', { timeZone: display.timezone })
  } catch {
    display = { ...display, timezone: 'UTC' }
    timezoneWarning = 'This browser does not support the organization timezone. Dates are shown in UTC.'
  }
}

export const getDisplayTimezoneWarning = () => timezoneWarning

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
  if (display.timezone === DISPLAY_TIMEZONE && display.date_format === 'day_month_year') return dateTimeFormat.format(new Date(iso))
  return formatConfigured(new Date(iso), display, true)
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
  const calendar = /^\d{4}-\d{2}-\d{2}$/.test(value)
  if (display.timezone === DISPLAY_TIMEZONE && display.date_format === 'day_month_year') {
    return calendar ? calendarFormat.format(new Date(`${value}T00:00:00Z`)) : instantDateFormat.format(new Date(value))
  }
  return formatConfigured(new Date(calendar ? `${value}T00:00:00Z` : value), { ...display, timezone: calendar ? 'UTC' : display.timezone }, false)
}

export function previewDateTime(iso: string, preferences: DisplayPreferences): string {
  return formatConfigured(new Date(iso), preferences, true)
}

function formatConfigured(value: Date, preferences: DisplayPreferences, time: boolean): string {
  const parts = new Intl.DateTimeFormat(preferences.date_format === 'month_day_year' ? 'en-US' : 'en-GB', {
    timeZone: preferences.timezone, year: 'numeric', month: preferences.date_format === 'iso' ? '2-digit' : 'short', day: '2-digit',
    ...(time ? { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' as const } : {}),
  })
  if (preferences.date_format !== 'iso') return parts.format(value)
  const fields = Object.fromEntries(parts.formatToParts(value).map((part) => [part.type, part.value]))
  return `${fields.year}-${fields.month}-${fields.day}${time ? ` ${fields.hour}:${fields.minute}` : ''}`
}
