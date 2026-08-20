import { useEffect, useId, useRef } from 'react'
import { ALPHA_LINE } from '../alpha.ts'

// What the chip in the top bar opens: the short alpha line, for somebody who
// is already inside and never reads the landing page again.
// The native dialog for the focus trap, inert background and Esc, the same way
// every other panel in the app is built.
export default function AlphaNotice({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
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
        onClose()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id={titleId}>Alpha testing</h2>
        </header>

        <div className="item-detail">
          <p>{ALPHA_LINE}</p>
        </div>

        <footer className="overlay-foot">
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </footer>
      </section>
    </dialog>
  )
}
