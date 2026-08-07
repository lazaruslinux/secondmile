import { useEffect, useState } from 'react'
import type { RoutePoint } from '../api.ts'
import { cachedRoute, loadRoute, routePath } from '../route.ts'

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

  useEffect(() => {
    let live = true
    void loadRoute(workoutId).then((found) => {
      if (live) setPoints(found)
    })
    return () => {
      live = false
    }
  }, [workoutId])

  if (!points) return null
  const [width, height] = compact ? COMPACT_BOX : FEED_BOX
  const path = routePath(points, width, height)
  if (!path) return null

  return (
    <div className={compact ? 'route-map route-map-small' : 'route-map'}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio={compact ? 'xMinYMid meet' : 'xMidYMid meet'}
        role="img"
        aria-label="Route"
      >
        <polyline className="route-line" points={path} />
      </svg>
    </div>
  )
}
