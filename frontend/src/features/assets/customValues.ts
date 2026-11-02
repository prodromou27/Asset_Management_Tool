import type { CustomFieldDefinition } from '../../shared/api/types'

export type CustomValues = Record<string, string>

/** Stored JSON value → form string. */
export function toFormValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

/** Form string → API value (null clears; the server coerces numbers and dates). */
export function toApiValues(
  definitions: CustomFieldDefinition[],
  values: CustomValues,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const definition of definitions) {
    const raw = (values[definition.key] ?? '').trim()
    if (raw === '') out[definition.key] = null
    else if (definition.field_type === 'boolean') out[definition.key] = raw === 'true'
    else out[definition.key] = raw
  }
  return out
}
