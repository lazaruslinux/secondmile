import { useEffect, useId, useRef, type ReactNode } from 'react'

// The last thing before something destructive is done, in the one shape every
// such question in this app is asked in: a native modal dialog, which brings
// the focus trap, the page held still behind it, and Esc with the element
// rather than having them built by hand.
//
// The container is all this is. What each question says is the caller's, so a
// flow that moves onto this keeps its own heading, its own sentences, and its
// own words on the two buttons. Nothing is done until the button is pressed:
// closing is the caller's business either way.
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
