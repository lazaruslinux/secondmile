// Reading the letter. The app asks twice whether there is anything in it, once
// to decide whether to show it at all and once to draw it, so the rules for
// what counts as something are written here rather than in both places.
//
// Everything is read defensively: a field that is missing means nothing
// happened, never that anything is wrong.

import type { RecapEncouragement, RecapNote, RecapState } from './api.ts'

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

// The one line about the border's growth, or nothing when it did not move. A
// stage on its own is read as a rise, since a server only mentions the stage
// when it changed.
export function flourishLine(recap: RecapState): string {
  const stage = recap.flourish_stage
  if (!recap.flourish_rose && stage === undefined) return ''
  if (typeof stage === 'number' && stage > 0) {
    return `Your border has grown. Stage ${stage}.`
  }
  return recap.flourish_rose ? 'Your border has grown.' : ''
}

// Whether the letter says anything at all. Nothing to read is not worth
// interrupting anybody for.
export function recapHasNews(recap: RecapState): boolean {
  return (
    recap.miles > 0 ||
    (recap.chests_delivered ?? 0) > 0 ||
    (recap.plant_growth?.length ?? 0) > 0 ||
    (recap.medals?.length ?? 0) > 0 ||
    recapNotes(recap.encouragement).length > 0 ||
    recapCheers(recap.encouragement) > 0 ||
    flourishLine(recap) !== ''
  )
}
