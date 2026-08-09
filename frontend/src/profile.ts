// Things read off a profile that more than one screen needs. Home shows a short
// form of the You screen in its side column, so the rules for what appears there
// are written once here rather than twice in the views.

import type { Medal, Profile } from './api.ts'
import { chestName } from './labels.ts'

// How many seeds there are to find. The species outside the catalogue is not
// counted, on the server or here, so this never reads as one more than twelve.
export const SEEDS_TO_FIND = 12

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
// sum of them, so the adding up happens here. distance is raw miles: what the
// body covered, not the game's weighted Miles.
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

// The weekly medals and the raw miles each one is earned at, which is the
// server's ladder written down a second time so a target can be shown before
// it is reached. Raw miles, never converted Miles: a week is twenty-five miles
// walked, run, ridden or swum, and no conversion rate has any business changing
// what it is.
const WEEKLY_TARGETS: { id: string; miles: number }[] = [
  { id: 'weekly_10', miles: 10 },
  { id: 'weekly_15', miles: 15 },
  { id: 'weekly_25', miles: 25 },
  { id: 'weekly_40', miles: 40 },
]

// The next weekly medal a week is working toward, given its raw miles so far.
// Null once all four are behind it, which is a week with nothing left to aim
// at rather than a week with no answer.
export function nextWeeklyTarget(rawMiles: number): { id: string; miles: number } | null {
  return WEEKLY_TARGETS.find((row) => rawMiles < row.miles) ?? null
}
