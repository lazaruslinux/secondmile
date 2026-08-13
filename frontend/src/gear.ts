// The shoe pickers, and the words a pair is drawn with.
//
// The lists are the server's as well, in app/gear.py, and they are changed in
// both places or in neither: a size this file offers and the server refuses is
// a form that cannot be saved.

import type { Gear, GearStyle } from './api.ts'

export const GEAR_STYLES: { id: GearStyle; label: string }[] = [
  { id: 'mens', label: "Men's" },
  { id: 'womens', label: "Women's" },
]

// US sizing in half steps, and the widths each style is sold in. The standard
// width is the one the form opens on, because almost nobody knows their width
// and a question most people cannot answer is a worse form.
const SIZE_RANGE: Record<GearStyle, [number, number]> = {
  mens: [6, 16],
  womens: [4, 14],
}

const WIDTHS: Record<GearStyle, { id: string; label: string }[]> = {
  mens: [
    { id: 'B', label: 'B - Narrow' },
    { id: 'D', label: 'D - Standard (Default)' },
    { id: '2E', label: '2E - Wide' },
    { id: '4E', label: '4E - Extra Wide' },
  ],
  womens: [
    { id: '2A', label: '2A - Narrow' },
    { id: 'B', label: 'B - Standard (Default)' },
    { id: 'D', label: 'D - Wide' },
    { id: '2E', label: '2E - Extra Wide' },
  ],
}

export const DEFAULT_WIDTH: Record<GearStyle, string> = { mens: 'D', womens: 'B' }

export function gearSizes(style: GearStyle): number[] {
  const [low, high] = SIZE_RANGE[style]
  const steps = (high - low) * 2 + 1
  return Array.from({ length: steps }, (_, step) => low + step * 0.5)
}

export function gearWidths(style: GearStyle): { id: string; label: string }[] {
  return WIDTHS[style]
}

// Half sizes read as 10.5 and whole ones as 10, which is how a shoe box says it.
export function sizeLabel(size: number): string {
  return Number.isInteger(size) ? String(size) : size.toFixed(1)
}

// What a pair is called: its nickname, or its brand and model. The server names
// them the same way on a workout card, so the two never disagree.
export function gearName(pair: Gear): string {
  const given = pair.nickname?.trim()
  return given ? given : `${pair.brand} ${pair.model}`.trim()
}

// The line under the name where a nickname has taken it, and nothing at all
// where the name is already the brand and model.
export function gearSubline(pair: Gear): string {
  return pair.nickname?.trim() ? `${pair.brand} ${pair.model}`.trim() : ''
}

// The size and width, said the way a box says them.
export function fitLine(pair: Gear): string {
  const style = GEAR_STYLES.find((row) => row.id === pair.style)?.label ?? ''
  return `${style} ${sizeLabel(pair.size)}, ${pair.width}`.trim()
}

// Whole miles, because this is wear on a shoe rather than a figure anybody is
// measuring themselves against.
export function milesLine(miles: number): string {
  return `${Math.round(miles).toLocaleString()} mi`
}

// The quiet wear line, and only for a pair somebody set a replacement mileage
// on. Nothing warns and nothing nags: this says where they are and stops.
export function wearLine(pair: Gear): string {
  if (pair.replace_around_mi === null || pair.replace_around_mi === undefined) return ''
  return `${Math.round(pair.miles).toLocaleString()} of about ${Math.round(
    pair.replace_around_mi,
  ).toLocaleString()} mi`
}

// What the pickers offer: everything not put away. A retired pair keeps its
// miles and stays on the activities it is already on, and takes nothing new.
export function wearable(gear: Gear[]): Gear[] {
  return gear.filter((pair) => !pair.retired)
}
