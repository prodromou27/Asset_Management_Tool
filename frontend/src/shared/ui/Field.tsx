import {
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react'

interface FieldShellProps {
  id: string
  label: string
  help?: ReactNode
  error?: string[]
  children: ReactNode
}

function FieldShell({ id, label, help, error, children }: FieldShellProps) {
  return (
    <div className={`field${error?.length ? ' field--invalid' : ''}`}>
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      {children}
      {help && (
        <p className="field__help" id={`${id}-help`}>
          {help}
        </p>
      )}
      {error?.map((message) => (
        <p className="field__error" id={`${id}-error`} key={message}>
          {message}
        </p>
      ))}
    </div>
  )
}

function describedBy(id: string, help: unknown, error?: string[]) {
  return (
    [help ? `${id}-help` : null, error?.length ? `${id}-error` : null].filter(Boolean).join(' ') ||
    undefined
  )
}

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string
  name: string
  help?: ReactNode
  error?: string[]
}

export function TextField({ label, name, help, error, ...input }: TextFieldProps) {
  const id = `field-${name}-${useId()}`
  return (
    <FieldShell id={id} label={label} help={help} error={error}>
      <input
        id={id}
        name={name}
        className="field__control"
        aria-invalid={error?.length ? true : undefined}
        aria-describedby={describedBy(id, help, error)}
        {...input}
      />
    </FieldShell>
  )
}

interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: string
  name: string
  options: { value: string; label: string }[]
  help?: ReactNode
  error?: string[]
}

export function SelectField({ label, name, options, help, error, ...select }: SelectFieldProps) {
  const id = `field-${name}-${useId()}`
  return (
    <FieldShell id={id} label={label} help={help} error={error}>
      <select
        id={id}
        name={name}
        className="field__control"
        aria-invalid={error?.length ? true : undefined}
        aria-describedby={describedBy(id, help, error)}
        {...select}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldShell>
  )
}

interface CheckboxGroupProps {
  legend: string
  name: string
  options: { value: string; label: string; description?: string }[]
  value: string[]
  onChange: (value: string[]) => void
  error?: string[]
  disabled?: boolean
}

export function CheckboxGroup({
  legend,
  name,
  options,
  value,
  onChange,
  error,
  disabled,
}: CheckboxGroupProps) {
  const id = `field-${name}-${useId()}`
  return (
    <fieldset
      className={`field fieldset${error?.length ? ' field--invalid' : ''}`}
      aria-describedby={error?.length ? `${id}-error` : undefined}
      id={id}
    >
      <legend className="field__label">{legend}</legend>
      <div className="checkbox-list">
        {options.map((option) => (
          <label key={option.value} className="checkbox">
            <input
              type="checkbox"
              name={name}
              value={option.value}
              checked={value.includes(option.value)}
              disabled={disabled}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...value, option.value]
                    : value.filter((item) => item !== option.value),
                )
              }
            />
            <span>
              <span className="checkbox__label">{option.label}</span>
              {option.description && (
                <span className="checkbox__description">{option.description}</span>
              )}
            </span>
          </label>
        ))}
      </div>
      {error?.map((message) => (
        <p className="field__error" id={`${id}-error`} key={message}>
          {message}
        </p>
      ))}
    </fieldset>
  )
}

interface TextAreaFieldProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  label: string
  name: string
  help?: ReactNode
  error?: string[]
}

export function TextAreaField({ label, name, help, error, ...textarea }: TextAreaFieldProps) {
  const id = `field-${name}-${useId()}`
  return (
    <FieldShell id={id} label={label} help={help} error={error}>
      <textarea
        id={id}
        name={name}
        className="field__control field__control--textarea"
        aria-invalid={error?.length ? true : undefined}
        aria-describedby={describedBy(id, help, error)}
        {...textarea}
      />
    </FieldShell>
  )
}
