// Reading the letter. The app asks twice whether there is anything in it, once
// to decide whether to show it at all and once to draw it, so the rules for
// what counts as something are written here rather than in both places.
//
// Everything is read defensively: a field that is missing means nothing
// happened, never that anything is wrong.

import type {
  Activity,
  RecapChest,
  RecapEncouragement,
  RecapGrowth,
  RecapNote,
  RecapState,
} from './api.ts'
import { chestName, plantingName } from './labels.ts'

// Whoever wrote a note, under whichever of the field names the server used. An
// empty string means the note goes out unsigned rather than signed "someone".
export function noteAuthor(note: RecapNote): string {
  return note.from_username ?? note.username ?? note.from ?? ''
}

// The notes worth drawing: the ones that actually carry words.
export function recapNotes(given: RecapEncouragement | undefined): RecapNote[] {
  return (given?.notes ?? []).filter(
    (note) => typeof note.body === 'string' && note.body.trim() !== '',
  )
}

// Cheers, however they were counted. One number and a row per workout are both
// allowed for, since either is a reasonable way for a server to say it.
export function recapCheers(given: RecapEncouragement | undefined): number {
  if (!given) return 0
  if (typeof given.cheers === 'number') return given.cheers
  if (Array.isArray(given.cheers)) {
    let total = 0
    for (const row of given.cheers) total += row.cheers ?? row.count ?? 1
    return total
  }
  return given.cheer_count ?? 0
}

// The four rows the letter always draws, in his order rather than the app's:
// running leads, and every activity gets its past-tense word. The rows are not
// filtered by whether anything happened, because a week with no swimming in it
// still says so, and four rows in the same order every time are read at a
// glance where a list that changes shape has to be read properly.
const MILE_ROWS: { activity: Activity; word: string }[] = [
  { activity: 'run', word: 'ran' },
  { activity: 'walk', word: 'walked' },
  { activity: 'swim', word: 'swam' },
  { activity: 'cycle', word: 'biked' },
]

export interface RecapMileRow {
  activity: Activity
  word: string
  // Raw miles: what a body covered, never the weighted number.
  miles: number
}

// The rows as the letter prints them. The map is taken as possibly missing on
// purpose: an activity with nothing under it, or a whole payload without the
// field, is none rather than a fault.
export function recapMiles(given: RecapState['miles'] | undefined): RecapMileRow[] {
  return MILE_ROWS.map((row) => {
    // Anything that is not a real number is none. This field changed shape
    // once already, from a single total to a figure per activity, and a row
    // that throws while being printed takes the whole app down with it.
    const value = given?.[row.activity]
    return { ...row, miles: typeof value === 'number' && isFinite(value) ? value : 0 }
  })
}

// The total under the four rows, added up from the rows as they are printed
// rather than from the server's own total. The one job this line has is to
// equal the four figures above it: two activities of four hundredths of a mile
// each print as two zeros, and a tenth of a mile underneath them would read as
// an arithmetic mistake.
export function recapMilesTotal(rows: RecapMileRow[]): number {
  return rows.reduce((sum, row) => sum + Number(row.miles.toFixed(1)), 0)
}

// The chests that landed, named by their step: "10K chest, Marathon chest".
// Named rather than counted, and two of the same step are said twice, because
// there are only ever a handful and the name is the thing that happened.
export function recapChestNames(chests: RecapChest[] | undefined): string {
  return (chests ?? []).map((chest) => chestName(chest.tier_id ?? chest.tier)).join(', ')
}

// Who lifted which of the chests that landed. One count per gifted chest, so
// two from the same friend say two, and the names are said once each. Gifted is
// the word for it: the chest was earned, and somebody else made it richer.
//
// How many chests there were in total decides the wording, not how many were
// gifted. "One of them" says there were others, so a letter carrying a single
// chest has to say "It", or it describes a delivery that did not happen.
export function recapGiftLine(chests: RecapChest[] | undefined): string {
  const all = chests ?? []
  const givers = all
    .map((chest) => chest.gifted_by)
    .filter((name): name is string => typeof name === 'string' && name !== '')
  if (givers.length === 0) return ''
  const names = [...new Set(givers)].join(' and ')
  if (all.length === 1) return `It was gifted by ${names}.`
  if (givers.length === 1) return `One of them was gifted by ${names}.`
  return `${givers.length} of them were gifted by ${names}.`
}

// What one plant changing shape reads as: the crossing told as a story, one
// verb per boundary it went over. Coming up out of the ground is "sprouted" and
// reaching level one is "matured", and a week fast enough to do both says the
// whole of it rather than jumping to the end.
//
// Both numbers have to be there and the plant has to have moved forward: a
// server that sends neither, and a plot rebuilt part way through a replay, both
// read as nothing to say.
function stageCrossing(row: RecapGrowth): string {
  const before = row.stage_before
  const stage = row.stage
  if (typeof before !== 'number' || typeof stage !== 'number' || stage <= before) return ''
  const name = plantingName(row)
  if (before <= 1 && stage >= 3) return `${name}. Sprouted, grew, matured.`
  if (stage >= 3) return `${name} matured.`
  return `${name} sprouted.`
}

// What one plant's growth reads as. Coming up out of the ground wins over
// gaining levels when a plant did both, because maturing happens once and
// growing happens every week. Nothing here mentions fruit: that mechanic is not
// built, and the letter does not promise what the app cannot do.
export function growthLine(row: RecapGrowth): string {
  // The crossing is the whole of the plant's week, so it takes the line. A
  // plant only ever matures by reaching level one, which is what "is grown"
  // below says: told twice it would read as two separate pieces of news.
  const crossing = stageCrossing(row)
  if (crossing !== '') return crossing
  const name = plantingName(row)
  const level = row.level ?? 0
  // Worked back from the levels gained when the starting level is missing, so
  // an older server still says which two numbers the climb ran between.
  const before = row.level_before ?? Math.max(0, level - (row.levels_gained ?? 0))
  if (before === 0 && level >= 1) return `${name} is grown. Level ${level}.`
  if (level > before) return `${name} reached level ${level}.`
  return ''
}

// The grove lines worth drawing. A row that says nothing is dropped here rather
// than in the view, so the section can hide on the same answer the letter is
// drawn from.
export function recapGrowthLines(recap: RecapState): string[] {
  return (recap.plant_growth ?? []).map(growthLine).filter((line) => line !== '')
}

// The one line about the frame's growth, said only when the server says it rose.
// The stage is carried on every letter, so it is the rise and not the stage that
// decides whether anything is said at all.
export function flourishLine(recap: RecapState): string {
  if (!recap.flourish_rose) return ''
  const stage = recap.flourish_stage
  if (typeof stage === 'number' && stage > 0) return `Your frame grew. Stage ${stage}.`
  return 'Your frame grew.'
}

// Whether the letter says anything at all. Nothing to read is not worth
// interrupting anybody for.
export function recapHasNews(recap: RecapState): boolean {
  return (
    (recap.miles_total ?? 0) > 0 ||
    recapMilesTotal(recapMiles(recap.miles)) > 0 ||
    (recap.chests?.length ?? 0) > 0 ||
    (recap.workouts?.length ?? 0) > 0 ||
    recapGrowthLines(recap).length > 0 ||
    (recap.medals?.length ?? 0) > 0 ||
    recapNotes(recap.encouragement).length > 0 ||
    recapCheers(recap.encouragement) > 0 ||
    flourishLine(recap) !== ''
  )
}
