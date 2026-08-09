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

// Adjusted miles on screen: one decimal, and never converted, whether the word
// beside it is miles on the profile or XP on a workout card. They are the same
// number in every account.
export function convertedValue(miles: number): string {
  return miles.toFixed(1)
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

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    timeZone: zone,
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

// What the instance's clock read at a moment, expressed as the milliseconds a
// UTC clock would need to show the same figures. The gap between that and the
// moment itself is the zone's offset, which is the only way to say which
// instant a wall-clock reading names.
function zonedReading(at: Date): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    // h23 rather than hour12: false, which renders midnight as 24 in some
    // browsers and would put the reading on the wrong day.
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(at)
  const found = new Map(parts.map((part) => [part.type, Number(part.value)]))
  return Date.UTC(
    found.get('year') ?? 0,
    (found.get('month') ?? 1) - 1,
    found.get('day') ?? 1,
    found.get('hour') ?? 0,
    found.get('minute') ?? 0,
    found.get('second') ?? 0,
  )
}

// A moment in the shape a datetime-local input reads and writes, yyyy-mm-ddThh:mm,
// on the instance's clock rather than the browser's.
export function zonedInputValue(at: Date): string {
  return new Date(zonedReading(at)).toISOString().slice(0, 16)
}

// The moment a datetime-local reading names, taken as the instance's clock.
// Corrected twice: the offset at the first guess is the wrong one for a reading
// that falls the far side of a clock change.
export function instantFromZonedInput(reading: string): Date {
  // Trimmed to yyyy-mm-ddThh:mm: some browsers hand back seconds as well, and
  // the suffix below already supplies them.
  const naive = Date.parse(`${reading.slice(0, 16)}:00Z`)
  if (isNaN(naive)) return new Date(NaN)
  let at = new Date(naive)
  for (let pass = 0; pass < 2; pass += 1) {
    at = new Date(at.getTime() + (naive - zonedReading(at)))
  }
  return at
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
