// The four activities, in the order every screen lists them, and the words the
// interface uses for them. Kept in one place so the Almanac, the profile, and
// the recap never disagree about what to call a bike ride.

import type { Activity } from './api.ts'

export const ACTIVITY_ORDER: Activity[] = ['walk', 'run', 'cycle', 'swim']

export const ACTIVITY_NAMES: Record<Activity, string> = {
  walk: 'Walk',
  run: 'Run',
  cycle: 'Cycle',
  swim: 'Swim',
}
