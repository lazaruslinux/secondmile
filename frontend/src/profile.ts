// Things read off a profile that more than one screen needs. Home shows a short
// form of the You screen in its side column, so the rules for what appears there
// are written once here rather than twice in the views.

import type { Medal, Profile } from './api.ts'
import { CHEST_TIER_ORDER, chestName } from './labels.ts'

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

// What each step of the ladder costs, in XP. Written down here rather than
// asked for because the steps are named after the distances: a 5K step is a 5K.
// The order itself is the labels' business and is not repeated.
const STEP_XP: Record<string, number> = {
  '5k': 3.1,
  '10k': 6.2,
  half: 13.1,
  marathon: 26.2,
  ultra: 31.1,
}

// One step of the ladder, as the bar draws it. behind is walked, next is the one
// being walked, ahead is still to come; fill is how far into that step the
// walker has got, and only the next step is ever part filled.
export interface ChestStep {
  tier: string
  state: 'behind' | 'next' | 'ahead'
  fill: number
  // The friend whose oil lifts this chest, where the server has named one.
  giftedBy: string | null
}

export interface ChestBarState {
  steps: ChestStep[]
  // "Half chest, 1.1 XP away", or nothing where the server has not said how far
  // off it is. The ladder is climbed on the weighted number, so this is XP and
  // never miles. A made-up distance would be worse than no line.
  away: string
  // Whoever's oil has no chest to land on yet. A gift on a step that cannot be
  // lifted waits rather than being spent, so it belongs to a later chest and
  // the bar has to say so or it reads as nothing happening.
  waiting: string[]
  // Whether the chest coming is the top step, which is the reason a gift would
  // be waiting rather than named.
  nextIsTop: boolean
}

// The names on the waiting gifts, read as defensively as anything crossing the
// seam: a field that is not there is none of them, and a row without a name in
// it is not a name.
function giverNames(profile: Profile): string[] {
  const pending = profile.pending_gifts
  if (!Array.isArray(pending)) return []
  return pending
    .map((row) => (typeof row?.from === 'string' ? row.from.trim() : ''))
    .filter((name) => name !== '')
}

// The whole five-step cycle with the walker somewhere on it, or null where the
// server says nothing at all about the chest coming. Every field the gifts ride
// in on is optional: a server without them draws a plain bar rather than
// throwing, which is the only way two halves can land in either order.
export function chestBar(profile: Profile): ChestBarState | null {
  const named = profile.next_chest?.tier_id ?? profile.next_chest?.tier ?? profile.next_chest_tier
  const tier = (named ?? '').toString().toLowerCase()
  if (tier === '') return null

  const away =
    profile.next_chest?.miles_away ?? profile.next_chest?.mi_away ?? profile.next_chest_mi
  const known = typeof away === 'number' && isFinite(away) && away >= 0
  const at = CHEST_TIER_ORDER.indexOf(tier)

  // A step this build has never heard of leaves the walker off the bar rather
  // than on the wrong rung: every step reads as still to come.
  const cost = STEP_XP[tier] ?? 0
  const into = known && cost > 0 ? Math.min(100, Math.max(0, ((cost - away) / cost) * 100)) : 0

  const giftedBy = profile.next_chest?.gifted_by?.trim() ?? ''
  const steps: ChestStep[] = CHEST_TIER_ORDER.map((step, index) => ({
    tier: step,
    state: at < 0 || index > at ? 'ahead' : index < at ? 'behind' : 'next',
    fill: at < 0 || index > at ? 0 : index < at ? 100 : into,
    giftedBy: index === at && giftedBy !== '' ? giftedBy : null,
  }))

  // The named giver is still pending until the chest actually drops, so the
  // server may well send them in both places. Counting them once here leaves
  // exactly the gifts with nowhere yet to land, whichever way it sends them.
  const waiting = giverNames(profile)
  const alsoPending = giftedBy === '' ? -1 : waiting.indexOf(giftedBy)
  if (alsoPending >= 0) waiting.splice(alsoPending, 1)

  return {
    steps,
    away: known ? `${chestName(tier)}, ${(away as number).toFixed(1)} XP away` : '',
    waiting,
    nextIsTop: tier === CHEST_TIER_ORDER[CHEST_TIER_ORDER.length - 1],
  }
}

// This week across every activity. The profile carries per-activity rows and no
// sum of them, so the adding up happens here. distance is raw miles: what the
// body covered, not the weighted number the game runs on, which is XP.
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

// Everything an account has ever covered, in raw miles. This is the distance a
// body went, never the weighted number the game counts as XP, and it is the
// only number the screens are allowed to call miles.
export function lifetimeMiles(profile: Profile): number {
  let distance = 0
  for (const row of Object.values(profile.lifetime)) distance += row.distance_mi
  return distance
}

// The weekly medals and the raw miles each one is earned at, which is the
// server's ladder written down a second time so a target can be shown before
// it is reached. Raw miles, never XP: a week is twenty-five miles walked, run,
// ridden or swum, and no conversion rate has any business changing what it is.
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
