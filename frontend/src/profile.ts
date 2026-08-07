// Things read off a profile that more than one screen needs. Home shows a short
// form of the You screen in its side column, so the rules for what appears there
// are written once here rather than twice in the views.

import type { Activity, Profile, RaceBadge } from './api.ts'
import { ACTIVITY_ORDER, chestName } from './labels.ts'

// How many sports get a diamond. The server enforces the same number.
export const MAX_DIAMONDS = 3

// Which sports get a diamond. The server sends the effective list; a server that
// predates the field leaves the same choice to be made here, which is the three
// sports with the most lifetime distance behind them.
export function diamondsOf(profile: Profile): Activity[] {
  if (profile.diamond_sports) return profile.diamond_sports.slice(0, MAX_DIAMONDS)
  return ACTIVITY_ORDER.filter((name) => (profile.lifetime[name]?.distance_mi ?? 0) > 0)
    .sort(
      (left, right) =>
        (profile.lifetime[right]?.distance_mi ?? 0) - (profile.lifetime[left]?.distance_mi ?? 0),
    )
    .slice(0, MAX_DIAMONDS)
}

// How many times each race distance has been run, by badge id. A server that
// predates the field, or a recap entry that carries no count, reads as none.
export function raceCountsOf(badges: RaceBadge[] | undefined): Map<string, number> {
  return new Map((badges ?? []).map((row) => [row.id, row.count ?? 0]))
}

// How many workouts are behind an account, across every activity. The profile
// counts them per activity and never totals them.
export function lifetimeWorkouts(profile: Profile): number {
  let count = 0
  for (const row of Object.values(profile.lifetime)) count += row.workouts
  return count
}

// The one line about the chest on its way, or nothing at all. Nothing is the
// ordinary answer against a server that does not say how far off the next one
// is: a made-up distance would be worse than no line.
export function nextChestLine(profile: Profile): string {
  const tier = profile.next_chest?.tier ?? profile.next_chest_tier
  const away =
    profile.next_chest?.miles_away ?? profile.next_chest?.mi_away ?? profile.next_chest_mi
  if (typeof away !== 'number' || !isFinite(away) || away < 0) return ''
  return `${chestName(tier)}, ${away.toFixed(1)} mi away`
}

// This week across every activity. The profile carries per-activity rows and no
// sum of them, so the adding up happens here.
export function weekTotals(profile: Profile) {
  let distance = 0
  let kcal = 0
  let workouts = 0
  for (const row of Object.values(profile.week)) {
    distance += row.distance_mi
    kcal += row.active_kcal
    workouts += row.workouts
  }
  return { distance, kcal, workouts }
}
