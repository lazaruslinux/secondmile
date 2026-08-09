import { useEffect, useRef, useState } from 'react'
import type { Stack } from '../satchel.ts'
import { ItemDialog, Square } from './Inventory.tsx'

// The word the question spends. It is the plain one rather than the item's
// proper name, because "Use 1 oil" reads as a sentence and "Use 1 Olive Oil"
// reads as a label off a shelf. Anything without a word of its own falls back to
// what it is called.
const SPENT_AS: Record<string, string> = { water: 'water', oil: 'oil' }

function spentAs(stack: Stack): string {
  return SPENT_AS[stack.kind] ?? stack.name.toLowerCase()
}

interface Props {
  title: string
  hint: string
  // What is held that could be spent here, already piled into squares. Items
  // only: a person is a name, and a grid of faces without names is harder to
  // read than the list they stay in.
  stacks: Stack[]
  // What the question names at the end: one of their plants, or the person.
  onto: string
  // What the popup says when the satchel has nothing for this.
  empty: string
  busy: boolean
  error: string
  onUse: (stack: Stack) => void
  onCancel: () => void
}

// Picking a thing to spend, as the inventory's own squares. It is the satchel's
// grid drawn small: the art, the rarity frame, the bold count. Then the question
// naming what it goes onto, because an item that leaves the satchel does not
// come back and the last thing before that should be a sentence rather than a
// row in a list.
export default function ItemPicker({
  title,
  hint,
  stacks,
  onto,
  empty,
  busy,
  error,
  onUse,
  onCancel,
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [picked, setPicked] = useState<Stack | null>(null)

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  // The question, in the panel a tapped square opens everywhere else, so the
  // thing being spent is still on screen while it is being asked about. Cancel
  // here cancels the act rather than stepping back to the squares: the squares
  // are one tap away again and [Use] [Cancel] is a pair of answers to a
  // question, not a way back through a list.
  if (picked !== null) {
    return (
      <ItemDialog
        stack={picked}
        line={`Use 1 ${spentAs(picked)} on ${onto}?`}
        verbs={[{ id: 'use', label: 'Use' }]}
        busy={busy}
        error={error}
        cancelLabel="Cancel"
        onRun={() => onUse(picked)}
        onClose={onCancel}
      />
    )
  }

  return (
    <dialog
      className="overlay overlay-middle"
      ref={dialog}
      aria-labelledby="pick-title"
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onCancel()
      }}
    >
      <section className="overlay-panel pick-panel">
        <header className="overlay-head">
          <h2 id="pick-title">{title}</h2>
          <p className="hint">{hint}</p>
        </header>

        {/* The satchel's own scrolling body, so the squares sit at the spacing
            they sit at on the Grove screen and a long shelf of them scrolls. */}
        <div className="item-detail">
          {stacks.length === 0 ? (
            <p className="hint">{empty}</p>
          ) : (
            <ul className="inv-grid">
              {stacks.map((stack) => (
                <Square key={stack.key} stack={stack} onOpen={() => setPicked(stack)} />
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
            Cancel
          </button>
        </footer>
      </section>
    </dialog>
  )
}
