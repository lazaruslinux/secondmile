import type { Activity, ActivityStats, Units } from '../api.ts'
import { formatDistance } from '../format.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import Icon from './Icon.tsx'

function totalsOf(stats: Partial<Record<Activity, ActivityStats>>) {
  let converted = 0
  let kcal = 0
  let workouts = 0
  for (const row of Object.values(stats)) {
    converted += row.converted_mi
    kcal += row.active_kcal ?? 0
    workouts += row.workouts
  }
  return { converted, kcal, workouts }
}

interface Props {
  stats: Partial<Record<Activity, ActivityStats>>
  units: Units
  empty: string
}

// Calories column drawn only where present: a friend hiding theirs sends rows
// without the figure, and a column of blanks reads as missing data.
export default function Stats({ stats, units, empty }: Props) {
  const rows = ACTIVITY_ORDER.filter((name) => stats[name])
  if (rows.length === 0) return <p className="hint">{empty}</p>
  const totals = totalsOf(stats)
  const showKcal = rows.some((name) => typeof stats[name]?.active_kcal === 'number')

  return (
    <table className="stats">
      <thead>
        <tr>
          <th scope="col">Activity</th>
          <th scope="col">Distance</th>
          {/* The weighted number the game runs on, so a swim and a bike ride
              are worth what they cost rather than what they measure. It is
              called XP everywhere it is shown, because miles on screen mean
              the distance itself. */}
          <th scope="col">XP</th>
          <th scope="col">Workouts</th>
          {showKcal && <th scope="col">Calories</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((name) => {
          const row = stats[name]
          if (!row) return null
          return (
            <tr key={name}>
              <th scope="row">
                <span className="sport-icon sport-icon-small">
                  <Icon name={ACTIVITY_ICONS[name]} />
                </span>
                {ACTIVITY_NAMES[name]}
              </th>
              <td>{formatDistance(row.distance_mi, units)}</td>
              <td>{row.converted_mi.toFixed(1)}</td>
              <td>{row.workouts}</td>
              {showKcal && <td>{Math.round(row.active_kcal ?? 0)}</td>}
            </tr>
          )
        })}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Total</th>
          <td />
          <td>{totals.converted.toFixed(1)}</td>
          <td>{totals.workouts}</td>
          {showKcal && <td>{Math.round(totals.kcal)}</td>}
        </tr>
      </tfoot>
    </table>
  )
}
