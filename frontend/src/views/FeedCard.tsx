import {
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from 'react'
import {
  ApiError,
  avatarUrl,
  deleteWorkout,
  deleteWorkoutPhoto,
  deleteWorkoutVideo,
  encourage,
  errorText,
  getWorkoutNotes,
  PHOTO_TOO_LARGE,
  updateWorkout,
  uploadWorkoutPhoto,
  uploadWorkoutVideo,
  VIDEO_TOO_LARGE,
  workoutPhotoUrl,
  workoutVideoPosterUrl,
  workoutVideoUrl,
  type Activity,
  type FeedItem,
  type Gear,
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
import { gearName, wearable } from '../gear.ts'
import {
  activityIcon,
  ACTIVITY_NAMES,
  defaultHeadline,
  personName,
  TOO_MANY_UPLOADS,
} from '../labels.ts'
import AvatarFrame from './AvatarFrame.tsx'
import Confirm from './Confirm.tsx'
import Icon from './Icon.tsx'
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
// Photos and videos share these slots, which is why the name is not PHOTO.
const MEDIA_LIMIT = 6

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

// One person's words, with their face beside their name. Both the picture and
// the name open their profile where the screen holding the card can go there;
// where it cannot, the row reads exactly as it did before either became a
// control. Nobody's own "You wrote" row is drawn this way: you are not a
// destination, and the row above says who wrote it either way.
function NoteRow({
  note,
  onOpenPerson,
}: {
  note: WorkoutNote
  onOpenPerson?: (userId: number) => void
}) {
  const who = personName(note.user)
  const face = (
    <AvatarFrame
      name={who}
      src={note.user.has_avatar ? avatarUrl(note.user.user_id, null) : null}
      borderTier={note.user.border_tier}
      flourish={note.user.flourish}
      frameClass="note-frame"
    />
  )
  return (
    <li className="encourage-note">
      {onOpenPerson ? (
        <button
          type="button"
          className="feed-identity"
          aria-label={`${who}'s profile`}
          onClick={() => onOpenPerson(note.user.user_id)}
        >
          {face}
        </button>
      ) : (
        face
      )}
      <span className="encourage-note-said">
        <span className="encourage-note-who">
          {onOpenPerson ? (
            <button
              type="button"
              className="feed-name-open"
              onClick={() => onOpenPerson(note.user.user_id)}
            >
              {who}
            </button>
          ) : (
            who
          )}
        </span>
        <span className="encourage-note-body">{note.body}</span>
      </span>
    </li>
  )
}

// The count line and the words behind it, wherever a card carries them: your
// own workout and a friend's read the same way now, so the rule about who may
// open a thread lives in one component rather than in two copies of it.
//
// The counts are the line, and tapping it is what asks the server. Nothing is
// fetched until somebody does, and what came back is kept, so closing and
// reopening a card does not ask again.
function NoteThread({
  workoutId,
  counts,
  hasNotes,
  onOpenPerson,
}: {
  workoutId: number
  // The whole line as it is printed, worked out by whoever is drawing it: an
  // own card counts nobody's cheer as its own and a friend's card does.
  counts: string
  // Whether there is anything behind the line. A line of hype alone is not a
  // door, so it is not drawn as one.
  hasNotes: boolean
  onOpenPerson?: (userId: number) => void
}) {
  const [notes, setNotes] = useState<WorkoutNote[] | null>(null)
  const [showing, setShowing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState('')

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

  return (
    <>
      {hasNotes ? (
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

      {/* Everybody's words and not only this account's. A comment sits on the
          workout it was written about, and anybody who can see the workout can
          read what was said on it. Somebody in here you have never met is a
          card away: their face opens their profile. */}
      {showing && notes !== null && (
        <ul className="encourage-notes">
          {notes.map((note, index) => (
            <NoteRow key={index} note={note} onOpenPerson={onOpenPerson} />
          ))}
        </ul>
      )}
    </>
  )
}

// Under a friend's workout: a place to write on it, a cheer for when there is
// nothing to say, and the thread of what everybody else has already written.
// Nothing here suggests any words; whatever gets sent is typed by the person
// sending it.
function EncourageRow({
  workoutId,
  encouragement,
  onOpenPerson,
}: EncourageProps & { onOpenPerson?: (userId: number) => void }) {
  // Null until this account acts, so the counts stay the server's word up to
  // that point and this account's own doing afterwards.
  const [acted, setActed] = useState<Given | null>(null)
  const [draft, setDraft] = useState('')
  // How many notes this account has written here. Only ever used as the
  // thread's key: writing one makes whatever was fetched a line out of date,
  // and a fresh component is the shortest way to say so.
  const [sent, setSent] = useState(0)
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
      setSent((count) => count + 1)
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

      {counts !== '' && (
        <NoteThread
          // A note this account just wrote is part of the thread now, so the
          // key moves and the component comes back with nothing cached.
          key={sent}
          workoutId={workoutId}
          counts={counts}
          hasNotes={given.notes > 0}
          onOpenPerson={onOpenPerson}
        />
      )}
    </div>
  )
}

// Under your own workout: what came back for it, and the words themselves once
// you ask for them. No box and no hype button, because both of those go toward
// the person who did the miles and that is you.
function ReceivedRow({
  workoutId,
  encouragement,
  onOpenPerson,
}: EncourageProps & { onOpenPerson?: (userId: number) => void }) {
  const counts = countLine({
    cheers: encouragement.cheers,
    notes: encouragement.notes,
    cheered: false,
  })
  if (counts === '') return null

  return (
    <div className="encourage">
      <NoteThread
        workoutId={workoutId}
        counts={counts}
        hasNotes={encouragement.notes > 0}
        onOpenPerson={onOpenPerson}
      />
    </div>
  )
}

// An empty box means the field is being emptied, which the server reads as a
// null rather than as an empty string.
function orNull(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

// A picture or a video is refused for reasons a person can act on, and two of
// them can be answered by the proxy in front of the app rather than by the
// server, so those sentences are written here rather than read off the
// response. The too-large one differs by what was being added, so it is passed
// in rather than guessed at.
function mediaErrorText(err: unknown, tooLarge: string): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return tooLarge
    if (err.status === 429) return TOO_MANY_UPLOADS
    return err.message
  }
  return 'Something went wrong. Try again.'
}

// The pictures and the video on a workout, at the size a card can hold without
// becoming an album. Every box keeps its space whether what is inside it
// arrives or not, so one that will not load leaves a gap rather than shortening
// the card.
//
// A video sits in the strip as its poster with a play mark on it, and pressing
// it swaps that slot for the browser's own player across the full width of the
// strip. Inline rather than in a dialog: a clip is part of the card the way a
// photograph is, and a thumbnail-sized player is no use to anybody.
function MediaStrip({
  workoutId,
  photos,
  videos,
}: {
  workoutId: number
  photos: number[]
  videos: number[]
}) {
  const [playing, setPlaying] = useState<number | null>(null)
  const stripRef = useRef<HTMLUListElement>(null)
  // Where the strip sat the instant Close was pressed, read back once the
  // collapse has been laid out.
  const closedFrom = useRef<{ top: number; height: number } | null>(null)

  // The player stands far taller than the poster it replaces, so closing it
  // shortens the card and everything under it climbs by the difference. Only
  // the part of that shrink that sat above the top of the window moves what
  // the reader is looking at, so the strip is put back that far down and no
  // further: a strip already fully on screen lost nothing above the fold and
  // is left exactly where it was. Measured against where the strip actually
  // landed, so the browser's own anchoring and a scroll clamped by the shorter
  // page are corrected rather than counted twice. Before paint, so it is one
  // frame with the collapse.
  useLayoutEffect(() => {
    const before = closedFrom.current
    closedFrom.current = null
    const strip = stripRef.current
    if (!before || !strip) return
    const now = strip.getBoundingClientRect()
    const shrink = Math.max(0, before.height - now.height)
    const want = before.top + Math.min(shrink, Math.max(0, -before.top))
    const drift = now.top - want
    if (Math.abs(drift) > 0.5) window.scrollBy(0, drift)
  }, [playing])

  if (photos.length === 0 && videos.length === 0) return null
  return (
    <ul className="feed-photos" ref={stripRef}>
      {photos.map((photoId) => (
        <li key={`p${photoId}`} className="photo-thumb">
          <img src={workoutPhotoUrl(workoutId, photoId)} alt="" loading="lazy" />
        </li>
      ))}
      {videos.map((videoId) =>
        playing === videoId ? (
          <li key={`v${videoId}`} className="video-playing">
            {/* No caption track: a clip off somebody's phone has none to
                offer, and inventing one would be putting words in their
                mouth. The player's own controls carry everything else.
                nodownload takes the save button off those controls; the
                bytes still arrive, because they have to for it to play. */}
            <video
              className="feed-video"
              controls
              controlsList="nodownload"
              autoPlay
              playsInline
              preload="metadata"
              poster={workoutVideoPosterUrl(workoutId, videoId)}
              src={workoutVideoUrl(workoutId, videoId)}
            />
            {/* Under the player, in the strip's own small-button shape, rather
                than floating over the frame where the native controls live.
                Unmounting the video is what stops the sound. */}
            <button
              type="button"
              className="video-close"
              onClick={() => {
                const rect = stripRef.current?.getBoundingClientRect()
                closedFrom.current = rect ? { top: rect.top, height: rect.height } : null
                setPlaying(null)
              }}
            >
              Close video
            </button>
          </li>
        ) : (
          <li key={`v${videoId}`} className="photo-thumb">
            <button
              type="button"
              className="video-open"
              aria-label="Play video"
              onClick={() => setPlaying(videoId)}
            >
              <img src={workoutVideoPosterUrl(workoutId, videoId)} alt="" loading="lazy" />
              <span className="video-play">
                <Icon name="play" />
              </span>
            </button>
          </li>
        ),
      )}
    </ul>
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
          <span className="label">Avg. HR</span>
          <span className="stat-value">
            {Math.round(item.avg_hr)}
            <span className="stat-unit">bpm</span>
          </span>
        </div>
      )}
    </div>
  )
}

// What a workout was done in, beside the numbers and quiet about it: a small
// mark, and the pair's name only once somebody asks for it. Tapping shows it and
// tapping again puts it away, which is the whole of it; the full account of a
// pair is on the Shoes card of whoever owns it.
//
// A button rather than a title, because a title is a thing a mouse hovers over
// and this app is used on a phone.
function GearMark({ name }: { name: string }) {
  const [showing, setShowing] = useState(false)
  return (
    <p className="gear-line">
      <button
        type="button"
        className="gear-mark"
        aria-label="Shoes"
        aria-expanded={showing}
        onClick={() => setShowing((open) => !open)}
      >
        <Icon name="shoe" />
      </button>
      {showing && <span>{name}</span>}
    </p>
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
  videos?: number[]
  // What it was, and what it was done in. Both are read by the shoe picker and
  // by nothing else here: shoes go on walks and runs alone.
  activity?: Activity
  gear?: string | null
  gear_id?: number | null
}

// How long a deleted workout waits under Activity before it is gone for good.
// The server's own window, said here as well because the dialog below has to
// state it plainly and a number nobody can read is not a promise.
const DELETED_DAYS = 30

// The last thing before a workout goes: what deleting one costs, in the shared
// confirm every destructive question in this app is asked in.
//
// One dialog for one workout and for a batch of them, because the consequences
// are the same ones and saying them twice in two places is how the two drift
// apart. The count is named in the question and on the button, so nobody
// confirms a number they were not shown.
export function ConfirmDelete({
  busy,
  error,
  count = 1,
  onConfirm,
  onCancel,
}: {
  busy: boolean
  error: string
  count?: number
  onConfirm: () => void
  onCancel: () => void
}) {
  const many = count > 1

  return (
    <Confirm
      heading={many ? `Delete ${count} activities?` : 'Delete this activity?'}
      confirmLabel={many ? `Delete ${count}` : 'Delete'}
      cancelLabel={many ? 'Keep them' : 'Keep it'}
      busy={busy}
      error={error}
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      <p>
        {many
          ? "They go out of your feed and your friends' feeds."
          : "It goes out of your feed and your friends' feeds."}
      </p>
      <p>
        The miles come back off your totals, your level, your streak and the
        medals they earned. What those miles already grew in your grove
        stays, and chests you have already found stay.
      </p>
      <p>
        {many ? 'They wait' : 'It waits'} under Deleted on your Activity tab
        for {DELETED_DAYS} days, and you can put{' '}
        {many ? 'any of them' : 'it'} back any time until then. After that{' '}
        {many ? 'they are' : 'it is'} gone for good.
      </p>
    </Confirm>
  )
}

interface EditProps<T extends EditableWorkout> {
  item: T
  // Handed back as the same shape it came in as, so whoever owns the row can
  // put the change back where it lives without losing the rest of the row.
  onChanged: (item: T) => void
  onClose: () => void
  // Where deleting is offered. Given by the feed and the Activity tab, which
  // can take a card off the screen and ask for the totals again; left out by
  // the letter,
  // whose rows are a report of what arrived and would be reporting a workout
  // that is no longer there.
  onDeleted?: (workoutId: number) => void
  // Whether to open with the line saying what can and cannot be edited. The
  // feed keeps it; the letter drops it, because a letter that lists several
  // workouts would repeat the same paragraph down the page.
  explain?: boolean
  // This account's shoes, where the screen holding the card has them. Without
  // them there is no picker, which is what the letter opens with.
  gear?: Gear[]
}

// The owner's panel, on the card itself rather than over the page: what is being
// written is read in the place it will be read from. The words are saved
// together by Save; a picture or a video is its own act and is added or taken
// away the moment it is chosen.
export function EditPanel<T extends EditableWorkout>({
  item,
  onChanged,
  onClose,
  onDeleted,
  explain = true,
  gear = [],
}: EditProps<T>) {
  const [title, setTitle] = useState(item.title ?? '')
  const [post, setPost] = useState(item.post ?? '')
  const [gearId, setGearId] = useState(item.gear_id ?? null)
  const [saving, setSaving] = useState(false)
  // Which media call is in flight, so the note can say what is happening. A
  // video is its own value because it is the one that takes a moment.
  const [mediaBusy, setMediaBusy] = useState<'' | 'photo' | 'video' | 'remove'>('')
  const [failed, setFailed] = useState('')
  const [asking, setAsking] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteFailed, setDeleteFailed] = useState('')

  const photos = item.photos ?? []
  const videos = item.videos ?? []
  // Shoes go on walks and runs alone. The pair already on this one is offered
  // whatever its state, so a retired pair does not quietly read as None; every
  // other retired pair is out, because retired takes nothing new.
  const picker =
    item.activity === 'walk' || item.activity === 'run'
      ? [
          ...wearable(gear),
          ...gear.filter((pair) => pair.retired && pair.id === item.gear_id),
        ]
      : []
  const busy = saving || mediaBusy !== '' || deleting
  // One count over both, because they fill the same slots.
  const full = photos.length + videos.length >= MEDIA_LIMIT

  async function save(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setFailed('')
    try {
      const saved = await updateWorkout(item.workout_id, {
        title: orNull(title),
        post: orNull(post),
        // Only where the picker is drawn. Sending it from a panel that has no
        // picker would take the shoes off a workout nobody asked about.
        ...(picker.length > 0 ? { gear_id: gearId } : {}),
      })
      // Redrawn from what came back rather than from what was typed, so the
      // trimming the server did is what ends up on the card.
      onChanged({
        ...item,
        title: saved.title ?? null,
        post: saved.post ?? null,
        gear: saved.gear ?? null,
        gear_id: saved.gear_id ?? null,
      })
      onClose()
    } catch (err) {
      setFailed(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  // Cleared either way, so choosing the same file twice still counts as a
  // change and the picker does not sit there naming a spent upload.
  function taken(event: ChangeEvent<HTMLInputElement>): File | null {
    const file = event.target.files?.[0] ?? null
    event.target.value = ''
    return file
  }

  async function addPhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = taken(event)
    if (!file) return
    setMediaBusy('photo')
    setFailed('')
    try {
      const photoId = await uploadWorkoutPhoto(item.workout_id, file)
      onChanged({ ...item, photos: [...photos, photoId] })
    } catch (err) {
      setFailed(mediaErrorText(err, PHOTO_TOO_LARGE))
    } finally {
      setMediaBusy('')
    }
  }

  async function removePhoto(photoId: number) {
    setMediaBusy('remove')
    setFailed('')
    try {
      await deleteWorkoutPhoto(item.workout_id, photoId)
      onChanged({ ...item, photos: photos.filter((id) => id !== photoId) })
    } catch (err) {
      setFailed(mediaErrorText(err, PHOTO_TOO_LARGE))
    } finally {
      setMediaBusy('')
    }
  }

  async function addVideo(event: ChangeEvent<HTMLInputElement>) {
    const file = taken(event)
    if (!file) return
    setMediaBusy('video')
    setFailed('')
    try {
      const videoId = await uploadWorkoutVideo(item.workout_id, file)
      onChanged({ ...item, videos: [...videos, videoId] })
    } catch (err) {
      setFailed(mediaErrorText(err, VIDEO_TOO_LARGE))
    } finally {
      setMediaBusy('')
    }
  }

  async function remove() {
    setDeleting(true)
    setDeleteFailed('')
    try {
      await deleteWorkout(item.workout_id)
      setAsking(false)
      // The panel is not closed on the way out: the card it is inside goes
      // with the workout, and whoever owns the list takes both away.
      onDeleted?.(item.workout_id)
    } catch (err) {
      setDeleteFailed(errorText(err))
    } finally {
      setDeleting(false)
    }
  }

  async function removeVideo(videoId: number) {
    setMediaBusy('remove')
    setFailed('')
    try {
      await deleteWorkoutVideo(item.workout_id, videoId)
      onChanged({ ...item, videos: videos.filter((id) => id !== videoId) })
    } catch (err) {
      setFailed(mediaErrorText(err, VIDEO_TOO_LARGE))
    } finally {
      setMediaBusy('')
    }
  }

  return (
    <form className="feed-edit-panel" onSubmit={save}>
      {explain && (
        <p className="hint">
          You can edit the title, your words, and up to {MEDIA_LIMIT} photos and videos.
          Distance and time are not editable.
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

      {picker.length > 0 && (
        <label className="label">
          {/* The mark and the word are one item, because the captions in this
              panel are stacked and a bare mark would take a line of its own. */}
          <span>
            <span className="sport-icon sport-icon-small">
              <Icon name="shoe" />
            </span>
            Shoes
          </span>
          <select
            value={gearId === null ? '' : String(gearId)}
            disabled={busy}
            onChange={(event) =>
              setGearId(event.target.value === '' ? null : Number(event.target.value))
            }
          >
            <option value="">None</option>
            {picker.map((pair) => (
              <option key={pair.id} value={String(pair.id)}>
                {gearName(pair)}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="feed-edit-photos">
        <p className="label">Photos and video</p>
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

        {/* The video sits under the pictures and is removed the same way. Its
            poster stands in for it here: this is the picking of media, not the
            watching of it, and there is a player on the card itself. */}
        {videos.length > 0 && (
          <ul className="photo-edit-list">
            {videos.map((videoId) => (
              <li key={videoId}>
                <span className="photo-thumb">
                  <img
                    src={workoutVideoPosterUrl(item.workout_id, videoId)}
                    alt=""
                    loading="lazy"
                  />
                </span>
                <button
                  type="button"
                  className="photo-remove"
                  disabled={busy}
                  aria-label="Remove video"
                  onClick={() => void removeVideo(videoId)}
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

        <label className="file-field label">
          Add a video
          <input
            type="file"
            accept="video/*"
            disabled={busy || full || videos.length > 0}
            onChange={addVideo}
          />
        </label>

        <p className="hint">
          {full
            ? `${MEDIA_LIMIT} photos and videos is the limit. Remove one to add another.`
            : `Up to ${MEDIA_LIMIT} photos and videos, 10 MB a photo. One video of about a ` +
              'minute, 100 MB. Each one is saved as soon as you choose it.'}
        </p>
        {mediaBusy === 'photo' && (
          <p className="hint" role="status">
            Uploading.
          </p>
        )}
        {/* Said differently because it is true differently: the server
            re-encodes the clip before it answers, so this one waits. */}
        {mediaBusy === 'video' && (
          <p className="hint" role="status">
            Uploading. A video takes a moment.
          </p>
        )}
        {mediaBusy === 'remove' && (
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

      {/* Under the two that save, behind a rule and behind a question: it is
          not a third way to leave the panel. Absent altogether where deleting
          is not offered, which is the letter. */}
      {onDeleted && (
        <button
          type="button"
          className="workout-delete"
          disabled={busy}
          onClick={() => {
            setDeleteFailed('')
            setAsking(true)
          }}
        >
          Delete activity
        </button>
      )}

      {asking && (
        <ConfirmDelete
          busy={deleting}
          error={deleteFailed}
          onConfirm={() => void remove()}
          onCancel={() => setAsking(false)}
        />
      )}
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
  // A deleted one is handed back the same way, and the card goes with it. Only
  // your own cards ever offer it, and only where the screen holding them can
  // ask the server for its totals again.
  onDeleted?: (workoutId: number) => void
  // What the server marked about the numbers, in a sentence, on your own card
  // only. The Activity tab is the one screen that reads flags, so this arrives
  // from there rather than off the row.
  note?: string
  // This account's shoes, for the picker in the panel behind the pencil. Only
  // your own cards ever open one.
  gear?: Gear[]
  // Opens somebody's profile. On a friend's card that is whoever it belongs
  // to, from their picture and from their name; on your own it is whoever
  // wrote to you, from the notes under it. Your own header is never a way to
  // your own screen the long way round, and the cards on a profile do not lead
  // to another one, which is where this arrives undefined.
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
  onDeleted,
  note,
  gear,
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
  // The sport's mark sits beside the headline on every card, titled or not, so
  // the sport is in the same place down the whole feed. The activity name still
  // moves to the small line when a title takes the headline; the mark does not
  // follow it.
  const mark = (
    <span className="sport-icon">
      <Icon name={activityIcon(item.activity, item.indoor)} />
    </span>
  )
  const post = (item.post ?? '').trim()
  const photos = item.photos ?? []
  const videos = item.videos ?? []
  const medals = item.medals ?? []
  // The name they go by if they gave one, and their username otherwise.
  const who = personName(user)

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
            <p className="feed-when">{when}</p>
            <p className="feed-source">{SOURCE_NAMES[item.source]}</p>
          </div>
          {/* The owner's way in, and only the words and the media are behind
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
            gear={gear}
            onChanged={onChanged}
            onDeleted={onDeleted}
            onClose={() => setEditing(false)}
          />
        ) : (
          <h2 className="feed-title">
            {mark}
            {headline}
          </h2>
        )}

        {/* This and the media are in the panel while it is open, so the card
            does not say the same thing twice. */}
        {!editing && post !== '' && <p className="feed-post">{post}</p>}

        <StatRow item={item} units={units} />

        {item.gear && <GearMark name={item.gear} />}

        {/* Under the numbers it is about, and worded as the sentence it is: a
            flagged workout still counts, and the card says so rather than
            hiding a machine word behind a tooltip. */}
        {note && <p className="flag-note">{note}</p>}

        {item.has_route && <RouteLine workoutId={item.workout_id} />}

        {!editing && (
          <MediaStrip workoutId={item.workout_id} photos={photos} videos={videos} />
        )}

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

        {/* Your own card, and the people in it are the ones who wrote to you:
            the way through to them is here rather than in the header, which is
            you. */}
        <ReceivedRow
          workoutId={item.workout_id}
          encouragement={item.encouragement}
          onOpenPerson={onOpenPerson}
        />
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
          <p className="feed-when">{when}</p>
        </div>
      </header>

      <h2 className="feed-title">
        {mark}
        {headline}
      </h2>

      {/* What they wrote and what they pointed a camera at, theirs to share,
          and sharing it is what putting it here was. */}
      {post !== '' && <p className="feed-post">{post}</p>}

      <StatRow item={item} units={units} />

      {item.gear && <GearMark name={item.gear} />}

      {item.has_route && <RouteLine workoutId={item.workout_id} />}

      <MediaStrip workoutId={item.workout_id} photos={photos} videos={videos} />

      {medals.length > 0 && (
        <p className="feed-foot">
          {medals.map((id) => (
            <MedalChip key={id} id={id} />
          ))}
        </p>
      )}

      <EncourageRow
        workoutId={item.workout_id}
        encouragement={item.encouragement}
        onOpenPerson={onOpenPerson}
      />
    </article>
  )
}
