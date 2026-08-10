import { useCallback, useEffect, useState } from 'react'
import {
  errorText,
  listWeeks,
  listWorkouts,
  type Units,
  type Week,
  type Workout,
  type WorkoutFlags,
} from '../api.ts'
import {
  formatDistance,
  formatDuration,
  formatStart,
  weekStartKey,
  zonedDay,
} from '../format.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import Icon from './Icon.tsx'
import { MedalChip } from './Medals.tsx'
import RouteLine from './RouteLine.tsx'

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
function flagNotes(flags: WorkoutFlags): string[] {
  const notes: string[] = []
  if (flags.impossible_pace) {
    notes.push(
      'The pace on this one is faster than the server treats as possible, so the numbers may be wrong. It still counts.',
    )
  }
  if (flags.daily_cap) {
    notes.push(
      'This day went past the daily distance limit set for this activity. It still counts.',
    )
  }
  return notes
}

interface Cached {
  workouts: Workout[]
  weeks: Week[]
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
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  const load = useCallback(async () => {
    try {
      const [history, totals] = await Promise.all([
        listWorkouts(WORKOUT_PAGE),
        listWeeks(WEEK_COUNT),
      ])
      cache.set(userId, { workouts: history, weeks: totals })
      setWorkouts(history)
      setWeeks(totals)
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

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
            <div className="week" key={group.key}>
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

              <ul className="workouts">
                {group.workouts.map((workout) => {
                  const notes = flagNotes(workout.flags)
                  return (
                    <li key={workout.id}>
                      <div className="workout-head">
                        <span className="workout-activity">
                          <span className="sport-icon">
                            <Icon name={ACTIVITY_ICONS[workout.activity]} />
                          </span>
                          {ACTIVITY_NAMES[workout.activity]}
                        </span>
                        <span className="muted">{formatStart(workout.start_ts)}</span>
                      </div>
                      {/* What it was called, when it was given a name. Naming
                          one and writing about it happen on its feed card. */}
                      {workout.title && <p className="workout-title">{workout.title}</p>}
                      <div className="workout-body">
                        <span>{formatDistance(workout.distance_mi, units)}</span>
                        <span>{formatDuration(workout.duration_s)}</span>
                        {workout.active_kcal !== null && (
                          <span>{Math.round(workout.active_kcal)} kcal</span>
                        )}
                        {workout.avg_hr !== null && (
                          <span>{Math.round(workout.avg_hr)} bpm</span>
                        )}
                        {/* One chip per medal the workout earned, up to two. */}
                        {(workout.medals ?? []).map((id) => (
                          <MedalChip key={id} id={id} />
                        ))}
                        {workout.source === 'manual' && <span className="tag">Manual</span>}
                        {notes.length > 0 && (
                          <span className="tag tag-flag" title={notes.join(' ')}>
                            Flagged
                          </span>
                        )}
                      </div>
                      {workout.has_route && <RouteLine workoutId={workout.id} compact />}
                      {notes.length > 0 && <p className="flag-note">{notes.join(' ')}</p>}
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })}
      </section>
    </>
  )
}
