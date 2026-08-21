import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteWorkouts,
  errorText,
  getProfile,
  listDeletedWorkouts,
  listWeeks,
  listWorkouts,
  restoreWorkout,
  type Activity as Sport,
  type DeletedWorkout,
  type FeedItem,
  type Gear,
  type SortOrder,
  type Units,
  type Week,
  type Workout,
  type WorkoutFlags,
  type WorkoutSort,
} from '../api.ts'
import {
  formatDayKey,
  formatDistance,
  formatClock,
  formatPace,
  formatShortDate,
  formatStart,
  weekStartKey,
  zonedDay,
} from '../format.ts'
import {
  ACTIVITY_ICONS,
  activityIcon,
  ACTIVITY_NAMES,
  ACTIVITY_ORDER,
  defaultHeadline,
  NOTHING_RECORDED,
} from '../labels.ts'
import FeedCard, { ConfirmDelete } from './FeedCard.tsx'
import Icon from './Icon.tsx'
import Insights from './Insights.tsx'

// Twenty at a time, which is the feed's page as well: the cards view draws the
// same card the feed does, and fifty of them at once is a page that keeps
// drawing long after somebody has stopped reading it.
const WORKOUT_PAGE = 20

// Which of the two views this browser was last left on. The only thing kept
// between visits: a sort is asked for on purpose and a sport filter even more
// so, and coming back tomorrow to yesterday's filter would be the app hiding
// workouts nobody asked it to hide.
const VIEW_KEY = 'secondmile.activity.view'

type Shape = 'cards' | 'list'

function rememberedShape(): Shape {
  try {
    return localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'cards'
  } catch {
    // A browser with storage turned off simply opens on the cards every time.
    return 'cards'
  }
}

function rememberShape(shape: Shape): void {
  try {
    localStorage.setItem(VIEW_KEY, shape)
  } catch {
    // Nothing to say: the choice holds for this visit and is forgotten after.
  }
}

// What the four sorts are called, and what each direction of each one means. A
// direction has no name of its own here: descending distance is the longest
// first and descending pace is the slowest, and the buttons say so rather than
// making somebody work out which way an arrow points. The first of each pair is
// the one a sort opens on.
const SORT_NAMES: Record<WorkoutSort, string> = {
  date: 'Date',
  distance: 'Distance',
  pace: 'Pace',
  avg_hr: 'Avg. HR',
}

const SORT_ORDERS: Record<WorkoutSort, { order: SortOrder; word: string }[]> = {
  date: [
    { order: 'desc', word: 'Newest' },
    { order: 'asc', word: 'Oldest' },
  ],
  distance: [
    { order: 'desc', word: 'Longest' },
    { order: 'asc', word: 'Shortest' },
  ],
  pace: [
    { order: 'asc', word: 'Fastest' },
    { order: 'desc', word: 'Slowest' },
  ],
  avg_hr: [
    { order: 'desc', word: 'Highest' },
    { order: 'asc', word: 'Lowest' },
  ],
}

const SORT_KEYS = Object.keys(SORT_NAMES) as WorkoutSort[]

// The Monday that starts a workout's week, read in the instance's zone, which
// is the zone the weekly totals below it were added up in.
function weekKeyOf(iso: string): string {
  return weekStartKey(zonedDay(iso))
}

// What a workout is called on screen: what its owner named it, or what the app
// calls a workout nobody named. Read by the list's rows and by the tick over a
// card, so the two say the same thing about the same workout.
function headlineOf(workout: Workout): string {
  const given = (workout.title ?? '').trim()
  return given === '' ? defaultHeadline(workout.activity, workout.start_ts) : given
}

// Flags are machine words in the database; a person reading their own history
// deserves the sentence version.
function flagNotes(flags: WorkoutFlags): string {
  const notes: string[] = []
  if (flags.impossible_pace) {
    notes.push('This pace looks too fast, so the numbers may be off. It still counts.')
  }
  if (flags.daily_cap) {
    notes.push('This day went over the daily distance limit. It still counts.')
  }
  return notes.join(' ')
}

// "1 day left" the day before it goes, and "gone today" on the last of them,
// which is the honest reading of a window that has hours rather than days in
// it. The number is the server's; this only puts it into words.
function daysLeftLine(days: number): string {
  if (days <= 0) return 'Gone today'
  return `${days} ${days === 1 ? 'day' : 'days'} left`
}

interface Cached {
  workouts: Workout[]
  weeks: Week[]
  deleted: DeletedWorkout[]
  avatarVersion: number | null
  // The account's own shoes, for the picker behind a card's pencil. Off the
  // profile this screen already loads rather than a call of its own.
  gear: Gear[]
  // Kept with the rows they produced, so coming back to the tab draws the list
  // the controls above it claim to be showing.
  sort: WorkoutSort
  order: SortOrder
  sport: Sport | null
  // Whether the last page was a short one, so Load more is not offered again
  // at the end of a history that has already been walked to its end.
  done: boolean
}

// What this tab last showed, kept by account so a second person signing in on
// the same browser never sees the first one's history. It lives as long as the
// page does and no longer.
const cache = new Map<number, Cached>()

interface Props {
  userId: number
  units: Units
  // Whoever wrote on one of these workouts, from the notes under the card.
  onOpenPerson: (userId: number) => void
  // The screen behind a card, from its title and its figures. The shoes go
  // with it: this screen is already holding the list, and the screen behind
  // the card has no call of its own for it.
  onOpenWorkout: (item: FeedItem, gear: Gear[]) => void
}

export default function ActivityView({
  userId,
  units,
  onOpenPerson,
  onOpenWorkout,
}: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [workouts, setWorkouts] = useState<Workout[]>(() => cache.get(userId)?.workouts ?? [])
  const [weeks, setWeeks] = useState<Week[]>(() => cache.get(userId)?.weeks ?? [])
  const [deleted, setDeleted] = useState<DeletedWorkout[]>(
    () => cache.get(userId)?.deleted ?? [],
  )
  const [shape, setShape] = useState<Shape>(rememberedShape)
  const [sort, setSort] = useState<WorkoutSort>(() => cache.get(userId)?.sort ?? 'date')
  const [order, setOrder] = useState<SortOrder>(() => cache.get(userId)?.order ?? 'desc')
  const [sport, setSport] = useState<Sport | null>(() => cache.get(userId)?.sport ?? null)
  // Which row of the list is unfolded, one at a time: two cards open at once in
  // a list built for scanning is a feed again, only a worse one.
  const [opened, setOpened] = useState<number | null>(null)
  const [showDeleted, setShowDeleted] = useState(false)
  // Which row is being put back, so only its own button says so.
  const [restoring, setRestoring] = useState<number | null>(null)
  const [restoreError, setRestoreError] = useState('')
  // Only ever used to address your own picture, so a new one shows here as soon
  // as it shows anywhere else.
  const [avatarVersion, setAvatarVersion] = useState<number | null>(
    () => cache.get(userId)?.avatarVersion ?? null,
  )
  const [gear, setGear] = useState<Gear[]>(() => cache.get(userId)?.gear ?? [])
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')
  // Whether the history has been walked to its end under the controls as they
  // stand, and the state of the button that walks it.
  const [done, setDone] = useState(() => cache.get(userId)?.done ?? false)
  const [moreBusy, setMoreBusy] = useState(false)
  const [moreError, setMoreError] = useState('')
  // Select mode, and what is ticked in it. Ids rather than rows: a row can be
  // redrawn under a tick and the tick still means the same workout.
  const [selecting, setSelecting] = useState(false)
  const [picked, setPicked] = useState<Set<number>>(() => new Set())
  const [asking, setAsking] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [removeError, setRemoveError] = useState('')

  // Which request the screen is waiting for. Every control here starts a fresh
  // one, and two of them can easily be in the air at once: on a phone, a press
  // half a second after another is ordinary, and answers to a multiplexed
  // connection arrive in whatever order the server finishes them. Without this
  // count the slower answer lands last and the list shows a sort the buttons no
  // longer claim, with no way back except pressing something else, because
  // pressing the one already lit changes no state and asks for nothing. That is
  // the freeze: rows stuck in April under a header saying Newest.
  const wanted = useRef(0)

  const load = useCallback(async () => {
    const mine = ++wanted.current
    // Said before the first await, so the page is already saying it is thinking
    // by the time anything is in the air. Every one of these takes four
    // requests, and a phone on a slow connection spends most of a second on
    // them with nothing on screen changing but the button that was pressed:
    // that wait is what reads as a freeze.
    setLoading(true)
    try {
      const [history, totals, gone, me] = await Promise.all([
        // The sorting and the filtering are the server's: a page is twenty rows
        // of a history that may run to thousands, so ordering what arrived
        // would order the wrong twenty.
        listWorkouts(WORKOUT_PAGE, {
          sort,
          order,
          ...(sport === null ? {} : { activity: sport }),
        }),
        // Every week, not the recent ones: Load more walks back past any
        // window, and a heading with no totals under it is a week the page
        // could not add up.
        listWeeks(),
        listDeletedWorkouts(),
        getProfile(),
      ])
      if (mine !== wanted.current) return
      setWorkouts(history)
      setDone(history.length < WORKOUT_PAGE)
      setWeeks(totals)
      setDeleted(gone)
      setAvatarVersion(me.avatar_version)
      setGear(me.gear ?? [])
      setLoadError('')
    } catch (err) {
      if (mine !== wanted.current) return
      setLoadError(errorText(err))
    } finally {
      if (mine === wanted.current) setLoading(false)
    }
  }, [sort, order, sport])

  useEffect(() => {
    // A fresh set of controls is a fresh first page: what was loaded before
    // was a different question's answer, and ticks put against rows that are
    // no longer on screen are not a list anybody chose.
    setMoreError('')
    setPicked(new Set())
    void load()
  }, [load])

  // The next page, appended. Counted by what is already on screen rather than
  // by a page number, so a Load more pressed after a deletion asks for what
  // comes after the rows still here.
  async function loadMore() {
    const mine = wanted.current
    // What the offset was counted from. A press that lands while the first page
    // of a fresh sort is still in the air asks for what comes after a list that
    // is about to be thrown away, and appending it would leave a hole where the
    // rows between the two should be.
    const from = workouts.length
    setMoreBusy(true)
    setMoreError('')
    try {
      const next = await listWorkouts(WORKOUT_PAGE, {
        sort,
        order,
        offset: from,
        ...(sport === null ? {} : { activity: sport }),
      })
      // A page asked for under controls that have since changed is not this
      // list's page, whenever it turns up.
      if (mine !== wanted.current) return
      setWorkouts((current) => {
        // Not the list this page was counted off, so it is not this list's
        // page. The button is unavailable while a fresh first page is on its
        // way, which is what keeps this from arising; it is checked anyway,
        // because the cost of being wrong is a gap in somebody's history.
        if (current.length !== from) return current
        // An offset moves when a row is deleted under it, so a repeat is
        // possible and is dropped rather than drawn twice.
        const held = new Set(current.map((row) => row.workout_id))
        return [...current, ...next.filter((row) => !held.has(row.workout_id))]
      })
      if (next.length < WORKOUT_PAGE) setDone(true)
    } catch (err) {
      if (mine === wanted.current) setMoreError(errorText(err))
    } finally {
      setMoreBusy(false)
    }
  }

  // Kept from what is on screen rather than from what arrived, so a card edited
  // here is still edited after a trip to another tab. A load that failed writes
  // nothing, so a first visit that went wrong still says Loading on the next.
  useEffect(() => {
    if (!loading && loadError === '')
      cache.set(userId, {
        workouts,
        weeks,
        deleted,
        avatarVersion,
        gear,
        sort,
        order,
        sport,
        done,
      })
  }, [
    userId,
    workouts,
    weeks,
    deleted,
    avatarVersion,
    gear,
    sort,
    order,
    sport,
    done,
    loading,
    loadError,
  ])

  function chooseShape(next: Shape) {
    setShape(next)
    rememberShape(next)
    // What is ticked survives the swap: both shapes tick the same workouts, and
    // a shape changed halfway through a tidy-up is a different way of looking
    // at the same list rather than a reason to start again.
  }

  function stopSelecting() {
    setSelecting(false)
    setPicked(new Set())
    setAsking(false)
    setRemoveError('')
  }

  function pick(workoutId: number) {
    setPicked((current) => {
      const next = new Set(current)
      if (!next.delete(workoutId)) next.add(workoutId)
      return next
    })
  }

  // The batch. One call, one confirmation, one answer: the rows leave the list
  // at once and the Deleted list above takes them, which is where the count on
  // the pill comes from, so nothing is asked for again to draw it. The week
  // totals did change and are the one thing fetched afresh.
  async function removePicked() {
    setRemoving(true)
    setRemoveError('')
    try {
      const gone = await deleteWorkouts([...picked])
      const ids = new Set(gone.map((row) => row.workout_id))
      setWorkouts((current) => current.filter((row) => !ids.has(row.workout_id)))
      setOpened((open) => (open !== null && ids.has(open) ? null : open))
      // Straight to the front: they were deleted just now, and the list is in
      // the order they were deleted in.
      setDeleted((current) => [...gone, ...current])
      stopSelecting()
      setWeeks(await listWeeks())
    } catch (err) {
      setRemoveError(errorText(err))
    } finally {
      setRemoving(false)
    }
  }

  // A new sort opens on its own natural direction: picking Pace means wanting
  // the fastest, not whichever way the last sort happened to be pointed.
  function chooseSort(next: WorkoutSort) {
    setSort(next)
    setOrder(SORT_ORDERS[next][0].order)
    setOpened(null)
  }

  // An edited card is put back where it sat, flags and all: the panel hands
  // back the feed's part of the row and the rest of it is already here.
  const cardChanged = useCallback((updated: FeedItem) => {
    setWorkouts((current) =>
      current.map((row) =>
        row.workout_id === updated.workout_id ? { ...row, ...updated } : row,
      ),
    )
  }, [])

  // A deleted card leaves at once so the screen answers the press, and the
  // whole page is asked for again underneath: the week totals above it and the
  // Deleted list both changed, and neither can be worked out here.
  const cardDeleted = useCallback(
    (workoutId: number) => {
      setWorkouts((current) => current.filter((row) => row.workout_id !== workoutId))
      setOpened((open) => (open === workoutId ? null : open))
      void load()
    },
    [load],
  )

  async function putBack(workoutId: number) {
    setRestoring(workoutId)
    setRestoreError('')
    try {
      await restoreWorkout(workoutId)
      const left = deleted.filter((row) => row.workout_id !== workoutId)
      setDeleted(left)
      // The pill goes with the last row in it, and so does what it opened: an
      // empty drawer left standing would reopen itself on the next deletion.
      if (left.length === 0) setShowDeleted(false)
      // Straight back into the history in its own place, with this week's
      // totals and the streak behind it: the same reload the deletion does.
      await load()
    } catch (err) {
      setRestoreError(errorText(err))
    } finally {
      setRestoring(null)
    }
  }

  const totalsByWeek = new Map(weeks.map((week) => [week.week_start.slice(0, 10), week]))

  // Weekly totals are a date-sort idea: they add up a week of rows that are
  // next to each other because they happened next to each other. Sorted by
  // distance, or narrowed to one sport, the page is one list and says so.
  const grouped = sort === 'date' && sport === null

  // The history arrives in week order when it is in date order, so walking it
  // produces the groups in the same order. Ungrouped, it is one list under one
  // empty key, so both views draw the same shape either way.
  const groups: { key: string; workouts: Workout[] }[] = []
  for (const workout of workouts) {
    const key = grouped ? weekKeyOf(workout.start_ts) : ''
    const current = groups[groups.length - 1]
    if (current && current.key === key) current.workouts.push(workout)
    else groups.push({ key, workouts: [workout] })
  }

  function card(workout: Workout) {
    return (
      <FeedCard
        key={workout.workout_id}
        item={workout}
        units={units}
        avatarVersion={avatarVersion}
        gear={gear}
        onChanged={cardChanged}
        onDeleted={cardDeleted}
        note={flagNotes(workout.flags)}
        onOpenPerson={onOpenPerson}
        onOpenDetails={(row) => onOpenWorkout(row, gear)}
      />
    )
  }

  // The same card with the ticking over it: the whole card is the target, the
  // mark sits in the corner the pencil is gone from, and the card underneath is
  // inert, so nothing on it can be opened, tapped, or tabbed to by mistake
  // while what is being chosen is the card itself. Nothing about the card is
  // drawn differently, which is the point: it is the workout you were reading a
  // moment ago, with a tick on it.
  function pickableCard(workout: Workout) {
    const ticked = picked.has(workout.workout_id)
    return (
      <div className="card-pick" key={workout.workout_id}>
        {/* Inert rather than merely covered: a control under a button is still
            reachable by a keyboard, and none of these are anybody's way
            anywhere while the cards are being ticked. */}
        <div inert>
          <FeedCard
            item={workout}
            units={units}
            avatarVersion={avatarVersion}
            gear={gear}
            onChanged={cardChanged}
            onDeleted={cardDeleted}
            note={flagNotes(workout.flags)}
            selecting
          />
        </div>
        <button
          type="button"
          className={ticked ? 'card-pick-hit card-pick-on' : 'card-pick-hit'}
          aria-pressed={ticked}
          aria-label={`Select ${headlineOf(workout)}`}
          onClick={() => pick(workout.workout_id)}
        >
          <span className={ticked ? 'list-tick list-tick-on' : 'list-tick'} aria-hidden="true" />
        </button>
      </div>
    )
  }

  // One row of the list: what it was, when, and its figures, and nothing that
  // has to be fetched. Pressing it unfolds the whole card underneath, pencil
  // and all; pressing it again folds it away. Whole row is the hit target in
  // Select mode; the tick box alone is too small.
  function row(workout: Workout) {
    const open = opened === workout.workout_id
    const ticked = picked.has(workout.workout_id)
    const headline = headlineOf(workout)
    const flagged = flagNotes(workout.flags) !== ''
    return (
      <li key={workout.workout_id} className="list-item">
        <button
          type="button"
          className={
            selecting
              ? ticked
                ? 'list-row list-row-ticked'
                : 'list-row'
              : open
                ? 'list-row list-row-open'
                : 'list-row'
          }
          aria-expanded={selecting ? undefined : open}
          aria-pressed={selecting ? ticked : undefined}
          onClick={() =>
            selecting ? pick(workout.workout_id) : setOpened(open ? null : workout.workout_id)
          }
        >
          <span className="list-head">
            {/* Drawn rather than an input: the whole row is the control, and a
                checkbox inside a button is a second control nobody can reach.
                The row carries the thumb target; this is the mark on it, and
                the button's own pressed state is what a reader is told. */}
            {selecting && (
              <span
                className={ticked ? 'list-tick list-tick-on' : 'list-tick'}
                aria-hidden="true"
              />
            )}
            <span className="sport-icon sport-icon-small">
              <Icon name={activityIcon(workout.activity, workout.indoor)} />
            </span>
            <span className="list-name">{headline}</span>
            {/* The server's own doubt about the numbers, marked rather than
                explained: the card underneath carries the sentence. */}
            {flagged && <span className="tag tag-flag">Flagged</span>}
          </span>
          <span className="list-figures">
            <span>{formatShortDate(workout.start_ts)}</span>
            <span>{formatDistance(workout.distance_mi, units)}</span>
            <span>{formatClock(workout.duration_s)}</span>
            <span>
              {formatPace(workout.activity, workout.distance_mi, workout.duration_s, units)}
            </span>
            {/* Empty rather than absent, so the columns stay columns down a
                list where some workouts carried a heart rate and some did not. */}
            <span>
              {typeof workout.avg_hr === 'number' ? `${Math.round(workout.avg_hr)} bpm` : ''}
            </span>
          </span>
        </button>

        {/* Nothing unfolds while rows are being ticked: the list is a tool
            then, and a card in the middle of it is somewhere to lose a tick. */}
        {!selecting && open && card(workout)}
      </li>
    )
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">Activity</h1>
      </div>

      <section className="dash">
        <div className="dash-top">
          <div className="choice dash-shape">
            {/* Cards is what this tab has always been, so it is what a first
                visit opens on. */}
            <button
              type="button"
              className={shape === 'cards' ? 'choice-option choice-current' : 'choice-option'}
              aria-pressed={shape === 'cards'}
              onClick={() => chooseShape('cards')}
            >
              Cards
            </button>
            <button
              type="button"
              className={shape === 'list' ? 'choice-option choice-current' : 'choice-option'}
              aria-pressed={shape === 'list'}
              onClick={() => chooseShape('list')}
            >
              List
            </button>
          </div>

          {/* The way into tidying up, offered by both shapes: a card is as much
              a workout as a row is, and the one you can see is the one you want
              to be rid of. */}
          <button
            type="button"
            className={selecting ? 'dash-select dash-select-on' : 'dash-select'}
            aria-pressed={selecting}
            onClick={() => {
              if (selecting) stopSelecting()
              else {
                setSelecting(true)
                setOpened(null)
              }
            }}
          >
            Select
          </button>

          {/* Absent at zero: a pill reading Deleted (0) would put the idea in
              front of somebody who has never deleted anything. */}
          {deleted.length > 0 && (
            <button
              type="button"
              className={showDeleted ? 'deleted-pill deleted-pill-open' : 'deleted-pill'}
              aria-expanded={showDeleted}
              onClick={() => setShowDeleted((open) => !open)}
            >
              Deleted ({deleted.length})
            </button>
          )}
        </div>

        <div className="dash-sort">
          <label className="label dash-field">
            Sort
            <select
              value={sort}
              onChange={(event) => chooseSort(event.target.value as WorkoutSort)}
            >
              {SORT_KEYS.map((key) => (
                <option key={key} value={key}>
                  {SORT_NAMES[key]}
                </option>
              ))}
            </select>
          </label>

          <div className="choice dash-order">
            {SORT_ORDERS[sort].map((choice) => (
              <button
                key={choice.order}
                type="button"
                className={
                  order === choice.order ? 'choice-option choice-current' : 'choice-option'
                }
                aria-pressed={order === choice.order}
                onClick={() => {
                  setOrder(choice.order)
                  setOpened(null)
                }}
              >
                {choice.word}
              </button>
            ))}
          </div>
        </div>

        {/* One sport at a time, or all of them, which is where it starts. */}
        <ul className="filter-chips">
          {([null, ...ACTIVITY_ORDER] as (Sport | null)[]).map((name) => {
            const on = sport === name
            return (
              <li key={name ?? 'all'}>
                <button
                  type="button"
                  className={on ? 'filter-chip filter-chip-on' : 'filter-chip'}
                  aria-pressed={on}
                  onClick={() => {
                    setSport(name)
                    setOpened(null)
                  }}
                >
                  {name !== null && (
                    <span className="sport-icon sport-icon-small">
                      <Icon name={ACTIVITY_ICONS[name]} />
                    </span>
                  )}
                  {name === null ? 'All' : ACTIVITY_NAMES[name]}
                </button>
              </li>
            )
          })}
        </ul>

        {/* What is ticked and what can be done with it, in the header the
            ticking was started from. Nothing goes until the dialog says so. */}
        {selecting && (
          <div className="dash-acts">
            {/* The app's delete verb, which is the accent: the same button the
                confirmation behind it wears. */}
            <button
              type="button"
              className="primary"
              disabled={picked.size === 0 || removing}
              onClick={() => {
                setRemoveError('')
                setAsking(true)
              }}
            >
              Delete selected ({picked.size})
            </button>
            <button type="button" className="secondary" disabled={removing} onClick={stopSelecting}>
              Cancel
            </button>
          </div>
        )}
      </section>

      {asking && (
        <ConfirmDelete
          busy={removing}
          error={removeError}
          count={picked.size}
          onConfirm={() => void removePicked()}
          onCancel={() => setAsking(false)}
        />
      )}

      {/* Opened from the pill above and drawn here, at the top, where it was
          asked for. Rows rather than cards, because a deleted workout has no
          pictures to show and nothing to say. */}
      {showDeleted && deleted.length > 0 && (
        <section className="deleted">
          <h2>Deleted</h2>
          <p className="hint">
            Hidden from everyone and out of your totals. Put one back any time
            before its last day.
          </p>

          {restoreError && (
            <p className="error" role="alert">
              {restoreError}
            </p>
          )}

          <ul className="deleted-list">
            {deleted.map((gone) => (
              <li key={gone.workout_id} className="deleted-row">
                <span className="deleted-what">
                  <span className="sport-icon sport-icon-small">
                    <Icon name={activityIcon(gone.activity, gone.indoor)} />
                  </span>
                  <span className="deleted-name">
                    {gone.title?.trim() || defaultHeadline(gone.activity, gone.start_ts)}
                  </span>
                  <span className="muted">
                    {formatStart(gone.start_ts)}, {formatDistance(gone.distance_mi, units)}
                  </span>
                </span>
                <span className="deleted-left">{daysLeftLine(gone.days_left)}</span>
                <button
                  type="button"
                  className="secondary"
                  disabled={restoring !== null}
                  onClick={() => void putBack(gone.workout_id)}
                >
                  {restoring === gone.workout_id ? 'Restoring.' : 'Restore'}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Above the history and shut until it is asked for. This tab is only
          ever your own, so what is in it is only ever your own: the band reads
          the endpoint that answers for the account holding the session and for
          nobody else. */}
      <Insights units={units} />

      <section>
        <h2>History</h2>
        {/* A live region, because this one comes and goes as somebody works
            the controls rather than only on the way in. */}
        {loading && (
          <p className="notice" role="status">
            Loading.
          </p>
        )}
        {loadError && (
          <p className="error" role="alert">
            {loadError}
          </p>
        )}
        {!loading && !loadError && groups.length === 0 && (
          <p className="notice">
            {sport === null
              ? NOTHING_RECORDED
              : 'Nothing recorded in that sport yet.'}
          </p>
        )}

        {/* What is on screen while a new answer is on its way is the old
            answer, so it is dimmed: the page is showing yesterday's list and
            saying so, rather than looking like a list that will not respond.
            The controls above are outside this and stay live. */}
        {groups.map((group) => (
          <div
            className={loading ? 'activity-group activity-group-stale' : 'activity-group'}
            key={group.key}
          >
            {grouped && (
              <div className="week">
                <h3>Week of {formatDayKey(group.key)}</h3>

                {totalsByWeek.get(group.key) && (
                  <ul className="totals">
                    {ACTIVITY_ORDER.map((name) => {
                      const total = totalsByWeek.get(group.key)?.activities[name]
                      if (!total) return null
                      return (
                        <li key={name}>
                          {/* Inside the label rather than beside it, so the mark
                              comes out of the width the label already reserves
                              and the figures stay in their column. */}
                          <span className="totals-activity">
                            <span className="sport-icon sport-icon-small">
                              <Icon name={ACTIVITY_ICONS[name]} />
                            </span>
                            {ACTIVITY_NAMES[name]}
                          </span>
                          <span>{formatDistance(total.distance_mi, units)}</span>
                          <span className="muted">
                            {total.workouts} {total.workouts === 1 ? 'workout' : 'workouts'}
                            {total.active_kcal > 0 && `, ${Math.round(total.active_kcal)} kcal`}
                          </span>
                        </li>
                      )
                    })}
                    <li className="totals-week">
                      <span className="totals-activity">Week</span>
                      <span>
                        {Math.round(totalsByWeek.get(group.key)?.total_active_kcal ?? 0)} kcal
                      </span>
                    </li>
                  </ul>
                )}
              </div>
            )}

            {/* The same card the feed draws, because it is the same workout:
                naming one, writing about it, and adding pictures happen here as
                well. The list draws the row and unfolds the very same card. */}
            {shape === 'cards' ? (
              group.workouts.map((workout) =>
                selecting ? pickableCard(workout) : card(workout),
              )
            ) : (
              <ul className="activity-list">{group.workouts.map((workout) => row(workout))}</ul>
            )}
          </div>
        ))}

        {moreError && (
          <p className="error" role="alert">
            {moreError}
          </p>
        )}

        {/* The foot of both views. Absent once the history has been walked to
            its end, so nobody presses a button that can only answer with
            nothing. */}
        {workouts.length > 0 && !done && (
          <button
            type="button"
            className="secondary"
            // Nothing to add a page to while the first page of a fresh sort is
            // still coming: the list under it is about to be replaced.
            disabled={moreBusy || loading}
            onClick={() => void loadMore()}
          >
            {moreBusy ? 'Loading.' : 'Load more'}
          </button>
        )}
      </section>
    </>
  )
}
