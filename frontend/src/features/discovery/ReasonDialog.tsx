import { useState, type ReactNode } from 'react'
import { Dialog } from '../../shared/ui/Dialog'
import { TextAreaField } from '../../shared/ui/Field'

/** Confirmation dialog that requires a reason of at least 5 characters. */
export function ReasonDialog({
  title,
  confirmLabel,
  help,
  busy,
  error,
  onClose,
  onConfirm,
  children,
}: {
  title: string
  confirmLabel: string
  help?: string
  busy?: boolean
  error?: string | null
  onClose: () => void
  onConfirm: (reason: string) => void
  children?: ReactNode
}) {
  const [reason, setReason] = useState('')
  const [invalid, setInvalid] = useState<string[] | undefined>()
  return (
    <Dialog
      open
      title={title}
      confirmLabel={confirmLabel}
      busy={busy}
      onClose={onClose}
      onConfirm={() => {
        if (reason.trim().length < 5) setInvalid(['Enter a reason of at least 5 characters.'])
        else onConfirm(reason.trim())
      }}
    >
      {help && <p>{help}</p>}
      {children}
      {error && <p className="field__error">{error}</p>}
      <TextAreaField
        label="Reason"
        name="bulk_reason"
        rows={2}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        error={invalid}
        autoFocus
      />
    </Dialog>
  )
}
