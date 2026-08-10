import type { Activity, ActivityStats, Units } from '../api.ts'
import { distanceValue, unitName } from '../format.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import Icon from './Icon.tsx'

interface Props {
  stats: Partial<Record<Activity, ActivityStats>>
  units: Units
}

// Lifetime distance in all four sports, always in the same order and always all
// four, a sport never done reading as zero. Nothing is ranked against anyone
// else here. Shared by the You screen and a friend's profile so the two rows
// read identically.
export default function SportChips({ stats, units }: Props) {
  return (
    <div className="sport-totals">
      <ul className="sport-chips">
        {ACTIVITY_ORDER.map((name) => (
          <li key={name} className="sport-chip">
            {/* The sport's own mark rather than the diamond every chip used to
                wear, so the four chips are told apart at a glance. The word
                underneath is what names it. */}
            <span className="sport-icon">
              <Icon name={ACTIVITY_ICONS[name]} />
            </span>
            <span className="chip-value">
              {distanceValue(stats[name]?.distance_mi ?? 0, units)}
              <span className="chip-unit">{unitName(units)}</span>
            </span>
            <span className="label">{ACTIVITY_NAMES[name]}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
