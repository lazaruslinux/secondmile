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

function place(value: number): string {
  return value.toFixed(1)
}

// Equirectangular, with longitude squeezed by the cosine of the route's own
// mean latitude so a mile east reads the same length as a mile north. The
// result is scaled to fit the box it is given and centred in it, never
// stretched: the shape is the point. Routes that cross the 180th meridian are
// out of scope; one would draw as a line the width of the world.
export function routePath(
  points: RoutePoint[],
  viewWidth: number,
  viewHeight: number,
): string | null {
  let latSum = 0
  for (const [lat] of points) latSum += lat
  const squeeze = Math.cos(((latSum / points.length) * Math.PI) / 180)

  // North is up and the screen counts downwards, hence the negated latitude.
  const xs = points.map(([, lon]) => lon * squeeze)
  const ys = points.map(([lat]) => -lat)
  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const spanX = Math.max(...xs) - minX
  const spanY = Math.max(...ys) - minY

  // A route that never moved has no shape at all. One run in a straight line
  // has no span on one axis, which only means that axis does not set the scale.
  if (spanX <= 0 && spanY <= 0) return null
  const margin = Math.min(viewWidth, viewHeight) * MARGIN_SHARE
  const room = viewWidth - margin * 2
  const height = viewHeight - margin * 2
  const scale = Math.min(
    spanX > 0 ? room / spanX : Infinity,
    spanY > 0 ? height / spanY : Infinity,
  )

  const left = margin + (room - spanX * scale) / 2
  const top = margin + (height - spanY * scale) / 2
  return points
    .map(
      (_, index) =>
        `${place(left + (xs[index] - minX) * scale)},${place(top + (ys[index] - minY) * scale)}`,
    )
    .join(' ')
}
