import { useState, type ChangeEvent, type FormEvent } from 'react'
import {
  ApiError,
  avatarUrl,
  deleteWorkoutPhoto,
  encourage,
  errorText,
  PHOTO_TOO_LARGE,
  updateWorkout,
  uploadWorkoutPhoto,
  workoutPhotoUrl,
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
import { ACTIVITY_NAMES, medalName, personName } from '../labels.ts'
import AvatarFrame from './AvatarFrame.tsx'
import Icon from './Icon.tsx'
import RouteLine from './RouteLine.tsx'

const SOURCE_NAMES = {
  sync: 'Apple Health',
  manual: 'Manual entry',
}

// The most a note can carry, which is the server's limit as well.
const NOTE_LIMIT = 500

// The server's limits, stated here as well so a box stops taking letters at the
// point the server would have refused them.
const TITLE_LIMIT = 100
const POST_LIMIT = 2000
const PHOTO_LIMIT = 6

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

// An empty box means the field is being emptied, which the server reads as a
// null rather than as an empty string.
function orNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

// A picture is refused for reasons a person can act on, and two of them can be
// answered by the proxy in front of the app rather than by the server, so the
// sentence is written here rather than read off the response.
function photoErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return PHOTO_TOO_LARGE
    if (err.status === 429) return 'Too many uploads just now. Wait a minute and try again.'
    return err.message
  }
  return 'Something went wrong. Try again.'
}

// The pictures on a workout, at the size a card can hold without becoming an
// album. Every box keeps its space whether the picture inside it arrives or not,
// so one that will not load leaves a gap rather than shortening the card.
function PhotoStrip({ workoutId, photos }: { workoutId: number; photos: number[] }) {
  if (photos.length === 0) return null
  return (
    <ul className="feed-photos">
      {photos.map((photoId) => (
        <li key={photoId} className="photo-thumb">
          <img src={workoutPhotoUrl(workoutId, photoId)} alt="" loading="lazy" />
        </li>
      ))}
    </ul>
  )
}

interface EditProps {
  item: FeedItem
  onChanged: (item: FeedItem) => void
  onClose: () => void
}

// The owner's panel, on the card itself rather than over the page: what is being
// written is read in the place it will be read from. The words are saved
// together by Save; a picture is its own act and is added or taken away the
// moment it is chosen.
function EditPanel({ item, onChanged, onClose }: EditProps) {
  const [title, setTitle] = useState(item.title ?? '')
  const [post, setPost] = useState(item.post ?? '')
  const [saving, setSaving] = useState(false)
  // Which picture call is in flight, so the note can say what is happening.
  const [photoBusy, setPhotoBusy] = useState<'' | 'upload' | 'remove'>('')
  const [failed, setFailed] = useState('')

  const photos = item.photos ?? []
  const busy = saving || photoBusy !== ''
  const full = photos.length >= PHOTO_LIMIT

  async function save(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setFailed('')
    try {
      const saved = await updateWorkout(item.workout_id, {
        title: orNull(title),
        post: orNull(post),
      })
      // Redrawn from what came back rather than from what was typed, so the
      // trimming the server did is what ends up on the card.
      onChanged({ ...item, title: saved.title ?? null, post: saved.post ?? null })
      onClose()
    } catch (err) {
      setFailed(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  async function addPhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // Cleared either way, so choosing the same file twice still counts as a
    // change and the picker does not sit there naming a spent upload.
    event.target.value = ''
    if (!file) return
    setPhotoBusy('upload')
    setFailed('')
    try {
      const photoId = await uploadWorkoutPhoto(item.workout_id, file)
      onChanged({ ...item, photos: [...photos, photoId] })
    } catch (err) {
      setFailed(photoErrorText(err))
    } finally {
      setPhotoBusy('')
    }
  }

  async function removePhoto(photoId: number) {
    setPhotoBusy('remove')
    setFailed('')
    try {
      await deleteWorkoutPhoto(item.workout_id, photoId)
      onChanged({ ...item, photos: photos.filter((id) => id !== photoId) })
    } catch (err) {
      setFailed(photoErrorText(err))
    } finally {
      setPhotoBusy('')
    }
  }

  return (
    <form className="feed-edit-panel" onSubmit={save}>
      <p className="hint">
        Your title, your words, and up to {PHOTO_LIMIT} photos. The distance, the time, and
        when it happened are not editable.
      </p>

      <label className="label">
        Title
        <input
          type="text"
          value={title}
          maxLength={TITLE_LIMIT}
          disabled={busy}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>

      <label className="label">
        Post
        <textarea
          value={post}
          maxLength={POST_LIMIT}
          rows={4}
          disabled={busy}
          placeholder="Write about this activity..."
          onChange={(event) => setPost(event.target.value)}
        />
      </label>

      <div className="feed-edit-photos">
        <p className="label">Photos</p>
        {photos.length > 0 && (
          <ul className="photo-edit-list">
            {photos.map((photoId) => (
              <li key={photoId}>
                <span className="photo-thumb">
                  <img src={workoutPhotoUrl(item.workout_id, photoId)} alt="" loading="lazy" />
                </span>
                <button
                  type="button"
                  className="photo-remove"
                  disabled={busy}
                  aria-label="Remove photo"
                  onClick={() => void removePhoto(photoId)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}

        <label className="file-field label">
          Add a photo
          <input type="file" accept="image/*" disabled={busy || full} onChange={addPhoto} />
        </label>
        <p className="hint">
          {full
            ? `${PHOTO_LIMIT} photos is the limit. Remove one to add another.`
            : `Up to ${PHOTO_LIMIT} photos, 10 MB each. A photo is saved as soon as you choose it.`}
        </p>
        {photoBusy === 'upload' && (
          <p className="hint" role="status">
            Uploading.
          </p>
        )}
        {photoBusy === 'remove' && (
          <p className="hint" role="status">
            Removing.
          </p>
        )}
      </div>

      {failed && (
        <p className="error" role="alert">
          {failed}
        </p>
      )}

      <div className="choice">
        <button type="submit" className="primary" disabled={busy}>
          Save
        </button>
        <button type="button" className="secondary" disabled={saving} onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  )
}

interface Props {
  item: FeedItem
  units: Units
  // Changes with every upload of this account's own picture, so a new one shows
  // straight away. Friends' pictures are addressed without it.
  avatarVersion: number | null
  // An edited card is handed back to whoever holds the feed, so the row it is
  // drawn from carries the change rather than only this card knowing about it.
  onChanged: (item: FeedItem) => void
}

// One event in the feed. This account's own workouts read as they always have,
// numbers and all. A friend's carries what they did and nothing measured about
// how hard they were breathing: distance, time, the medal, the line they ran.
export default function FeedCard({ item, units, avatarVersion, onChanged }: Props) {
  const [editing, setEditing] = useState(false)
  const { user } = item
  const activityName = ACTIVITY_NAMES[item.activity]
  const given = (item.title ?? '').trim()
  // A title takes the headline and pushes the activity name down to the small
  // line the date and the source sit on. Without one nothing moves.
  const headline = given === '' ? activityName : given
  const when =
    given === ''
      ? formatStart(item.start_ts)
      : `${activityName}, ${formatStart(item.start_ts)}`
  const post = (item.post ?? '').trim()
  const photos = item.photos ?? []
  const medals = item.medals ?? []
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
            <p className="feed-when">{when}</p>
            <p className="feed-source">{SOURCE_NAMES[item.source]}</p>
          </div>
          {/* The owner's way in, and only the words and the pictures are behind
              it. What was covered, how long it took, and when it happened are
              editable nowhere. */}
          <button
            type="button"
            className="icon-button feed-edit"
            aria-label="Edit activity"
            aria-expanded={editing}
            title="Edit activity"
            onClick={() => setEditing((open) => !open)}
          >
            <Icon name="pencil" />
          </button>
        </header>

        {editing ? (
          <EditPanel
            item={item}
            onChanged={onChanged}
            onClose={() => setEditing(false)}
          />
        ) : (
          <h2 className="feed-title">{headline}</h2>
        )}

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

        {/* Both of these are in the panel while it is open, so the card does not
            say the same thing twice. */}
        {!editing && post !== '' && <p className="feed-post">{post}</p>}
        {!editing && <PhotoStrip workoutId={item.workout_id} photos={photos} />}

        {(item.xp !== undefined || medals.length > 0) && (
          <p className="feed-foot">
            {item.xp !== undefined && (
              <span className="feed-xp">+{convertedValue(item.xp)} XP</span>
            )}
            {/* One chip per medal the workout earned. A long run started before
                dawn earns two, and the strip wraps rather than truncates. */}
            {medals.map((id) => (
              <span key={id} className="feed-badge">
                {medalName(id)}
              </span>
            ))}
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
          <p className="feed-when">{when}</p>
        </div>
      </header>

      <h2 className="feed-title">{headline}</h2>

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

      {/* What they wrote and what they took pictures of. Unlike the pace, this
          is theirs to share, and sharing it is what putting it here was. */}
      {post !== '' && <p className="feed-post">{post}</p>}
      <PhotoStrip workoutId={item.workout_id} photos={photos} />

      {medals.length > 0 && (
        <p className="feed-foot">
          {medals.map((id) => (
            <span key={id} className="feed-badge">
              {medalName(id)}
            </span>
          ))}
        </p>
      )}

      <EncourageRow workoutId={item.workout_id} encouragement={item.encouragement} />
    </article>
  )
}
