/** Only same-origin absolute paths; blocks //host and scheme-based open redirects. */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/'
  return next
}
