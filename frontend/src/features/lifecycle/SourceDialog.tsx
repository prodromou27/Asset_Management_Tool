import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { isApiError } from '../../shared/api/client'
import { createSource, lifecycleKeys } from '../../shared/api/lifecycle'
import type { LifecycleSource } from '../../shared/api/types'
import { Dialog } from '../../shared/ui/Dialog'
import { SelectField, TextAreaField, TextField } from '../../shared/ui/Field'
import { ErrorSummary } from '../../shared/ui/States'
import { SOURCE_TYPE } from './labels'

const today = () => new Date().toISOString().slice(0, 10)

/** Records one evidence document. Official vendor pages are preferred; third-party
 * sources are labelled and only ever supporting evidence (docs/06). */
export function SourceDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated?: (source: LifecycleSource) => void
}) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    publisher: '',
    title: '',
    url: '',
    source_type: 'vendor',
    document_ref: '',
    collected_on: today(),
    notes: '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))
  const save = useMutation({
    mutationFn: () => createSource(form as Parameters<typeof createSource>[0]),
    onSuccess: (source) => {
      queryClient.invalidateQueries({ queryKey: lifecycleKeys.sources })
      onCreated?.(source)
      onClose()
    },
  })
  const errors = isApiError(save.error) ? save.error.fieldErrors : {}
  return (
    <Dialog open title="New evidence source" confirmLabel="Save source" busy={save.isPending} onClose={onClose} onConfirm={() => save.mutate()}>
      {save.isError && (
        <ErrorSummary
          message={save.error.message}
          fieldErrors={errors}
          fieldLabels={{ publisher: 'Publisher', title: 'Title', url: 'Link', collected_on: 'Collected on' }}
        />
      )}
      <SelectField
        label="Source type"
        name="source-type"
        value={form.source_type}
        onChange={set('source_type')}
        options={Object.entries(SOURCE_TYPE).map(([value, label]) => ({ value, label }))}
        help={form.source_type === 'third_party' ? 'Third-party dates are shown as lower confidence; prefer the vendor page.' : undefined}
      />
      <TextField label="Publisher" name="source-publisher" value={form.publisher} onChange={set('publisher')} error={errors.publisher} required />
      <TextField label="Title" name="source-title" value={form.title} onChange={set('title')} error={errors.title} required />
      <TextField label="Link" name="source-url" type="url" value={form.url} onChange={set('url')} error={errors.url} />
      <TextField label="Document reference (optional)" name="source-ref" value={form.document_ref} onChange={set('document_ref')} />
      <TextField label="Collected on" name="source-collected" type="date" value={form.collected_on} onChange={set('collected_on')} error={errors.collected_on} />
      <TextAreaField label="Notes (optional)" name="source-notes" value={form.notes} onChange={set('notes')} />
    </Dialog>
  )
}
