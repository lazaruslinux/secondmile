import { useCallback, useEffect, useState } from 'react'
import {
  avatarUrl,
  errorText,
  getProfile,
  listFeed,
  listGrove,
  type FeedItem,
  type Medal,
  type Planting,
  type Profile as ProfileData,
  type Units,
} from '../api.ts'
import {
  convertedValue,
  distanceValue,
  formatShortDate,
  formatStart,
  unitName,
} from '../format.ts'
import { plantStage } from '../grove.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, medalName, plantingName } from '../labels.ts'
import {
  displayNameOf,
  lifetimeMiles,
  lifetimeWorkouts,
  medalCountsOf,
  nextWeeklyTarget,
  starsFor,
  weekTotals,
} from '../profile.ts'
import AvatarFrame from './AvatarFrame.tsx'
import FeedCard from './FeedCard.tsx'
import Icon from './Icon.tsx'
import MedalNest from './MedalNest.tsx'
import { MedalMark } from './Medals.tsx'
import PlantArt from './PlantArt.tsx'

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

// The width the side rails appear at, written exactly as the stylesheet writes
// its own breakpoint. The two are separate copies of one number and have to
// flip together, so neither is changed without the other.
const WIDE = '(min-width: 900px)'

// Which arrangement this screen is wide enough for. The rail and the phone's
// streak card hold the same components, so this chooses where they are put
// rather than which of two copies is shown: nothing is drawn twice.
function useWide(): boolean {
  const [wide, setWide] = useState(() => window.matchMedia(WIDE).matches)
  useEffect(() => {
    const query = window.matchMedia(WIDE)
    // Read again on the way in, in case the window changed between the first
    // read and this line.
    setWide(query.matches)
    const onChange = (event: MediaQueryListEvent) => setWide(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])
  return wide
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

// No days at all, which is what an account with a quiet week has and also what
// a server that predates week_days says.
const NO_DAYS = [false, false, false, false, false, false, false]

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

// What came in lately rather than the whole catalogue: the catalogue is a
// screen of its own on You, and this much room is better spent on what has just
// happened. Written once and put in the rail on a wide screen or in the streak
// card on a phone, so the two arrangements can never say different things.
function RecentMedals({ recent }: { recent: Recent[] }) {
  return (
    <>
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
    </>
  )
}

// The next weekly medal and how far into it this week is, on the same terms as
// the medals above: one place, two homes. The distance is raw miles, which is
// what the medal is measured in; showing XP here would name a number the server
// never counts a week in.
function Challenge({ distance, counts }: { distance: number; counts: Map<string, number> }) {
  const target = nextWeeklyTarget(distance)
  return (
    <>
      <h2 className="label">Challenges</h2>
      {target ? (
        <>
          <div className="challenge">
            <MedalMark id={target.id} earned={(counts.get(target.id) ?? 0) > 0} />
            <div className="challenge-text">
              <p className="challenge-name">{medalName(target.id)}</p>
              <p className="challenge-progress">
                {distance.toFixed(1)} of {target.miles} mi
              </p>
            </div>
          </div>
          <progress className="xp-meter" value={distance} max={target.miles}>
            {distance.toFixed(1)} of {target.miles} mi
          </progress>
        </>
      ) : (
        /* Past forty miles there is no rung left this week, so the section says
           what was done rather than inventing a target above the ladder. */
        <p className="challenge-done">
          Every weekly medal earned this week, at {distance.toFixed(1)} mi.
        </p>
      )}
    </>
  )
}

// The plot in miniature: the band's row of plants, a plain count off the mature
// flag, and the way through to where they are tended. Shown only in the wide
// rail; the phone reaches the grove from its tab bar, so this is never folded in
// below like the two cards above it.
function GrovePreview({
  plantings,
  onOpenGrove,
}: {
  plantings: Planting[]
  onOpenGrove: () => void
}) {
  const grown = plantings.filter((row) => row.mature).length
  const growing = plantings.length - grown
  return (
    <>
      <h2 className="label">Grove</h2>
      {plantings.length === 0 ? (
        <p className="hint">Nothing planted yet. Seeds come out of chests.</p>
      ) : (
        <>
          {/* The same tiles the You band draws, at the same stage: one plant per
              species, so the row stays short enough to wrap inside the card. */}
          <ul className="grove-preview">
            {plantings.map((row) => (
              <li
                key={row.id}
                className={row.mature ? 'band-plant band-plant-grown' : 'band-plant'}
              >
                <PlantArt
                  species={row.species}
                  name={plantingName(row)}
                  stage={plantStage(row)}
                  gilded={row.gilded}
                />
              </li>
            ))}
          </ul>
          <p className="hint">
            {growing} growing, {grown} grown
          </p>
        </>
      )}
      <button type="button" className="row-link" onClick={onOpenGrove}>
        Open the grove
      </button>
    </>
  )
}

interface Cached {
  profile: ProfileData
  feed: FeedItem[]
  done: boolean
  // Null until the plot has loaded once, so a card that has never loaded (or
  // whose fetch failed) can be told apart from an empty plot and left undrawn.
  grove: Planting[] | null
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
  // A friend's card goes to their screen. Own cards ignore it, which is what
  // keeps your own rows from being a way back to the screen you came from.
  onOpenPerson: (userId: number) => void
}

export default function Home({
  userId,
  units,
  refreshToken,
  onOpenLog,
  onOpenGrove,
  onOpenProfile,
  onOpenPerson,
}: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [profile, setProfile] = useState<ProfileData | null>(
    () => cache.get(userId)?.profile ?? null,
  )
  const [feed, setFeed] = useState<FeedItem[]>(() => cache.get(userId)?.feed ?? [])
  const [done, setDone] = useState(() => cache.get(userId)?.done ?? false)
  const [grove, setGrove] = useState<Planting[] | null>(() => cache.get(userId)?.grove ?? null)
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')
  const [moreBusy, setMoreBusy] = useState(false)
  const [moreError, setMoreError] = useState('')
  const wide = useWide()

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
    // The rail's grove card is a nicety, not the page: a plot that will not load
    // leaves the card undrawn rather than taking the feed down with it.
    try {
      setGrove(await listGrove())
    } catch {
      // Left as it was. A first-load failure keeps it null, so the card never draws.
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  useEffect(() => {
    if (profile) cache.set(userId, { profile, feed, done, grove })
  }, [userId, profile, feed, done, grove])

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
  // From the profile, which is where the streak beside it comes from too. It
  // used to be worked out from the first page of the feed, which meant a week
  // whose earlier days had scrolled off the page lost its diamonds, and a
  // browser in another timezone put them on the wrong days.
  const days = profile.week_days ?? NO_DAYS
  const week = weekTotals(profile)
  const activities = lifetimeWorkouts(profile)
  // The summary card is about this account, so the line under it names this
  // account's last workout rather than whatever is at the top of the feed.
  const mine = feed.find((item) => item.own)
  const counts = medalCountsOf(profile.medals)
  const recent = recentMedals(profile.medals)
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
              {/* Raw miles, the same number the You screen leads with: what the
                  body covered rather than what the game weighted it at. */}
              <span className="count-value">{lifetimeMiles(profile).toFixed(1)}</span>
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
                {/* The same mark every other activity in the app wears. This
                    line was the last one naming a sport without one. */}
                <span className="sport-icon sport-icon-small">
                  <Icon name={ACTIVITY_ICONS[mine.activity]} />
                </span>
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
              {convertedValue(profile.xp_for_next_level)} XP
            </progress>
            {/* XP here as on the You screen, since the level is climbed on the
                weighted number. The miles tile above is the raw distance. */}
            <p className="hint summary-xp">
              {convertedValue(profile.xp_into_level)} of{' '}
              {convertedValue(profile.xp_for_next_level)} XP toward level {profile.level + 1}
            </p>
          </div>
        </section>
      </aside>

      <aside className="home-col home-right">
        {/* The phone's copy of the streak, and on a phone the only card this
            column has: the wide layout shows the streak inside the summary card
            instead and hides this one. */}
        <section className="card home-streak">
          <Streak streak={streak} days={days} />
          <p className="hint">
            Miles counted this week. Your phone syncs on its own, so nothing here needs
            opening the app.
          </p>
          {/* There is no rail on a phone, so what the rail holds is folded in
              here under a rule rather than lost. */}
          {!wide && (
            <>
              <div className="streak-fold">
                <RecentMedals recent={recent} />
              </div>
              <div className="streak-fold">
                <Challenge distance={week.distance} counts={counts} />
              </div>
            </>
          )}
        </section>

        {/* The same two blocks with room to be cards of their own. Only the
            arrangement differs, which is why they are rendered here rather than
            written out a second time. */}
        {wide && (
          <>
            <section className="card">
              <RecentMedals recent={recent} />
            </section>
            <section className="card">
              <Challenge distance={week.distance} counts={counts} />
            </section>
            {/* Last in the rail, after the two above. Only once the plot has
                loaded: a fetch that never returned leaves grove null and the
                card unwritten. */}
            {grove && (
              <section className="card">
                <GrovePreview plantings={grove} onOpenGrove={onOpenGrove} />
              </section>
            )}
          </>
        )}
      </aside>

      <div className="home-col home-main">
        {/* Names the column it heads. One label for both arrangements: the
            streak card is ordered above this wrapper on a phone, so it lands
            under the streak there and over the middle column on a wide
            screen. */}
        <p className="label home-feed-label">Feed</p>

        {loadError && (
          <p className="error" role="alert">
            {loadError}
          </p>
        )}

        {feed.length === 0 && !loadError && (
          <p className="notice">Nothing recorded yet. Your next sync fills this in.</p>
        )}

        {feed.map((item) => (
          <FeedCard
            key={item.workout_id}
            item={item}
            units={units}
            avatarVersion={profile.avatar_version}
            onChanged={cardChanged}
            onOpenPerson={onOpenPerson}
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
