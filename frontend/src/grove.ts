// The plot, read the same way wherever it is drawn: the whole of it on the
// Grove screen and a row of silhouettes in the band on You.

import type { Planting } from './api.ts'

// Which of the three drawings a planting is at: a seedling, something growing,
// or the grown thing. Half way to maturity is where the middle picture starts.
export function plantStage(planting: Planting): number {
  if (planting.mature) return 3
  const maturity = planting.maturity_mi
  if (!(maturity > 0)) return 1
  return planting.growth_mi / maturity >= 0.5 ? 2 : 1
}
