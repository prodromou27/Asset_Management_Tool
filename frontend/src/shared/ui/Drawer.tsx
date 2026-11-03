import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Button } from './Button'

interface DrawerProps {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}

/** Side panel on <dialog>: modal focus trap, Escape closes, focus returns to the
 * element that opened it (docs/07 SourceEvidenceDrawer, 8px radius drawers). */
export function Drawer({ open, title, onClose, children }: DrawerProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const opener = useRef<Element | null>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      opener.current = document.activeElement
      if (typeof dialog.showModal === 'function') dialog.showModal()
      else dialog.setAttribute('open', '')
      dialog.querySelector<HTMLElement>('[data-autofocus]')?.focus()
    } else if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
      if (opener.current instanceof HTMLElement) opener.current.focus()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className="drawer"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onKeyDown={(event) => {
        // jsdom/older engines without native cancel handling
        if (event.key === 'Escape') {
          event.preventDefault()
          onClose()
        }
      }}
    >
      {open && (
        <>
          <div className="drawer__header">
            <h2 className="drawer__title" id={titleId}>
              {title}
            </h2>
            <Button variant="quiet" onClick={onClose} data-autofocus>
              Close
            </Button>
          </div>
          <div className="drawer__body">{children}</div>
        </>
      )}
    </dialog>
  )
}
