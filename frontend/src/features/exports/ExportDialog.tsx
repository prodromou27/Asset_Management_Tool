import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { isApiError } from '../../shared/api/client'
import { createExport, exportKeys, fetchExportFamilies } from '../../shared/api/exports'
import type { ExportCreate, ExportJob } from '../../shared/api/types'
import { Dialog } from '../../shared/ui/Dialog'
import { CheckboxGroup } from '../../shared/ui/Field'
import { ErrorSummary, LoadingState, QueryErrorState } from '../../shared/ui/States'
import { FORMAT_LABEL } from './labels'

const FIELD_LABELS: Record<string, string> = {
  columns: 'Columns',
  related: 'Related data',
  filters: 'Filters',
  ids: 'Records',
}

type Scope = ExportJob['scope']
type Format = ExportJob['file_format']

interface ExportDialogProps {
  open: boolean
  onClose: () => void
  family: ExportCreate['family']
  /** Current list filters; offered as the "Current filters" scope. */
  filters?: Record<string, string>
  /** Specific records (for example one group); offered as the "Selected" scope. */
  selected?: { ids: string[]; label: string }
  /** Related tables ticked by default. */
  defaultRelated?: string[]
}

/** docs/07 ExportDialog: scope, format, related data, columns, privacy note, queued job. */
export function ExportDialog({
  open,
  onClose,
  family,
  filters = {},
  selected,
  defaultRelated = [],
}: ExportDialogProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const families = useQuery({
    queryKey: exportKeys.families,
    queryFn: fetchExportFamilies,
    enabled: open,
  })
  const spec = families.data?.find((f) => f.code === family)
  const activeFilters = Object.fromEntries(
    Object.entries(filters).filter(([key, value]) => value && spec?.filter_keys.includes(key)),
  )
  const hasFilters = Object.keys(activeFilters).length > 0
  const initialScope: Scope = selected ? 'selected' : hasFilters ? 'filtered' : 'all'

  const [scope, setScope] = useState<Scope | null>(null)
  const [format, setFormat] = useState<Format>('xlsx')
  const [related, setRelated] = useState<string[] | null>(null)
  const [columns, setColumns] = useState<string[] | null>(null)

  const allowedColumns = spec?.columns.filter((c) => c.allowed) ?? []
  const chosenScope = scope ?? initialScope
  const chosenRelated = related ?? defaultRelated.filter((r) => spec?.related.some((x) => x.key === r))
  const chosenColumns = columns ?? allowedColumns.map((c) => c.key)
  const hiddenPersonal = spec?.columns.filter((c) => !c.allowed).map((c) => c.label) ?? []

  const submit = useMutation({
    mutationFn: () =>
      createExport({
        family,
        format,
        scope: chosenScope,
        filters: chosenScope === 'filtered' ? activeFilters : {},
        ids: chosenScope === 'selected' ? selected?.ids ?? [] : [],
        columns: chosenColumns.length === allowedColumns.length ? [] : chosenColumns,
        related: chosenRelated,
      }),
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: exportKeys.list })
      close()
      navigate(`/exports?job=${job.id}`)
    },
  })

  function close() {
    setScope(null)
    setRelated(null)
    setColumns(null)
    submit.reset()
    onClose()
  }

  const scopes: { value: Scope; label: string; available: boolean }[] = [
    { value: 'filtered', label: 'Current filters', available: hasFilters },
    { value: 'selected', label: selected?.label ?? 'Selected records', available: !!selected },
    { value: 'all', label: 'Everything you can see', available: true },
  ]

  return (
    <Dialog
      open={open}
      title={`Export ${spec?.label.toLowerCase() ?? family}`}
      confirmLabel="Start export"
      busy={submit.isPending}
      onConfirm={() => {
        if (spec && chosenColumns.length > 0) submit.mutate()
      }}
      onClose={close}
    >
      {families.isPending && <LoadingState label="Loading export options…" />}
      {families.isError && <QueryErrorState error={families.error} what="export options" />}
      {families.isSuccess && !spec && (
        <p className="inline-note">You do not have permission to export this data.</p>
      )}
      {spec && (
        <>
          {submit.isError && (
            <ErrorSummary
              message={submit.error.message}
              fieldErrors={isApiError(submit.error) ? submit.error.fieldErrors : {}}
              fieldLabels={FIELD_LABELS}
            />
          )}
          <fieldset className="fieldset field">
            <legend className="field__label">Records</legend>
            <div className="radio-list">
              {scopes
                .filter((s) => s.available)
                .map((s) => (
                  <label key={s.value} className="radio">
                    <input
                      type="radio"
                      name="export-scope"
                      value={s.value}
                      checked={chosenScope === s.value}
                      onChange={() => setScope(s.value)}
                    />
                    <span>{s.label}</span>
                  </label>
                ))}
            </div>
          </fieldset>

          <fieldset className="fieldset field">
            <legend className="field__label">Format</legend>
            <div className="radio-list radio-list--inline">
              {(Object.keys(FORMAT_LABEL) as Format[]).map((value) => (
                <label key={value} className="radio">
                  <input
                    type="radio"
                    name="export-format"
                    value={value}
                    checked={format === value}
                    onChange={() => setFormat(value)}
                  />
                  <span>{FORMAT_LABEL[value]}</span>
                </label>
              ))}
            </div>
          </fieldset>

          {spec.related.length > 0 && (
            <CheckboxGroup
              legend="Related data"
              name="export-related"
              options={spec.related.map((r) => ({ value: r.key, label: r.label }))}
              value={chosenRelated}
              onChange={setRelated}
            />
          )}

          <details className="export-columns">
            <summary>
              Columns ({chosenColumns.length} of {allowedColumns.length})
            </summary>
            <CheckboxGroup
              legend="Columns to include"
              name="export-columns"
              options={allowedColumns.map((c) => ({ value: c.key, label: c.label }))}
              value={chosenColumns}
              onChange={setColumns}
              error={chosenColumns.length === 0 ? ['Choose at least one column.'] : undefined}
            />
          </details>

          <p className="inline-note">
            Only records in your sites are exported. The file is prepared in the background,
            stored encrypted and can be downloaded by you only, for 24 hours. Exports are
            recorded in the audit log.
            {hiddenPersonal.length > 0 &&
              ` Personal data (${hiddenPersonal.join(', ')}) is left out because your role does not include it.`}
          </p>
        </>
      )}
    </Dialog>
  )
}
