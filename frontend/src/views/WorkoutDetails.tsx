import { useEffect, useState } from 'react'
import {
  errorText,
  getWorkoutDetails,
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

// Where each of the five zones begins, as a share of the ceiling. Below half is
// not a zone: it is standing about, and it is left out of the bars rather than
// drawn as a sixth band nobody trains in.
const ZONE_FLOORS = [0.5, 0.6, 0.7, 0.8, 0.9]

// The heart rate chart's own coordinates. The height is also its height on the
// page, in pixels, so nothing about the vertical scale changes with the width
// of the column: only the horizontal stretches, and every stroke in it keeps
// its weight whatever it is stretched to.
const PLOT_W = 400
const PLOT_H = 150
// Room at the top and the bottom for the line's own thickness, so a peak
// touching the ceiling is not sliced in half by the edge of the box.
const PLOT_INSET = 3

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

// How many minutes were spent in each of the five bands. A minute is counted by
// its own average, which is the reading the chart above draws, and one below
// the first floor is counted nowhere.
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

// The air a session happened in, in the unit the account reads. Stored in
// Fahrenheit the way distance is stored in miles, so the conversion happens
// here on the way out.
function temperatureValue(fahrenheit: number, units: Units): string {
  return String(Math.round(units === 'metric' ? ((fahrenheit - 32) * 5) / 9 : fahrenheit))
}

// A split's pace as a bar: the quickest one fills the row and everything slower
// is shorter in proportion. One hue, because this is one measurement of one
// session rather than five things being told apart.
function SplitBar({ share }: { share: number }) {
  return (
    <span className="split-track">
      <span className={`split-fill ${fillClass(share * 100)}`} />
    </span>
  )
}

// The heart rate over the session: the average of each minute as a line, and
// the range that minute covered as a band behind it.
//
// One axis, three quiet rules, and no hover of any kind. The numbers themselves
// are in the splits table and in the figures at the top of the screen, which is
// where a value is read; this is the shape of the effort rather than a thing to
// interrogate, and a tooltip is not something a thumb can open anyway.
function HeartChart({ minutes, ceiling }: { minutes: WorkoutMinute[]; ceiling: number }) {
  const beating = minutes.filter((row) => typeof row.hr_avg === 'number')
  if (beating.length < 2) return null

  const first = beating[0].minute
  const last = beating[beating.length - 1].minute
  const across = last - first || 1
  // The floor is the quietest reading the session holds and the ceiling is the
  // highest, which is what makes the top of the axis the direct label for the
  // maximum rather than a round number near it.
  let floor = ceiling
  for (const row of beating) {
    floor = Math.min(floor, row.hr_min ?? row.hr_avg ?? floor)
  }
  const span = ceiling - floor || 1

  const atX = (minute: number) => ((minute - first) / across) * PLOT_W
  const atY = (beat: number) =>
    PLOT_H - PLOT_INSET - ((beat - floor) / span) * (PLOT_H - PLOT_INSET * 2)

  const line = beating
    .map((row) => `${atX(row.minute).toFixed(1)},${atY(row.hr_avg ?? floor).toFixed(1)}`)
    .join(' ')

  // The band is drawn only over the minutes that recorded both ends of a range,
  // out along the highs and back along the lows.
  const ranged = beating.filter(
    (row) => typeof row.hr_min === 'number' && typeof row.hr_max === 'number',
  )
  const highs = ranged.map(
    (row) => `${atX(row.minute).toFixed(1)},${atY(row.hr_max ?? 0).toFixed(1)}`,
  )
  const lows = ranged
    .map((row) => `${atX(row.minute).toFixed(1)},${atY(row.hr_min ?? 0).toFixed(1)}`)
    .reverse()
  const band = ranged.length > 1 ? `M${highs.join('L')}L${lows.join('L')}Z` : ''

  const middle = Math.round((floor + ceiling) / 2)

  return (
    <div className="hr-chart">
      {/* The axis is written in the page's own type rather than inside the
          drawing, so it stays the size the rest of the screen is read at
          whatever width the chart is stretched to. The top rung is the
          session's highest beat, which makes it the label for the peak. */}
      <div className="hr-axis">
        <span>Max {ceiling}</span>
        <span>{middle}</span>
        <span>{floor}</span>
      </div>
      <svg
        className="hr-plot"
        viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Heart rate over ${beating.length} minutes, ${floor} to ${ceiling} bpm`}
      >
        {/* Three rules and no more, at the top, the middle and the bottom of
            the range, which are the three the axis beside them names. */}
        {[PLOT_INSET, PLOT_H / 2, PLOT_H - PLOT_INSET].map((rule) => (
          <line key={rule} className="hr-grid" x1="0" y1={rule} x2={PLOT_W} y2={rule} />
        ))}
        {band !== '' && <path className="hr-band" d={band} />}
        <polyline className="hr-line" points={line} />
      </svg>
    </div>
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
  // What the bars are scaled against: the quickest split fills its row and
  // every slower one is shorter in proportion. Nought where there is nothing to
  // scale, which is a screen with no splits on it.
  const quickest = splits.reduce((best, split) => {
    const pace = secondsPerUnit(split, units)
    return pace > 0 && (best === 0 || pace < best) ? pace : best
  }, 0)
  const step = unitInMiles(units)

  const ceiling =
    typeof details.zone_max === 'number' && details.zone_max > 0 ? details.zone_max : null
  const spent = ceiling === null ? [] : zonesOf(minutes, ceiling)
  const inZones = spent.reduce((sum, band) => sum + band, 0)
  const longestZone = Math.max(...spent, 0)

  // Steps a minute is what a walk and a run are paced by. A bike sends the same
  // array and it means something else entirely there, so it is not drawn.
  const paced = item.activity === 'walk' || item.activity === 'run'
  const cadence = paced ? cadenceOf(minutes) : null

  // The highest beat the session saw, from the summary the export sent, and the
  // top of the chart's own axis, which is the highest reading it can draw. The
  // same number on every workout whose arrays and summary agree, and the higher
  // of the two where they do not.
  // What it was done in, where the row names a pair and the list handed down
  // holds it. A row that carries no pair, and a screen that was handed no
  // list, both resolve to nothing and draw no line at all.
  const shoes = gear.find((pair) => pair.id === item.gear_id)

  const peak = typeof details.max_hr === 'number' ? details.max_hr : null
  const beatingMinutes = minutes.filter((row) => typeof row.hr_avg === 'number').length
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
          {peak !== null && <Figure label="Max HR" value={String(peak)} unit="bpm" />}
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
          {typeof details.temperature_f === 'number' && (
            <Figure
              label="Temp"
              value={temperatureValue(details.temperature_f, units)}
              unit={units === 'metric' ? '°C' : '°F'}
            />
          )}
          {typeof details.humidity_pct === 'number' && (
            <Figure
              label="Humidity"
              value={String(Math.round(details.humidity_pct))}
              unit="%"
            />
          )}
        </div>

        {/* The pair it was done in, named the way every other pair in the app
            is named. One quiet line and no figure: the miles on a pair are
            read on the You screen, and nothing about shoes is a score. */}
        {shoes && (
          <p className="hint details-gear">
            <span className="sport-icon sport-icon-small">
              <Icon name="shoe" />
            </span>
            {gearName(shoes)}
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
              const whole = split.miles >= step - 0.0005
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
                  <span className="split-pace">
                    {formatPace(item.activity, split.miles, split.seconds, units)}
                  </span>
                  <SplitBar share={pace > 0 && quickest > 0 ? quickest / pace : 0} />
                  <span className="split-hr">
                    {split.avgHr === null ? '' : `${Math.round(split.avgHr)} bpm`}
                  </span>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {beatingMinutes > 1 && charted > 0 && (
        <section className="card">
          <h2 className="label">Heart rate</h2>
          <HeartChart minutes={minutes} ceiling={charted} />
        </section>
      )}

      {ceiling !== null && inZones > 0 && (
        <section className="card">
          <h2 className="label">Zones</h2>
          <ul className="zone-list">
            {spent.map((band, index) => (
              <li key={ZONE_FLOORS[index]} className="zone-row">
                <span className="zone-name">Z{index + 1}</span>
                <span className="zone-track">
                  <span
                    className={`zone-fill zone-fill-${index + 1} ${fillClass(
                      longestZone > 0 ? (band / longestZone) * 100 : 0,
                    )}`}
                  />
                </span>
                <span className="zone-minutes">{band} min</span>
              </li>
            ))}
          </ul>
          {/* Said plainly, because the two ladders are not the same claim: one
              is an estimate from an age and the other is the hardest this
              body has actually been seen working. */}
          <p className="hint">
            {details.zone_basis === 'age'
              ? `Bands of ${ceiling} bpm, estimated from age.`
              : `Bands of ${ceiling} bpm, the highest beat on record.`}
          </p>
        </section>
      )}
    </>
  )
}
