// The four activities, in the order every screen lists them, and the words the
// interface uses for them. Kept in one place so the feed, the Activity tab, and
// the You screen never disagree about what to call a bike ride.

import type {
  Activity,
  FriendPlanting,
  ItemKind,
  Person,
  Planting,
  Rarity,
  SatchelItem,
} from './api.ts'
import { zonedHour } from './format.ts'

export const ACTIVITY_ORDER: Activity[] = ['walk', 'run', 'cycle', 'swim']

export const ACTIVITY_NAMES: Record<Activity, string> = {
  walk: 'Walk',
  run: 'Run',
  cycle: 'Cycle',
  swim: 'Swim',
}

// The mark each activity wears, beside the word and never instead of it. The
// names are the files under src/assets/icons, so this map is the one place a
// renamed file has to be answered.
export const ACTIVITY_ICONS: Record<Activity, string> = {
  walk: 'sport-walk',
  run: 'sport-run',
  cycle: 'sport-cycle',
  swim: 'sport-swim',
}

// The mark an indoor session wears instead of its sport's own. Walks and runs
// only: a treadmill is what those two happen on indoors, and a stationary bike
// and a pool are neither this drawing nor each other.
const TREADMILL_ICON = 'sport-treadmill'
const TREADMILL_ACTIVITIES: Activity[] = ['walk', 'run']

// Which mark one row wears. Every place that draws a workout's own activity
// goes through here, so a treadmill run is drawn the same way on the feed, in
// the Activity tab, in the letter and in the Deleted list. The lists that draw
// an activity in the abstract, such as the sport chips and the filters, read
// ACTIVITY_ICONS directly: there is no such thing as an indoor total.
export function activityIcon(activity: Activity, indoor?: boolean): string {
  return indoor && TREADMILL_ACTIVITIES.includes(activity)
    ? TREADMILL_ICON
    : ACTIVITY_ICONS[activity]
}

// What a workout is called when nobody has named it: the part of the day it
// started in, then the activity. Read on the instance's clock, which is the
// clock the card's own date line is read on, so a run started at 05:44 is a
// morning run wherever the browser thinks it is. Written once here and used
// wherever a headline falls back, so the feed, the Activity tab, and the letter
// never name the same workout two ways.
export function defaultHeadline(activity: Activity, startTs: string): string {
  const hour = zonedHour(startTs)
  const bucket = hour >= 4 && hour < 12 ? 'Morning' : hour >= 12 && hour < 17 ? 'Lunch' : 'Evening'
  return `${bucket} ${ACTIVITY_NAMES[activity]}`
}

// The two the edit form offers. The API accepts exactly these, so the list is
// changed in both places or in neither.
export const GENDERS = ['Male', 'Female']

// The medal catalogue: twenty-four medals in the order every screen draws
// them, which is the server's own catalogue order. No screen groups them by
// family, so the order is the whole of the arrangement. All but the last four
// repeat, so a medal is a count rather than a yes or a no; the odometer at the
// end is earned once each. The catalogue is fixed rather than grown: nothing
// here is added to without the art and the server being changed together.
export const MEDAL_ORDER = [
  'race_1mi',
  'race_2mi',
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
  'cycle_10',
  'cycle_25',
  'cycle_50',
  'cycle_100',
  'swim_half',
  'swim_1',
  'swim_2',
  'lifetime_100',
  'lifetime_250',
  'lifetime_500',
  'lifetime_1000',
]

// The names are the interface's own, not the server's, so the whole set reads
// as one wherever it is drawn. The stylesheet is what puts them in capitals.
// The eleven that reach 40-mile week are settled; First Mile and Second Mile
// are the owner's own and never change; the eleven below them are DRAFT NAMES
// waiting on his word.
export const MEDAL_NAMES: Record<string, string> = {
  race_1mi: 'First Mile',
  race_2mi: 'Second Mile',
  race_5k: '5K',
  race_10k: '10K',
  race_half: 'Half',
  race_marathon: 'Marathon',
  race_ultra: '50K',
  weekly_10: '10-mile week',
  weekly_15: '15-mile week',
  weekly_25: '25-mile week',
  weekly_40: '40-mile week',
  early_riser: 'Early Riser',
  night_owl: 'Night Owl',
  cycle_10: '10 Mile Ride',
  cycle_25: '25 Mile Ride',
  cycle_50: '50 Mile Ride',
  cycle_100: 'Century',
  swim_half: 'Half Mile Swim',
  swim_1: 'Mile Swim',
  swim_2: '2 Mile Swim',
  lifetime_100: '100 Miles',
  lifetime_250: '250 Miles',
  lifetime_500: '500 Miles',
  lifetime_1000: '1000 Miles',
}

// How to earn each one, written as the instruction it is rather than as a
// description of it. The thresholds are the server's and they are written out
// in docs/03-artwork.md as well. All of them are raw miles on the ground except
// the last four, which are the converted Miles the level bar counts in and say
// so. The race medals and the two time medals are earned on foot, walked or
// run; a week counts every activity; the rides and the swims are each their own
// sport only. The clock times are the instance's timezone, which is every
// account's local time only while one instance serves one place. No line takes
// a trailing period: they read as one catalogue.
export const MEDAL_DETAILS: Record<string, string> = {
  race_1mi: 'Walk or run 1 mile',
  race_2mi: 'Walk or run 2 miles',
  race_5k: 'Walk or run a 5K (3.1mi)',
  race_10k: 'Walk or run a 10K (6.2mi)',
  race_half: 'Walk or run a half-marathon (13.1mi)',
  race_marathon: 'Walk or run a marathon (26.2mi)',
  race_ultra: 'Walk or run a 50K (31.1mi)',
  weekly_10: 'Cover 10 or more miles in one week, in any activity',
  weekly_15: 'Cover 15 or more miles in one week, in any activity',
  weekly_25: 'Cover 25 or more miles in one week, in any activity',
  weekly_40: 'Cover 40 or more miles in one week, in any activity',
  early_riser: 'Start a walk or run of a mile or more between 4am and 5:59am',
  night_owl: 'Start a walk or run of a mile or more between 8pm and 3:59am',
  cycle_10: 'Ride 10 miles or more in one ride',
  cycle_25: 'Ride 25 miles or more in one ride',
  cycle_50: 'Ride 50 miles or more in one ride',
  cycle_100: 'Ride 100 miles or more in one ride',
  swim_half: 'Swim half a mile or more in one swim',
  swim_1: 'Swim a mile or more in one swim',
  swim_2: 'Swim 2 miles or more in one swim',
  lifetime_100: 'Reach 100 lifetime Miles, the total the level bar counts',
  lifetime_250: 'Reach 250 lifetime Miles',
  lifetime_500: 'Reach 500 lifetime Miles',
  lifetime_1000: 'Reach 1000 lifetime Miles',
}

// A medal id the server sent that this build has no name for still has to read
// as something: the server's own name for it, and the id itself failing that.
export function medalName(id: string, given?: string | null): string {
  return MEDAL_NAMES[id] ?? (given?.trim() ? given : id)
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
// Takes the two halves it reads rather than a whole Person, so the search
// rows, which carry the restricted card instead, are named the same way.
export function personName(person: Pick<Person, 'username'> & { display_name?: string | null }): string {
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

// Said under anything that has reached the last level, and nowhere else: every
// other grown plant says which level it is on instead.
export const FULLY_GROWN = 'Fully grown.'

// Where a plant has got to, in one line, so the same plant reads the same way
// in the plot, over the fence, and in the row that offers it a drink. A grown
// plant says which level it is on, the last level is the only one that says it
// is finished, and anything younger says which of the two early drawings it is
// at. The stage is passed in because each screen reads it from what it has: a
// friend's row carries the stage itself, and the own plot works it out from the
// miles behind it. A row that arrived without a level says its stage rather
// than inventing a number.
export function plantStateLine(
  row: { gilded?: boolean; mature?: boolean; level?: number },
  stage: number,
): string {
  if (row.gilded === true) return FULLY_GROWN
  if (row.mature === true && typeof row.level === 'number') return `Level ${row.level}`
  return stage === 1 ? 'Seedling' : 'Growing'
}

// The species on its own, for the tab under a seed's square. The name in the
// hand already ends in the word seed and the square is plainly a seed, so the
// word is dropped and what is left is the one thing the tab is there to say.
export function seedSpecies(item: SatchelItem): string {
  const shown = seedName(item)
  return shown.replace(/\s*seeds?$/i, '').trim() || shown
}

const RARITY_NAMES: Record<Rarity, string> = {
  common: 'Common',
  uncommon: 'Uncommon',
  rare: 'Rare',
  epic: 'Epic',
  legendary: 'Legendary',
  special: '',
}

// How rare a seed is, in a word. The rarity that never rolls has no word: the
// app says nothing anywhere about the one seed that is not like the others.
export function rarityWord(rarity: Rarity | string): string {
  return RARITY_NAMES[rarity as Rarity] ?? ''
}

export type RarityTier = 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary'

// Which of the five frames a thing is drawn in. Seeds roll no higher than rare;
// the two steps above belong to the tools. The rarity that never rolls is
// framed as rare rather than given a frame of its own, so nothing is said about
// the one seed that is not like the others.
export function rarityTier(rarity: Rarity | string): RarityTier {
  if (rarity === 'uncommon') return 'uncommon'
  if (rarity === 'rare' || rarity === 'special') return 'rare'
  if (rarity === 'epic') return 'epic'
  if (rarity === 'legendary') return 'legendary'
  return 'common'
}

// The tools are one rarity each by what they are, so their frame is read off
// the kind rather than off the row. Rows written before the tiers grew carry
// older rarities and are not rewritten, and this is what makes an old potion and
// a new one draw the same. A seed keeps the rarity it was rolled at.
//
// Water is the one thing held that has no rarity at all: its row carries
// whichever slot it fell out of, which would colour one jar white and the next
// one blue for no difference anybody can spend. The empty string is no rarity,
// and the frame draws that in its plain white.
const KIND_RARITY: Record<string, Rarity | ''> = {
  water: '',
  wish: 'epic',
  oil: 'legendary',
}

export function itemRarity(item: SatchelItem): Rarity | string {
  return KIND_RARITY[item.kind] ?? item.rarity
}

// What the tab under an item's square says. The colour is already the rarity,
// so the tab is free to name the thing itself wherever the rarity alone cannot
// tell two squares apart: twelve seeds are twelve species, and water has no
// rarity to name in the first place. Everything else is one square of its own
// and keeps the rarity word.
export function itemTabLabel(item: SatchelItem): string | undefined {
  if (item.kind === 'seed' && item.species) return seedSpecies(item)
  if (item.kind === 'water') return KIND_NAMES.water
  return undefined
}

// The boost potion is named for what it does. The kind stays 'oil' everywhere
// under the screen, in the database and across the API: this is the word, not
// the thing. The verb is still anoint.
const KIND_NAMES: Record<ItemKind, string> = {
  seed: 'Seed',
  water: 'Water',
  oil: 'Boost potion',
  wish: 'Unmarked seed',
}

// What one thing in the satchel is called. A seed is named after what it grows
// into, since that is the whole of what it is.
export function itemName(item: SatchelItem): string {
  if (item.kind === 'seed' && item.species) return seedName(item)
  return KIND_NAMES[item.kind] ?? item.kind
}

// What each item is for, said once here and read wherever a square is opened.
export const ITEM_LINES: Record<ItemKind, string> = {
  // XP rather than miles: the grove has always grown on the weighted number,
  // and miles on screen mean raw distance everywhere else in the app.
  seed: 'Plant it and it grows with your XP.',
  water: 'Pour it on a plant for 10 XP of growth.',
  oil: 'Anoint a friend to boost their next chest!',
  wish: 'Choose any seed you have not found yet. One use.',
}

// The same three tools where a chest has just given one up. Nothing is spent
// from a reveal, so these say where the act happens instead.
export const REVEAL_LINES: Record<string, string> = {
  water: 'Pour it onto one plant from your inventory.',
  oil: 'Anoint a friend with it from your inventory.',
  wish: 'Choose what it will become: any seed you have not yet found.',
}

// What oil buys, said wherever a person is picked for it. The same promise the
// square makes, without the square's exclamation: this one is read while
// choosing rather than while opening.
export const ANOINT_HINT = 'Boosts their next chest, one step rarer.'

// What the three acts say once they are done, and what a refused anointing adds
// so a legendary item never looks spent for nothing.
export const PLANTED = 'Planted. It is in your grove.'
export const POURED = 'Poured. Ten XP of growth.'
export const ANOINTED = 'Done. Their next chest opens one step rarer.'
export const OIL_KEPT = 'The potion is still in your inventory.'

// What an empty list says. A person's own screens can promise the sync that
// fills them in; a friend's page says the shorter half, because their next sync
// is not the reader's to wait on.
export const NOTHING_RECORDED = 'Nothing recorded yet. Your next sync fills this in.'
export const NOTHING_RECORDED_FRIEND = 'Nothing recorded yet.'

// The week's own version, which needs no such split: a week with nothing in it
// yet is the same sentence on either screen.
export const NOTHING_THIS_WEEK = 'Nothing recorded this week yet.'

// Said over an empty plot, on the Grove screen and in the card on You.
export const NOTHING_PLANTED = 'Nothing planted yet. Seeds come out of chests.'

// The same over an empty inventory, where the grid stands down rather than
// showing rows of squares with an instruction to tap them.
export const NOTHING_HELD = 'Nothing found yet. Items come out of chests.'

// Where water comes from, said the way the potion lines beside it are said.
export const NO_WATER = 'No water in your inventory. It comes out of chests.'

// The harvest, and the four things manna is spent on. Every line here says what
// is true and nothing more: manna buys fruit, never growth, and only gathered
// fruit is ever at risk.
export const HARVEST_HINT =
  'Your plants bear fruit every 33 XP, all at once. Gather brings the fruit in ' +
  'whole. Manna is banked from your calories and keeps for good.'
export const NOTHING_BORNE = 'Nothing to gather yet.'
export const EMPTY_BASKET = 'Nothing gathered. Fruit lands here when you gather it.'
export const NO_MANNA = 'No manna yet. Your calories earn it.'
export const GATHER_HINT =
  'The fruit comes in whole. Gathered fruit keeps for a week; what stays on the ' +
  'plant keeps for good.'
export const FED = 'Fed. Its next harvest is bigger.'
export const MANNA_SENT = 'Sent. It is in their manna.'
export const FRUIT_GIVEN = 'Given. It is in their basket.'

// What feeding buys, said wherever a plant is picked for it. The second
// sentence is the two-lane law in the app's own voice, and it is here because
// this is the one screen where somebody might expect otherwise.
export function feedHint(cost: number): string {
  return `${cost.toLocaleString()} manna for one more fruit next time it bears. It never makes anything grow faster.`
}

// What one plant is carrying, said under it. Both numbers come from the server
// already joined, so nothing here counts anything.
export function fedLine(fed: number): string {
  return `Fed, ${fed} more next harvest`
}

export function readyLine(label: string): string {
  return `${label} ready`
}

// What a refused upload says. The proxy in front of the app answers some of
// these before the server does, so the sentence is written here rather than
// read off the response, and it is word for word the server's own.
export const TOO_MANY_UPLOADS = 'Too many uploads just now. Wait a minute.'

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

// The five steps in the order they are walked, which is the order their squares
// read in. A step nothing is waiting on simply has no square.
export const CHEST_TIER_ORDER = ['5k', '10k', 'half', 'marathon', 'ultra']

// The step on its own, for the tab under a chest square where the whole name
// would not fit. A chest from before the ladder is only a chest.
export function chestTierWord(tier: string | null | undefined): string {
  return (tier ? CHEST_TIER_NAMES[tier.toLowerCase()] : undefined) ?? 'Chest'
}

// The chest ladder runs up the same five colours the frames do, so a Marathon
// chest is drawn in the same purple the wish inside it is framed in. What the
// colour means is the floor: the worst the chest can come up as. A chest from
// before the ladder rolls as the first step and is coloured as one.
const CHEST_TIER_RARITY: Record<string, RarityTier> = {
  '5k': 'common',
  '10k': 'uncommon',
  half: 'rare',
  marathon: 'epic',
  ultra: 'legendary',
}

export function chestTierRarity(tier: string | null | undefined): RarityTier {
  return (tier ? CHEST_TIER_RARITY[tier.toLowerCase()] : undefined) ?? 'common'
}

// Common is the type colour already, so it takes no class of its own.
export function chestTierClass(tier: string | null | undefined): string | undefined {
  const step = chestTierRarity(tier)
  return step === 'common' ? undefined : `chest-tier-${step}`
}
