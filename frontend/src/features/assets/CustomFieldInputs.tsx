import type { CustomFieldDefinition } from '../../shared/api/types'
import type { CustomValues } from './customValues'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'

interface Props {
  definitions: CustomFieldDefinition[]
  values: CustomValues
  onChange: (key: string, value: string) => void
  errors: Record<string, string[]>
}

export function CustomFieldInputs({ definitions, values, onChange, errors }: Props) {
  if (definitions.length === 0) {
    return <p className="field__help">This category has no custom fields.</p>
  }
  return (
    <div className="form-grid">
      {definitions.map((definition) => {
        const common = {
          name: `cf_${definition.key}`,
          label: `${definition.label}${definition.required ? ' (required)' : ''}`,
          value: values[definition.key] ?? '',
          error: errors[`custom_fields.${definition.key}`],
          help: definition.help_text || undefined,
        }
        const set = (value: string) => onChange(definition.key, value)
        switch (definition.field_type) {
          case 'long_text':
            return (
              <TextAreaField
                key={definition.id}
                {...common}
                rows={3}
                onChange={(event) => set(event.target.value)}
              />
            )
          case 'boolean':
            return (
              <SelectField
                key={definition.id}
                {...common}
                options={[
                  { value: '', label: 'Not set' },
                  { value: 'true', label: 'Yes' },
                  { value: 'false', label: 'No' },
                ]}
                onChange={(event) => set(event.target.value)}
              />
            )
          case 'choice':
            return (
              <SelectField
                key={definition.id}
                {...common}
                options={[
                  { value: '', label: 'Not set' },
                  ...definition.choices.map((choice) => ({
                    value: String(choice),
                    label: String(choice),
                  })),
                ]}
                onChange={(event) => set(event.target.value)}
              />
            )
          case 'date':
            return (
              <TextField
                key={definition.id}
                {...common}
                type="date"
                onChange={(event) => set(event.target.value)}
              />
            )
          case 'integer':
          case 'decimal':
            return (
              <TextField
                key={definition.id}
                {...common}
                inputMode={definition.field_type === 'integer' ? 'numeric' : 'decimal'}
                onChange={(event) => set(event.target.value)}
              />
            )
          default:
            return (
              <TextField
                key={definition.id}
                {...common}
                onChange={(event) => set(event.target.value)}
              />
            )
        }
      })}
    </div>
  )
}
