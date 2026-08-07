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
import { borderArt } from '../art.ts'
import {
  convertedValue,
  distanceValue,
  formatClock,
  formatPace,
  formatStart,
  unitName,
} from '../format.ts'
import { ACTIVITY_NAMES, RACE_BADGE_ORDER, raceBadgeName } from '../labels.ts'
import { lifetimeWorkouts, raceCountsOf, weekTotals } from '../profile.ts'
import Icon from './Icon.tsx'
import MedalNest from './MedalNest.tsx'
import { RaceBadgeMark } from './RaceBadges.tsx'
import RouteLine from './RouteLine.tsx'

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

// The weeks counted and this week's days. Drawn twice on the page: once in the
// summary card the wide layout has, and once in a card of its own for the phone,
// where there is no side column to put it in. Only one of the two is ever shown.
function Streak({ streak, days }: { streak: number; days: boolean[] }) {
  return (
    <>
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
    </>
  )
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
  // The app owns which screen is up, so the rows that go somewhere are handed
  // the switch rather than reaching for it.
  onOpenLog: () => void
  onOpenCards: () => void
}

export default function Home({ userId, units, refreshToken, onOpenLog, onOpenCards }: Props) {
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
  const border = borderArt(profile.border_tier)
  const week = weekTotals(profile)
  const activities = lifetimeWorkouts(profile)
  const latest = workouts[0]
  const raceCounts = raceCountsOf(profile.race_badges)

  // Only the race medals among the chosen four are drawn here. This screen does
  // not fetch the achievement catalogue, so an achievement badge has no artwork
  // to draw from; the You screen shows all four.
  const nestMedals = profile.displayed_badges
    .filter((id) => (raceCounts.get(id) ?? 0) > 0)
    .map((id) => <RaceBadgeMark key={id} id={id} earned standalone />)

  // Three columns from 900px up and one below it. The columns are wrappers
  // rather than a reordering, so the phone still draws the streak, then the
  // feed, in the order they are written.
  return (
    <div className="home">
      <aside className="home-col home-left">
        <section className="card summary">
          <div className="avatar-frame summary-frame">
            {profile.has_avatar ? (
              <img
                className="avatar-shot"
                src={avatarUrl(profile.user_id, profile.avatar_version)}
                alt={`${profile.username}'s picture`}
              />
            ) : (
              <span className="avatar-shot avatar-empty" aria-hidden="true">
                {profile.username.slice(0, 1).toUpperCase()}
              </span>
            )}
            {border && <img className="avatar-border" src={border} alt="" />}
            <MedalNest items={nestMedals} />
          </div>

          <h2 className="summary-name">{profile.username}</h2>

          <ul className="summary-stats">
            <li>
              <span className="count-value">{convertedValue(profile.xp)}</span>
              <span className="count-label">Miles</span>
            </li>
            <li>
              <span className="count-value">{activities}</span>
              <span className="count-label">Activities</span>
            </li>
            <li>
              <span className="count-value">{profile.level}</span>
              <span className="count-label">Level</span>
            </li>
          </ul>

          {latest && (
            <p className="summary-latest">
              <span className="label">Latest activity</span>
              <span className="summary-latest-line">
                {ACTIVITY_NAMES[latest.activity]}, {formatStart(latest.start_ts)}
              </span>
            </p>
          )}

          <div className="summary-streak">
            <Streak streak={streak} days={days} />
          </div>

          <button type="button" className="row-link" onClick={onOpenLog}>
            Your training log
          </button>
        </section>

        <section className="card">
          <h2 className="label">This week</h2>
          <ul className="week-totals">
            <li>
              <span className="count-value">
                {distanceValue(week.distance, units)}
                <span className="chip-unit">{unitName(units)}</span>
              </span>
              <span className="count-label">Distance</span>
            </li>
            <li>
              <span className="count-value">{Math.round(week.kcal)}</span>
              <span className="count-label">Calories</span>
            </li>
            <li>
              <span className="count-value">{week.workouts}</span>
              <span className="count-label">Workouts</span>
            </li>
          </ul>

          <div className="summary-level">
            <progress
              className="xp-meter"
              value={profile.xp_into_level}
              max={profile.xp_for_next_level}
            >
              {convertedValue(profile.xp_into_level)} of{' '}
              {convertedValue(profile.xp_for_next_level)}
            </progress>
            {/* Miles here as on the You screen. The feed below still counts the
                same number as XP on each card. */}
            <p className="hint summary-xp">
              {convertedValue(profile.xp_into_level)} of{' '}
              {convertedValue(profile.xp_for_next_level)} mi toward level {profile.level + 1}
            </p>
          </div>
        </section>
      </aside>

      <aside className="home-col home-right">
        {/* The phone's copy of the streak. The wide layout shows the one inside
            the summary card instead and hides this. */}
        <section className="card home-streak">
          <Streak streak={streak} days={days} />
          <p className="hint">
            Miles counted this week. Your phone syncs on its own, so nothing here needs
            opening the app.
          </p>
        </section>

        <section className="card home-medals">
          <h2 className="label">Medals</h2>
          <ul className="medal-list">
            {RACE_BADGE_ORDER.map((id) => {
              const count = raceCounts.get(id) ?? 0
              return (
                <li key={id} className={count > 0 ? 'medal-row' : 'medal-row medal-row-none'}>
                  <RaceBadgeMark id={id} earned={count > 0} />
                  <span className="medal-name">{raceBadgeName(id)}</span>
                  <span className="medal-count">{count}</span>
                </li>
              )
            })}
          </ul>
        </section>

        <section className="card home-collection">
          <h2 className="label">Cards</h2>
          <p className="collection-count">
            <span className="count-value">
              {profile.cards.owned} of {profile.cards.total}
            </span>
            <span className="count-label">collected</span>
          </p>
          <button type="button" className="secondary" onClick={onOpenCards}>
            Open cards
          </button>
        </section>
      </aside>

      <div className="home-col home-main">
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

            {workout.has_route && <RouteLine workoutId={workout.id} />}

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

            {/* The strip along the bottom: what the workout was worth, and the
                race badge it earned if it earned one. */}
            {(workout.xp !== undefined || workout.race_badge) && (
              <p className="feed-foot">
                {workout.xp !== undefined && (
                  <span className="feed-xp">+{convertedValue(workout.xp)} XP</span>
                )}
                {workout.race_badge && (
                  <span className="feed-badge">{raceBadgeName(workout.race_badge)}</span>
                )}
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
      </div>
    </div>
  )
}
