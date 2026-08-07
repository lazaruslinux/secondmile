import { useState, type FormEvent } from 'react'
import {
  ApiError,
  avatarUrl,
  encourage,
  errorText,
  type FeedItem,
  type Units,
} from '../api.ts'
import {
  convertedValue,
  distanceValue,
  formatClock,
  formatPace,
  formatStart,
  unitName,
} from '../format.ts'
import { ACTIVITY_NAMES, personName, raceBadgeName } from '../labels.ts'
import AvatarFrame from './AvatarFrame.tsx'
import Icon from './Icon.tsx'
import RouteLine from './RouteLine.tsx'

const SOURCE_NAMES = {
  sync: 'Apple Health',
  manual: 'Manual entry',
}

// The most a note can carry, which is the server's limit as well.
const NOTE_LIMIT = 500

interface Given {
  cheers: number
  notes: number
  cheered: boolean
}

// "2 cheers, 1 note", and nothing at all when there is nothing. A workout
// nobody has said anything about looks like a workout, not like an empty box.
function countLine(given: Given): string {
  const parts: string[] = []
  if (given.cheers > 0) parts.push(`${given.cheers} ${given.cheers === 1 ? 'cheer' : 'cheers'}`)
  if (given.notes > 0) parts.push(`${given.notes} ${given.notes === 1 ? 'note' : 'notes'}`)
  return parts.join(', ')
}

interface EncourageProps {
  workoutId: number
  encouragement: FeedItem['encouragement']
}

// Under a friend's workout: a place to write to them, and a cheer for when
// there is nothing to say. Nothing here suggests any words; whatever gets sent
// is typed by the person sending it.
function EncourageRow({ workoutId, encouragement }: EncourageProps) {
  // Null until this account acts, so the counts stay the server's word up to
  // that point and this account's own doing afterwards.
  const [acted, setActed] = useState<Given | null>(null)
  const [draft, setDraft] = useState('')
  const [written, setWritten] = useState<string[]>([])
  const [showing, setShowing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')

  const given: Given = acted ?? {
    cheers: encouragement.cheers,
    notes: encouragement.notes,
    cheered: encouragement.cheered_by_me,
  }

  async function cheer() {
    if (given.cheered) return
    setBusy(true)
    setFailed('')
    try {
      await encourage(workoutId, 'cheer')
      setActed({ ...given, cheers: given.cheers + 1, cheered: true })
    } catch (err) {
      // A cheer already given answers 409, which means it is there rather than
      // that anything failed, so the button lands in the same quiet state.
      if (err instanceof ApiError && err.status === 409) setActed({ ...given, cheered: true })
      else setFailed(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    const body = draft.trim()
    if (body === '') return
    setBusy(true)
    setFailed('')
    try {
      await encourage(workoutId, 'note', body)
      setActed({ ...given, notes: given.notes + 1 })
      setWritten((current) => [...current, body])
      setDraft('')
    } catch (err) {
      setFailed(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const counts = countLine(given)

  return (
    <div className="encourage">
      <form className="encourage-form" onSubmit={send}>
        <input
          type="text"
          className="encourage-input"
          placeholder="Write a note..."
          maxLength={NOTE_LIMIT}
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
          aria-label="Write a note"
        />
        <button type="submit" className="primary" disabled={busy || draft.trim() === ''}>
          Send
        </button>
        {/* Wordless on purpose: a cheer carries no message, and there is no
            list of ready-made ones to pick from anywhere in this app. */}
        <button
          type="button"
          className={given.cheered ? 'cheer cheer-on' : 'cheer'}
          aria-pressed={given.cheered}
          aria-label={given.cheered ? 'Cheered' : 'Cheer'}
          title={given.cheered ? 'Cheered' : 'Cheer'}
          disabled={busy}
          onClick={() => void cheer()}
        >
          <Icon name="cheer" />
        </button>
      </form>

      {failed && (
        <p className="error" role="alert">
          {failed}
        </p>
      )}

      {counts !== '' &&
        (written.length > 0 ? (
          <button
            type="button"
            className="encourage-counts encourage-counts-open"
            aria-expanded={showing}
            onClick={() => setShowing((open) => !open)}
          >
            {counts}
          </button>
        ) : (
          <p className="encourage-counts">{counts}</p>
        ))}

      {/* Words belong to the person they were written for: they arrive in that
          account's letter. What is held here is what was typed on this screen. */}
      {showing && written.length > 0 && (
        <ul className="encourage-notes">
          {written.map((body, index) => (
            <li key={index}>
              <span className="encourage-note-who">You wrote</span>
              <span className="encourage-note-body">{body}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface Props {
  item: FeedItem
  units: Units
  // Changes with every upload of this account's own picture, so a new one shows
  // straight away. Friends' pictures are addressed without it.
  avatarVersion: number | null
}

// One event in the feed. This account's own workouts read as they always have,
// numbers and all. A friend's carries what they did and nothing measured about
// how hard they were breathing: distance, time, the medal, the line they ran.
export default function FeedCard({ item, units, avatarVersion }: Props) {
  const { user } = item
  const title = ACTIVITY_NAMES[item.activity]
  // The name they go by if they gave one, and their username otherwise.
  const who = personName(user)

  if (item.own) {
    return (
      <article className="card feed">
        <header className="feed-head">
          {user.has_avatar ? (
            <img
              className="feed-avatar"
              src={avatarUrl(user.user_id, avatarVersion)}
              alt=""
            />
          ) : (
            <span className="feed-avatar feed-avatar-empty" aria-hidden="true">
              {who.slice(0, 1).toUpperCase()}
            </span>
          )}
          <div className="feed-who">
            <p className="feed-name">{who}</p>
            <p className="feed-when">{formatStart(item.start_ts)}</p>
            <p className="feed-source">{SOURCE_NAMES[item.source]}</p>
          </div>
        </header>

        <h2 className="feed-title">{title}</h2>

        {item.has_route && <RouteLine workoutId={item.workout_id} />}

        <div className="stat-row">
          <div className="stat">
            <span className="label">Distance</span>
            <span className="stat-value">
              {distanceValue(item.distance_mi, units)}
              <span className="stat-unit">{unitName(units)}</span>
            </span>
          </div>
          <div className="stat">
            <span className="label">Pace</span>
            <span className="stat-value">
              {formatPace(item.activity, item.distance_mi, item.duration_s, units)}
            </span>
          </div>
          <div className="stat">
            <span className="label">Time</span>
            <span className="stat-value">{formatClock(item.duration_s)}</span>
          </div>
        </div>

        {(item.xp !== undefined || item.race_badge) && (
          <p className="feed-foot">
            {item.xp !== undefined && (
              <span className="feed-xp">+{convertedValue(item.xp)} XP</span>
            )}
            {item.race_badge && (
              <span className="feed-badge">{raceBadgeName(item.race_badge)}</span>
            )}
          </p>
        )}
      </article>
    )
  }

  return (
    <article className="card feed">
      <header className="feed-head">
        <AvatarFrame
          name={who}
          src={user.has_avatar ? avatarUrl(user.user_id, null) : null}
          borderTier={user.border_tier}
          flourish={user.flourish}
          frameClass="feed-frame"
        />
        <div className="feed-who">
          <p className="feed-name">{who}</p>
          <p className="feed-when">{formatStart(item.start_ts)}</p>
        </div>
      </header>

      <h2 className="feed-title">{title}</h2>

      {item.has_route && <RouteLine workoutId={item.workout_id} />}

      {/* Two figures, not three. What somebody else did is a distance and a
          length of time; how fast they were going is theirs. */}
      <div className="stat-row stat-row-pair">
        <div className="stat">
          <span className="label">Distance</span>
          <span className="stat-value">
            {distanceValue(item.distance_mi, units)}
            <span className="stat-unit">{unitName(units)}</span>
          </span>
        </div>
        <div className="stat">
          <span className="label">Time</span>
          <span className="stat-value">{formatClock(item.duration_s)}</span>
        </div>
      </div>

      {item.race_badge && (
        <p className="feed-foot">
          <span className="feed-badge">{raceBadgeName(item.race_badge)}</span>
        </p>
      )}

      <EncourageRow workoutId={item.workout_id} encouragement={item.encouragement} />
    </article>
  )
}
