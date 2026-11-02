import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  assetKeys,
  createCategory,
  createCategoryField,
  fetchCategories,
  fetchCategoryFields,
  updateCategory,
  updateCategoryField,
} from '../../shared/api/assets'
import { isApiError } from '../../shared/api/client'
import type { AssetCategory, CustomFieldDefinition, FieldType } from '../../shared/api/types'
import { Button } from '../../shared/ui/Button'
import { Dialog } from '../../shared/ui/Dialog'
import { CheckboxGroup, SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { PageHeader } from '../../shared/ui/PageHeader'
import { EmptyState, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { StatusBadge } from '../../shared/ui/StatusBadge'
import { categoryOptions } from '../assets/labels'

const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'long_text', label: 'Long text' },
  { value: 'integer', label: 'Integer' },
  { value: 'decimal', label: 'Decimal' },
  { value: 'boolean', label: 'Yes/No' },
  { value: 'date', label: 'Date' },
  { value: 'choice', label: 'Choice' },
]
const TYPE_LABEL = Object.fromEntries(FIELD_TYPES.map((t) => [t.value, t.label]))

function useErrors(error: unknown, client: Record<string, string[]>) {
  const server = isApiError(error) ? error.fieldErrors : {}
  const merged = { ...server, ...client }
  const summary = error && Object.keys(server).length === 0 ? (error as Error).message : null
  return { errors: merged, summary }
}

export function CategoriesPage() {
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('category')
  const categories = useQuery({ queryKey: assetKeys.categories, queryFn: fetchCategories })
  const [editing, setEditing] = useState<AssetCategory | 'new' | null>(null)

  const selected = categories.data?.find((c) => c.id === selectedId) ?? null

  return (
    <div className="page page--wide">
      <PageHeader
        title="Categories & fields"
        meta="Asset taxonomy and typed fields per category. Fields on a category also apply to its subcategories."
        actions={
          <Button variant="primary" onClick={() => setEditing('new')}>
            Add category
          </Button>
        }
      />
      <div className="split-layout">
        <section className="panel panel--flush" aria-labelledby="cat-heading">
          <h2 className="section-title section-title--inset" id="cat-heading">
            Categories
          </h2>
          {categories.isPending && <LoadingState label="Loading categories…" />}
          {categories.isError && <QueryErrorState error={categories.error} what="categories" />}
          {categories.data && (
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Code</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {categories.data.map((category) => (
                  <tr
                    key={category.id}
                    className={category.id === selectedId ? 'row--selected' : undefined}
                  >
                    <td style={{ paddingLeft: `${12 + category.depth * 20}px` }}>
                      <button
                        type="button"
                        className="link-button link-button--plain"
                        aria-current={category.id === selectedId ? 'true' : undefined}
                        onClick={() => setParams({ category: category.id }, { replace: true })}
                      >
                        {category.name}
                      </button>
                    </td>
                    <td className="mono cell-muted">{category.code}</td>
                    <td>
                      <StatusBadge
                        tone={category.is_active ? 'success' : 'neutral'}
                        label={category.is_active ? 'Active' : 'Inactive'}
                      />
                    </td>
                    <td>
                      <Button variant="quiet" onClick={() => setEditing(category)}>
                        Edit<span className="visually-hidden"> {category.name}</span>
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="panel" aria-labelledby="fields-heading">
          {selected ? (
            <FieldsPanel category={selected} />
          ) : (
            <>
              <h2 className="section-title" id="fields-heading">
                Fields
              </h2>
              <EmptyState title="Select a category to manage its fields." />
            </>
          )}
        </section>
      </div>
      {editing && categories.data && (
        <CategoryDialog
          category={editing === 'new' ? null : editing}
          categories={categories.data}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

function CategoryDialog({
  category,
  categories,
  onClose,
}: {
  category: AssetCategory | null
  categories: AssetCategory[]
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [name, setName] = useState(category?.name ?? '')
  const [parent, setParent] = useState(category?.parent ?? '')
  const [description, setDescription] = useState(category?.description ?? '')
  const [active, setActive] = useState(category?.is_active ?? true)
  const [client, setClient] = useState<Record<string, string[]>>({})

  const mutation = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), parent: parent || null, description }
      return category
        ? updateCategory(category.id, category.version, { ...body, is_active: active })
        : createCategory(body)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: assetKeys.categories })
      onClose()
    },
  })
  const { errors, summary } = useErrors(mutation.error, client)
  const excluded = new Set<string>()
  if (category) {
    // A category cannot move under itself or its descendants.
    const stack = [category.id]
    while (stack.length) {
      const id = stack.pop()!
      excluded.add(id)
      categories.filter((c) => c.parent === id).forEach((c) => stack.push(c.id))
    }
  }
  const moving = category && (category.parent ?? '') !== parent

  return (
    <Dialog
      open
      title={category ? `Edit ${category.name}` : 'Add category'}
      confirmLabel={category ? 'Save category' : 'Add category'}
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        const errs: Record<string, string[]> = {}
        if (!name.trim()) errs.name = ['Enter a name.']
        setClient(errs)
        if (!Object.keys(errs).length) mutation.mutate()
      }}
    >
      {summary && <p className="field__error">{summary}</p>}
      <TextField
        label="Name"
        name="category_name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        error={errors.name}
        autoFocus
      />
      <SelectField
        label="Parent"
        name="category_parent"
        options={[
          { value: '', label: 'None (top level)' },
          ...categoryOptions(categories).filter((o) => !excluded.has(o.value)),
        ]}
        value={parent}
        onChange={(e) => setParent(e.target.value)}
        error={errors.parent}
        help={
          moving
            ? 'Moving changes the path shown for all assets in this category and its subcategories, and which inherited fields apply.'
            : undefined
        }
      />
      <TextAreaField
        label="Description"
        name="category_description"
        rows={2}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        error={errors.description}
      />
      {category && (
        <CheckboxGroup
          legend="Status"
          name="category_active"
          options={[
            {
              value: 'active',
              label: 'Active',
              description: 'Inactive categories cannot be chosen for new or reclassified assets.',
            },
          ]}
          value={active ? ['active'] : []}
          onChange={(v) => setActive(v.includes('active'))}
        />
      )}
    </Dialog>
  )
}

function FieldsPanel({ category }: { category: AssetCategory }) {
  const effective = useQuery({
    queryKey: assetKeys.fields(category.id, true),
    queryFn: () => fetchCategoryFields(category.id, true),
  })
  const own = useQuery({
    queryKey: assetKeys.fields(category.id, false),
    queryFn: () => fetchCategoryFields(category.id, false),
  })
  const [editing, setEditing] = useState<CustomFieldDefinition | 'new' | null>(null)
  const inherited = (effective.data ?? []).filter((d) => d.category !== category.id)

  return (
    <>
      <div className="section-header">
        <h2 className="section-title" id="fields-heading">
          Fields for {category.path}
        </h2>
        <Button onClick={() => setEditing('new')}>Add field</Button>
      </div>
      {(own.isPending || effective.isPending) && <LoadingState label="Loading fields…" />}
      {own.isError && <QueryErrorState error={own.error} what="fields" />}
      {own.data && own.data.length === 0 && inherited.length === 0 && (
        <EmptyState title="No fields yet.">Add typed fields that assets in this category record.</EmptyState>
      )}
      {own.data && own.data.length > 0 && (
        <table className="data-table">
          <caption className="audit-detail__caption">Defined on this category</caption>
          <thead>
            <tr>
              <th scope="col">Label</th>
              <th scope="col">Key</th>
              <th scope="col">Type</th>
              <th scope="col">Required</th>
              <th scope="col">Status</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {own.data.map((d) => (
              <tr key={d.id}>
                <td>{d.label}</td>
                <td className="mono">{d.key}</td>
                <td>
                  {TYPE_LABEL[d.field_type]}
                  {d.field_type === 'choice' && (
                    <span className="cell-secondary">{d.choices.join(', ')}</span>
                  )}
                </td>
                <td>{d.required ? 'Yes' : 'No'}</td>
                <td>{d.is_active ? 'Active' : 'Inactive'}</td>
                <td>
                  <Button variant="quiet" onClick={() => setEditing(d)}>
                    Edit<span className="visually-hidden"> {d.label}</span>
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {inherited.length > 0 && (
        <table className="data-table">
          <caption className="audit-detail__caption">Inherited from parent categories</caption>
          <thead>
            <tr>
              <th scope="col">Label</th>
              <th scope="col">Key</th>
              <th scope="col">Type</th>
              <th scope="col">Required</th>
            </tr>
          </thead>
          <tbody>
            {inherited.map((d) => (
              <tr key={d.id}>
                <td>{d.label}</td>
                <td className="mono">{d.key}</td>
                <td>{TYPE_LABEL[d.field_type]}</td>
                <td>{d.required ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editing && (
        <FieldDialog
          category={category}
          field={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  )
}

function FieldDialog({
  category,
  field,
  onClose,
}: {
  category: AssetCategory
  field: CustomFieldDefinition | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [key, setKey] = useState(field?.key ?? '')
  const [label, setLabel] = useState(field?.label ?? '')
  const [type, setType] = useState<FieldType>(field?.field_type ?? 'text')
  const [flags, setFlags] = useState<string[]>([
    ...(field?.required ? ['required'] : []),
    ...((field?.is_active ?? true) ? ['active'] : []),
  ])
  const [choices, setChoices] = useState((field?.choices ?? []).join('\n'))
  const [help, setHelp] = useState(field?.help_text ?? '')
  const [min, setMin] = useState(field?.min_value ?? '')
  const [max, setMax] = useState(field?.max_value ?? '')
  const [client, setClient] = useState<Record<string, string[]>>({})

  const numeric = type === 'integer' || type === 'decimal'
  const mutation = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        label: label.trim(),
        required: flags.includes('required'),
        help_text: help.trim(),
        choices:
          type === 'choice'
            ? choices
                .split('\n')
                .map((c) => c.trim())
                .filter(Boolean)
            : [],
        ...(numeric ? { min_value: min === '' ? null : min, max_value: max === '' ? null : max } : {}),
      }
      return field
        ? updateCategoryField(field.id, field.version, { ...body, is_active: flags.includes('active') })
        : createCategoryField(category.id, { ...body, key: key.trim(), field_type: type })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['asset-categories'] })
      onClose()
    },
  })
  const { errors, summary } = useErrors(mutation.error, client)

  return (
    <Dialog
      open
      title={field ? `Edit field ${field.label}` : `Add field to ${category.name}`}
      confirmLabel={field ? 'Save field' : 'Add field'}
      busy={mutation.isPending}
      onClose={onClose}
      onConfirm={() => {
        const errs: Record<string, string[]> = {}
        if (!field && !/^[a-z][a-z0-9_]{0,49}$/.test(key.trim())) {
          errs.key = ['Start with a letter; use lowercase letters, digits and underscores.']
        }
        if (!label.trim()) errs.label = ['Enter a label.']
        if (type === 'choice' && !choices.trim()) errs.choices = ['Add at least one choice.']
        setClient(errs)
        if (!Object.keys(errs).length) mutation.mutate()
      }}
    >
      {summary && <p className="field__error">{summary}</p>}
      <TextField
        label="Label"
        name="field_label"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        error={errors.label}
        autoFocus
      />
      {field ? (
        <p className="field__help">
          Key <span className="mono">{field.key}</span> and type {TYPE_LABEL[field.field_type]} cannot
          change, so stored values stay valid.
        </p>
      ) : (
        <>
          <TextField
            label="Key"
            name="field_key"
            className="field__control mono"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            error={errors.key}
            help="Used in the API and exports. Cannot be changed later."
          />
          <SelectField
            label="Type"
            name="field_type"
            options={FIELD_TYPES}
            value={type}
            onChange={(e) => setType(e.target.value as FieldType)}
            error={errors.field_type}
          />
        </>
      )}
      {type === 'choice' && (
        <TextAreaField
          label="Choices (one per line)"
          name="field_choices"
          rows={4}
          value={choices}
          onChange={(e) => setChoices(e.target.value)}
          error={errors.choices}
        />
      )}
      {numeric && (
        <div className="form-grid">
          <TextField
            label="Minimum"
            name="field_min"
            inputMode="decimal"
            value={min}
            onChange={(e) => setMin(e.target.value)}
            error={errors.min_value}
          />
          <TextField
            label="Maximum"
            name="field_max"
            inputMode="decimal"
            value={max}
            onChange={(e) => setMax(e.target.value)}
            error={errors.max_value}
          />
        </div>
      )}
      <TextField
        label="Help text"
        name="field_help"
        value={help}
        onChange={(e) => setHelp(e.target.value)}
        error={errors.help_text}
      />
      <CheckboxGroup
        legend="Options"
        name="field_flags"
        options={[
          {
            value: 'required',
            label: 'Required',
            description: 'Enforced when assets are created or moved into this category.',
          },
          ...(field ? [{ value: 'active', label: 'Active', description: 'Inactive fields are hidden from forms; stored values are kept.' }] : []),
        ]}
        value={flags}
        onChange={setFlags}
      />
    </Dialog>
  )
}
