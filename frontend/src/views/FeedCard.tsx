import { useState, type ChangeEvent, type FormEvent } from 'react'
import {
  ApiError,
  avatarUrl,
  deleteWorkoutPhoto,
  encourage,
  errorText,
  getWorkoutNotes,
  PHOTO_TOO_LARGE,
  updateWorkout,
  uploadWorkoutPhoto,
  workoutPhotoUrl,
  type FeedItem,
  type Units,
  type WorkoutNote,
} from '../api.ts'
import {
  convertedValue,
  distanceValue,
  formatClock,
  formatPace,
  formatStart,
  unitName,
} from '../format.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, defaultHeadline, personName } from '../labels.ts'
import AvatarFrame from './AvatarFrame.tsx'
import Icon from './Icon.tsx'
import { MAX_MEDAL_SLOTS } from './MedalNest.tsx'
import { MedalChip } from './Medals.tsx'
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

// "+6 hype, 1 comment", and nothing at all when there is nothing. A workout
// nobody has said anything about looks like a workout, not like an empty box.
// The kind stays 'note' under the screen; on the feed it is a comment.
function countLine(given: Given): string {
  const parts: string[] = []
  if (given.cheers > 0) parts.push(`+${given.cheers} hype`)
  if (given.notes > 0) parts.push(`${given.notes} ${given.notes === 1 ? 'comment' : 'comments'}`)
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
          placeholder="Drop some encouragement"
          maxLength={NOTE_LIMIT}
          value={draft}
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
          aria-label="Drop some encouragement"
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
          aria-label={given.cheered ? 'hyped' : '+1 hype'}
          title={given.cheered ? 'hyped' : '+1 hype'}
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

// Under your own workout: what came back for it, and the words themselves once
// you ask for them. No box and no hype button, because both of those go toward
// the person who did the miles and that is you.
function ReceivedRow({ workoutId, encouragement }: EncourageProps) {
  // Null until the first time the notes are opened, and kept afterwards, so
  // closing and reopening a card does not ask again.
  const [notes, setNotes] = useState<WorkoutNote[] | null>(null)
  const [showing, setShowing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')

  const counts = countLine({
    cheers: encouragement.cheers,
    notes: encouragement.notes,
    cheered: false,
  })

  async function toggle() {
    if (showing) {
      setShowing(false)
      return
    }
    setShowing(true)
    if (notes !== null) return
    setBusy(true)
    setFailed('')
    try {
      setNotes(await getWorkoutNotes(workoutId))
    } catch (err) {
      setFailed(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  if (counts === '') return null

  return (
    <div className="encourage">
      {encouragement.notes > 0 ? (
        <button
          type="button"
          className="encourage-counts encourage-counts-open"
          aria-expanded={showing}
          disabled={busy}
          onClick={() => void toggle()}
        >
          {counts}
        </button>
      ) : (
        <p className="encourage-counts">{counts}</p>
      )}

      {failed && (
        <p className="error" role="alert">
          {failed}
        </p>
      )}

      {showing && notes !== null && (
        <ul className="encourage-notes">
          {notes.map((note, index) => (
            <li key={index}>
              <span className="encourage-note-who">{note.from}</span>
              <span className="encourage-note-body">{note.body}</span>
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

// The medals somebody chose to show, beside their name. Friends' cards only:
// your own three are already nestled on your picture on the You screen, so the
// feed says them about everybody but you. These are who they are rather than
// what this workout earned, which is why they sit at the top of the card and
// the earned ones stay along the foot. They are drawn at the foot's size and
// not nestled on the picture: nested medals come to about three times the width
// of a 2.5rem feed avatar and would lie across the name, and shrinking them
// takes the word off the plate, which is the only thing telling 5K from
// MARATHON.
function ChosenMedals({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null
  return (
    <p className="feed-chosen">
      {ids.slice(0, MAX_MEDAL_SLOTS).map((id) => (
        <MedalChip key={id} id={id} />
      ))}
    </p>
  )
}

// What a workout was, in numbers. Every card says it the same way, own and
// friend's alike, so it is written down once. A figure the person hiding it kept
// back does not arrive at all, so it simply is not drawn: there is no empty slot
// and nothing saying something is missing, because a card announcing what it
// will not show is a worse answer than a card that reads whole.
function StatRow({ item, units }: { item: FeedItem; units: Units }) {
  return (
    <div className="stat-row">
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
      <div className="stat">
        <span className="label">Pace</span>
        <span className="stat-value">
          {formatPace(item.activity, item.distance_mi, item.duration_s, units)}
        </span>
      </div>
      {typeof item.active_kcal === 'number' && (
        <div className="stat">
          <span className="label">Calories</span>
          <span className="stat-value">{Math.round(item.active_kcal)}</span>
        </div>
      )}
      {typeof item.avg_hr === 'number' && (
        <div className="stat">
          <span className="label">Heart rate</span>
          <span className="stat-value">
            {Math.round(item.avg_hr)}
            <span className="stat-unit">bpm</span>
          </span>
        </div>
      )}
    </div>
  )
}

// The parts of a workout the panel below actually touches, which is all it ever
// needed to know about one. A feed row satisfies it and so does a row in the
// letter, so both open the same panel rather than growing a second one.
export interface EditableWorkout {
  workout_id: number
  title?: string | null
  post?: string | null
  photos?: number[]
}

interface EditProps<T extends EditableWorkout> {
  item: T
  // Handed back as the same shape it came in as, so whoever owns the row can
  // put the change back where it lives without losing the rest of the row.
  onChanged: (item: T) => void
  onClose: () => void
  // Whether to open with the line saying what can and cannot be edited. The
  // feed keeps it; the letter drops it, because a letter that lists several
  // workouts would repeat the same paragraph down the page.
  explain?: boolean
}

// The owner's panel, on the card itself rather than over the page: what is being
// written is read in the place it will be read from. The words are saved
// together by Save; a picture is its own act and is added or taken away the
// moment it is chosen.
export function EditPanel<T extends EditableWorkout>({
  item,
  onChanged,
  onClose,
  explain = true,
}: EditProps<T>) {
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
      {explain && (
        <p className="hint">
          You can edit the title, your words, and up to {PHOTO_LIMIT} photos. Distance and
          time are not editable.
        </p>
      )}

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
          placeholder="Write about this activity"
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
  // What the server marked about the numbers, in a sentence, on your own card
  // only. The log is the one screen that reads flags, so this arrives from
  // there rather than off the row.
  note?: string
  // Opens the profile of whoever this card belongs to, from their picture and
  // from their name. Only a friend's card ever uses it: your own rows are not a
  // way to your own screen the long way round, and the cards on a profile do
  // not lead to another one.
  onOpenPerson?: (userId: number) => void
}

// One event in the feed. This account's own workouts read as they always have,
// numbers and all. A friend's carries what they did in full, minus whatever
// they have asked to keep back in their own settings, which arrives here as a
// field the server did not send.
export default function FeedCard({
  item,
  units,
  avatarVersion,
  onChanged,
  note,
  onOpenPerson,
}: Props) {
  const [editing, setEditing] = useState(false)
  const { user } = item
  const activityName = ACTIVITY_NAMES[item.activity]
  const given = (item.title ?? '').trim()
  // A title takes the headline and pushes the activity name down to the small
  // line the date and the source sit on. Without one the workout is named for
  // the part of the day it started in.
  const headline = given === '' ? defaultHeadline(item.activity, item.start_ts) : given
  const when =
    given === ''
      ? formatStart(item.start_ts)
      : `${activityName}, ${formatStart(item.start_ts)}`
  // The sport's mark goes wherever the activity name went, which is the headline
  // on a card without a title and the small line underneath on a card with one.
  // It is drawn once either way, beside the word rather than in place of it, and
  // it takes the smaller size on the small line so it sits with those words
  // rather than over them.
  const mark = (
    <span className={given === '' ? 'sport-icon' : 'sport-icon sport-icon-small'}>
      <Icon name={ACTIVITY_ICONS[item.activity]} />
    </span>
  )
  const post = (item.post ?? '').trim()
  const photos = item.photos ?? []
  const medals = item.medals ?? []
  // The name they go by if they gave one, and their username otherwise.
  const who = personName(user)
  // Read as optional on purpose: the field arrives on the person card, and a
  // card without it draws no medals rather than throwing. Own cards never draw
  // it at all: your picture on You already wears the same three.
  const chosen = user.displayed_badges ?? []

  if (item.own) {
    return (
      <article className="card feed">
        <header className="feed-head">
          {/* The same frame a friend's card has always had. Your own border and
              your own growth are worth as much on your own workout as on
              somebody else's, and the version is here because a picture just
              uploaded has to show straight away. */}
          <AvatarFrame
            name={who}
            src={user.has_avatar ? avatarUrl(user.user_id, avatarVersion) : null}
            borderTier={user.border_tier}
            flourish={user.flourish}
            frameClass="feed-frame"
          />
          <div className="feed-who">
            <p className="feed-name">{who}</p>
            <p className="feed-when">
              {given !== '' && mark}
              {when}
            </p>
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
          <h2 className="feed-title">
            {given === '' && mark}
            {headline}
          </h2>
        )}

        {/* This and the pictures are in the panel while it is open, so the card
            does not say the same thing twice. */}
        {!editing && post !== '' && <p className="feed-post">{post}</p>}

        <StatRow item={item} units={units} />

        {/* Under the numbers it is about, and worded as the sentence it is: a
            flagged workout still counts, and the card says so rather than
            hiding a machine word behind a tooltip. */}
        {note && <p className="flag-note">{note}</p>}

        {item.has_route && <RouteLine workoutId={item.workout_id} />}

        {!editing && <PhotoStrip workoutId={item.workout_id} photos={photos} />}

        {(item.xp !== undefined || medals.length > 0) && (
          <p className="feed-foot">
            {item.xp !== undefined && (
              <span className="feed-xp">+{convertedValue(item.xp)} XP</span>
            )}
            {/* One chip per medal the workout earned. A long run started before
                dawn earns two, and the strip wraps rather than truncates. */}
            {medals.map((id) => (
              <MedalChip key={id} id={id} />
            ))}
          </p>
        )}

        <ReceivedRow workoutId={item.workout_id} encouragement={item.encouragement} />
      </article>
    )
  }

  const face = (
    <AvatarFrame
      name={who}
      src={user.has_avatar ? avatarUrl(user.user_id, null) : null}
      borderTier={user.border_tier}
      flourish={user.flourish}
      frameClass="feed-frame"
    />
  )

  return (
    <article className="card feed">
      <header className="feed-head">
        {/* Their picture and their name both open their profile. Both are
            stripped back to nothing, so the card reads exactly as it did before
            either of them became a control. */}
        {onOpenPerson ? (
          <button
            type="button"
            className="feed-identity"
            aria-label={`${who}'s profile`}
            onClick={() => onOpenPerson(user.user_id)}
          >
            {face}
          </button>
        ) : (
          face
        )}
        <div className="feed-who">
          <p className="feed-name">
            {onOpenPerson ? (
              <button
                type="button"
                className="feed-name-open"
                onClick={() => onOpenPerson(user.user_id)}
              >
                {who}
              </button>
            ) : (
              who
            )}
          </p>
          <p className="feed-when">
            {given !== '' && mark}
            {when}
          </p>
        </div>
        <ChosenMedals ids={chosen} />
      </header>

      <h2 className="feed-title">
        {given === '' && mark}
        {headline}
      </h2>

      {/* What they wrote and what they took pictures of, theirs to share, and
          sharing it is what putting it here was. */}
      {post !== '' && <p className="feed-post">{post}</p>}

      <StatRow item={item} units={units} />

      {item.has_route && <RouteLine workoutId={item.workout_id} />}

      <PhotoStrip workoutId={item.workout_id} photos={photos} />

      {medals.length > 0 && (
        <p className="feed-foot">
          {medals.map((id) => (
            <MedalChip key={id} id={id} />
          ))}
        </p>
      )}

      <EncourageRow workoutId={item.workout_id} encouragement={item.encouragement} />
    </article>
  )
}
