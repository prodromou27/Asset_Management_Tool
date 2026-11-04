import type { RuleNode } from '../../shared/api/groups'
import type { RuleField } from '../../shared/api/types'

export const OPERATOR_LABEL: Record<string, string> = {
  eq: 'is',
  in: 'is any of',
  contains: 'contains',
  before: 'is before',
  after: 'is after',
}

export type Condition = { field: string; operator: string; value: unknown }
export type Group = { op: 'and' | 'or'; rules: RuleNode[] }

export const isGroup = (n: RuleNode): n is Group => 'op' in n && (n.op === 'and' || n.op === 'or')
export const isNot = (n: RuleNode): n is { op: 'not'; rule: RuleNode } => 'op' in n && n.op === 'not'

export const emptyRule = (): RuleNode => ({ op: 'and', rules: [{ field: 'manufacturer', operator: 'eq', value: '' }] })

/** True when every condition has a value (the server validates everything again). */
export function ruleComplete(node: RuleNode): boolean {
  if (isGroup(node)) return node.rules.length > 0 && node.rules.every(ruleComplete)
  if (isNot(node)) return ruleComplete(node.rule)
  const value = (node as Condition).value
  if (Array.isArray(value)) return value.length > 0
  return value === null || (typeof value === 'string' && value.trim() !== '')
}

/** One-line description of a rule for lists and history. */
export function describeRule(node: RuleNode | null | undefined, fields: RuleField[] = []): string {
  if (!node) return ''
  if (isGroup(node)) return node.rules.map((r) => describeRule(r, fields)).join(node.op === 'and' ? ' and ' : ' or ')
  if (isNot(node)) return `not (${describeRule(node.rule, fields)})`
  const c = node as Condition
  const label = fields.find((f) => f.field === c.field)?.label ?? c.field
  const value = Array.isArray(c.value) ? `${c.value.length} values` : c.value === null ? 'not set' : String(c.value)
  return `${label} ${OPERATOR_LABEL[c.operator] ?? c.operator} ${value}`
}
