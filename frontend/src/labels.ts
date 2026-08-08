// The four activities, in the order every screen lists them, and the words the
// interface uses for them. Kept in one place so the feed, the log, and the You
// screen never disagree about what to call a bike ride.

import type {
  Activity,
  FriendPlanting,
  ItemKind,
  MedalFamily,
  Person,
  Planting,
  Rarity,
  SatchelItem,
} from './api.ts'

export const ACTIVITY_ORDER: Activity[] = ['walk', 'run', 'cycle', 'swim']

export const ACTIVITY_NAMES: Record<Activity, string> = {
  walk: 'Walk',
  run: 'Run',
  cycle: 'Cycle',
  swim: 'Swim',
}

// The medal catalogue: twelve medals in four families, in the order every screen
// draws them. Every one of them repeats, so a medal is a count rather than a
// yes or a no, and the catalogue is fixed rather than grown: nothing here is
// added to without the art and the server being changed together.
export const MEDAL_ORDER = [
  'race_5k',
  'race_10k',
  'race_half',
  'race_marathon',
  'race_ultra',
  'weekly_10',
  'weekly_15',
  'weekly_25',
  'weekly_40',
  'early_riser',
  'night_owl',
  'second_mile',
]

export const MEDAL_FAMILY_ORDER: MedalFamily[] = ['race', 'weekly', 'time', 'second_mile']

// Which family each medal belongs to. The server sends this as well; this is
// what the screens group by, so the layout is the same whatever a server that
// predates the field does or does not say.
export const MEDAL_FAMILIES: Record<string, MedalFamily> = {
  race_5k: 'race',
  race_10k: 'race',
  race_half: 'race',
  race_marathon: 'race',
  race_ultra: 'race',
  weekly_10: 'weekly',
  weekly_15: 'weekly',
  weekly_25: 'weekly',
  weekly_40: 'weekly',
  early_riser: 'time',
  night_owl: 'time',
  second_mile: 'second_mile',
}

export const MEDAL_FAMILY_NAMES: Record<MedalFamily, string> = {
  race: 'Distance',
  weekly: 'Weeks',
  time: 'Hours',
  second_mile: 'Second mile',
}

// The names are the interface's own, not the server's, so twelve medals read as
// one set wherever they are drawn. The stylesheet is what puts them in capitals.
export const MEDAL_NAMES: Record<string, string> = {
  race_5k: '5K',
  race_10k: '10K',
  race_half: 'Half',
  race_marathon: 'Marathon',
  race_ultra: 'Ultra',
  weekly_10: '10-mile week',
  weekly_15: '15-mile week',
  weekly_25: '25-mile week',
  weekly_40: '40-mile week',
  early_riser: 'Early Riser',
  night_owl: 'Night Owl',
  second_mile: 'Second Mile',
}

// What earns each one. The thresholds are the server's, in statute miles, and
// they are written out in docs/03-artwork.md as well.
export const MEDAL_DETAILS: Record<string, string> = {
  race_5k: 'One run of 3.1 miles or more.',
  race_10k: 'One run of 6.2 miles or more.',
  race_half: 'One run of 13.1 miles or more.',
  race_marathon: 'One run of 26.2 miles or more.',
  race_ultra: 'One run of 31.1 miles or more.',
  weekly_10: 'Ten miles inside one week, any activity.',
  weekly_15: 'Fifteen miles inside one week.',
  weekly_25: 'Twenty-five miles inside one week.',
  weekly_40: 'Forty miles inside one week.',
  early_riser: 'A run of 5K or more started between four and six in the morning.',
  night_owl: 'A run of 5K or more started between eight at night and four in the morning.',
  second_mile: 'Twenty miles inside one week, double the smallest weekly target.',
}

// A medal id the server sent that this build has no name for still has to read
// as something: the server's own name for it, and the id itself failing that.
export function medalName(id: string, given?: string | null): string {
  return MEDAL_NAMES[id] ?? (given?.trim() ? given : id)
}

// The catalogue in family order, ready to draw as four groups. Families with
// nothing in them are left out, which cannot happen while the catalogue is the
// fixed twelve but keeps the callers from having to check.
export function medalsByFamily(): { family: MedalFamily; ids: string[] }[] {
  return MEDAL_FAMILY_ORDER.map((family) => ({
    family,
    ids: MEDAL_ORDER.filter((id) => MEDAL_FAMILIES[id] === family),
  })).filter((group) => group.ids.length > 0)
}

// The server names every species it sends, so a rename there is a rename here
// with nothing to keep in step. Where a name is missing the id is tidied up
// instead, which is enough for a species this build has never heard of.
export function speciesName(species: string, name?: string | null): string {
  if (name) return name
  const words = species.replace(/[_-]+/g, ' ').trim()
  return words === '' ? 'Plant' : words.slice(0, 1).toUpperCase() + words.slice(1)
}

// What to call somebody: the name they gave if they gave one, and the name they
// sign in with otherwise. The username is the identity; this is only the label.
export function personName(person: Person): string {
  const given = person.display_name?.trim()
  return given ? given : person.username
}

// A species has two names, and which one is right depends on where it is said.
// In the hand it is a seed; in the ground it is what it grew into. Servers that
// send only one name still read correctly: the seed form adds the word itself
// when the name it was given does not already carry it.
export function seedName(item: SatchelItem): string {
  const shown = speciesName(item.species ?? '', item.seed_name ?? item.name)
  return /seed$/i.test(shown) ? shown : `${shown} seed`
}

export function plantingName(row: Planting | FriendPlanting): string {
  return speciesName(row.species, row.plant_name ?? row.name)
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

// Which of the three frames a plant or a seed is drawn in. The rarity that
// never rolls is framed as the rarest rather than given a frame of its own, so
// the frames stay three and nothing is said about it.
export function rarityTier(rarity: Rarity | string): 'common' | 'uncommon' | 'rare' {
  if (rarity === 'uncommon') return 'uncommon'
  if (rarity === 'rare' || rarity === 'special') return 'rare'
  return 'common'
}

const KIND_NAMES: Record<ItemKind, string> = {
  seed: 'Seed',
  water: 'Water',
  oil: 'Oil',
}

// What one thing in the satchel is called. A seed is named after what it grows
// into, since that is the whole of what it is.
export function itemName(item: SatchelItem): string {
  if (item.kind === 'seed' && item.species) return seedName(item)
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
