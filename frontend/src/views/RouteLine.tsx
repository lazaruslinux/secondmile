import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { RoutePoint } from '../api.ts'
import { basemapInstalled } from '../basemap.ts'
import { cachedRoute, loadRoute, routePath } from '../route.ts'

// The renderer is a large thing to carry for a picture that draws itself, so it
// arrives on the tap and not before.
const RouteMap = lazy(() => import('./RouteMap.tsx'))

// A feed card gives the route a wide band across the middle of it. A row of
// history gets a small sketch instead, in a box near enough to square that the
// shape still reads at that size, held against the left edge of the row.
const FEED_BOX = [600, 240]
const COMPACT_BOX = [96, 64]

interface Props {
  workoutId: number
  // Set on a Log row, where the line is a strip beside the numbers rather than
  // the picture at the top of a card.
  compact?: boolean
}

// Nothing is drawn until the points are in hand: a workout still waiting for
// them, or one whose route turned out to be nothing, looks exactly like a
// workout that never had one.
export default function RouteLine({ workoutId, compact = false }: Props) {
  const [points, setPoints] = useState<RoutePoint[] | null>(
    () => cachedRoute(workoutId) ?? null,
  )
  const [shot, setShot] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    let live = true
    void loadRoute(workoutId).then((found) => {
      if (live) setPoints(found)
    })
    return () => {
      live = false
    }
  }, [workoutId])

  // The map behind the line, if this server has an archive to draw it from. Two
  // things have to be true before any of maplibre is fetched: the basemap is
  // installed, and this particular card is on the screen. A card nobody
  // scrolled to costs nothing, and a server without the archive never asks for
  // the renderer at all.
  useEffect(() => {
    const button = box.current
    if (compact || !points || shot || !button) return
    let live = true
    let watcher: IntersectionObserver | undefined

    void basemapInstalled().then((have) => {
      if (!live || !have) return
      watcher = new IntersectionObserver((entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        watcher?.disconnect()
        void import('../snapshot.ts')
          .then((maps) => maps.routeShot(workoutId, points))
          .then((picture) => {
            if (live && picture) setShot(picture)
          })
          .catch(() => {
            // The line is already on the card; a picture that never came is
            // nothing a reader needs told about.
          })
      })
      watcher.observe(button)
    })

    return () => {
      live = false
      watcher?.disconnect()
    }
  }, [compact, points, shot, workoutId])

  if (!points) return null
  const [width, height] = compact ? COMPACT_BOX : FEED_BOX
  const path = routePath(points, width, height)
  if (!path) return null

  return (
    <>
      {/* The sketch is the way into the map, so the box itself is the control.
          The name moves to the button with it, and the drawing goes quiet
          rather than being announced twice. */}
      <button
        type="button"
        className={compact ? 'route-map route-map-small route-open' : 'route-map route-open'}
        aria-label="Open route map"
        onClick={() => setOpen(true)}
        ref={box}
      >
        {/* The line stands in until the map arrives, and steps aside when it
            does: the picture has the route drawn into it already. */}
        {shot ? (
          <img className="route-thumb" src={shot} alt="" />
        ) : (
          <svg
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio={compact ? 'xMinYMid meet' : 'xMidYMid meet'}
            aria-hidden="true"
          >
            <polyline className="route-line" points={path} />
          </svg>
        )}
      </button>

      {/* The map is handed the points already fetched, so the tap costs the
          server nothing. */}
      {open && (
        <Suspense fallback={null}>
          <RouteMap points={points} onClose={() => setOpen(false)} />
        </Suspense>
      )}
    </>
  )
}
