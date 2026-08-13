import { SEEDS_TO_FIND } from '../profile.ts'

interface Props {
  // Raw miles, summed across the four activities: the distance the account
  // actually covered. The weighted total is XP and is named as such wherever
  // it is shown.
  miles: number
  activities: number
  level: number
  medalsEarned: number
}

// The four color-coded chips under the level, shared because the You screen
// and a friend's profile show the same four in the same order. Written once so
// the two cannot drift into counting different things. Colors are the chips'
// own and deliberately not crimson: these are facts, never flags.
export default function ProfileCounts({ miles, activities, level, medalsEarned }: Props) {
  return (
    <div className="stat-chips-box">
    <ul className="stat-chips">
      <li className="stat-chip chip-miles">
        <span className="count-value">{miles.toFixed(1)}</span>
        <span className="count-label">Miles</span>
      </li>
      <li className="stat-chip chip-activities">
        <span className="count-value">{activities}</span>
        <span className="count-label">Activities</span>
      </li>
      <li className="stat-chip chip-level">
        <span className="count-value">{level}</span>
        <span className="count-label">Level</span>
      </li>
      <li className="stat-chip chip-medals">
        <span className="count-value">{medalsEarned.toLocaleString()}</span>
        <span className="count-label">Medals earned</span>
      </li>
    </ul>
    </div>
  )
}

// The two grove counts that used to sit with the chips. They live beside the
// grove band now: they are facts about the plants, not about the person.
export function GroveTallies({ seeds, plantLevels }: { seeds: number; plantLevels: number }) {
  return (
    <p className="grove-tallies">
      Seeds found {seeds} / {SEEDS_TO_FIND} &middot; Plant levels {plantLevels}
    </p>
  )
}
