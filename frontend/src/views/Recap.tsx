import { useEffect, useRef, useState } from 'react'
import { errorText, openChest, type RecapState, type SatchelItem } from '../api.ts'
import { formatDate } from '../format.ts'
import { chestName, chestTierClass, MEDAL_DETAILS, medalName } from '../labels.ts'
import { chestGiver, flourishLine, noteAuthor, recapCheers, recapNotes } from '../recap.ts'
import ChestItem from './ChestItem.tsx'
import { MedalMark } from './Medals.tsx'

interface Props {
  recap: RecapState
  // The parent acks the recap and reloads whatever the opened chests changed.
  onDismiss: () => void
}

// The letter waiting on the mat. Everything in it already happened: the miles
// were covered, the chests were dropped, the badges were earned. Opening the
// app is how you read about it, never how you cause it.
export default function Recap({ recap, onDismiss }: Props) {
  const [opened, setOpened] = useState<Record<number, SatchelItem>>({})
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

  // The recap lists one entry per earning, so two 5K runs arrive as two rows
  // naming the same medal. Grouping them is what turns that into one line with
  // a number on it, and the order the medals were earned in is the order they
  // are read in.
  const medals: { id: string; count: number }[] = []
  for (const row of recap.medals ?? []) {
    const held = medals.find((one) => one.id === row.id)
    if (held) held.count += 1
    else medals.push({ id: row.id, count: 1 })
  }

  const notes = recapNotes(recap.encouragement)
  const cheers = recapCheers(recap.encouragement)
  const grew = flourishLine(recap)

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
            never expire. Open them here or later on the You screen.
          </p>
        </header>

        <div className="recap">
          <p className="recap-miles">
            <span className="recap-miles-value">{recap.miles.toFixed(1)}</span>
            <span className="label">Miles counted</span>
          </p>

          {/* What other people said comes before anything the app worked out.
              The words are the event; the counting is not. */}
          {(notes.length > 0 || cheers > 0) && (
            <section className="recap-section">
              <h3>Words for you</h3>
              {notes.length > 0 && (
                <ul className="recap-notes">
                  {notes.map((note, index) => {
                    const who = noteAuthor(note)
                    return (
                      <li key={index} className="recap-note">
                        {who !== '' && <p className="recap-note-who">{who}</p>}
                        <p className="recap-note-body">{note.body}</p>
                      </li>
                    )
                  })}
                </ul>
              )}
              {cheers > 0 && (
                <p className="recap-cheers">
                  {cheers} {cheers === 1 ? 'cheer' : 'cheers'}.
                </p>
              )}
            </section>
          )}

          {medals.length > 0 && (
            <section className="recap-section">
              <h3>New medals</h3>
              {/* Every family reads the same way here. A week counted and an
                  hour kept are earnings like a distance run, said in the same
                  words and given the same room. */}
              <ul className="medal-earns">
                {medals.map((row) => {
                  const times = row.count > 1 ? ` ${row.count} times` : ''
                  const detail = MEDAL_DETAILS[row.id]
                  return (
                    <li key={row.id} className="medal-earn">
                      <MedalMark id={row.id} earned />
                      <div className="medal-earn-body">
                        <p className="medal-earn-name">
                          You earned the {medalName(row.id)} medal{times}.
                        </p>
                        {detail && <p className="medal-earn-detail">{detail}</p>}
                      </div>
                    </li>
                  )
                })}
              </ul>
            </section>
          )}

          {chests > 0 && (
            <section className="recap-section">
              <h3>
                {chests} {chests === 1 ? 'chest' : 'chests'} waiting
              </h3>
              <p className="hint">Opened here or later. Nothing is lost either way.</p>
              <ul className="chests">
                {recap.chests.map((chest) => {
                  const reveal = opened[chest.id]
                  const giver = chestGiver(chest)
                  return (
                    <li key={chest.id} className="recap-chest">
                      {/* Oil says nothing when it is used. This line is where
                          the person who gave it is finally named, so it reads
                          with the weight the words in the letter have. */}
                      {giver !== '' && (
                        <p className="recap-chest-from">
                          {giver} sent this one. More than your miles earned.
                        </p>
                      )}
                      <div className="chest-line">
                        {/* Named in the colour of the step it dropped on. */}
                        <span className={chestTierClass(chest.tier)}>
                          {chestName(chest.tier)}
                        </span>
                        {!reveal && (
                          <button
                            type="button"
                            className="secondary"
                            aria-label={`Open ${chestName(chest.tier)}`}
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
                          <ChestItem item={reveal} />
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </section>
          )}

          {/* One line, said once. Growth comes from encouraging other people,
              so this is the only place the app mentions it. */}
          {grew !== '' && <p className="hint recap-grew">{grew}</p>}
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
