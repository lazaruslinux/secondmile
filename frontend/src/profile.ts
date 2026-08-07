// Things read off a profile that more than one screen needs. Home shows a short
// form of the You screen in its side column, so the rules for what appears there
// are written once here rather than twice in the views.

import type { Activity, Medal, Profile } from './api.ts'
import { ACTIVITY_ORDER, chestName } from './labels.ts'

// How many sports get a diamond. The server enforces the same number.
export const MAX_DIAMONDS = 3

// One star for every fifty earnings of the same medal, and never more than
// thirty three of them. Nothing about the stars comes from the server: they are
// the count read a second way, so the two can never disagree.
export const EARNS_PER_STAR = 50
export const MAX_STARS = 33

export function starsFor(count: number): number {
  if (!(count > 0)) return 0
  return Math.min(MAX_STARS, Math.floor(count / EARNS_PER_STAR))
}

// The name on the profile header, or nothing at all. The server composes it;
// where it has not, the two halves are put together here so a profile just
// saved reads right before the next fetch lands.
export function displayNameOf(profile: Profile): string {
  const given = profile.display_name?.trim()
  if (given) return given
  return [profile.first_name, profile.last_name]
    .map((part) => part?.trim() ?? '')
    .filter((part) => part !== '')
    .join(' ')
}

// Whole years since a birthdate, worked out here only when the server has not
// done it. Nothing is stored either way: an age that was stored would be wrong
// by tomorrow.
export function ageOf(profile: Profile): number | null {
  if (typeof profile.age === 'number') return profile.age
  const born = profile.birthdate
  if (!born) return null
  const date = new Date(`${born}T00:00:00`)
  if (isNaN(date.getTime())) return null
  const now = new Date()
  let years = now.getFullYear() - date.getFullYear()
  const month = now.getMonth() - date.getMonth()
  if (month < 0 || (month === 0 && now.getDate() < date.getDate())) years -= 1
  return years >= 0 && years < 150 ? years : null
}

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

// How many times each medal has been earned, by medal id. A server that
// predates the field reads as none of everything.
export function medalCountsOf(medals: Medal[] | undefined): Map<string, number> {
  return new Map((medals ?? []).map((row) => [row.id, row.count ?? 0]))
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
