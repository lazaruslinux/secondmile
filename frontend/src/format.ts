// Numbers on their way to a screen.
//
// Distances are stored in miles whatever the account displays, so the
// conversion happens here, at the edge, on the way out. XP is the game's own
// weighted unit and is never converted: it is the same number in every
// account, and it is never called miles.

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

// The same figure to one decimal, for a total read at a glance rather than
// compared: the totals beside it on the identity band are written that way, and
// two decimals in a line of one-decimal numbers reads as a different kind of
// figure than it is.
export function distanceBrief(miles: number, units: Units): string {
  return toDisplayDistance(miles, units).toFixed(1)
}

// XP on screen: one decimal, and never converted. XP is distance weighted by
// how hard the activity is, so a mile swum is one mile and four XP, and it is
// the same figure in every account whatever unit that account reads distances
// in. The word beside it is always XP, never miles and never mi.
export function convertedValue(miles: number): string {
  return miles.toFixed(1)
}

// How long it has been: "2 days", "1 day", "3 hours", "22 minutes", or "a
// moment" for anything under a minute. Largest whole unit, rounded down; days
// never roll into weeks or months. Unparseable stamp returns '' so the caller
// can drop the sentence whole.
export function formatElapsed(iso: string): string {
  const at = Date.parse(iso)
  if (isNaN(at)) return ''
  const seconds = Math.max(0, (Date.now() - at) / 1000)
  const days = Math.floor(seconds / 86400)
  if (days >= 1) return `${days} ${days === 1 ? 'day' : 'days'}`
  const hours = Math.floor(seconds / 3600)
  if (hours >= 1) return `${hours} ${hours === 1 ? 'hour' : 'hours'}`
  const minutes = Math.floor(seconds / 60)
  if (minutes >= 1) return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'}`
  return 'a moment'
}

// The zone the instance keeps, learned from GET /api/status when the app boots.
// Times are read in it rather than in the browser's, because the browser's is
// not to be trusted: a fingerprint-protection setting that pins the browser to
// UTC turns a run started at 05:44 into one started at 12:44, and moves the
// workouts either side of midnight into the wrong day and the wrong week.
// undefined means the browser's own zone, which is the fallback.
let zone: string | undefined

export function setInstanceTimezone(name: string | null | undefined): void {
  if (!name) {
    zone = undefined
    return
  }
  try {
    // Throws on a zone this browser does not know, and hands back the
    // canonical spelling of one it does.
    zone = new Intl.DateTimeFormat('en-US', { timeZone: name }).resolvedOptions().timeZone
  } catch {
    // A zone this browser's date library does not carry is no better than
    // none, and passing it on would throw on every date drawn.
    zone = undefined
  }
}

export function instanceTimezone(): string | undefined {
  return zone
}

// The month and the year, without the day. What a member card says about when
// somebody joined: how long they have been here is worth knowing and which
// Tuesday they signed up on is not.
export function formatMonth(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    timeZone: zone,
    month: 'long',
    year: 'numeric',
  })
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    timeZone: zone,
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

// A calendar date that was worked out rather than measured: the yyyy-mm-dd a
// week is keyed by, written the long way. The key is already a date in the
// instance's zone, so it is built and read in one zone rather than converted
// between two: UTC in and UTC out is the only pairing no offset can move by a
// day, and a Monday printed as the Sunday before it is the whole of the bug
// this avoids.
export function formatDayKey(key: string): string {
  const [year, month, day] = key.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(undefined, {
    timeZone: 'UTC',
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}

// A date short enough for a rail row: Aug 6. No year, because the only place
// this is read is a list of what was earned lately.
export function formatShortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    timeZone: zone,
    month: 'short',
    day: 'numeric',
  })
}

export function formatStart(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    timeZone: zone,
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

// The moment a thing was acquired, written short enough to sit under a plant in
// the plot: 08/08/26 12:00pm. Assembled from the parts rather than taken whole,
// because no locale writes the meridiem without a space in front of it. Read on
// the instance's clock like every other time on screen.
export function formatAcquired(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    year: '2-digit',
    month: '2-digit',
    day: '2-digit',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).formatToParts(new Date(iso))
  const found = new Map(parts.map((part) => [part.type, part.value]))
  const meridiem = (found.get('dayPeriod') ?? '').toLowerCase()
  return `${found.get('month')}/${found.get('day')}/${found.get('year')} ${found.get(
    'hour',
  )}:${found.get('minute')}${meridiem}`
}

// A time of day on its own: 1:47pm. Same assembly as formatAcquired and for the
// same reason, that no locale writes the meridiem without a space in front.
export function formatTimeOfDay(iso: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).formatToParts(new Date(iso))
  const found = new Map(parts.map((part) => [part.type, part.value]))
  const meridiem = (found.get('dayPeriod') ?? '').toLowerCase()
  return `${found.get('hour')}:${found.get('minute')}${meridiem}`
}

// The hour a moment falls on in the instance's zone, 0 to 23. Read from Intl
// for the same reason the day below is: Date's own getters answer in the
// browser's zone, and that is the zone this app does not trust. Midnight comes
// back as 24 from some engines, which the remainder puts back at 0.
export function zonedHour(iso: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    hour: 'numeric',
    hour12: false,
  }).formatToParts(new Date(iso))
  const hour = Number(parts.find((part) => part.type === 'hour')?.value)
  return isFinite(hour) ? hour % 24 : 0
}

// Monday first, which is how the weeks are counted here and on the server.
const WEEKDAY_ORDER = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// The calendar day a moment lands on in the instance's zone. Date's own getters
// answer in the browser's zone and there is no setter that takes another, so
// the parts come from Intl instead.
export interface ZonedDay {
  // yyyy-mm-dd, which is the same shape the server sends a week start in.
  key: string
  // Monday 0 through Sunday 6.
  weekday: number
}

export function zonedDay(value: Date | string): ZonedDay {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
  }).formatToParts(typeof value === 'string' ? new Date(value) : value)
  const found = new Map(parts.map((part) => [part.type, part.value]))
  return {
    key: `${found.get('year')}-${found.get('month')}-${found.get('day')}`,
    weekday: Math.max(0, WEEKDAY_ORDER.indexOf(found.get('weekday') ?? '')),
  }
}

// The Monday that starts the week a day falls in, yyyy-mm-dd. Counted back over
// calendar dates in UTC rather than over milliseconds, so the hour a clock
// change takes away cannot move a workout into the wrong week.
export function weekStartKey(day: ZonedDay): string {
  const [year, month, date] = day.key.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, date - day.weekday)).toISOString().slice(0, 10)
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

// How far along a bar something is, as a class rather than a width. The content
// security policy allows no inline styles, so a width worked out per render
// cannot be written onto the element: the fill point is snapped to the nearest
// twentieth and carried as one of the stylesheet's twenty-one steps. Five per
// cent is under half a millimetre of bar on a phone.
const FILL_STEP = 5

export function fillClass(percent: number): string {
  const part = isFinite(percent) ? percent : 0
  return `fill-${Math.min(100, Math.max(0, Math.round(part / FILL_STEP) * FILL_STEP))}`
}
