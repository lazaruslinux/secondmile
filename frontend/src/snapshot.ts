// A picture of the route on the map, for the thumbnail on a card. A live map
// per card is not on the table: each one owns a WebGL context and a browser
// hands out about a dozen before it starts killing the oldest, so a feed of
// them is a page of blank boxes. Instead there is one map, off screen, drawing
// one route after another and handing back an image of each.

import { MapLibreMap } from 'maplibre-gl'
import type { RoutePoint } from './api.ts'
import { addRoute, basemapStyle, corners, setRoute } from './mapgl.ts'

// Rendered at the thumbnail's own proportions, a little roomier than the
// modal's padding so the shape survives being cropped to a narrower card.
const PADDING = 48

// Long enough for tiles off a cold archive, short enough that a card is not
// waiting on a picture that is never coming.
const PATIENCE = 6000

// Drawn once per workout and kept for the life of the page: scrolling a card
// past twice does not draw it twice. null is a workout that would not render,
// which leaves the card with the line it already had. Nothing is written to
// disk; a session is as long as these live.
const shots = new Map<number, string | null>()
const pending = new Map<number, Promise<string | null>>()
let queue: Promise<unknown> = Promise.resolve()

let ready: Promise<MapLibreMap | null> | undefined
let drawn = false

// The one map. It is parked off the top of the viewport by class, at the exact
// size the pictures are taken at, and it stays for the session.
function renderer(): Promise<MapLibreMap | null> {
  ready ??= new Promise((resolve) => {
    const box = document.createElement('div')
    box.className = 'route-shot'
    box.setAttribute('aria-hidden', 'true')
    document.body.append(box)

    const made = new MapLibreMap({
      container: box,
      style: basemapStyle(),
      // Without this the drawing buffer is thrown away after each frame and
      // every picture comes back blank. It costs a little render speed, which
      // is why the modal's map does not ask for it.
      canvasContextAttributes: { preserveDrawingBuffer: true },
      interactive: false,
      attributionControl: false,
      fadeDuration: 0,
    })

    let giveUp: ReturnType<typeof setTimeout> | undefined
    const loaded = () => {
      clearTimeout(giveUp)
      resolve(made)
    }
    giveUp = setTimeout(() => {
      // A map that never loaded is answered once, for good: the cards keep
      // their lines instead of every one of them waiting out the same clock.
      made.off('load', loaded)
      made.remove()
      box.remove()
      resolve(null)
    }, PATIENCE)
    made.once('load', loaded)
  })
  return ready
}

// Every tile in view fetched, drawn, and nothing left moving.
function settled(map: MapLibreMap): Promise<boolean> {
  return new Promise((resolve) => {
    let giveUp: ReturnType<typeof setTimeout> | undefined
    const done = () => {
      clearTimeout(giveUp)
      resolve(true)
    }
    giveUp = setTimeout(() => {
      map.off('idle', done)
      resolve(false)
    }, PATIENCE)
    map.once('idle', done)
  })
}

async function shoot(points: RoutePoint[]): Promise<string | null> {
  const map = await renderer()
  if (!map) return null

  if (drawn) setRoute(map, points)
  else {
    addRoute(map, points)
    drawn = true
  }
  map.fitBounds(corners(points), { padding: PADDING, animate: false })
  // A route that lands on the view already showing would otherwise leave the
  // map idle already and the wait below with nothing to wait for.
  map.triggerRepaint()

  if (!(await settled(map))) return null
  // webp where the browser has it, which is most of them; the ones that do not
  // hand back a png of the same picture instead.
  return map.getCanvas().toDataURL('image/webp', 0.85)
}

export function routeShot(workoutId: number, points: RoutePoint[]): Promise<string | null> {
  const held = shots.get(workoutId)
  if (held !== undefined) return Promise.resolve(held)
  const running = pending.get(workoutId)
  if (running) return running

  // One map means one picture at a time, so the jobs stand in a line. Twenty
  // cards asking at once is twenty turns, in the order they asked.
  const task = queue.then(async () => {
    let shot: string | null = null
    try {
      shot = await shoot(points)
    } catch {
      // A picture that would not come out is not worth saying anything about:
      // the card still has the line it drew itself.
      shot = null
    }
    shots.set(workoutId, shot)
    pending.delete(workoutId)
    return shot
  })
  queue = task
  pending.set(workoutId, task)
  return task
}
