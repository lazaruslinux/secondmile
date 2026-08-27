import { useEffect, useRef, useState, type PointerEvent } from 'react'
import {
  errorText,
  getInsights,
  type Activity as Sport,
  type InsightBucket,
  type Insights as Band,
  type PrTier,
  type SportInsights,
  type Units,
} from '../api.ts'
import {
  distanceBrief,
  distanceValue,
  elevationUnit,
  elevationValue,
  formatClock,
  formatDate,
  formatDayKey,
  formatMonthKey,
  formatPace,
  formatShortDayKey,
  KM_PER_MILE,
  toDisplayDistance,
  unitName,
} from '../format.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER, PR_TIER_NAMES } from '../labels.ts'
import { Figure } from './FeedCard.tsx'
import Icon from './Icon.tsx'

type Span = 'weeks' | 'months'

type ChartKey = 'distance' | 'elevation' | 'pace'

// Whether the band was left open on this device. Per device rather than per
// account, the same as the view toggle above it: it is a preference about a
// screen rather than a fact about a history.
const OPEN_KEY = 'secondmile.activity.insights.open'

// What the shut band offers. One line, and only while it is shut: open, the
// charts say it themselves.
const TEASER = 'Tap to open.'

// The plot's own coordinates, the same ones the minutes behind a workout are
// drawn in. The height is also its height on the page, in pixels, so nothing
// about the vertical scale changes with the width of the column: only the
// horizontal stretches, and every stroke in it keeps its weight.
const PLOT_W = 400
const PLOT_H = 110
// The top rung and the bottom one. The bottom is a rung short of the floor so
// its own hairline is drawn inside the box rather than half outside it, and the
// bars are taken past it to the edge, where the viewport cuts them square: a
// round cap gives them the top they want and nothing at the foot.
const TOP = 3
const BASE = 109

// How close the fastest and the slowest bucket have to be before the pace they
// span is one pace rather than a range. A tenth of a second is a tenth of what
// a pace is ever printed to, so nothing under it could be told apart at either
// end of the axis anyway.
const FLAT_PACE_S = 0.1

// What the readout says with nothing under the pointer, which is also what
// holds its row so the charts do not jump when a thumb lands on them.
const HINT: Record<Span, string> = {
  weeks: 'Drag across for detailed view.',
  months: 'Drag across for detailed view.',
}

const SPANS: { key: Span; word: string }[] = [
  { key: 'weeks', word: 'Weeks' },
  { key: 'months', word: 'Months' },
]

// What each best is called on its tile: the shared names, so a tile and the
// standing on a card never disagree about what a distance is called. A tier
// nobody has covered yet draws no tile at all.
const PR_NAMES = PR_TIER_NAMES

// How far each of them is, in miles, mirrored from the server. The time comes
// down and the pace is worked out here, so a metric account reads its own
// figure without the server having to know which one it is.
const PR_MILES: Record<PrTier, number> = {
  '5k': 3.1,
  '10k': 6.2,
  half: 13.1,
  marathon: 26.2,
}

const PR_TIERS = Object.keys(PR_NAMES) as PrTier[]

interface Chart {
  key: ChartKey
  name: string
  // What a reader who cannot see the drawing is told it holds.
  summary: string
  // A bar chart draws its buckets and a trend draws one line through them;
  // no chart here draws both.
  bars: { key: string; x: number; y: number }[]
  line: string
  labels: string[]
}

function rememberedOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === 'open'
  } catch {
    // A browser with storage turned off simply opens on the shut band, which is
    // where a first visit starts anyway.
    return false
  }
}

function rememberOpen(open: boolean): void {
  try {
    localStorage.setItem(OPEN_KEY, open ? 'open' : 'shut')
  } catch {
    // Nothing to say: the choice holds for this visit and is forgotten after.
  }
}

// One display unit in miles: a mile, or a kilometre expressed as one. What a
// pace is per, so the trend is read in the unit the account is set to.
function unitInMiles(units: Units): number {
  return units === 'metric' ? 1 / KM_PER_MILE : 1
}

// Seconds per display unit as the account reads a pace: minutes and seconds on
// foot, speed on a bike, which is the rule every other pace in the app keeps.
function paceText(seconds: number, sport: Sport, units: Units): string {
  return formatPace(sport, unitInMiles(units), seconds, units)
}

// The same figure without its unit, for an axis whose rungs are all the one
// measurement.
function paceLabel(seconds: number, sport: Sport, units: Units): string {
  return paceText(seconds, sport, units).split(' ')[0]
}

// The pace axis, top to bottom. The middle rung says nothing when it rounds to
// a figure already printed at one of the ends: an axis prints a figure once,
// and the same number twice down one column reads as a broken chart rather
// than as a steady one.
function paceAxis(
  fastest: number,
  slowest: number,
  sport: Sport,
  units: Units,
): string[] {
  const top = paceLabel(fastest, sport, units)
  const foot = paceLabel(slowest, sport, units)
  const middle = paceLabel((fastest + slowest) / 2, sport, units)
  return [top, middle === top || middle === foot ? '' : middle, foot]
}

// A bucket's own average pace, in seconds per display unit, or null for a
// bucket that covered nothing to have a pace over.
function paceOf(bucket: InsightBucket, units: Units): number | null {
  const distance = toDisplayDistance(bucket.miles, units)
  if (!(distance > 0) || !(bucket.seconds > 0)) return null
  return bucket.seconds / distance
}

// What a bucket is called: the Monday it starts, or the month it is. Built from
// the key in UTC rather than converted, because the key is already a date in
// the instance's zone and reading it in another could move it a day.
function bucketName(bucket: InsightBucket, span: Span): string {
  return span === 'weeks' ? formatDayKey(bucket.start) : formatMonthKey(bucket.start)
}

function bucketTick(bucket: InsightBucket, span: Span): string {
  return span === 'weeks' ? formatShortDayKey(bucket.start) : formatMonthKey(bucket.start)
}

// Where a bucket sits across the plot: the middle of its own share of the
// width, so a bar stands over the stretch of time it adds up.
function atX(index: number, count: number): number {
  return ((index + 0.5) / count) * PLOT_W
}

// Where a value sits between the two rungs. A bar chart is measured from
// nothing, because a quiet week drawn as half a good one is not a reading.
function atY(value: number, top: number): number {
  if (!(top > 0)) return BASE
  return BASE - (Math.max(0, value) / top) * (BASE - TOP)
}

// The charts for one sport over one run of buckets, in the order they are read:
// how far, how much climbing, and how fast. Each keeps its own scale and its
// own axis, because distance, height and pace are three measurements and there
// is no honest axis all three sit on.
function chartsOf(
  buckets: InsightBucket[],
  sport: Sport,
  units: Units,
  span: Span,
): Chart[] {
  const charts: Chart[] = []
  const miles = buckets.map((bucket) => bucket.miles)
  const furthest = Math.max(...miles)
  if (furthest > 0) {
    charts.push({
      key: 'distance',
      name: 'Distance',
      summary: `Distance in each of the last ${buckets.length} ${span}, up to ${distanceBrief(
        furthest,
        units,
      )} ${unitName(units)}`,
      bars: buckets
        .map((bucket, index) => ({
          key: bucket.start,
          x: atX(index, buckets.length),
          y: atY(miles[index], furthest),
        }))
        .filter((_, index) => miles[index] > 0),
      line: '',
      labels: [
        distanceBrief(furthest, units),
        distanceBrief(furthest / 2, units),
        '0',
      ],
    })
  }

  // Only where there is climbing to draw. A sport done on the flat, or one
  // whose exports never carried a climb, is not given an empty chart to
  // explain.
  const climbs = buckets.map((bucket) => bucket.elevation_ft)
  const highest = Math.max(...climbs)
  if (highest > 0) {
    charts.push({
      key: 'elevation',
      name: 'Climb',
      summary: `Climb in each of the last ${buckets.length} ${span}, up to ${elevationValue(
        highest,
        units,
      )} ${elevationUnit(units)}`,
      bars: buckets
        .map((bucket, index) => ({
          key: bucket.start,
          x: atX(index, buckets.length),
          y: atY(climbs[index], highest),
        }))
        .filter((_, index) => climbs[index] > 0),
      line: '',
      labels: [elevationValue(highest, units), elevationValue(highest / 2, units), '0'],
    })
  }

  // The trend rather than the buckets, so it is a line: pace is a rate, and a
  // rate drawn as a bar from nothing would be a chart of how far zero is.
  const paces = buckets.map((bucket) => paceOf(bucket, units))
  const known = paces.filter((pace): pace is number => pace !== null)
  if (known.length > 1) {
    const fastest = Math.min(...known)
    const slowest = Math.max(...known)
    // A season held at one pace is not a range. Drawn as one, a fraction of a
    // second either way would be spread up and down the whole plot as though it
    // were a story. Two ways to be level: a spread under what a pace is read to
    // at all, or two ends that print the same figure, which is the same thing
    // said by the formatter rather than by the numbers. Either way the domain
    // opens out around the middle, so the line draws flat across the centre
    // with the one figure it actually is beside it.
    const level =
      slowest - fastest < FLAT_PACE_S ||
      paceLabel(fastest, sport, units) === paceLabel(slowest, sport, units)
    const middle = (fastest + slowest) / 2
    // Fastest at the top, which is the way round a pace is read: fewer seconds
    // a mile is the better one, and a line that fell as it improved would say
    // the opposite of what it means.
    const at = (pace: number) =>
      BASE - (level ? 0.5 : 1 - (pace - fastest) / (slowest - fastest)) * (BASE - TOP)
    charts.push({
      key: 'pace',
      name: 'Pace',
      summary: level
        ? `Pace over the last ${buckets.length} ${span}, level at ${paceText(
            middle,
            sport,
            units,
          )}`
        : `Pace over the last ${buckets.length} ${span}, fastest ${paceText(
            fastest,
            sport,
            units,
          )}, slowest ${paceText(slowest, sport, units)}`,
      bars: [],
      // A bucket that covered nothing has no pace and is not a point on the
      // line. The line closes over it rather than breaking, the same way the
      // pace lane behind a workout closes over a minute spent standing still.
      line: paces
        .map((pace, index) =>
          pace === null ? '' : `${atX(index, buckets.length).toFixed(1)},${at(pace).toFixed(1)}`,
        )
        .filter((point) => point !== '')
        .join(' '),
      // The one figure on the middle rung where the flat line is drawn, or the
      // range's own three.
      labels: level
        ? ['', paceLabel(middle, sport, units), '']
        : paceAxis(fastest, slowest, sport, units),
    })
  }

  return charts
}

// Whether this sport has set any of the bests. The four tiers are not asked
// about: a tier is qualified for by a workout that carried a distance, and so
// is the longest, so a history with no longest has no tier either.
function anyBest(insights: SportInsights): boolean {
  const { longest, best_week, biggest_climb } = insights.prs
  return longest !== null || best_week !== null || biggest_climb !== null
}

interface Props {
  units: Units
}

// The band above the history: twelve weeks or twelve months of one sport, the
// bests behind them.
//
// Nothing here is earned or spent and nothing here is anybody else's. It reads
// what the history already holds, for the person whose history it is.
export default function Insights({ units }: Props) {
  const [open, setOpen] = useState(rememberedOpen)
  const [band, setBand] = useState<Band | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [chosen, setChosen] = useState<Sport | null>(null)
  const [span, setSpan] = useState<Span>('weeks')

  // Asked for once, the first time the band is opened: somebody who never opens
  // it never spends the request.
  const asked = useRef(false)
  const plots = useRef(new Map<ChartKey, SVGSVGElement>())
  const rules = useRef(new Map<ChartKey, SVGLineElement>())
  const readout = useRef<HTMLParagraphElement>(null)
  // The bucket a tap settled on, by its place in the run. A finger that lifts
  // has not stopped reading, so the choice outlives the gesture; null is nothing
  // chosen, which is what the hint line and a passing hover both are.
  const pinned = useRef<number | null>(null)

  useEffect(() => {
    if (!open || asked.current) return
    asked.current = true
    setLoading(true)
    setLoadError('')
    getInsights()
      .then(setBand)
      .catch((err) => {
        // Shutting the band and opening it again is what tries again: there is
        // nothing else here to press.
        asked.current = false
        setLoadError(errorText(err))
      })
      .finally(() => setLoading(false))
  }, [open])

  function toggle() {
    const next = !open
    setOpen(next)
    rememberOpen(next)
  }

  // Only the sports there is anything to draw for, in the order every screen
  // lists the four in. The one chosen holds until it is no longer one of them.
  const sports = band === null ? [] : ACTIVITY_ORDER.filter((name) => band[name] !== undefined)
  const sport = chosen !== null && sports.includes(chosen) ? chosen : (sports[0] ?? null)
  const insights = band === null || sport === null ? null : (band[sport] ?? null)
  const buckets = insights === null ? [] : span === 'weeks' ? insights.weekly : insights.monthly
  const charts = insights === null || sport === null ? [] : chartsOf(buckets, sport, units, span)

  function clearCursor() {
    pinned.current = null
    for (const rule of rules.current.values()) {
      rule.setAttribute('visibility', 'hidden')
    }
    if (readout.current) readout.current.textContent = HINT[span]
  }

  // One bucket, drawn in every chart at once. Every chart sits in the same
  // column at the same width, so one of their boxes is every chart's box and
  // the rule lands at the same x in all of them. The rule and the words are
  // written straight onto the drawing through refs: the content security policy
  // allows no inline styles, so a position worked out per pointer event has
  // nowhere else to go.
  function drawAt(index: number) {
    if (sport === null) return
    const bucket = buckets[index]
    if (bucket === undefined) return
    const x = atX(index, buckets.length).toFixed(1)
    for (const rule of rules.current.values()) {
      rule.setAttribute('x1', x)
      rule.setAttribute('x2', x)
      rule.setAttribute('visibility', 'visible')
    }
    const said = [
      bucketName(bucket, span),
      `${distanceValue(bucket.miles, units)} ${unitName(units)}`,
    ]
    if (charts.some((chart) => chart.key === 'elevation')) {
      said.push(`${elevationValue(bucket.elevation_ft, units)} ${elevationUnit(units)}`)
    }
    const pace = paceOf(bucket, units)
    if (pace !== null) said.push(paceText(pace, sport, units))
    if (readout.current) readout.current.textContent = said.join(' · ')
  }

  // Where the pointer is, as the bucket nearest it. Pinning is what a deliberate
  // gesture does: a tap, and a drag of either kind. A mouse crossing the charts
  // with no button held is only looking, and looking leaves the choice alone.
  function readAt(event: PointerEvent<HTMLDivElement>, pin: boolean) {
    const plot = plots.current.values().next().value
    if (!plot) return
    const box = plot.getBoundingClientRect()
    if (box.width <= 0) return
    const part = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width))
    const index = Math.min(buckets.length - 1, Math.floor(part * buckets.length))
    if (pin) pinned.current = index
    drawAt(index)
  }

  // A pointer leaving is not the reading ending. A phone has nothing else to do
  // with a finger once it lifts, and wiping the line then would leave the reader
  // holding nothing; a mouse wandering off goes back to the bucket that was
  // chosen rather than to whatever it grazed on the way out. With nothing chosen
  // there is nothing to go back to, and the hint returns.
  function restoreCursor() {
    if (pinned.current !== null) drawAt(pinned.current)
    else clearCursor()
  }

  return (
    <section className="card insights">
      {/* One line, and grey until it is opened: the history under it is what
          this tab is for, and this is a drawer beside it rather than a second
          screen in front of it. The caret is what says it opens at all, and
          the line under it is what says what is behind it; shut, a bare word in
          a box is a rectangle nobody presses. */}
      <button
        type="button"
        className={open ? 'insight-head insight-head-open' : 'insight-head'}
        aria-expanded={open}
        onClick={toggle}
      >
        <span className="insight-head-words">
          <span className="label">Insights</span>
          {!open && <span className="insight-teaser">{TEASER}</span>}
        </span>
        <Icon name="caret" />
      </button>

      {open && (
        <>
          {loading && (
            <p className="notice" role="status">
              Loading.
            </p>
          )}
          {loadError && (
            <p className="error" role="alert">
              {loadError}
            </p>
          )}
          {/* Only once an answer has actually come back: an account with no
              history says so, and one waiting on the first read says nothing. */}
          {!loading && loadError === '' && band !== null && insights === null && (
            <p className="notice">Nothing to read yet. Sync a workout and this fills in.</p>
          )}

          {insights !== null && sport !== null && (
            <>
              {/* One sport at a time, and only the ones there is a history in:
                  a chart is one measurement of one thing, and four sports on
                  one axis would be four scales pretending to be one. */}
              <ul className="filter-chips">
                {sports.map((name) => {
                  const on = name === sport
                  return (
                    <li key={name}>
                      <button
                        type="button"
                        className={on ? 'filter-chip filter-chip-on' : 'filter-chip'}
                        aria-pressed={on}
                        onClick={() => {
                          setChosen(name)
                          clearCursor()
                        }}
                      >
                        <span className="sport-icon sport-icon-small">
                          <Icon name={ACTIVITY_ICONS[name]} />
                        </span>
                        {ACTIVITY_NAMES[name]}
                      </button>
                    </li>
                  )
                })}
              </ul>

              <div className="choice">
                {SPANS.map((choice) => (
                  <button
                    key={choice.key}
                    type="button"
                    className={
                      span === choice.key ? 'choice-option choice-current' : 'choice-option'
                    }
                    aria-pressed={span === choice.key}
                    onClick={() => {
                      setSpan(choice.key)
                      clearCursor()
                    }}
                  >
                    {choice.word}
                  </button>
                ))}
              </div>

              {charts.length === 0 ? (
                <p className="notice">Nothing recorded in the last twelve {span}.</p>
              ) : (
                <>
                  <p className="lane-readout" role="status" ref={readout}>
                    {HINT[span]}
                  </p>

                  <div
                    className="lane-stack"
                    onPointerDown={(event) => {
                      // Capture, so a thumb dragging off the edge of one chart
                      // keeps reading rather than handing the drag back to the
                      // page.
                      event.currentTarget.setPointerCapture(event.pointerId)
                      readAt(event, true)
                    }}
                    onPointerMove={(event) => {
                      readAt(event, !(event.pointerType === 'mouse' && event.buttons === 0))
                    }}
                    onPointerLeave={restoreCursor}
                    onPointerCancel={restoreCursor}
                  >
                    {charts.map((chart) => (
                      <div className="lane" key={chart.key}>
                        <p className="lane-name">{chart.name}</p>
                        <div className="lane-body">
                          {/* The axis is written in the page's own type rather
                              than inside the drawing, so it stays the size the
                              rest of the screen is read at whatever width the
                              chart is stretched to. */}
                          <div className="insight-axis">
                            {chart.labels.map((text, index) => (
                              <span key={index}>{text}</span>
                            ))}
                          </div>
                          <svg
                            className="insight-plot"
                            viewBox={`0 0 ${PLOT_W} ${PLOT_H}`}
                            preserveAspectRatio="none"
                            role="img"
                            aria-label={chart.summary}
                            ref={(el) => {
                              if (el) plots.current.set(chart.key, el)
                              else plots.current.delete(chart.key)
                            }}
                          >
                            {/* Two rungs and a middle, which are the three the
                                axis beside them names. */}
                            {[TOP, (TOP + BASE) / 2, BASE].map((rung) => (
                              <line
                                key={rung}
                                className="lane-grid"
                                x1="0"
                                y1={rung}
                                x2={PLOT_W}
                                y2={rung}
                              />
                            ))}
                            {chart.bars.map((bar) => (
                              // Taken to the floor of the box rather than to
                              // the rung, so the round cap that gives the bar
                              // its top is cut square at the foot by the
                              // viewport instead of bulging under the axis.
                              <line
                                key={bar.key}
                                className="insight-bar"
                                x1={bar.x.toFixed(1)}
                                y1={PLOT_H}
                                x2={bar.x.toFixed(1)}
                                y2={bar.y.toFixed(1)}
                              />
                            ))}
                            {chart.line !== '' && (
                              <polyline className="lane-line" points={chart.line} />
                            )}
                            <line
                              className="lane-cursor"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2={PLOT_H}
                              visibility="hidden"
                              ref={(el) => {
                                if (el) rules.current.set(chart.key, el)
                                else rules.current.delete(chart.key)
                              }}
                            />
                          </svg>
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Three of the twelve rather than all of them: a phone has
                      room for the ends and the middle, and the readout above
                      names whichever one is under the thumb. */}
                  <div className="insight-ticks">
                    <span>{bucketTick(buckets[0], span)}</span>
                    <span>{bucketTick(buckets[Math.floor(buckets.length / 2)], span)}</span>
                    <span>{bucketTick(buckets[buckets.length - 1], span)}</span>
                  </div>
                </>
              )}

              {/* The bests, each one only where something qualified for it.
                  Quiet figures rather than trophies: they are facts about a
                  history, and nothing in the game reads any of them. A sport
                  that has set none of them gets no row at all. */}
              {anyBest(insights) && (
                <>
                  <h2 className="label">Personal records</h2>
                  <ul className="insight-prs">
                    {insights.prs.longest !== null && (
                      <li className="insight-pr">
                        <Figure
                          label="Longest"
                          value={distanceValue(insights.prs.longest.miles, units)}
                          unit={unitName(units)}
                        />
                        <span className="insight-when">
                          {formatDate(insights.prs.longest.start_ts)}
                        </span>
                      </li>
                    )}
                    {/* The time first, because the time is the record: a 5K is
                        a distance everybody already knows the length of, and what
                        is remembered about one is how long it took. The pace
                        under it is that time over that distance, worked out here
                        so a metric account reads its own. */}
                    {PR_TIERS.map((tier) => {
                      const best = insights.prs.tiers[tier]
                      if (!best) return null
                      return (
                        <li className="insight-pr" key={tier}>
                          <Figure label={PR_NAMES[tier]} value={formatClock(best.seconds)} />
                          <span className="insight-pace">
                            {formatPace(sport, PR_MILES[tier], best.seconds, units)}
                          </span>
                          <span className="insight-when">{formatDate(best.start_ts)}</span>
                        </li>
                      )
                    })}
                    {insights.prs.best_week !== null && (
                      <li className="insight-pr">
                        <Figure
                          label="Best week"
                          value={distanceValue(insights.prs.best_week.miles, units)}
                          unit={unitName(units)}
                        />
                        <span className="insight-when">
                          {formatDayKey(insights.prs.best_week.start)}
                        </span>
                      </li>
                    )}
                    {insights.prs.biggest_climb !== null && (
                      <li className="insight-pr">
                        <Figure
                          label="Biggest climb"
                          value={elevationValue(insights.prs.biggest_climb.elevation_ft, units)}
                          unit={elevationUnit(units)}
                        />
                        <span className="insight-when">
                          {formatDate(insights.prs.biggest_climb.start_ts)}
                        </span>
                      </li>
                    )}
                  </ul>
                </>
              )}
            </>
          )}
        </>
      )}
    </section>
  )
}
