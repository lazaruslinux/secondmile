// The plot, read the same way wherever it is drawn: the whole of it on the
// Grove screen and a row of silhouettes in the band on You.

import type { Planting } from './api.ts'

// Which of the three drawings a planting is at: a seedling, something growing,
// or the grown thing. The server works this out, so this only has to stand in
// for it: grown from level one on, and the first third of level zero is the
// seedling.
export function plantStage(planting: Planting): number {
  if (planting.stage != null) return Math.min(3, Math.max(1, planting.stage))
  if (planting.mature) return 3
  const step = planting.level_mi
  if (!(step > 0)) return 1
  return planting.growth_mi / step >= 1 / 3 ? 2 : 1
}

// How far into its current level a planting is, in converted miles, and what
// that level costs. A finished plant has no next level, so it has no bar.
export function levelProgress(planting: Planting): { into: number; step: number } {
  const step = planting.level_mi > 0 ? planting.level_mi : 1
  return { into: planting.growth_mi - planting.level * step, step }
}
