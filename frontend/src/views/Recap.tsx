import { useEffect, useRef, useState } from 'react'
import { type RecapState, type RecapWorkout, type Units } from '../api.ts'
import {
  convertedValue,
  formatDate,
  formatDistance,
  formatDuration,
  formatElapsed,
  formatStart,
  formatTimeOfDay,
} from '../format.ts'
import {
  ACTIVITY_ICONS,
  ACTIVITY_NAMES,
  defaultHeadline,
  MEDAL_DETAILS,
  medalName,
} from '../labels.ts'
import {
  flourishLine,
  noteAuthor,
  recapCheers,
  recapChestNames,
  recapGiftLine,
  recapGrowthLines,
  recapMiles,
  recapMilesTotal,
  recapNotes,
} from '../recap.ts'
import { EditPanel } from './FeedCard.tsx'
import Icon from './Icon.tsx'
import { MedalMark } from './Medals.tsx'

interface Props {
  recap: RecapState
  // The account's own unit, for the distances in the activity list. Everything
  // above that list is miles by name, so this is the only place it matters.
  units: Units
  // The parent acks the recap and reloads whatever changed while away.
  onDismiss: () => void
}

// The letter waiting on the mat. Everything in it already happened: the miles
// were covered, the chests were dropped, the badges were earned. Opening the
// app is how you read about it, never how you cause it.
export default function Recap({ recap, units, onDismiss }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  // The workouts as this letter now knows them: a title written here is on the
  // row underneath before the dialog is closed.
  const [workouts, setWorkouts] = useState<RecapWorkout[]>(recap.workouts ?? [])
  // Which row has its panel open, by workout. One at a time, because the panel
  // is tall and two of them turn the letter into a form.
  const [editing, setEditing] = useState<number | null>(null)

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const elapsed = recap.since ? formatElapsed(recap.since) : ''
  // A first-ever visit has nothing to measure from, and a stamp that will not
  // parse is the same silence, so the clause is dropped rather than guessed at.
  const welcome =
    elapsed === '' ? 'Welcome back.' : `Welcome back. It's been ${elapsed}.`

  const synced = recap.last_sync_at
  const mileRows = recapMiles(recap.miles)
  const milesTotal = recapMilesTotal(mileRows)
  const chestNames = recapChestNames(recap.chests)
  const gift = recapGiftLine(recap.chests)

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
  const growth = recapGrowthLines(recap)
  const grew = flourishLine(recap)
  // What the letter had to leave out. The server sends the newest ten and the
  // true count, and a cut nobody is told about is the same as a lie.
  const held = Math.max(0, (recap.workouts_total ?? workouts.length) - workouts.length)

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
          {/* The dialog is already titled with the words his markup opened on,
              so what goes here is the greeting and the length of the gap. */}
          <p className="hint">{welcome}</p>
        </header>

        <div className="recap">
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
                <p className="recap-cheers">+{cheers} hype.</p>
              )}
            </section>
          )}

          {/* How current the numbers underneath are. An account that has never
              synced is not late for anything, so it says nothing at all. */}
          {synced && (
            <p className="recap-sync">
              Last health sync: {formatDate(synced)} at {formatTimeOfDay(synced)}
            </p>
          )}

          {/* Four rows every time, zeros included, and raw miles in all of them:
              this is what a body covered, never the weighted number. */}
          <ul className="recap-ledger">
            {mileRows.map((row) => (
              <li key={row.activity}>
                <span className="recap-ledger-value">{row.miles.toFixed(1)}</span> miles {row.word}
              </li>
            ))}
            <li className="recap-ledger-total">
              <span className="recap-ledger-value">{milesTotal.toFixed(1)}</span> miles total
            </li>
          </ul>

          {chestNames !== '' && (
            <section className="recap-section">
              <p className="recap-line">
                <span className="recap-line-label">Chests found:</span> {chestNames}
              </p>
              {/* A potion says nothing when it is spent, so this is the only
                  place the person who gave it is named. */}
              {gift !== '' && <p className="hint">{gift}</p>}
            </section>
          )}

          {/* The weighted number, said once and called what it is. It is here
              whatever it comes to, because zero XP is an answer. */}
          <p className="recap-line">
            <span className="recap-line-label">XP earned:</span> {convertedValue(recap.xp ?? 0)}
          </p>

          {medals.length > 0 && (
            <section className="recap-section">
              <h3>Medals earned</h3>
              {/* Every family reads the same way here. A week counted and an
                  hour kept are earnings like a distance run, said in the same
                  words and given the same room. The name is the heading and
                  what earned it sits underneath, which is the same shape the
                  medal rail uses. */}
              <ul className="medal-earns">
                {medals.map((row) => {
                  const times = row.count > 1 ? ` ${row.count} times` : ''
                  const detail = MEDAL_DETAILS[row.id]
                  return (
                    <li key={row.id} className="medal-earn">
                      <MedalMark id={row.id} earned />
                      <div className="medal-earn-body">
                        <p className="medal-earn-name">
                          {medalName(row.id)}
                          {times}
                        </p>
                        {detail && <p className="medal-earn-detail">{detail}</p>}
                      </div>
                    </li>
                  )
                })}
              </ul>
            </section>
          )}

          {growth.length > 0 && (
            <section className="recap-section">
              <h3>In your grove</h3>
              <ul className="recap-growth">
                {growth.map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
            </section>
          )}

          {/* One line, said once. Growth comes from encouraging other people,
              so this is the only place the app mentions it. */}
          {grew !== '' && <p className="hint recap-grew">{grew}</p>}

          {/* Last, closest to Done, because it is the one part of the letter
              that is something to do rather than something to read. Nothing is
              held back from the feed by being here: these were credited and
              published when they arrived, and this is the second chance to say
              something about them. */}
          {workouts.length > 0 && (
            <section className="recap-section">
              <h3>New activities</h3>
              <ul className="recap-activities">
                {workouts.map((row) => {
                  const open = editing === row.workout_id
                  const name = ACTIVITY_NAMES[row.activity]
                  const title = (row.title ?? '').trim()
                  // Named the same way the feed names it: the activity while a
                  // title of its own sits on the line below, and the
                  // time-of-day name while there is none.
                  const heading = title === '' ? defaultHeadline(row.activity, row.start_ts) : name
                  return (
                    <li key={row.workout_id} className="recap-activity">
                      <div className="recap-activity-head">
                        <div className="recap-activity-body">
                          <p className="recap-activity-name">
                            <span className="sport-icon">
                              <Icon name={ACTIVITY_ICONS[row.activity]} />
                            </span>
                            {heading}
                          </p>
                          <p className="recap-activity-stats">
                            <span>{formatDistance(row.distance_mi, units)}</span>
                            <span>{formatDuration(row.duration_s)}</span>
                            <span>{formatStart(row.start_ts)}</span>
                          </p>
                          {/* A name written here shows on the row underneath at
                              once, so saving one is seen to have worked. */}
                          {title !== '' && <p className="recap-activity-title">{title}</p>}
                        </div>
                        {/* The same way in the feed card has, and behind it the
                            same panel: only the words and the pictures are
                            editable, here as there. */}
                        <button
                          type="button"
                          className="icon-button"
                          aria-label={`Edit ${name}`}
                          aria-expanded={open}
                          title="Edit activity"
                          onClick={() => setEditing(open ? null : row.workout_id)}
                        >
                          <Icon name="pencil" />
                        </button>
                      </div>
                      {open && (
                        <EditPanel
                          item={row}
                          onChanged={(changed) =>
                            setWorkouts((current) =>
                              current.map((one) =>
                                one.workout_id === changed.workout_id ? changed : one,
                              ),
                            )
                          }
                          onClose={() => setEditing(null)}
                          explain={false}
                        />
                      )}
                    </li>
                  )
                })}
              </ul>
              {held > 0 && <p className="hint">and {held} more under Activity.</p>}
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
