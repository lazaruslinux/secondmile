// The line a workout drew, fetched once per workout and drawn as one stroke.
// Nothing here reaches outside the app: the shape is the whole map, there are
// no tiles behind it and never will be.

import { getWorkoutRoute, type RoutePoint } from './api.ts'

// Kept for the life of the page, so switching tabs or loading more of the feed
// redraws the same lines rather than asking for them again. Workout ids are
// unique across accounts, so a second person signing in cannot read these.
// undefined means never asked; null means asked and there is nothing to draw
// (no route, or the call failed), which the card treats the same either way.
const cache = new Map<number, RoutePoint[] | null>()
const inFlight = new Map<number, Promise<RoutePoint[] | null>>()

// A feed page is twenty cards and an Activity page fifty. Without a limit, one screen
// would ask for fifty routes at once.
const MAX_ACTIVE = 4
let active = 0
const waiting: (() => void)[] = []

function takeSlot(): Promise<void> {
  if (active < MAX_ACTIVE) {
    active += 1
    return Promise.resolve()
  }
  return new Promise((resolve) => {
    waiting.push(() => {
      active += 1
      resolve()
    })
  })
}

function freeSlot(): void {
  active -= 1
  waiting.shift()?.()
}

// Anything that is not a pair of real numbers is dropped, and a route that has
// no length left after that is nothing to draw.
function usable(points: RoutePoint[]): RoutePoint[] | null {
  const kept = points.filter(
    (point) =>
      Array.isArray(point) &&
      point.length === 2 &&
      Number.isFinite(point[0]) &&
      Number.isFinite(point[1]),
  )
  return kept.length < 2 ? null : kept
}

export function cachedRoute(workoutId: number): RoutePoint[] | null | undefined {
  return cache.get(workoutId)
}

export async function loadRoute(workoutId: number): Promise<RoutePoint[] | null> {
  const held = cache.get(workoutId)
  if (held !== undefined) return held
  const running = inFlight.get(workoutId)
  if (running) return running

  const task = (async () => {
    await takeSlot()
    try {
      const found = usable((await getWorkoutRoute(workoutId)).points)
      cache.set(workoutId, found)
      return found
    } catch {
      // A workout with no stored route answers 404, which is ordinary rather
      // than wrong. Anything else is a bad moment. Neither is worth putting on
      // a workout card, so both come out as nothing to draw.
      cache.set(workoutId, null)
      return null
    } finally {
      freeSlot()
      inFlight.delete(workoutId)
    }
  })()
  inFlight.set(workoutId, task)
  return task
}

// A share of the shorter side rather than a fixed number, so the small sketch in
// a row of history keeps the same breathing room as the band on a card.
const MARGIN_SHARE = 0.06

// The room the standing renderer leaves around a route when it takes a picture
// of one. It lives here rather than beside the renderer so the overlay drawn on
// top of that picture can be fitted the same way without pulling maplibre into
// the main bundle; snapshot.ts reads it back.
export const SHOT_PADDING = 48

const RADIANS = Math.PI / 180

// One place on a drawing: x and y in the box the route was fitted into.
export type Spot = [number, number]

function place(value: number): string {
  return value.toFixed(1)
}

// A run of spots as the points list an SVG polyline is written with.
export function pathOf(spots: Spot[]): string {
  return spots.map(([x, y]) => `${place(x)},${place(y)}`).join(' ')
}

// Flat coordinates scaled to fit the box they are given and centred in it,
// never stretched: the shape is the point. The margin is room kept on all four
// sides.
//
// A route that never moved has no shape at all and comes back as nothing. One
// run in a straight line has no span on one axis, which only means that axis
// does not set the scale.
function fitted(
  xs: number[],
  ys: number[],
  viewWidth: number,
  viewHeight: number,
  margin: number,
): Spot[] | null {
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const spanX = Math.max(...xs) - minX
  const spanY = Math.max(...ys) - minY
  if (spanX <= 0 && spanY <= 0) return null
  const scale = Math.min(
    spanX > 0 ? (viewWidth - margin * 2) / spanX : Infinity,
    spanY > 0 ? (viewHeight - margin * 2) / spanY : Infinity,
  )
  const midX = minX + spanX / 2
  const midY = minY + spanY / 2
  return xs.map((x, index) => [
    viewWidth / 2 + (x - midX) * scale,
    viewHeight / 2 + (ys[index] - midY) * scale,
  ])
}

// The line the app draws itself. Equirectangular, with longitude squeezed by
// the cosine of the route's own mean latitude so a mile east reads the same
// length as a mile north. Routes that cross the 180th meridian are out of
// scope; one would draw as a line the width of the world.
export function sketchCoords(
  points: RoutePoint[],
  viewWidth: number,
  viewHeight: number,
): Spot[] | null {
  let latSum = 0
  for (const [lat] of points) latSum += lat
  const squeeze = Math.cos((latSum / points.length) * RADIANS)

  // North is up and the screen counts downwards, hence the negated latitude.
  return fitted(
    points.map(([, lon]) => lon * squeeze),
    points.map(([lat]) => -lat),
    viewWidth,
    viewHeight,
    Math.min(viewWidth, viewHeight) * MARGIN_SHARE,
  )
}

// Web Mercator, in the unit square: nought to one west to east, and nought to
// one north to south. The poles run off to infinity, so the latitude is held
// inside the band every web map cuts itself off at.
const MERCATOR_LIMIT = 85.051129

function mercator([lat, lon]: RoutePoint): Spot {
  const held = Math.min(MERCATOR_LIMIT, Math.max(-MERCATOR_LIMIT, lat))
  const sine = Math.sin(held * RADIANS)
  return [(lon + 180) / 360, 0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI)]
}

// Where the map put each point in the picture it took of the route.
//
// The thumbnail is a photograph of a real map, fitted to the route with the
// same room on all four sides, so anything drawn on top of that picture has to
// land in the same places. That fit is Mercator scaled by whichever axis runs
// out of room first and centred on the middle of the bounds, which is exactly
// what the arithmetic above does, so it is arithmetic here rather than a second
// renderer: none of maplibre is pulled in for it.
export function mapCoords(
  points: RoutePoint[],
  viewWidth: number,
  viewHeight: number,
  padding: number,
): Spot[] | null {
  const world = points.map(mercator)
  return fitted(
    world.map(([x]) => x),
    world.map(([, y]) => y),
    viewWidth,
    viewHeight,
    padding,
  )
}

// How far apart two points are, as the angle between them at the centre of the
// earth. Only ever read as a share of a whole route below, so the radius the
// angle would be multiplied by cancels and is never written down.
function apart([lat1, lon1]: RoutePoint, [lat2, lon2]: RoutePoint): number {
  const halfLat = ((lat2 - lat1) * RADIANS) / 2
  const halfLon = ((lon2 - lon1) * RADIANS) / 2
  const chord =
    Math.sin(halfLat) ** 2 +
    Math.cos(lat1 * RADIANS) * Math.cos(lat2 * RADIANS) * Math.sin(halfLon) ** 2
  return 2 * Math.asin(Math.min(1, Math.sqrt(chord)))
}

// How far along the line each point sits, as a share of the whole: nought at
// the first and one at the last. What lets a stretch of a workout, measured in
// miles, be found on a line that is only ever measured in itself.
export function alongRoute(points: RoutePoint[]): number[] {
  const walked = [0]
  let total = 0
  for (let step = 1; step < points.length; step += 1) {
    total += apart(points[step - 1], points[step])
    walked.push(total)
  }
  return total > 0 ? walked.map((far) => far / total) : walked.map(() => 0)
}

// The place a share of the way along the line falls, worked out between the two
// points it lands between. Shares outside the line are held to its ends.
export function spotAt(spots: Spot[], walked: number[], part: number): Spot | null {
  if (spots.length === 0) return null
  if (spots.length < 2) return spots[0]
  const want = Math.min(1, Math.max(0, part))
  let step = 1
  while (step < walked.length - 1 && walked[step] < want) step += 1
  const span = walked[step] - walked[step - 1]
  const share = span > 0 ? (want - walked[step - 1]) / span : 0
  const [fromX, fromY] = spots[step - 1]
  const [toX, toY] = spots[step]
  return [fromX + (toX - fromX) * share, fromY + (toY - fromY) * share]
}

// The stretch of line between two shares of the way along it: the two ends
// worked out where they fall, and every point of the line that lies between
// them kept as it is.
export function spotsBetween(
  spots: Spot[],
  walked: number[],
  from: number,
  to: number,
): Spot[] {
  const start = Math.min(from, to)
  const end = Math.max(from, to)
  const head = spotAt(spots, walked, start)
  const tail = spotAt(spots, walked, end)
  if (head === null || tail === null) return []
  return [head, ...spots.filter((_, at) => walked[at] > start && walked[at] < end), tail]
}
