// Numbers on their way to a screen.
//
// Distances are stored in miles whatever the account displays, so the
// conversion happens at the edge: here on the way out, and in the entry form on
// the way in. Adjusted miles are the game's own weighted unit and are never
// converted: they are the same number in every account.

import type { Activity, Units } from './api.ts'

export const KM_PER_MILE = 1.609344

export function pad(value: number): string {
  return String(value).padStart(2, '0')
}

export function unitName(units: Units): string {
  return units === 'metric' ? 'km' : 'mi'
}

export function toDisplayDistance(miles: number, units: Units): number {
  return units === 'metric' ? miles * KM_PER_MILE : miles
}

export function formatDistance(miles: number, units: Units): string {
  return `${toDisplayDistance(miles, units).toFixed(2)} ${unitName(units)}`
}

// The distance on its own, for the places that label the unit separately.
export function distanceValue(miles: number, units: Units): string {
  return toDisplayDistance(miles, units).toFixed(2)
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

export function formatStart(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

// Rounded to the minute, which is how a history reads.
export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours > 0 ? `${hours}h ${pad(minutes)}m` : `${minutes}m`
}

// The clock form, for the stat row on the feed: 1:04:31, or 24:07 under an hour.
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds))
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const secs = whole % 60
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(secs)}`
    : `${minutes}:${pad(secs)}`
}

// Time per unit of distance for the activities people think of that way, and
// speed for cycling, which nobody reads in minutes per mile. A workout with no
// distance on it has no pace at all, which is a dash rather than a division.
export function formatPace(
  activity: Activity,
  miles: number,
  seconds: number,
  units: Units,
): string {
  const distance = toDisplayDistance(miles, units)
  if (!(distance > 0) || !(seconds > 0)) return '--'

  if (activity === 'cycle') {
    const speed = distance / (seconds / 3600)
    return `${speed.toFixed(1)} ${units === 'metric' ? 'km/h' : 'mph'}`
  }

  const perUnit = seconds / distance
  let minutes = Math.floor(perUnit / 60)
  let secs = Math.round(perUnit % 60)
  // Rounding 59.6 up has to carry rather than print :60.
  if (secs === 60) {
    minutes += 1
    secs = 0
  }
  return `${minutes}:${pad(secs)} ${units === 'metric' ? '/km' : '/mi'}`
}
