import { useEffect, useRef, useState, type ReactNode } from 'react'

// What is picked is usually a row in the database and so a number, but a wish
// is spent on a species, which is a name. The id is whatever the list is a list
// of, and the caller gets back exactly the type it put in.
export interface Choice<Id = number> {
  id: Id
  label: string
  // The quiet half of a row: how far along a planting is, and so on.
  detail?: string
  // Whose row this is, where the list covers more than one person. A heading is
  // written each time this changes, so the choices arrive already in order.
  group?: string
}

interface Props<Id> {
  title: string
  hint: string
  choices: Choice<Id>[]
  // What the list says when there is nothing to choose from. Left unsaid where
  // something has been put above the list instead.
  empty: string
  busy: boolean
  error: string
  // Anything to read above the list: what came out of a chest, said where the
  // verb that opened it was.
  children?: ReactNode
  // A box to narrow the list with, where the list is of people rather than of
  // the two or three things a satchel holds. Its own placeholder, or nothing.
  searchPlaceholder?: string
  // The way out, which is Cancel while there is still something to pick and
  // Close once the picking is done and over with.
  cancelLabel?: string
  onChoose: (id: Id) => void
  onCancel: () => void
}

// A plain list to pick one thing out of, in the same modal dialog the letter
// uses: the focus trap, the page held still behind it, and Esc all come with
// the element rather than being built here.
export default function Chooser<Id extends number | string>({
  title,
  hint,
  choices,
  empty,
  busy,
  error,
  children,
  searchPlaceholder,
  cancelLabel = 'Cancel',
  onChoose,
  onCancel,
}: Props<Id>) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [query, setQuery] = useState('')

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const wanted = query.trim().toLowerCase()
  const shown =
    wanted === '' ? choices : choices.filter((one) => one.label.toLowerCase().includes(wanted))

  return (
    <dialog
      className="overlay"
      ref={dialog}
      aria-labelledby="chooser-title"
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onCancel()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id="chooser-title">{title}</h2>
          <p className="hint">{hint}</p>
        </header>

        <div className="chooser-body">
          {children}

          {searchPlaceholder !== undefined && choices.length > 0 && (
            <input
              className="chooser-search"
              type="search"
              value={query}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              onChange={(event) => setQuery(event.target.value)}
            />
          )}

          {choices.length === 0 && !children && <p className="hint">{empty}</p>}

          {shown.length === 0 && choices.length > 0 && (
            <p className="hint">Nobody by that name.</p>
          )}

          {shown.length > 0 && (
            <ul className="chooser-list">
              {shown.map((choice, index) => (
                <li key={choice.id}>
                  {choice.group !== undefined && choice.group !== shown[index - 1]?.group && (
                    <p className="label chooser-group">{choice.group}</p>
                  )}
                  <button
                    type="button"
                    className="chooser-option"
                    disabled={busy}
                    onClick={() => onChoose(choice.id)}
                  >
                    <span className="chooser-name">{choice.label}</span>
                    {choice.detail !== undefined && (
                      <span className="muted">{choice.detail}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>

        <footer className="overlay-foot">
          <button type="button" className="secondary" onClick={onCancel}>
            {cancelLabel}
          </button>
        </footer>
      </section>
    </dialog>
  )
}
