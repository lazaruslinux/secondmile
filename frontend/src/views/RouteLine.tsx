import { lazy, Suspense, useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import type { RoutePoint } from '../api.ts'
import { basemapInstalled } from '../basemap.ts'
import {
  alongRoute,
  cachedRoute,
  loadRoute,
  mapCoords,
  pathOf,
  SHOT_PADDING,
  sketchCoords,
  spotAt,
  spotsBetween,
} from '../route.ts'
import { type Theme, useTheme } from '../theme.ts'

// The renderer is a large thing to carry for a picture that draws itself, so it
// arrives on the tap and not before.
const RouteMap = lazy(() => import('./RouteMap.tsx'))

// A feed card gives the route a wide band across the middle of it. A row of
// history gets a small sketch instead, in a box near enough to square that the
// shape still reads at that size, held against the left edge of the row.
//
// The wide one is also the size the pictures are taken at, which is what lets
// an overlay drawn in these coordinates land on the picture: .route-shot is the
// same box, and object-fit: cover crops it exactly as preserveAspectRatio does
// below.
const FEED_BOX = [600, 240]
const COMPACT_BOX = [96, 64]

// The cursor's dot, in the box above rather than on the page: a card about two
// thirds that width draws it nine pixels across.
const DOT_R = 7

// A way to put a dot on the route line and take it off again, handed up to
// whoever is driving it. The graph's cursor moves per pointer event, so this
// writes attributes on the circle rather than rendering: the same reason the
// rule across the lanes is written that way, and the same content security
// policy behind it.
export interface RouteMarker {
  at: (part: number) => void
  clear: () => void
}

interface Props {
  workoutId: number
  // Set on an Activity row, where the line is a strip beside the numbers
  // rather than the picture at the top of a card.
  compact?: boolean
  // The stretch of the route to pick out, as two shares of the way along it.
  // The details screen sets it from a tapped split; nothing else passes one.
  highlight?: { from: number; to: number } | null
  // Filled in with a way to move the dot, for as long as there is a line to
  // move it along.
  marker?: RefObject<RouteMarker | null>
}

// Nothing is drawn until the points are in hand: a workout still waiting for
// them, or one whose route turned out to be nothing, looks exactly like a
// workout that never had one.
export default function RouteLine({
  workoutId,
  compact = false,
  highlight = null,
  marker,
}: Props) {
  const [points, setPoints] = useState<RoutePoint[] | null>(
    () => cachedRoute(workoutId) ?? null,
  )
  // A picture is taken on one ground. It is kept with the ground it was drawn
  // on, so a theme flip falls back to the line the card draws itself and asks
  // for another rather than leaving a dark map on a light card.
  const [shot, setShot] = useState<{ src: string; ground: Theme } | null>(null)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLButtonElement>(null)
  const dot = useRef<SVGCircleElement>(null)
  const theme = useTheme()
  const picture = shot?.ground === theme ? shot.src : null
  const [width, height] = compact ? COMPACT_BOX : FEED_BOX

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
    if (compact || !points || picture || !button) return
    let live = true
    let watcher: IntersectionObserver | undefined

    void basemapInstalled().then((have) => {
      if (!live || !have) return
      watcher = new IntersectionObserver((entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return
        watcher?.disconnect()
        void import('../snapshot.ts')
          .then((maps) => maps.routeShot(workoutId, points, theme))
          .then((taken) => {
            if (live && taken) setShot({ src: taken, ground: theme })
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
  }, [compact, points, picture, theme, workoutId])

  // Where every point of the route lands, in the two projections this box is
  // ever drawn in: the map's own once there is a picture to sit on, and the
  // app's own sketch until then. The same points either way, so a picture
  // arriving mid-drag moves the dot rather than losing it.
  const spots = useMemo(() => {
    if (!points) return null
    return picture
      ? mapCoords(points, width, height, SHOT_PADDING)
      : sketchCoords(points, width, height)
  }, [points, picture, width, height])
  const walked = useMemo(() => (points ? alongRoute(points) : []), [points])

  useEffect(() => {
    if (!marker) return
    marker.current = {
      at(part: number) {
        const spot = spots === null ? null : spotAt(spots, walked, part)
        if (spot === null || !dot.current) return
        dot.current.setAttribute('cx', spot[0].toFixed(1))
        dot.current.setAttribute('cy', spot[1].toFixed(1))
        dot.current.setAttribute('visibility', 'visible')
      },
      clear() {
        dot.current?.setAttribute('visibility', 'hidden')
      },
    }
    return () => {
      marker.current = null
    }
  }, [marker, spots, walked])

  if (!points || !spots) return null

  // The stretch a tapped split covers, and the dot the graph's cursor drives.
  // Both are drawn over the picture when there is one and into the sketch when
  // there is not, in the same coordinates, so neither knows which it is on.
  const stretch =
    highlight === null ? '' : pathOf(spotsBetween(spots, walked, highlight.from, highlight.to))
  const marks = stretch === '' && !marker ? null : (
    <>
      {stretch !== '' && (
        <>
          <polyline className="route-trail-edge" points={stretch} />
          <polyline className="route-trail" points={stretch} />
        </>
      )}
      {marker && (
        <circle className="route-dot" r={DOT_R} visibility="hidden" ref={dot} />
      )}
    </>
  )

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
            does: the picture has the route drawn into it already. Whatever is
            marked on top of it stays, in a layer of its own cropped the way the
            picture under it is. */}
        {picture ? (
          <>
            <img className="route-thumb" src={picture} alt="" />
            {marks && (
              <svg
                className="route-over"
                viewBox={`0 0 ${width} ${height}`}
                preserveAspectRatio="xMidYMid slice"
                aria-hidden="true"
              >
                {marks}
              </svg>
            )}
          </>
        ) : (
          <svg
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio={compact ? 'xMinYMid meet' : 'xMidYMid meet'}
            aria-hidden="true"
          >
            <polyline className="route-line" points={pathOf(spots)} />
            {marks}
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
