import { useEffect, useId, useRef, type ReactNode } from 'react'

// Native dialog for the focus trap, inert background and Esc. Copy and close
// behaviour are the caller's.
export default function Confirm({
  heading,
  confirmLabel,
  cancelLabel,
  busy = false,
  error = '',
  onConfirm,
  onCancel,
  children,
}: {
  heading: string
  confirmLabel: string
  cancelLabel: string
  busy?: boolean
  error?: string
  onConfirm: () => void
  onCancel: () => void
  // What is lost, said plainly and in full, because every one of these is a
  // consequence somebody would rather hear now than find out.
  children: ReactNode
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  // Two of these can be on the screen at once, so the heading's id is generated
  // rather than written, and the label still points at the right one.
  const titleId = useId()

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  return (
    <dialog
      className="overlay overlay-middle"
      ref={dialog}
      aria-labelledby={titleId}
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onCancel()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id={titleId}>{heading}</h2>
        </header>

        <div className="item-detail">
          {children}

          <div className="item-verbs">
            <button type="button" className="primary" disabled={busy} onClick={onConfirm}>
              {confirmLabel}
            </button>
          </div>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>

        <footer className="overlay-foot">
          <button type="button" className="secondary" disabled={busy} onClick={onCancel}>
            {cancelLabel}
          </button>
        </footer>
      </section>
    </dialog>
  )
}
