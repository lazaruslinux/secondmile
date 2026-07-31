// Numbers on their way to a screen.
//
// Distances are stored in miles whatever the account displays, so the
// conversion happens at the edge: here on the way out, and in the entry form on
// the way in. Miles with a capital M are the game's own unit and are never
// converted: a Mile is a Mile in every account.

import type { Units } from './api.ts'

export const KM_PER_MILE = 1.609344

export function unitName(units: Units): string {
  return units === 'metric' ? 'km' : 'mi'
}

export function toDisplayDistance(miles: number, units: Units): number {
  return units === 'metric' ? miles * KM_PER_MILE : miles
}

export function formatDistance(miles: number, units: Units): string {
  return `${toDisplayDistance(miles, units).toFixed(2)} ${unitName(units)}`
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}
