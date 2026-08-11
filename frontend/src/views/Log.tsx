import { useCallback, useEffect, useState } from 'react'
import {
  errorText,
  getProfile,
  listWeeks,
  listWorkouts,
  type FeedItem,
  type Units,
  type Week,
  type Workout,
  type WorkoutFlags,
} from '../api.ts'
import { formatDistance, weekStartKey, zonedDay } from '../format.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import FeedCard from './FeedCard.tsx'
import Icon from './Icon.tsx'

const WORKOUT_PAGE = 50
const WEEK_COUNT = 8

// The Monday that starts a workout's week, read in the instance's zone, which
// is the zone the weekly totals below it were added up in.
function weekKeyOf(iso: string): string {
  return weekStartKey(zonedDay(iso))
}

// A plain calendar date rather than a moment, so no zone comes into it: the
// date is built and read in the same one.
function formatWeekStart(key: string): string {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
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

interface Cached {
  workouts: Workout[]
  weeks: Week[]
  avatarVersion: number | null
}

// What this tab last showed, kept by account so a second person signing in on
// the same browser never sees the first one's history. It lives as long as the
// page does and no longer.
const cache = new Map<number, Cached>()

interface Props {
  userId: number
  units: Units
}

export default function Log({ userId, units }: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [workouts, setWorkouts] = useState<Workout[]>(() => cache.get(userId)?.workouts ?? [])
  const [weeks, setWeeks] = useState<Week[]>(() => cache.get(userId)?.weeks ?? [])
  // Only ever used to address your own picture, so a new one shows here as soon
  // as it shows anywhere else.
  const [avatarVersion, setAvatarVersion] = useState<number | null>(
    () => cache.get(userId)?.avatarVersion ?? null,
  )
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  const load = useCallback(async () => {
    try {
      const [history, totals, mine] = await Promise.all([
        listWorkouts(WORKOUT_PAGE),
        listWeeks(WEEK_COUNT),
        getProfile(),
      ])
      setWorkouts(history)
      setWeeks(totals)
      setAvatarVersion(mine.avatar_version)
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // Kept from what is on screen rather than from what arrived, so a card edited
  // here is still edited after a trip to another tab. A load that failed writes
  // nothing, so a first visit that went wrong still says Loading on the next.
  useEffect(() => {
    if (!loading && loadError === '') cache.set(userId, { workouts, weeks, avatarVersion })
  }, [userId, workouts, weeks, avatarVersion, loading, loadError])

  // An edited card is put back where it sat, flags and all: the panel hands
  // back the feed's part of the row and the rest of it is already here.
  const cardChanged = useCallback((updated: FeedItem) => {
    setWorkouts((current) =>
      current.map((row) =>
        row.workout_id === updated.workout_id ? { ...row, ...updated } : row,
      ),
    )
  }, [])

  const totalsByWeek = new Map(weeks.map((week) => [week.week_start.slice(0, 10), week]))

  // The history arrives newest first, so walking it in order produces the week
  // groups newest first as well.
  const groups: { key: string; workouts: Workout[] }[] = []
  for (const workout of workouts) {
    const key = weekKeyOf(workout.start_ts)
    const current = groups[groups.length - 1]
    if (current && current.key === key) current.workouts.push(workout)
    else groups.push({ key, workouts: [workout] })
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">Log</h1>
      </div>

      <section>
        <h2>History</h2>
        {loading && <p className="notice">Loading.</p>}
        {loadError && (
          <p className="error" role="alert">
            {loadError}
          </p>
        )}
        {!loading && !loadError && groups.length === 0 && (
          <p className="notice">Nothing recorded yet. Your next sync fills this in.</p>
        )}

        {groups.map((group) => {
          const totals = totalsByWeek.get(group.key)
          return (
            <div className="log-week" key={group.key}>
              <div className="week">
                <h3>Week of {formatWeekStart(group.key)}</h3>

                {totals && (
                  <ul className="totals">
                    {ACTIVITY_ORDER.map((name) => {
                      const total = totals.activities[name]
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
                      <span>{Math.round(totals.total_active_kcal)} kcal</span>
                    </li>
                  </ul>
                )}
              </div>

              {/* The same card the feed draws, because it is the same workout:
                  naming one, writing about it, and adding pictures happen here
                  as well now, rather than only on the home screen. */}
              {group.workouts.map((workout) => (
                <FeedCard
                  key={workout.workout_id}
                  item={workout}
                  units={units}
                  avatarVersion={avatarVersion}
                  onChanged={cardChanged}
                  note={flagNotes(workout.flags)}
                />
              ))}
            </div>
          )
        })}
      </section>
    </>
  )
}
