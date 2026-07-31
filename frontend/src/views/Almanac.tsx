import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  createWorkout,
  listWeeks,
  listWorkouts,
  type Activity,
  type Units,
  type Week,
  type Workout,
  type WorkoutFlags,
} from '../api.ts'
import { formatDistance, KM_PER_MILE, unitName } from '../format.ts'
import { ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'

const WORKOUT_PAGE = 50
const WEEK_COUNT = 8

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours > 0 ? `${hours}h ${pad(minutes)}m` : `${minutes}m`
}

function formatStart(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function localDateInput(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

// The Monday that starts a workout's week, in the browser's timezone. The
// server groups by its own timezone; the two agree unless a workout sits within
// a few hours of a week boundary.
function weekKeyOf(iso: string): string {
  const date = new Date(iso)
  date.setHours(0, 0, 0, 0)
  date.setDate(date.getDate() - ((date.getDay() + 6) % 7))
  return localDateInput(date)
}

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

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Try again.'
}

interface Props {
  units: Units
}

export default function Almanac({ units }: Props) {
  const [workouts, setWorkouts] = useState<Workout[]>([])
  const [weeks, setWeeks] = useState<Week[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [activity, setActivity] = useState<Activity>('walk')
  const [start, setStart] = useState(() => {
    const now = new Date()
    return `${localDateInput(now)}T${pad(now.getHours())}:${pad(now.getMinutes())}`
  })
  const [minutes, setMinutes] = useState('')
  const [distance, setDistance] = useState('')
  const [calories, setCalories] = useState('')
  const [heartRate, setHeartRate] = useState('')
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [formNote, setFormNote] = useState('')

  const load = useCallback(async () => {
    try {
      const [history, totals] = await Promise.all([
        listWorkouts(WORKOUT_PAGE),
        listWeeks(WEEK_COUNT),
      ])
      setWorkouts(history)
      setWeeks(totals)
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

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setFormError('')
    setFormNote('')
    const entered = Number(distance)
    try {
      await createWorkout({
        activity,
        start_ts: new Date(start).toISOString(),
        duration_s: Math.round(Number(minutes) * 60),
        distance_mi: units === 'metric' ? entered / KM_PER_MILE : entered,
        ...(calories === '' ? {} : { active_kcal: Number(calories) }),
        ...(heartRate === '' ? {} : { avg_hr: Number(heartRate) }),
      })
      setMinutes('')
      setDistance('')
      setCalories('')
      setHeartRate('')
      setFormNote('Added to the Almanac.')
      await load()
    } catch (err) {
      // The server identifies a workout by who, when, and how long, so a 409
      // means this one is already recorded rather than that anything failed.
      setFormError(
        err instanceof ApiError && err.status === 409
          ? 'That workout is already in the Almanac. Nothing was added.'
          : errorText(err),
      )
    } finally {
      setSaving(false)
    }
  }

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
      <section className="card">
        <h2>Add a workout</h2>
        <p className="hint">For anything your phone did not sync.</p>
        <form onSubmit={submit}>
          <div className="field-row">
            <label>
              Activity
              <select
                value={activity}
                onChange={(event) => setActivity(event.target.value as Activity)}
              >
                {ACTIVITY_ORDER.map((name) => (
                  <option key={name} value={name}>
                    {ACTIVITY_NAMES[name]}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Date and time
              <input
                type="datetime-local"
                value={start}
                onChange={(event) => setStart(event.target.value)}
                required
              />
            </label>
          </div>

          <div className="field-row">
            <label>
              Duration (minutes)
              <input
                type="number"
                inputMode="decimal"
                min="1"
                step="1"
                value={minutes}
                onChange={(event) => setMinutes(event.target.value)}
                required
              />
            </label>

            <label>
              Distance ({unitName(units)})
              <input
                type="number"
                inputMode="decimal"
                min="0"
                step="0.01"
                value={distance}
                onChange={(event) => setDistance(event.target.value)}
                required
              />
            </label>
          </div>

          <div className="field-row">
            <label>
              Active calories (optional)
              <input
                type="number"
                inputMode="numeric"
                min="0"
                step="1"
                value={calories}
                onChange={(event) => setCalories(event.target.value)}
              />
            </label>

            <label>
              Average heart rate (optional)
              <input
                type="number"
                inputMode="numeric"
                min="0"
                step="1"
                value={heartRate}
                onChange={(event) => setHeartRate(event.target.value)}
              />
            </label>
          </div>

          {formError && (
            <p className="error" role="alert">
              {formError}
            </p>
          )}
          {formNote && <p className="note">{formNote}</p>}

          <button type="submit" className="primary" disabled={saving}>
            Add workout
          </button>
        </form>
      </section>

      <section>
        <h2>History</h2>
        {loading && <p className="notice">Loading.</p>}
        {loadError && (
          <p className="error" role="alert">
            {loadError}
          </p>
        )}
        {!loading && !loadError && groups.length === 0 && (
          <p className="notice">
            Nothing recorded yet. Sync your phone or add a workout above.
          </p>
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
                        <span className="totals-activity">{ACTIVITY_NAMES[name]}</span>
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
                          {ACTIVITY_NAMES[workout.activity]}
                        </span>
                        <span className="muted">{formatStart(workout.start_ts)}</span>
                      </div>
                      <div className="workout-body">
                        <span>{formatDistance(workout.distance_mi, units)}</span>
                        <span>{formatDuration(workout.duration_s)}</span>
                        {workout.active_kcal !== null && (
                          <span>{Math.round(workout.active_kcal)} kcal</span>
                        )}
                        {workout.avg_hr !== null && (
                          <span>{Math.round(workout.avg_hr)} bpm</span>
                        )}
                        {workout.source === 'manual' && <span className="tag">Manual</span>}
                        {notes.length > 0 && (
                          <span className="tag tag-flag" title={notes.join(' ')}>
                            Flagged
                          </span>
                        )}
                      </div>
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
