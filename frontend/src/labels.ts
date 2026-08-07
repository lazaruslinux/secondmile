// The four activities, in the order every screen lists them, and the words the
// interface uses for them. Kept in one place so the feed, the log, and the You
// screen never disagree about what to call a bike ride.

import type { Activity } from './api.ts'

export const ACTIVITY_ORDER: Activity[] = ['walk', 'run', 'cycle', 'swim']

export const ACTIVITY_NAMES: Record<Activity, string> = {
  walk: 'Walk',
  run: 'Run',
  cycle: 'Cycle',
  swim: 'Swim',
}

// The five race distances, shortest first, which is the order they are drawn
// in. The ids are the server's; the names are what a runner calls them.
export const RACE_BADGE_ORDER = [
  'race_5k',
  'race_10k',
  'race_half',
  'race_marathon',
  'race_ultra',
]

export const RACE_BADGE_NAMES: Record<string, string> = {
  race_5k: '5K',
  race_10k: '10K',
  race_half: 'Half',
  race_marathon: 'Marathon',
  race_ultra: 'Ultra',
}

// What earns each one. The thresholds are the server's, in statute miles.
export const RACE_BADGE_DETAILS: Record<string, string> = {
  race_5k: 'One run of 3.1 miles or more.',
  race_10k: 'One run of 6.2 miles or more.',
  race_half: 'One run of 13.1 miles or more.',
  race_marathon: 'One run of 26.2 miles or more.',
  race_ultra: 'One run of 31.1 miles or more.',
}

// A badge id the server sent that this build has no name for still has to read
// as something.
export function raceBadgeName(id: string): string {
  return RACE_BADGE_NAMES[id] ?? id
}
