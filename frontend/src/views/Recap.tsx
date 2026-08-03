import { useEffect, useRef, useState } from 'react'
import { errorText, openChest, type OpenedChest, type RecapState } from '../api.ts'
import { formatDate } from '../format.ts'
import Badge from './Badge.tsx'
import CardPlate from './CardPlate.tsx'

interface Props {
  recap: RecapState
  // The parent acks the recap and reloads whatever the opened chests changed.
  onDismiss: () => void
}

// The letter waiting on the mat. Everything in it already happened: the miles
// were covered, the chests were dropped, the badges were earned. Opening the
// app is how you read about it, never how you cause it.
export default function Recap({ recap, onDismiss }: Props) {
  const [opened, setOpened] = useState<Record<number, OpenedChest>>({})
  const [busy, setBusy] = useState<number | null>(null)
  const [errors, setErrors] = useState<Record<number, string>>({})
  const dialog = useRef<HTMLDialogElement>(null)

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  async function open(chestId: number) {
    setBusy(chestId)
    try {
      const result = await openChest(chestId)
      setOpened((current) => ({ ...current, [chestId]: result }))
      setErrors((current) => ({ ...current, [chestId]: '' }))
    } catch (err) {
      setErrors((current) => ({ ...current, [chestId]: errorText(err) }))
    } finally {
      setBusy(null)
    }
  }

  const chests = recap.chests.length

  return (
    <dialog
      className="overlay"
      ref={dialog}
      aria-labelledby="recap-title"
      onCancel={(event) => {
        // Esc. Dismissing is the parent's business and it takes this off the
        // screen itself, so the browser's own close is left undone.
        event.preventDefault()
        onDismiss()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id="recap-title">While you were away</h2>
          <p className="hint">
            {recap.since ? `Since ${formatDate(recap.since)}.` : 'Everything so far.'} Chests
            keep. You can open them here or later on your profile.
          </p>
        </header>

        <div className="recap">
          <p className="recap-miles">
            <span className="recap-miles-value">{recap.miles.toFixed(1)}</span>
            <span className="recap-miles-label">Miles covered</span>
          </p>

          {recap.achievements.length > 0 && (
            <section className="recap-section">
              <h3>Earned</h3>
              <ul className="achievements">
                {recap.achievements.map((row) => (
                  <li key={row.id} className="achievement">
                    <Badge achievement={row} />
                    <div className="achievement-body">
                      <p className="achievement-name">
                        {row.name}
                        {row.gilded && <span className="tag tag-gilded">Gilded</span>}
                      </p>
                      <p className="achievement-detail">{row.detail}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {chests > 0 && (
            <section className="recap-section">
              <h3>
                {chests} {chests === 1 ? 'chest' : 'chests'} waiting
              </h3>
              <ul className="chests">
                {recap.chests.map((chest) => {
                  const reveal = opened[chest.id]
                  return (
                    <li key={chest.id} className="recap-chest">
                      <div className="chest-line">
                        <span>{chest.set_name} set</span>
                        {!reveal && (
                          <button
                            type="button"
                            className="secondary"
                            aria-label={`Open ${chest.set_name} chest`}
                            disabled={busy === chest.id}
                            onClick={() => void open(chest.id)}
                          >
                            Open
                          </button>
                        )}
                      </div>
                      {errors[chest.id] && (
                        <p className="error" role="alert">
                          {errors[chest.id]}
                        </p>
                      )}
                      {reveal && (
                        <div className="reveal">
                          <CardPlate
                            number={reveal.card.number}
                            rarity={reveal.card.rarity}
                            owned
                            cardId={reveal.card.id}
                            name={reveal.card.name}
                            flavor={reveal.card.flavor}
                            count={reveal.count}
                          />
                          <p className="hint">
                            {reveal.card.set_name} set.{' '}
                            {reveal.duplicate
                              ? `You already had this one. ${reveal.count} copies now.`
                              : 'New to the album.'}
                          </p>
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>
          )}
        </div>

        <footer className="overlay-foot">
          <button type="button" className="primary" onClick={onDismiss}>
            Done
          </button>
        </footer>
      </section>
    </dialog>
  )
}
