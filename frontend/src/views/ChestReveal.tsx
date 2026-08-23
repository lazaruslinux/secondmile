import { useEffect, useId, useRef } from 'react'
import type { SatchelItem } from '../api.ts'
import { chestName, FOUND_LEAD } from '../labels.ts'
import ChestItem from './ChestItem.tsx'

// What a chest says the moment it is opened. Before this the item appeared in a
// quiet strip under the chest list, which is easy to open a chest and never see:
// the thing that was earned deserves the screen for a moment.
//
// Native dialog for the focus trap, the inert background and Esc, the same as
// every other overlay here. The square inside is the satchel's own, so what a
// chest shows and what the inventory shows are one component.
export default function ChestReveal({
  tier,
  item,
  onPlanted,
  onClose,
}: {
  // The chest that was opened, for the heading. A chest from before the ladder
  // is only a chest, which chestName already answers for.
  tier: string | null
  item: SatchelItem
  onPlanted?: () => void
  onClose: () => void
}) {
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
        event.preventDefault()
        onClose()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id={titleId} className="chest-opened">{`${chestName(tier)} opened!`}</h2>
        </header>

        <div className="item-detail">
          <p className="hint chest-found">{FOUND_LEAD}</p>
          <div className="item-reveals">
            <ChestItem item={item} onPlanted={onPlanted} />
          </div>
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
