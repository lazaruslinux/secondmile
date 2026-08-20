import { useEffect, useRef, useState, type PointerEvent } from 'react'
import {
  errorText,
  getWorkoutDetails,
  type Activity,
  type FeedItem,
  type Gear,
  type Units,
  type WorkoutDetails as Details,
  type WorkoutMinute,
} from '../api.ts'
import {
  distanceValue,
  elevationUnit,
  elevationValue,
  FEET_PER_METRE,
  fillClass,
  formatClock,
  formatPace,
  formatStart,
  KM_PER_MILE,
  toDisplayDistance,
  unitName,
} from '../format.ts'
import { gearName } from '../gear.ts'
import { activityIcon, ACTIVITY_NAMES, defaultHeadline, personName } from '../labels.ts'
import { Figure } from './FeedCard.tsx'
import Icon from './Icon.tsx'
import RouteLine from './RouteLine.tsx'

// What the screen says where the charts would be, for a workout whose export
// never carried the arrays behind them. Every figure that does exist is still
// drawn above it, so this is one line rather than an empty screen.
const NO_MINUTES = 'No graph available. No data found.'

// The export writes one row a minute, and the rows are numbered from the start
// rather than stamped with a clock, so a minute is the whole of the timing this
// screen has to work from.
const MINUTE_S = 60

// Where each of the five zones begins, as a share of the ceiling. The standard
// model rather than the round tenths this screen first shipped with: Z1 is
// everything under sixty-five per cent, so the ladder starts at nothing and
// every minute the heart was recorded for lands on a band.
const ZONE_FLOORS = [0, 0.65, 0.81, 0.89, 0.97]

// What each band is for, in the words a training plan uses for it.
const ZONE_NAMES = ['Recovery', 'Endurance', 'Tempo', 'Threshold', 'Anaerobic']

// The floor a splits bar never goes under, so the slowest split of a session
// still reads as a bar rather than as nothing at all.
const SPLIT_FLOOR = 30

// How far short of a whole unit a split may fall and still be a whole one. The
// distances are summed out of four-decimal minutes, so the last hundredth of a
// mile arrives a rounding away from where arithmetic would put it.
const WHOLE_SPLIT = 0.0005

// Feet in a mile, for the one figure on this screen that is read in feet rather
// than in the distance the account is set to.
const FEET_PER_MILE = 5280

// Where the heat index is worth saying. The regression below is fitted for warm
// air and says nothing useful under it, and a feels-like within a degree or two
// of the thermometer is the thermometer said twice.
const HEAT_FLOOR_F = 80
const HEAT_MARGIN_F = 2

// A lane's own coordinates. The height is also its height on the page, in
// pixels, so nothing about the vertical scale changes with the width of the
// column: only the horizontal stretches, and every stroke in it keeps its
// weight whatever it is stretched to.
const PLOT_W = 400
const PLOT_H = 110
// Room at the top and the bottom for the line's own thickness, so a peak
// touching the ceiling is not sliced in half by the edge of the box.
const PLOT_INSET = 3

// What the readout says with nothing under the pointer. It is the instruction
// for the cursor as well as the line that keeps the row from collapsing when
// there is no reading to put in it.
const CURSOR_HINT = 'Drag across for the reading at a minute.'

interface Split {
  // First mile, second mile, and so on. Kilometres on a metric account.
  ordinal: number
  // How far it actually covered, in miles, whatever the account reads. A whole
  // split is one display unit; the last one is whatever was left over.
  miles: number
  seconds: number
  avgHr: number | null
}

// One display unit in miles: a mile, or a kilometre expressed as one.
function unitInMiles(units: Units): number {
  return units === 'metric' ? 1 / KM_PER_MILE : 1
}

// The session cut into miles or kilometres, from the distance each minute
// covered.
//
// The minutes are added up rather than read as a running total, and a minute
// that carries a boundary is divided at it: the seconds either side of the
// boundary are shared out in the proportion the distance was, which is the best
// a per-minute array can say about where a mile actually ended. A minute that
// covered nothing still spends its sixty seconds on the split it happened in,
// because standing at a crossing is part of the mile it happened in.
//
// The heart rate of a split is its minutes' own average weighted by how long
// each of them spent inside it, so a minute split across a boundary counts
// toward both in the proportion it belongs to each.
function splitsOf(minutes: WorkoutMinute[], units: Units): Split[] {
  const step = unitInMiles(units)
  const out: Split[] = []
  let covered = 0
  let seconds = 0
  let beats = 0
  let beatSeconds = 0
  let ordinal = 1

  for (const row of minutes) {
    let left = typeof row.distance_mi === 'number' && row.distance_mi > 0 ? row.distance_mi : 0
    let time = MINUTE_S
    const heart = typeof row.hr_avg === 'number' ? row.hr_avg : null

    // A fast minute on a bike can carry more than one boundary, so this closes
    // as many splits as the minute actually crossed.
    while (left > 0 && covered + left >= step) {
      const part = step - covered
      const took = time * (part / left)
      seconds += took
      if (heart !== null) {
        beats += heart * took
        beatSeconds += took
      }
      out.push({
        ordinal,
        miles: step,
        seconds,
        avgHr: beatSeconds > 0 ? beats / beatSeconds : null,
      })
      ordinal += 1
      covered = 0
      seconds = 0
      beats = 0
      beatSeconds = 0
      left -= part
      time -= took
    }

    covered += left
    seconds += time
    if (heart !== null) {
      beats += heart * time
      beatSeconds += time
    }
  }

  // Whatever the session ended part way through, at the distance it actually
  // reached rather than rounded up to a mile nobody ran. A tail shorter than a
  // hundredth of a unit is left off: it is the smallest thing the row could
  // print, and a split reading 0.00 is not a split.
  if (covered >= step / 100 && seconds > 0) {
    out.push({
      ordinal,
      miles: covered,
      seconds,
      avgHr: beatSeconds > 0 ? beats / beatSeconds : null,
    })
  }
  return out
}

// How long one split took per display unit, which is what the bars are scaled
// on and what makes a cycle's fastest split the fastest one here too: fewer
// seconds a mile is quicker, whichever way the pace itself is written.
function secondsPerUnit(split: Split, units: Units): number {
  const distance = toDisplayDistance(split.miles, units)
  return distance > 0 ? split.seconds / distance : 0
}

// Whether a split is a whole mile or kilometre rather than the tail a session
// ended on.
function isWhole(split: Split, units: Units): boolean {
  return split.miles >= unitInMiles(units) - WHOLE_SPLIT
}

// The quickest whole split of the session, or null where there are fewer than
// two whole ones. The tail is never it: a finish two tenths long is quicker per
// mile than any mile of the session on most runs, and calling that the fastest
// mile would be naming a mile nobody ran. One split on its own is not a
// comparison either, so it is left unmarked.
function fastestSplit(splits: Split[], units: Units): Split | null {
  const whole = splits.filter((split) => isWhole(split, units))
  if (whole.length < 2) return null
  return whole.reduce((best, split) =>
    secondsPerUnit(split, units) < secondsPerUnit(best, units) ? split : best,
  )
}

// The fastest split said in words, under the list that marks it. On foot the
// pace drops its /mi, because the sentence has already named the unit twice; a
// ride keeps its mph, which is the whole of what that number means.
function fastestLine(split: Split, activity: Activity, units: Units): string {
  const pace = formatPace(activity, split.miles, split.seconds, units)
  const said = activity === 'cycle' ? pace : pace.split(' ')[0]
  const word = units === 'metric' ? 'kilometer' : 'mile'
  return `Fastest ${word}: ${said} (${unitName(units)} ${split.ordinal})`
}

// Where one split sits in the range this workout actually ran: the quickest
// fills its row, the slowest keeps the floor, and everything between is spread
// evenly across the gap. Measuring every bar against the quickest split made a
// steady session read as five identical full bars, because five miles within
// four seconds of each other are ninety-nine per cent of one another.
//
// A workout with one split, or with every split inside a second of the rest,
// has no range to spread over, and every bar is full.
function splitShare(pace: number, fastest: number, slowest: number): number {
  if (!(pace > 0) || !(slowest - fastest >= 1)) return 100
  return 100 - (100 - SPLIT_FLOOR) * ((pace - fastest) / (slowest - fastest))
}

// How many minutes were spent in each of the five bands. A minute is counted by
// its own average, which is the reading the graph above draws.
function zonesOf(minutes: WorkoutMinute[], ceiling: number): number[] {
  const spent = [0, 0, 0, 0, 0]
  for (const row of minutes) {
    if (typeof row.hr_avg !== 'number') continue
    const share = row.hr_avg / ceiling
    for (let band = ZONE_FLOORS.length - 1; band >= 0; band -= 1) {
      if (share >= ZONE_FLOORS[band]) {
        spent[band] += 1
        break
      }
    }
  }
  return spent
}

// The beats one band covers at this account's ceiling: the share it starts at
// rounded up, and the beat below where the next band starts. The top band has
// no ceiling of its own, and the bottom one has no floor worth naming, so those
// two are written as the open ends they are.
function zoneRange(band: number, ceiling: number): string {
  const low = Math.ceil(ZONE_FLOORS[band] * ceiling)
  if (band === ZONE_FLOORS.length - 1) return `${low}+`
  const next = Math.ceil(ZONE_FLOORS[band + 1] * ceiling)
  return band === 0 ? `under ${next}` : `${low}-${next - 1}`
}

// Steps a minute, averaged over the minutes that recorded any. There is no
// cadence array in an export, whatever a watch shows on its own screen: steps
// in the minute is the reading that stands in for it, and on a walk or a run it
// is the same number.
function cadenceOf(minutes: WorkoutMinute[]): number | null {
  const counted = minutes.filter((row) => typeof row.steps === 'number' && row.steps > 0)
  if (counted.length === 0) return null
  const total = counted.reduce((sum, row) => sum + (row.steps ?? 0), 0)
  return total / counted.length
}

// Every step the session counted. Nought where the export carried no step
// array at all, which is every ride and every swim and some walks.
function stepsOf(minutes: WorkoutMinute[]): number {
  return minutes.reduce((sum, row) => sum + (typeof row.steps === 'number' ? row.steps : 0), 0)
}

// How far one step carried, averaged over the whole session: the distance the
// card says divided by the steps underneath it. Feet on an imperial account and
// metres on a metric one, which are the two units a stride is ever quoted in,
// and to the place each is read at: tenths of a foot, hundredths of a metre.
function strideText(miles: number, steps: number, units: Units): string {
  const feet = (miles * FEET_PER_MILE) / steps
  return units === 'metric' ? (feet / FEET_PER_METRE).toFixed(2) : feet.toFixed(1)
}

// What the air felt like, from what it was: the NOAA Rothfusz regression, in
// the Fahrenheit and whole per-cent it was fitted on. It is what a weather
// service means by feels like, and it is a fit rather than a measurement, so it
// is only ever quoted here in whole degrees.
//
// The two corrections are the National Weather Service's own, at the edges the
// fit is worst on: dry air, where it overstates the heat, and the humid low
// eighties, where it understates it.
function heatIndexF(temperature: number, humidity: number): number {
  const t = temperature
  const r = humidity
  let index =
    -42.379 +
    2.04901523 * t +
    10.14333127 * r -
    0.22475541 * t * r -
    0.00683783 * t * t -
    0.05481717 * r * r +
    0.00122874 * t * t * r +
    0.00085282 * t * r * r -
    0.00000199 * t * t * r * r
  if (r < 13 && t <= 112) {
    index -= ((13 - r) / 4) * Math.sqrt((17 - Math.abs(t - 95)) / 17)
  } else if (r > 85 && t <= 87) {
    index += ((r - 85) / 10) * ((87 - t) / 5)
  }
  return index
}

// A temperature in the unit the account reads. Fahrenheit is what the server
// stores, the way it stores distance in miles, so the conversion happens here
// on the way out.
function degreesText(fahrenheit: number, units: Units): string {
  const degrees = units === 'metric' ? ((fahrenheit - 32) * 5) / 9 : fahrenheit
  return `${Math.round(degrees)}${units === 'metric' ? '°C' : '°F'}`
}

// The air a session happened in, as one line rather than two figures: the
// temperature in the unit the account reads, and the humidity beside it. Either
// half stands on its own where the export carried only one of them, and neither
// leaves the line empty so the caller can drop the figure whole.
//
// Warm wet air gets a third clause, because on a day like that the thermometer
// is not what the session was run in. It needs both readings and it is left off
// unless it has something to add: cool air, dry air, and air the fit puts
// within a degree or two of the thermometer all say nothing.
function weatherLine(details: Details, units: Units): string {
  const temperature = details.temperature_f
  const humidity = details.humidity_pct
  const parts: string[] = []
  if (typeof temperature === 'number') {
    parts.push(degreesText(temperature, units))
  }
  if (typeof humidity === 'number') {
    parts.push(`${Math.round(humidity)}% Humidity`)
  }
  const line = parts.join(', ')
  if (line === '' || typeof temperature !== 'number' || typeof humidity !== 'number') return line
  if (temperature < HEAT_FLOOR_F) return line
  const feels = heatIndexF(temperature, humidity)
  if (feels - temperature < HEAT_MARGIN_F) return line
  return `${line} · Feels like ${degreesText(feels, units)}`
}

// A split's pace as a bar, spread across the range of the workout it belongs
// to. One hue, because this is one measurement of one session rather than five
// things being told apart.
function SplitBar({ percent }: { percent: number }) {
  return (
    <span className="split-track">
      <span className={`split-fill ${fillClass(percent)}`} />
    </span>
  )
}

type LaneKey = 'hr' | 'pace' | 'cadence'

// One lane of the graph: a series already turned into plot coordinates, the
// three labels that go beside it, and what it read at each minute. The readings
// are looked up by minute rather than by position, because a lane leaves out
// the minutes it has nothing to say about and the minute numbers are the one
// thing every lane shares.
interface Lane {
  key: LaneKey
  chip: string
  name: string
  summary: string
  line: string
  band: string
  labels: string[]
  said: Map<number, string>
}

// Plot coordinates down a lane's own scale. A lane can read the other way up:
// pace is drawn inverted, with the fewest seconds a mile at the top, because a
// quicker minute is the better minute and that is the way a pace chart is read.
function laneY(value: number, low: number, high: number, inverted: boolean): number {
  const span = high - low || 1
  const part = (value - low) / span
  const up = inverted ? 1 - part : part
  return PLOT_H - PLOT_INSET - up * (PLOT_H - PLOT_INSET * 2)
}

// A pace of so many seconds a display unit, written the way the app writes
// every other pace: minutes a mile on foot, and speed on a bike, which is the
// only way a cycling lane reads. One display unit at that many seconds is the
// same division the figure at the top of the screen does.
function paceText(seconds: number, activity: Activity, units: Units): string {
  return formatPace(activity, unitInMiles(units), seconds, units)
}

// The same figure without the unit, which is what goes down the side of a lane:
// naming /mi three times on one axis says nothing the readout does not.
function paceLabel(seconds: number, activity: Activity, units: Units): string {
  return paceText(seconds, activity, units).split(' ')[0]
}

// The lanes a workout has anything to draw, in the order they are stacked. A
// lane with fewer than two readings is not a line, and it is left out rather
// than drawn as a dot.
function lanesOf(
  minutes: WorkoutMinute[],
  activity: Activity,
  units: Units,
  ceiling: number,
  paced: boolean,
  atX: (minute: number) => number,
): Lane[] {
  const lanes: Lane[] = []

  // Heart rate: the average of each minute as a line, the range that minute
  // covered as a band behind it, and the session's highest beat as the top
  // rung, which is where the maximum is named now that no figure carries it.
  const beating = minutes.filter((row) => typeof row.hr_avg === 'number')
  if (beating.length > 1 && ceiling > 0) {
    let floor = ceiling
    for (const row of beating) {
      floor = Math.min(floor, row.hr_min ?? row.hr_avg ?? floor)
    }
    const at = (beat: number) => laneY(beat, floor, ceiling, false)
    // The band is drawn only over the minutes that recorded both ends of a
    // range, out along the highs and back along the lows.
    const ranged = beating.filter(
      (row) => typeof row.hr_min === 'number' && typeof row.hr_max === 'number',
    )
    const highs = ranged.map((row) => `${atX(row.minute).toFixed(1)},${at(row.hr_max ?? 0).toFixed(1)}`)
    const lows = ranged
      .map((row) => `${atX(row.minute).toFixed(1)},${at(row.hr_min ?? 0).toFixed(1)}`)
      .reverse()
    lanes.push({
      key: 'hr',
      chip: 'HR',
      name: 'Heart rate',
      summary: `Heart rate over ${beating.length} minutes, ${floor} to ${ceiling} bpm`,
      line: beating
        .map((row) => `${atX(row.minute).toFixed(1)},${at(row.hr_avg ?? floor).toFixed(1)}`)
        .join(' '),
      band: ranged.length > 1 ? `M${highs.join('L')}L${lows.join('L')}Z` : '',
      labels: [`Max ${ceiling}`, String(Math.round((floor + ceiling) / 2)), String(floor)],
      said: new Map<number, string>(
        beating.map((row) => [row.minute, `${Math.round(row.hr_avg ?? 0)} bpm`]),
      ),
    })
  }

  // Pace, worked out from the distance each minute covered: a minute is a
  // minute, so sixty seconds over what it covered is that minute's pace. A
  // minute that covered nothing has no pace at all, and it is left out rather
  // than drawn as an hour a mile that would flatten every other minute.
  const moving = minutes.filter((row) => typeof row.distance_mi === 'number' && row.distance_mi > 0)
  if (moving.length > 1) {
    const seconds = moving.map((row) => MINUTE_S / toDisplayDistance(row.distance_mi ?? 0, units))
    const fastest = Math.min(...seconds)
    const slowest = Math.max(...seconds)
    const at = (value: number) => laneY(value, fastest, slowest, true)
    lanes.push({
      key: 'pace',
      chip: 'Pace',
      name: 'Pace',
      summary: `Pace over ${moving.length} minutes, fastest ${paceText(
        fastest,
        activity,
        units,
      )}, slowest ${paceText(slowest, activity, units)}`,
      line: moving
        .map((row, index) => `${atX(row.minute).toFixed(1)},${at(seconds[index]).toFixed(1)}`)
        .join(' '),
      band: '',
      labels: [
        paceLabel(fastest, activity, units),
        paceLabel((fastest + slowest) / 2, activity, units),
        paceLabel(slowest, activity, units),
      ],
      said: new Map<number, string>(
        moving.map((row) => [row.minute, formatPace(activity, row.distance_mi ?? 0, MINUTE_S, units)]),
      ),
    })
  }

  // Cadence: the steps the minute counted, which is steps a minute. A bike
  // sends the same array and it means something else entirely there, so the
  // lane is drawn only for the sports it is a pace for, the same rule the
  // average cadence figure above already keeps.
  const stepping = paced
    ? minutes.filter((row) => typeof row.steps === 'number' && row.steps > 0)
    : []
  if (stepping.length > 1) {
    const counts = stepping.map((row) => row.steps ?? 0)
    const low = Math.min(...counts)
    const high = Math.max(...counts)
    const at = (value: number) => laneY(value, low, high, false)
    lanes.push({
      key: 'cadence',
      chip: 'Cadence',
      name: 'Cadence',
      summary: `Cadence over ${stepping.length} minutes, ${low} to ${high} steps a minute`,
      line: stepping
        .map((row, index) => `${atX(row.minute).toFixed(1)},${at(counts[index]).toFixed(1)}`)
        .join(' '),
      band: '',
      labels: [String(high), String(Math.round((low + high) / 2)), String(low)],
      said: new Map<number, string>(
        stepping.map((row) => [row.minute, `${Math.round(row.steps ?? 0)} spm`]),
      ),
    })
  }

  return lanes
}

// The graph: up to three lanes over one time axis, with one cursor across all
// of them.
//
// Each lane keeps its own true scale. A beat, a pace and a step count are three
// different measurements, and the only honest way to stack them is to give each
// one its own axis and share nothing but the minutes underneath.
//
// The cursor is written straight onto the drawing rather than rendered: the
// rule's x and the readout's words are set as attributes and text content
// through refs. The content security policy allows no inline styles, so a
// position worked out per pointer event has nowhere else to go, and a render a
// frame is not what React is for either.
function LaneGraph({
  minutes,
  activity,
  units,
  ceiling,
  paced,
}: {
  minutes: WorkoutMinute[]
  activity: Activity
  units: Units
  ceiling: number
  paced: boolean
}) {
  const [shown, setShown] = useState<Record<LaneKey, boolean>>({
    hr: true,
    pace: true,
    cadence: true,
  })
  const plots = useRef(new Map<LaneKey, SVGSVGElement>())
  const rules = useRef(new Map<LaneKey, SVGLineElement>())
  const readout = useRef<HTMLParagraphElement>(null)

  const first = minutes[0]?.minute ?? 0
  const last = minutes[minutes.length - 1]?.minute ?? 0
  const across = last - first || 1
  const atX = (minute: number) => ((minute - first) / across) * PLOT_W
  const lanes = lanesOf(minutes, activity, units, ceiling, paced, atX)
  if (lanes.length === 0) return null

  function clearCursor() {
    for (const rule of rules.current.values()) {
      rule.setAttribute('visibility', 'hidden')
    }
    if (readout.current) readout.current.textContent = CURSOR_HINT
  }

  // Where the pointer is, as the minute nearest it, drawn in every lane at
  // once. Every lane's plot sits in the same column at the same width, so one
  // of their boxes is every lane's box and the rule lands at the same x in all
  // of them.
  function readAt(event: PointerEvent<HTMLDivElement>) {
    const plot = plots.current.values().next().value
    if (!plot) return
    const box = plot.getBoundingClientRect()
    if (box.width <= 0) return
    const part = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width))
    const minute = first + Math.round(part * across)
    const x = atX(minute).toFixed(1)
    for (const rule of rules.current.values()) {
      rule.setAttribute('x1', x)
      rule.setAttribute('x2', x)
      rule.setAttribute('visibility', 'visible')
    }
    // A row is a whole minute rather than an instant, so the reading is named
    // at the middle of the minute it came out of rather than at either end.
    const parts = [formatClock(minute * MINUTE_S + MINUTE_S / 2)]
    for (const lane of lanes) {
      const value = shown[lane.key] ? lane.said.get(minute) : undefined
      if (value !== undefined) parts.push(value)
    }
    if (readout.current) readout.current.textContent = parts.join(' · ')
  }

  return (
    <section className="card">
      <h2 className="label">Minute by minute</h2>

      {/* One chip a lane, and only for a lane there is something to draw. Plain
          state: which lanes are showing is not worth remembering between one
          screen and the next. A single lane needs no chip to turn it off. */}
      {lanes.length > 1 && (
        <ul className="filter-chips">
          {lanes.map((lane) => {
            const on = shown[lane.key]
            return (
              <li key={lane.key}>
                <button
                  type="button"
                  className={on ? 'filter-chip filter-chip-on' : 'filter-chip'}
                  aria-pressed={on}
                  onClick={() => {
                    setShown({ ...shown, [lane.key]: !on })
                    // A lane arriving or leaving would leave the rule half
                    // drawn and the readout naming a lane that is gone.
                    clearCursor()
                  }}
                >
                  {lane.chip}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <p className="lane-readout" role="status" ref={readout}>
        {CURSOR_HINT}
      </p>

      <div
        className="lane-stack"
        onPointerDown={(event) => {
          // Capture, so a thumb dragging off the edge of one lane keeps
          // reading rather than handing the drag back to the page.
          event.currentTarget.setPointerCapture(event.pointerId)
          readAt(event)
        }}
        onPointerMove={readAt}
        onPointerLeave={clearCursor}
        onPointerCancel={clearCursor}
      >
        {lanes
          .filter((lane) => shown[lane.key])
          .map((lane) => (
            <div className="lane" key={lane.key}>
              <p className="lane-name">{lane.name}</p>
              <div className="lane-body">
                {/* The axis is written in the page's own type rather than
                    inside the drawing, so it stays the size the rest of the
                    screen is read at whatever width the lane is stretched
                    to. */}
                <div className="lane-axis">
                  {lane.labels.map((text, index) => (
                    <span key={index}>{text}</span>
                  ))}
                </div>
                <svg
                  className="lane-plot"
                  viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
                  preserveAspectRatio="none"
                  role="img"
                  aria-label={lane.summary}
                  ref={(el) => {
                    if (el) plots.current.set(lane.key, el)
                    else plots.current.delete(lane.key)
                  }}
                >
                  {/* Three rules and no more, at the top, the middle and the
                      bottom of the range, which are the three the axis beside
                      them names. */}
                  {[PLOT_INSET, PLOT_H / 2, PLOT_H - PLOT_INSET].map((rule) => (
                    <line key={rule} className="lane-grid" x1="0" y1={rule} x2={PLOT_W} y2={rule} />
                  ))}
                  {lane.band !== '' && <path className="lane-band" d={lane.band} />}
                  <polyline className="lane-line" points={lane.line} />
                  <line
                    className="lane-cursor"
                    x1="0"
                    y1="0"
                    x2="0"
                    y2={PLOT_H}
                    visibility="hidden"
                    ref={(el) => {
                      if (el) rules.current.set(lane.key, el)
                      else rules.current.delete(lane.key)
                    }}
                  />
                </svg>
              </div>
            </div>
          ))}
      </div>
    </section>
  )
}

interface Props {
  // The row the card was drawn from, handed over rather than fetched again:
  // everything in the header and half the figures are already on it.
  item: FeedItem
  // The account's own shoes, handed down from the screen that opened the card
  // rather than fetched here. Empty from a friend's profile, where the rows
  // carry no pair anyway.
  gear: Gear[]
  units: Units
  onBack: () => void
}

// The screen behind a card: the same workout, said minute by minute.
//
// Nothing here can be edited and nothing here earns anything. It is a reading
// of a session that already happened, and the only reason any of it is stored
// is this screen.
export default function WorkoutDetails({ item, gear, units, onBack }: Props) {
  const [details, setDetails] = useState<Details | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    let live = true
    setLoading(true)
    getWorkoutDetails(item.workout_id)
      .then((found) => {
        if (!live) return
        setDetails(found)
        setLoadError('')
      })
      .catch((err: unknown) => {
        if (live) setLoadError(errorText(err))
      })
      .finally(() => {
        if (live) setLoading(false)
      })
    return () => {
      live = false
    }
  }, [item.workout_id])

  const head = (
    <div className="view-head">
      <h1 className="view-title">Details</h1>
      <button type="button" className="secondary" onClick={onBack}>
        Back
      </button>
    </div>
  )

  if (loading) {
    return (
      <>
        {head}
        <p className="notice">Loading.</p>
      </>
    )
  }

  // The way back is drawn even when nothing else could be: a screen reached by
  // a tap has to be leavable by one.
  if (!details) {
    return (
      <>
        {head}
        <p className="error" role="alert">
          {loadError || 'Something went wrong. Try again.'}
        </p>
      </>
    )
  }

  const activityName = ACTIVITY_NAMES[item.activity]
  const given = (item.title ?? '').trim()
  const headline = given === '' ? defaultHeadline(item.activity, item.start_ts) : given
  const when =
    given === '' ? formatStart(item.start_ts) : `${activityName}, ${formatStart(item.start_ts)}`

  const minutes = Array.isArray(details.minutes) ? details.minutes : []
  const splits = splitsOf(minutes, units)
  // The range the bars are spread across: this workout's own quickest and
  // slowest split, rather than the quickest one alone. Nought on a screen with
  // no splits on it, which draws no bars either way.
  const paces = splits.map((split) => secondsPerUnit(split, units)).filter((pace) => pace > 0)
  const fastest = paces.length > 0 ? Math.min(...paces) : 0
  const slowest = paces.length > 0 ? Math.max(...paces) : 0
  // The quickest whole split, which the bars alone do not name: the tail is in
  // the range above and is never the one marked.
  const quickest = fastestSplit(splits, units)

  const ceiling =
    typeof details.zone_max === 'number' && details.zone_max > 0 ? details.zone_max : null
  const spent = ceiling === null ? [] : zonesOf(minutes, ceiling)
  const inZones = spent.reduce((sum, band) => sum + band, 0)
  const longestZone = Math.max(...spent, 0)
  // Hardest at the top, which is the way a zone ladder is drawn and the way the
  // crimson beside it darkens.
  const ladder = spent.map((_, index) => spent.length - 1 - index)

  // Steps a minute is what a walk and a run are paced by. A bike sends the same
  // array and it means something else entirely there, so it is not drawn.
  const paced = item.activity === 'walk' || item.activity === 'run'
  const cadence = paced ? cadenceOf(minutes) : null

  // How long a stride was, on the two sports it is a stride on. It needs both
  // halves of the division, so a session whose export carried no steps has none
  // and the figure is not drawn.
  const steps = paced ? stepsOf(minutes) : 0
  const stride =
    steps > 0 && item.distance_mi > 0 ? strideText(item.distance_mi, steps, units) : null

  const weather = weatherLine(details, units)

  // What it was done in, where the row names a pair and the list handed down
  // holds it. A row that carries no pair, and a screen that was handed no
  // list, both resolve to nothing and draw no line at all.
  const shoes = gear.find((pair) => pair.id === item.gear_id)
  // Everything the pair has covered, this session included. The server works it
  // out on every read of the gear list and it arrives on the list handed down,
  // so nothing is fetched for it here. Whole units, the way the You screen
  // writes it: this is wear on a shoe rather than a figure anybody is measuring
  // themselves against.
  const odometer =
    shoes && shoes.miles > 0
      ? `${Math.round(toDisplayDistance(shoes.miles, units)).toLocaleString()} ${unitName(
          units,
        )} total`
      : ''

  // The highest beat the session saw, from the summary the export sent, and the
  // top of the heart rate lane's own axis, which is the highest reading it can
  // draw. The same number on every workout whose arrays and summary agree, and
  // the higher of the two where they do not. No figure carries it any more: the
  // lane's top rung is where the maximum is named.
  const peak = typeof details.max_hr === 'number' ? details.max_hr : null
  const charted = minutes.reduce(
    (highest, row) => Math.max(highest, row.hr_max ?? row.hr_avg ?? 0),
    peak ?? 0,
  )

  return (
    <>
      {head}

      <article className="card">
        <p className="feed-name">{personName(item.user)}</p>
        <p className="feed-when">{when}</p>
        <h2 className="feed-title">
          <span className="sport-icon">
            <Icon name={activityIcon(item.activity, item.indoor)} />
          </span>
          {headline}
        </h2>

        {/* The card's own figures, and the ones a card has no room for. What
            the owner keeps back never arrives, so it is simply not drawn: the
            rule is the card's and it is not restated here. */}
        <div className="stat-row">
          <Figure
            label="Distance"
            value={distanceValue(item.distance_mi, units)}
            unit={unitName(units)}
          />
          <Figure label="Time" value={formatClock(item.duration_s)} />
          <Figure
            label="Pace"
            value={formatPace(item.activity, item.distance_mi, item.duration_s, units)}
          />
          {typeof item.active_kcal === 'number' && (
            <Figure label="Calories" value={String(Math.round(item.active_kcal))} />
          )}
          {typeof item.avg_hr === 'number' && (
            <Figure label="Avg. HR" value={String(Math.round(item.avg_hr))} unit="bpm" />
          )}
          {!item.indoor && typeof item.elevation_gain_ft === 'number' && (
            <Figure
              label="Elev. gain"
              value={elevationValue(item.elevation_gain_ft, units)}
              unit={elevationUnit(units)}
            />
          )}
          {cadence !== null && (
            <Figure label="Avg cadence" value={String(Math.round(cadence))} unit="spm" />
          )}
          {stride !== null && (
            <Figure label="Stride" value={stride} unit={units === 'metric' ? 'm' : 'ft'} />
          )}
          {/* The air, as one line. It is a sentence rather than a number, so it
              takes the width of the row instead of being set smaller than the
              figures beside it. */}
          {weather !== '' && <Figure label="Weather" value={weather} wide />}
        </div>

        {/* The pair it was done in, named the way every other pair in the app
            is named, with what is on them beside it. One quiet line and no
            figure: nothing about shoes is a score, and the odometer is here
            because a session is where somebody wonders how far a pair has
            gone. */}
        {shoes && (
          <p className="hint details-gear">
            <span className="sport-icon sport-icon-small">
              <Icon name="shoe" />
            </span>
            {odometer === '' ? gearName(shoes) : `${gearName(shoes)} · ${odometer}`}
          </p>
        )}

        {/* The card's own map, in the place the card puts it. The line is the
            way into the full map, the same as it is on the feed. */}
        {item.has_route && <RouteLine workoutId={item.workout_id} />}
      </article>

      {minutes.length === 0 && <p className="hint">{NO_MINUTES}</p>}

      {splits.length > 0 && (
        <section className="card">
          <h2 className="label">Splits</h2>
          <ul className="split-list">
            {splits.map((split) => {
              const pace = secondsPerUnit(split, units)
              const whole = isWhole(split, units)
              const best = quickest !== null && split.ordinal === quickest.ordinal
              return (
                <li key={split.ordinal} className="split-row">
                  {/* A last split that ended part way through says how far it
                      actually went, in the place the whole ones say which one
                      they are: a row reading quicker than the one above it is
                      then accounted for rather than confusing. */}
                  <span className={whole ? 'split-ordinal' : 'split-ordinal split-part'}>
                    {whole
                      ? split.ordinal
                      : `${distanceValue(split.miles, units)} ${unitName(units)}`}
                  </span>
                  {/* The quickest whole split is marked on its own pace, which
                      is the figure the mark is about. Colour and nothing else,
                      because the line under the list names it in words. */}
                  <span className={best ? 'split-pace split-fastest' : 'split-pace'}>
                    {formatPace(item.activity, split.miles, split.seconds, units)}
                  </span>
                  <SplitBar percent={splitShare(pace, fastest, slowest)} />
                  <span className="split-hr">
                    {split.avgHr === null ? '' : `${Math.round(split.avgHr)} bpm`}
                  </span>
                </li>
              )
            })}
          </ul>
          {quickest !== null && (
            <p className="hint">{fastestLine(quickest, item.activity, units)}</p>
          )}
        </section>
      )}

      <LaneGraph
        minutes={minutes}
        activity={item.activity}
        units={units}
        ceiling={charted}
        paced={paced}
      />

      {ceiling !== null && inZones > 0 && (
        <section className="card">
          <h2 className="label">Zones</h2>
          <ul className="zone-list">
            {ladder.map((band) => (
              <li key={band} className="zone-row">
                <span className="zone-name">{`Z${band + 1} ${ZONE_NAMES[band]}`}</span>
                <span className="zone-band">{zoneRange(band, ceiling)}</span>
                <span className="zone-track">
                  <span
                    className={`zone-fill zone-fill-${band + 1} ${fillClass(
                      longestZone > 0 ? (spent[band] / longestZone) * 100 : 0,
                    )}`}
                  />
                </span>
                {/* The minutes and the share of the session they were, the way
                    a card counts its hypes and its comments. */}
                <span className="zone-minutes">
                  {`${spent[band]} min · ${Math.round((spent[band] / inZones) * 100)}%`}
                </span>
              </li>
            ))}
          </ul>
          {/* Said plainly, because the two ladders are not the same claim: one
              is an estimate from an age and the other is the hardest this
              body has actually been seen working. */}
          <p className="hint">
            {details.zone_basis === 'age'
              ? `Ranges from a ceiling of ${ceiling} bpm, estimated from age.`
              : `Ranges from a ceiling of ${ceiling} bpm, the highest beat on record.`}
          </p>
        </section>
      )}
    </>
  )
}
