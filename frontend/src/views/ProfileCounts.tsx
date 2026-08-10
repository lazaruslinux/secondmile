import { MEDAL_ORDER } from '../labels.ts'
import { SEEDS_TO_FIND } from '../profile.ts'

interface Props {
  // Raw miles, summed across the four activities: the distance the account
  // actually covered. The weighted total is XP and is named as such wherever
  // it is shown.
  miles: number
  seeds: number
  plantLevels: number
  medalsOwned: number
}

// The four counts under the level, shared because the You screen and a friend's
// profile show the same four in the same order. Written once so the two cannot
// drift into counting different things.
export default function ProfileCounts({ miles, seeds, plantLevels, medalsOwned }: Props) {
  return (
    <ul className="profile-counts">
      <li>
        <span className="count-value">{miles.toFixed(1)}</span>
        <span className="count-label">Miles</span>
      </li>
      <li>
        <span className="count-value">
          {seeds} / {SEEDS_TO_FIND}
        </span>
        <span className="count-label">Seeds found</span>
      </li>
      <li>
        <span className="count-value">{plantLevels}</span>
        <span className="count-label">Plant levels</span>
      </li>
      <li>
        <span className="count-value">
          {medalsOwned} / {MEDAL_ORDER.length}
        </span>
        <span className="count-label">Medals</span>
      </li>
    </ul>
  )
}
