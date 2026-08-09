import { useCallback, useEffect, useState } from 'react'
import {
  avatarUrl,
  errorText,
  getProfile,
  listFeed,
  type FeedItem,
  type Medal,
  type Profile as ProfileData,
  type Units,
} from '../api.ts'
import {
  convertedValue,
  distanceValue,
  formatShortDate,
  formatStart,
  unitName,
  weekStartKey,
  zonedDay,
} from '../format.ts'
import { ACTIVITY_NAMES, medalName } from '../labels.ts'
import {
  displayNameOf,
  lifetimeWorkouts,
  medalCountsOf,
  nextWeeklyTarget,
  SEEDS_TO_FIND,
  starsFor,
  weekTotals,
} from '../profile.ts'
import AvatarFrame from './AvatarFrame.tsx'
import FeedCard from './FeedCard.tsx'
import Icon from './Icon.tsx'
import MedalNest from './MedalNest.tsx'
import { MedalMark } from './Medals.tsx'

const PAGE = 20

// How many medals the rail looks back over. Four rather than three: the whole
// catalogue used to stand here, and three rows leave the card shorter than the
// two under it.
const RECENT_MEDALS = 4

interface Recent {
  id: string
  count: number
  // When it last came. The list holds only medals that have one, so this is a
  // date rather than a maybe.
  at: string
}

// The medals earned most lately, newest first. Types rather than earnings: a
// medal won three times this week is one row, dated the last time it came. The
// profile already carries the dates, so the rail asks the server for nothing.
function recentMedals(medals: Medal[] | undefined): Recent[] {
  const earned: Recent[] = []
  for (const row of medals ?? []) {
    const at = row.last_earned_at
    if (!at || !(row.count > 0)) continue
    earned.push({ id: row.id, count: row.count, at })
  }
  earned.sort((first, second) => Date.parse(second.at) - Date.parse(first.at))
  return earned.slice(0, RECENT_MEDALS)
}

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

// Which days of this week already have something on them. Own rows only: the
// streak counts this account's miles, never anybody else's. Days and weeks are
// read in the instance's zone, which is the zone the server counted them in.
function daysThisWeek(feed: FeedItem[]): boolean[] {
  const days = [false, false, false, false, false, false, false]
  const monday = weekStartKey(zonedDay(new Date()))
  for (const item of feed) {
    if (!item.own) continue
    const day = zonedDay(item.start_ts)
    if (weekStartKey(day) !== monday) continue
    days[day.weekday] = true
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
  feed: FeedItem[]
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
  onOpenGrove: () => void
  onOpenProfile: () => void
}

export default function Home({
  userId,
  units,
  refreshToken,
  onOpenLog,
  onOpenGrove,
  onOpenProfile,
}: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [profile, setProfile] = useState<ProfileData | null>(
    () => cache.get(userId)?.profile ?? null,
  )
  const [feed, setFeed] = useState<FeedItem[]>(() => cache.get(userId)?.feed ?? [])
  const [done, setDone] = useState(() => cache.get(userId)?.done ?? false)
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')
  const [moreBusy, setMoreBusy] = useState(false)
  const [moreError, setMoreError] = useState('')

  const load = useCallback(async () => {
    try {
      const [mine, events] = await Promise.all([getProfile(), listFeed()])
      setProfile(mine)
      setFeed(events)
      setDone(events.length < PAGE)
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
    if (profile) cache.set(userId, { profile, feed, done })
  }, [userId, profile, feed, done])

  // An edited card is put back where it sat. The cache is written from this
  // state, so what was changed is still there when the tab is come back to.
  const cardChanged = useCallback((updated: FeedItem) => {
    setFeed((current) =>
      current.map((row) => (row.workout_id === updated.workout_id ? updated : row)),
    )
  }, [])

  async function loadMore() {
    const last = feed[feed.length - 1]
    if (!last) return
    setMoreBusy(true)
    setMoreError('')
    try {
      const next = await listFeed(last.start_ts)
      // The cursor is exclusive, so a repeat is not expected; filtering by id
      // anyway means a change under our feet cannot draw the same card twice.
      setFeed((current) => {
        const held = new Set(current.map((row) => row.workout_id))
        return [...current, ...next.filter((row) => !held.has(row.workout_id))]
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
  const days = daysThisWeek(feed)
  const week = weekTotals(profile)
  const activities = lifetimeWorkouts(profile)
  // The summary card is about this account, so the line under it names this
  // account's last workout rather than whatever is at the top of the feed.
  const mine = feed.find((item) => item.own)
  const counts = medalCountsOf(profile.medals)
  const recent = recentMedals(profile.medals)
  // Raw miles, the unit the weekly medals are earned in, whatever this account
  // displays distances as.
  const target = nextWeeklyTarget(week.distance)
  const shownName = displayNameOf(profile)
  // Own growth stage, from the profile when the server puts it there and from
  // this account's own feed row when it does not.
  const flourish = profile.flourish ?? mine?.user.flourish ?? 0

  // Three columns from 900px up and one below it. The columns are wrappers
  // rather than a reordering, so the phone still draws the streak, then the
  // feed, in the order they are written.
  return (
    <div className="home">
      <aside className="home-col home-left">
        <section className="card summary">
          {/* The picture and the name are the way to the You screen, which is
              where everything under them is said at length. */}
          <button type="button" className="summary-identity" onClick={onOpenProfile}>
            <AvatarFrame
              name={shownName || profile.username}
              src={
                profile.has_avatar ? avatarUrl(profile.user_id, profile.avatar_version) : null
              }
              borderTier={profile.border_tier}
              flourish={flourish}
              frameClass="summary-frame"
              labelled
            >
              {/* The same field the You screen draws from, drawn the same way,
                  so the two never show a different set. */}
              <MedalNest ids={profile.displayed_badges} />
            </AvatarFrame>

            <h2 className="summary-name">{shownName || profile.username}</h2>
            {shownName !== '' && <p className="summary-username">{profile.username}</p>}
          </button>

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

          {mine && (
            <p className="summary-latest">
              <span className="label">Latest activity</span>
              <span className="summary-latest-line">
                {ACTIVITY_NAMES[mine.activity]}, {formatStart(mine.start_ts)}
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

        {/* What came in lately rather than the whole catalogue: the catalogue
            is a screen of its own on You, and a rail is better spent on what
            has just happened. The rows are tighter here than the strip there. */}
        <section className="card home-medals">
          <h2 className="label">Recent medals</h2>
          {recent.length === 0 ? (
            <p className="hint">
              Nothing earned yet. A 5K, a ten-mile week, or a run before six all start one.
            </p>
          ) : (
            <ul className="medal-list">
              {recent.map((row) => (
                <li key={row.id} className="medal-row">
                  <MedalMark id={row.id} earned stars={starsFor(row.count)} />
                  <span className="medal-name">{medalName(row.id)}</span>
                  <span className="medal-when">{formatShortDate(row.at)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* The next weekly medal and how far into it this week is. Raw miles,
            which is what the medal is measured in: showing converted Miles here
            would name a number the server never counts a week in. */}
        <section className="card home-challenges">
          <h2 className="label">Challenges</h2>
          {target ? (
            <>
              <div className="challenge">
                <MedalMark id={target.id} earned={(counts.get(target.id) ?? 0) > 0} />
                <div className="challenge-text">
                  <p className="challenge-name">{medalName(target.id)}</p>
                  <p className="challenge-progress">
                    {week.distance.toFixed(1)} of {target.miles} mi
                  </p>
                </div>
              </div>
              <progress className="xp-meter" value={week.distance} max={target.miles}>
                {week.distance.toFixed(1)} of {target.miles} mi
              </progress>
            </>
          ) : (
            /* Past forty miles there is no rung left this week, so the section
               says what was done rather than inventing a target above the
               ladder. */
            <p className="challenge-done">
              Every weekly medal earned this week, at {week.distance.toFixed(1)} mi.
            </p>
          )}
        </section>

        <section className="card home-grove">
          <h2 className="label">Grove</h2>
          <ul className="grove-counts">
            <li>
              <span className="count-value">
                {profile.grove?.seeds_found ?? 0} / {SEEDS_TO_FIND}
              </span>
              <span className="count-label">Seeds found</span>
            </li>
            <li>
              <span className="count-value">{profile.grove?.plant_levels ?? 0}</span>
              <span className="count-label">Plant levels</span>
            </li>
          </ul>
          {/* The plot and the inventory are both on the Grove screen, so one
              way in is the whole of what this card owes them. */}
          <button type="button" className="secondary" onClick={onOpenGrove}>
            Open grove
          </button>
        </section>
      </aside>

      <div className="home-col home-main">
        {loadError && (
          <p className="error" role="alert">
            {loadError}
          </p>
        )}

        {feed.length === 0 && !loadError && (
          <p className="notice">Nothing recorded yet. Sync your phone or add a workout in Log.</p>
        )}

        {feed.map((item) => (
          <FeedCard
            key={item.workout_id}
            item={item}
            units={units}
            avatarVersion={profile.avatar_version}
            onChanged={cardChanged}
          />
        ))}

        {moreError && (
          <p className="error" role="alert">
            {moreError}
          </p>
        )}

        {feed.length > 0 && !done && (
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
