import { useEffect, useRef } from 'react'
import { type RecapState } from '../api.ts'
import { formatDate, formatTimeOfDay } from '../format.ts'
import { MEDAL_DETAILS, medalName, plantingName } from '../labels.ts'
import { flourishLine, noteAuthor, recapCheers, recapNotes } from '../recap.ts'
import { MedalMark } from './Medals.tsx'

interface Props {
  recap: RecapState
  // The parent acks the recap and reloads whatever changed while away.
  onDismiss: () => void
}

// Who lifted which of the chests that landed. One entry per gifted chest, so
// two from the same friend say two, and the names are said once each. Gifted is
// the word for it: the chest was earned, and somebody else made it richer.
function giftLine(givers: string[]): string {
  if (givers.length === 0) return ''
  const names = [...new Set(givers)]
  const which =
    givers.length === 1 ? 'One of them was gifted' : `${givers.length} of them were gifted`
  return `${which} by ${names.join(' and ')}.`
}

// The letter waiting on the mat. Everything in it already happened: the miles
// were covered, the chests were dropped, the badges were earned. Opening the
// app is how you read about it, never how you cause it.
export default function Recap({ recap, onDismiss }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const chests = recap.chests_delivered ?? 0
  const gift = giftLine(recap.chest_givers ?? [])
  const synced = recap.last_sync_at

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
          {/* Chests are opened in the inventory now, so nothing here offers to
              open one. What this says instead is how current the miles are. */}
          <p className="hint">
            {recap.since ? `Since ${formatDate(recap.since)}.` : 'Everything so far.'}
            {synced ? ` Last health sync at ${formatTimeOfDay(synced)}.` : ''}
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
              <h3>Welcome back</h3>
              <p>
                {chests} {chests === 1 ? 'chest was' : 'chests were'} delivered to your
                inventory.
              </p>
              {/* Oil says nothing when it is spent, so this is the only place
                  the person who gave it is named. */}
              {gift !== '' && <p className="hint">{gift}</p>}
            </section>
          )}

          {(recap.plant_growth?.length ?? 0) > 0 && (
            <section className="recap-section">
              <h3>In the grove</h3>
              <ul className="recap-growth">
                {recap.plant_growth?.map((row) => (
                  <li key={row.id}>
                    {plantingName(row)} reached Lv {row.level}.
                  </li>
                ))}
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
