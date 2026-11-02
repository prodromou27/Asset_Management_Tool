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
