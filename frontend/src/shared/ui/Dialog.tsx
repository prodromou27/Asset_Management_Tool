import { useEffect, useId, useRef, type FormEvent, type ReactNode } from 'react'
import { Button } from './Button'

interface DialogProps {
  open: boolean
  title: string
  confirmLabel: string
  confirmVariant?: 'primary' | 'danger'
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
  children: ReactNode
}

/** Modal built on <dialog>: native focus trap, Escape closes, focus returns to opener. */
export function Dialog({
  open,
  title,
  confirmLabel,
  confirmVariant = 'primary',
  busy = false,
  onConfirm,
  onClose,
  children,
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
    }
  }, [open])

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    onConfirm()
  }

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        if (!busy) onClose()
      }}
    >
      {open && (
        <form onSubmit={handleSubmit} noValidate>
          <h2 className="dialog__title" id={titleId}>
            {title}
          </h2>
          <div className="dialog__body">{children}</div>
          <div className="dialog__actions">
            <Button onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant={confirmVariant} busy={busy}>
              {confirmLabel}
            </Button>
          </div>
        </form>
      )}
    </dialog>
  )
}
