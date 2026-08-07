import { useCallback, useEffect, useState } from 'react'
import {
  avatarUrl,
  errorText,
  getProfile,
  listWorkouts,
  type Profile as ProfileData,
  type Units,
  type Workout,
} from '../api.ts'
import {
  distanceValue,
  formatClock,
  formatPace,
  formatStart,
  unitName,
} from '../format.ts'
import { ACTIVITY_NAMES } from '../labels.ts'
import Icon from './Icon.tsx'

const PAGE = 20

// Weeks start on Monday, which is what the server counts in as well.
const DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S']
const DAY_NAMES = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
]

const SOURCE_NAMES = {
  sync: 'Apple Health',
  manual: 'Manual entry',
}

// Midnight on the Monday of the week a moment falls in, browser timezone.
function weekStartOf(date: Date): Date {
  const start = new Date(date)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7))
  return start
}

// Which days of this week already have something on them. Compared week by week
// rather than by subtracting milliseconds, so the hour a clock change takes away
// cannot move a workout into the wrong day.
function daysThisWeek(workouts: Workout[]): boolean[] {
  const days = [false, false, false, false, false, false, false]
  const monday = weekStartOf(new Date()).getTime()
  for (const workout of workouts) {
    const when = new Date(workout.start_ts)
    if (weekStartOf(when).getTime() !== monday) continue
    days[(when.getDay() + 6) % 7] = true
  }
  return days
}

interface Cached {
  profile: ProfileData
  workouts: Workout[]
  done: boolean
}

// What this tab last showed, kept by account so a second person signing in on
// the same browser never sees the first one's feed. It lives as long as the page
// does and no longer.
const cache = new Map<number, Cached>()

interface Props {
  userId: number
  units: Units
  // Bumped by the app when something outside this view changed what it shows.
  refreshToken: number
}

export default function Home({ userId, units, refreshToken }: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [profile, setProfile] = useState<ProfileData | null>(
    () => cache.get(userId)?.profile ?? null,
  )
  const [workouts, setWorkouts] = useState<Workout[]>(() => cache.get(userId)?.workouts ?? [])
  const [done, setDone] = useState(() => cache.get(userId)?.done ?? false)
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')
  const [moreBusy, setMoreBusy] = useState(false)
  const [moreError, setMoreError] = useState('')

  const load = useCallback(async () => {
    try {
      const [mine, history] = await Promise.all([getProfile(), listWorkouts(PAGE)])
      setProfile(mine)
      setWorkouts(history)
      setDone(history.length < PAGE)
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  useEffect(() => {
    if (profile) cache.set(userId, { profile, workouts, done })
  }, [userId, profile, workouts, done])

  async function loadMore() {
    const last = workouts[workouts.length - 1]
    if (!last) return
    setMoreBusy(true)
    setMoreError('')
    try {
      const next = await listWorkouts(PAGE, last.start_ts)
      // The cursor is exclusive, so a repeat is not expected; filtering by id
      // anyway means a change under our feet cannot draw the same card twice.
      setWorkouts((current) => {
        const held = new Set(current.map((row) => row.id))
        return [...current, ...next.filter((row) => !held.has(row.id))]
      })
      if (next.length < PAGE) setDone(true)
    } catch (err) {
      setMoreError(errorText(err))
    } finally {
      setMoreBusy(false)
    }
  }

  if (loading) return <p className="notice">Loading.</p>
  if (!profile) {
    return (
      <p className="error" role="alert">
        {loadError || 'Something went wrong. Try again.'}
      </p>
    )
  }

  const streak = profile.streak_weeks ?? 0
  const days = daysThisWeek(workouts)

  return (
    <>
      <section className="card">
        <p className="label">Week streak</p>
        <p className="streak-count">
          <span className="streak-value">{streak}</span>
          <span className="streak-unit">{streak === 1 ? 'week' : 'weeks'}</span>
        </p>
        <ul className="streak-days">
          {DAY_LETTERS.map((letter, index) => (
            <li key={DAY_NAMES[index]} className="streak-day">
              <span className={days[index] ? 'diamond diamond-on' : 'diamond diamond-off'}>
                <Icon name="diamond" />
              </span>
              <span className="streak-letter">
                {letter}
                <span className="sr-only"> {DAY_NAMES[index]}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="hint">
          Miles counted this week. Your phone syncs on its own, so nothing here needs
          opening the app.
        </p>
      </section>

      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}

      {workouts.length === 0 && !loadError && (
        <p className="notice">Nothing recorded yet. Sync your phone or add a workout in Log.</p>
      )}

      {workouts.map((workout) => (
        <article className="card feed" key={workout.id}>
          <header className="feed-head">
            {profile.has_avatar ? (
              <img
                className="feed-avatar"
                src={avatarUrl(profile.user_id, profile.avatar_version)}
                alt=""
              />
            ) : (
              <span className="feed-avatar feed-avatar-empty" aria-hidden="true">
                {profile.username.slice(0, 1).toUpperCase()}
              </span>
            )}
            <div className="feed-who">
              <p className="feed-name">{profile.username}</p>
              <p className="feed-when">{formatStart(workout.start_ts)}</p>
              <p className="feed-source">{SOURCE_NAMES[workout.source]}</p>
            </div>
          </header>

          <h2 className="feed-title">{ACTIVITY_NAMES[workout.activity]}</h2>

          <div className="stat-row">
            <div className="stat">
              <span className="label">Distance</span>
              <span className="stat-value">
                {distanceValue(workout.distance_mi, units)}
                <span className="stat-unit">{unitName(units)}</span>
              </span>
            </div>
            <div className="stat">
              <span className="label">Pace</span>
              <span className="stat-value">
                {formatPace(workout.activity, workout.distance_mi, workout.duration_s, units)}
              </span>
            </div>
            <div className="stat">
              <span className="label">Time</span>
              <span className="stat-value">{formatClock(workout.duration_s)}</span>
            </div>
          </div>

          {workout.xp !== undefined && (
            <p className="feed-foot">
              <span className="feed-xp">+{workout.xp} XP</span>
            </p>
          )}
        </article>
      ))}

      {moreError && (
        <p className="error" role="alert">
          {moreError}
        </p>
      )}

      {workouts.length > 0 && !done && (
        <button
          type="button"
          className="secondary"
          disabled={moreBusy}
          onClick={() => void loadMore()}
        >
          Load more
        </button>
      )}
    </>
  )
}
