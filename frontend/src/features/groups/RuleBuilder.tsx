import { useQuery } from '@tanstack/react-query'
import { useSession } from '../../app/useSession'
import {
  assetKeys,
  fetchCategories,
  fetchDepartments,
  fetchLocations,
  fetchSites,
  fetchUserLookup,
} from '../../shared/api/assets'
import { discoveryKeys, fetchIntegrations } from '../../shared/api/discovery'
import { fetchGroups, fetchRuleFields, groupKeys, type RuleNode } from '../../shared/api/groups'
import { PERMISSIONS, type RuleField } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { categoryOptions } from '../assets/labels'
import { OPERATOR_LABEL, isGroup, isNot, type Condition, type Group } from './ruleUtils'

const MAX_DEPTH = 4
const NOT_SET = '__not_set__'

function useRefOptions() {
  const { can } = useSession()
  const categories = useQuery({ queryKey: assetKeys.categories, queryFn: fetchCategories })
  const sites = useQuery({ queryKey: assetKeys.sites, queryFn: fetchSites })
  const locations = useQuery({ queryKey: assetKeys.locations(), queryFn: () => fetchLocations() })
  const departments = useQuery({ queryKey: assetKeys.departments, queryFn: fetchDepartments })
  const users = useQuery({ queryKey: assetKeys.userLookup, queryFn: fetchUserLookup })
  const groups = useQuery({ queryKey: groupKeys.list, queryFn: fetchGroups })
  const integrations = useQuery({
    queryKey: discoveryKeys.integrations,
    queryFn: fetchIntegrations,
    enabled: can(PERMISSIONS.discoveryView) || can(PERMISSIONS.integrationsManage),
  })
  return (ref: string): { value: string; label: string }[] | null => {
    switch (ref) {
      case 'category':
        return categoryOptions(categories.data ?? [], { activeOnly: false })
      case 'site':
        return (sites.data ?? []).map((s) => ({ value: s.id, label: `${s.code} — ${s.name}` }))
      case 'location':
        return (locations.data ?? []).map((l) => ({ value: l.id, label: l.name }))
      case 'department':
        return (departments.data ?? []).map((d) => ({ value: d.id, label: d.name }))
      case 'user':
        return (users.data ?? []).map((u) => ({ value: u.id, label: u.display_name }))
      case 'group':
        return (groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))
      case 'integration':
        return integrations.data ? integrations.data.map((i) => ({ value: i.id, label: i.name })) : null
      default:
        return null
    }
  }
}

function ValueInput({
  field,
  condition,
  label,
  onChange,
  options,
}: {
  field: RuleField
  condition: Condition
  label: string
  onChange: (value: unknown) => void
  options: { value: string; label: string }[] | null
}) {
  const multi = condition.operator === 'in'
  if (field.kind === 'date') {
    return (
      <input
        className="field__control"
        type="date"
        aria-label={label}
        value={String(condition.value ?? '')}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  }
  const choices = field.kind === 'enum' ? field.choices : field.kind === 'ref' ? options : null
  if (choices) {
    if (multi) {
      const selected = Array.isArray(condition.value) ? (condition.value as string[]) : []
      return (
        <select
          className="field__control"
          multiple
          aria-label={label}
          value={selected}
          onChange={(e) => onChange(Array.from(e.target.selectedOptions, (o) => o.value))}
        >
          {choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      )
    }
    return (
      <select
        className="field__control"
        aria-label={label}
        value={condition.value === null ? NOT_SET : String(condition.value ?? '')}
        onChange={(e) => onChange(e.target.value === NOT_SET ? null : e.target.value)}
      >
        <option value="">Choose…</option>
        {field.kind === 'ref' && field.nullable && <option value={NOT_SET}>(not set)</option>}
        {choices.map((c) => (
          <option key={c.value} value={c.value}>
            {c.label}
          </option>
        ))}
      </select>
    )
  }
  if (multi) {
    return (
      <input
        className="field__control"
        aria-label={label}
        placeholder="Comma-separated values"
        value={Array.isArray(condition.value) ? (condition.value as string[]).join(', ') : ''}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(',')
              .map((v) => v.trim())
              .filter(Boolean),
          )
        }
      />
    )
  }
  return (
    <input
      className="field__control"
      aria-label={label}
      value={String(condition.value ?? '')}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

function ConditionRow({
  node,
  fields,
  options,
  index,
  onChange,
  onRemove,
}: {
  node: RuleNode
  fields: RuleField[]
  options: ReturnType<typeof useRefOptions>
  index: string
  onChange: (n: RuleNode) => void
  onRemove: () => void
}) {
  const negated = isNot(node)
  const condition = (negated ? node.rule : node) as Condition
  const field = fields.find((f) => f.field === condition.field) ?? fields[0]
  const wrap = (c: Condition, not = negated): RuleNode => (not ? { op: 'not', rule: c } : c)
  const resetValue = (operator: string) => (operator === 'in' ? [] : '')
  return (
    <li className="rule-row">
      <select
        className="field__control"
        aria-label={`Condition ${index} field`}
        value={condition.field}
        onChange={(e) => {
          const next = fields.find((f) => f.field === e.target.value)!
          onChange(wrap({ field: next.field, operator: next.operators[0], value: resetValue(next.operators[0]) }))
        }}
      >
        {fields.map((f) => (
          <option key={f.field} value={f.field}>
            {f.label}
          </option>
        ))}
      </select>
      <select
        className="field__control"
        aria-label={`Condition ${index} operator`}
        value={condition.operator}
        onChange={(e) =>
          onChange(wrap({ ...condition, operator: e.target.value, value: resetValue(e.target.value) }))
        }
      >
        {field.operators.map((op) => (
          <option key={op} value={op}>
            {OPERATOR_LABEL[op] ?? op}
          </option>
        ))}
      </select>
      <ValueInput
        field={field}
        condition={condition}
        label={`Condition ${index} value`}
        options={field.kind === 'ref' ? options(field.ref) : null}
        onChange={(value) => onChange(wrap({ ...condition, value }))}
      />
      <label className="checkbox rule-row__not">
        <input type="checkbox" checked={negated} onChange={(e) => onChange(wrap(condition, e.target.checked))} />
        Exclude
      </label>
      <Button variant="quiet" onClick={onRemove}>
        Remove<span className="visually-hidden"> condition {index}</span>
      </Button>
    </li>
  )
}

function GroupNode({
  node,
  fields,
  options,
  depth,
  path,
  onChange,
  onRemove,
}: {
  node: Group
  fields: RuleField[]
  options: ReturnType<typeof useRefOptions>
  depth: number
  path: string
  onChange: (n: RuleNode) => void
  onRemove?: () => void
}) {
  const setChild = (i: number, child: RuleNode) =>
    onChange({ ...node, rules: node.rules.map((r, n) => (n === i ? child : r)) })
  const removeChild = (i: number) => onChange({ ...node, rules: node.rules.filter((_, n) => n !== i) })
  const first = fields[0]
  return (
    <fieldset className="rule-group">
      <legend className="visually-hidden">Rule group {path}</legend>
      <div className="rule-group__head">
        <select
          className="field__control"
          aria-label={`Group ${path} match`}
          value={node.op}
          onChange={(e) => onChange({ ...node, op: e.target.value as 'and' | 'or' })}
        >
          <option value="and">Match all of</option>
          <option value="or">Match any of</option>
        </select>
        {onRemove && (
          <Button variant="quiet" onClick={onRemove}>
            Remove group<span className="visually-hidden"> {path}</span>
          </Button>
        )}
      </div>
      <ul className="rule-list">
        {node.rules.map((child, i) => {
          const index = path ? `${path}.${i + 1}` : String(i + 1)
          return isGroup(child) ? (
            <li key={i}>
              <GroupNode
                node={child}
                fields={fields}
                options={options}
                depth={depth + 1}
                path={index}
                onChange={(c) => setChild(i, c)}
                onRemove={() => removeChild(i)}
              />
            </li>
          ) : (
            <ConditionRow
              key={i}
              node={child}
              fields={fields}
              options={options}
              index={index}
              onChange={(c) => setChild(i, c)}
              onRemove={() => removeChild(i)}
            />
          )
        })}
      </ul>
      <div className="form-actions form-actions--start">
        <Button
          variant="quiet"
          onClick={() =>
            onChange({ ...node, rules: [...node.rules, { field: first.field, operator: first.operators[0], value: '' }] })
          }
        >
          Add condition
        </Button>
        {depth < MAX_DEPTH && (
          <Button
            variant="quiet"
            onClick={() =>
              onChange({
                ...node,
                rules: [...node.rules, { op: 'or', rules: [{ field: first.field, operator: first.operators[0], value: '' }] }],
              })
            }
          >
            Add nested group
          </Button>
        )}
      </div>
    </fieldset>
  )
}

/** docs/07 GroupRuleBuilder: typed rows, AND/OR nesting, validation by the server. */
export function RuleBuilder({ value, onChange }: { value: RuleNode; onChange: (n: RuleNode) => void }) {
  const fields = useQuery({ queryKey: groupKeys.fields, queryFn: fetchRuleFields })
  const options = useRefOptions()
  if (!fields.data) return <p className="field__help">Loading rule fields…</p>
  const root: Group = isGroup(value) ? value : { op: 'and', rules: [value] }
  return (
    <div className="rule-builder">
      <GroupNode node={root} fields={fields.data} options={options} depth={1} path="" onChange={onChange} />
    </div>
  )
}
