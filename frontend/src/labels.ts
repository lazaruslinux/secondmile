// The four activities, in the order every screen lists them, and the words the
// interface uses for them. Kept in one place so the feed, the log, and the You
// screen never disagree about what to call a bike ride.

import type { Activity, ItemKind, Rarity, SatchelItem } from './api.ts'

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

// The server names every species it sends, so a rename there is a rename here
// with nothing to keep in step. Where a name is missing the id is tidied up
// instead, which is enough for a species this build has never heard of.
export function speciesName(species: string, name?: string | null): string {
  if (name) return name
  const words = species.replace(/[_-]+/g, ' ').trim()
  return words === '' ? 'Plant' : words.slice(0, 1).toUpperCase() + words.slice(1)
}

const RARITY_NAMES: Record<Rarity, string> = {
  common: 'Common',
  uncommon: 'Uncommon',
  rare: 'Rare',
  special: '',
}

// How rare a seed is, in a word. The rarity that never rolls has no word: the
// app says nothing anywhere about the one seed that is not like the others.
export function rarityWord(rarity: Rarity | string): string {
  return RARITY_NAMES[rarity as Rarity] ?? ''
}

const KIND_NAMES: Record<ItemKind, string> = {
  seed: 'Seed',
  water: 'Water',
  oil: 'Oil',
}

// What one thing in the satchel is called. A seed is named after what it grows
// into, since that is the whole of what it is.
export function itemName(item: SatchelItem): string {
  if (item.kind === 'seed' && item.species) {
    return `${speciesName(item.species, item.name)} seed`
  }
  return KIND_NAMES[item.kind] ?? item.kind
}

// The step of the ladder a chest dropped on. The names are the server's; a
// chest from before the ladder simply has none.
const CHEST_TIER_NAMES: Record<string, string> = {
  '5k': '5K',
  '10k': '10K',
  half: 'Half',
  marathon: 'Marathon',
  ultra: 'Ultra',
}

export function chestName(tier: string | null | undefined): string {
  if (!tier) return 'Chest'
  return `${CHEST_TIER_NAMES[tier.toLowerCase()] ?? tier} chest`
}
