import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react'
// The map and the marker are files, not markup. Everything the code knows
// about them is the ids listed in docs/03-artwork.md, so both can be redrawn
// in a vector editor and dropped in without a change here.
import mapSource from '../assets/vale-map.svg?raw'
import markerSource from '../assets/marker.svg?raw'
import {
  ApiError,
  getJourney,
  listChests,
  openChest,
  setDestination,
  unlockRegion,
  type Chest,
  type JourneyPlace,
  type JourneyState,
  type OpenedChest,
} from '../api.ts'
import { ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import CardPlate from './CardPlate.tsx'

interface Box {
  x: number
  y: number
  w: number
  h: number
}

interface Asset {
  box: Box
  inner: string
}

// Read an asset down to the two things the code uses: the coordinate system it
// declares, and everything inside it. What is inside is never inspected.
function readAsset(source: string): Asset | null {
  const root = new DOMParser().parseFromString(source, 'image/svg+xml').documentElement
  if (root.nodeName !== 'svg') return null
  const numbers = (root.getAttribute('viewBox') ?? '').trim().split(/[\s,]+/).map(Number)
  if (numbers.length !== 4 || numbers.some((value) => !Number.isFinite(value))) return null
  return {
    box: { x: numbers[0], y: numbers[1], w: numbers[2], h: numbers[3] },
    inner: root.innerHTML,
  }
}

const MAP = readAsset(mapSource)
const MARKER = readAsset(markerSource)
const BASE: Box = MAP?.box ?? { x: 0, y: 0, w: 1000, h: 1000 }

const MIN_ZOOM = 1
const MAX_ZOOM = 6
// Sized against the map rather than in fixed units, so a replacement map drawn
// at another scale still gets a marker and tap targets that fit it. Both are
// divided by the zoom when drawn, which keeps them the same size on screen.
const MARKER_SIZE = BASE.w * 0.055
const TAP_RADIUS = BASE.w * 0.06
// Enough movement to call a press a drag rather than a tap.
const DRAG_SLOP = 6

interface View {
  zoom: number
  cx: number
  cy: number
}

function viewRect(view: View): Box {
  const w = BASE.w / view.zoom
  const h = BASE.h / view.zoom
  return { x: view.cx - w / 2, y: view.cy - h / 2, w, h }
}

// The view never leaves the map: panning stops at the edges rather than
// drifting off into empty space.
function clampView(view: View): View {
  const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom))
  const w = BASE.w / zoom
  const h = BASE.h / zoom
  const cx = Math.min(Math.max(view.cx, BASE.x + w / 2), BASE.x + BASE.w - w / 2)
  const cy = Math.min(Math.max(view.cy, BASE.y + h / 2), BASE.y + BASE.h - h / 2)
  return { zoom, cx, cy }
}

// A point in the map's own coordinates, whatever transforms sit between the
// element it came from and the root.
function toMapSpace(
  root: SVGSVGElement,
  el: SVGGraphicsElement,
  x: number,
  y: number,
): { x: number; y: number } | null {
  const rootCtm = root.getScreenCTM()
  const elCtm = el.getScreenCTM()
  if (!rootCtm || !elCtm) return null
  const point = new DOMPoint(x, y).matrixTransform(rootCtm.inverse().multiply(elCtm))
  return { x: point.x, y: point.y }
}

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Try again.'
}

function positionText(state: JourneyState): string {
  const at = state.position
  if (at.road_name && at.road_length_mi !== null) {
    return `${at.road_name}, ${at.position_mi.toFixed(1)} of ${at.road_length_mi} Miles`
  }
  return `At ${at.location_name ?? 'the Homestead'}`
}

interface Props {
  // Bumped by the app after the recap is dismissed, because chests opened
  // there change what this screen should show.
  refreshToken: number
}

export default function Vale({ refreshToken }: Props) {
  const [state, setState] = useState<JourneyState | null>(null)
  const [chests, setChests] = useState<Chest[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [view, setView] = useState<View>({
    zoom: MIN_ZOOM,
    cx: BASE.x + BASE.w / 2,
    cy: BASE.y + BASE.h / 2,
  })
  const [anchors, setAnchors] = useState<Record<string, { x: number; y: number }>>({})
  const [markerAt, setMarkerAt] = useState<{ x: number; y: number } | null>(null)

  const [pending, setPending] = useState<JourneyPlace | null>(null)
  const [travelError, setTravelError] = useState('')
  const [settingOut, setSettingOut] = useState(false)

  const [confirmRegion, setConfirmRegion] = useState<string | null>(null)
  const [unlockError, setUnlockError] = useState('')
  const [unlocking, setUnlocking] = useState(false)

  const [opened, setOpened] = useState<Record<number, OpenedChest>>({})
  const [chestError, setChestError] = useState('')
  const [openingChest, setOpeningChest] = useState<number | null>(null)

  const svgRef = useRef<SVGSVGElement>(null)
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const dragged = useRef(false)

  const load = useCallback(async () => {
    try {
      const [journey, unopened] = await Promise.all([getJourney(), listChests()])
      setState(journey)
      setChests(unopened)
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  // The places are measured once: the map is a static file, so where the
  // anchors sit never changes while the app is open.
  useLayoutEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const found: Record<string, { x: number; y: number }> = {}
    for (const el of svg.querySelectorAll<SVGGraphicsElement>('[id^="loc-"]')) {
      const box = el.getBBox()
      const point = toMapSpace(svg, el, box.x + box.width / 2, box.y + box.height / 2)
      if (point) found[el.id.slice(4)] = point
    }
    setAnchors(found)
  }, [])

  // Where the marker stands. On a road that is a distance along the drawn
  // path; at a place it is the place's anchor.
  useLayoutEffect(() => {
    const svg = svgRef.current
    const at = state?.position
    if (!svg || !at) {
      setMarkerAt(null)
      return
    }
    if (at.road_id && at.fraction !== null) {
      const path = svg.querySelector<SVGPathElement>(`[id="road-${at.road_id}"]`)
      if (path) {
        const point = path.getPointAtLength(path.getTotalLength() * at.fraction)
        setMarkerAt(toMapSpace(svg, path, point.x, point.y))
        return
      }
    }
    setMarkerAt(at.location_id ? (anchors[at.location_id] ?? null) : null)
  }, [state?.position, anchors])

  // A gate that has been opened is taken off the map.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg || !state) return
    for (const region of state.regions) {
      const gate = svg.querySelector<SVGElement>(`[id="gate-${region.id}"]`)
      if (gate) gate.style.display = region.unlocked ? 'none' : ''
    }
  }, [state])

  const zoomAt = useCallback((factor: number, clientX: number, clientY: number) => {
    const svg = svgRef.current
    const ctm = svg?.getScreenCTM()
    const point = ctm ? new DOMPoint(clientX, clientY).matrixTransform(ctm.inverse()) : null
    setView((current) => {
      const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current.zoom * factor))
      if (!point) return clampView({ ...current, zoom })
      // Keep whatever was under the fingers under the fingers.
      const ratio = current.zoom / zoom
      return clampView({
        zoom,
        cx: point.x - (point.x - current.cx) * ratio,
        cy: point.y - (point.y - current.cy) * ratio,
      })
    })
  }, [])

  // Wheel zoom needs a listener that is allowed to cancel the event, and React
  // registers its own as passive, so this one is attached by hand.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      zoomAt(Math.exp(-event.deltaY * 0.0015), event.clientX, event.clientY)
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  function onPointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.target instanceof Element) event.target.setPointerCapture(event.pointerId)
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY })
    if (pointers.current.size === 1) dragged.current = false
  }

  function onPointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const before = pointers.current.get(event.pointerId)
    if (!before) return
    const after = { x: event.clientX, y: event.clientY }
    const others = [...pointers.current.entries()].filter(([id]) => id !== event.pointerId)
    pointers.current.set(event.pointerId, after)

    const dx = after.x - before.x
    const dy = after.y - before.y
    if (Math.abs(dx) + Math.abs(dy) > DRAG_SLOP) dragged.current = true

    if (others.length === 0) {
      // The drag is measured in map units by putting both screen points
      // through the map's own transform, which stays right whatever the
      // element's shape does to the picture.
      const ctm = svgRef.current?.getScreenCTM()
      if (!ctm) return
      const inverse = ctm.inverse()
      const from = new DOMPoint(before.x, before.y).matrixTransform(inverse)
      const to = new DOMPoint(after.x, after.y).matrixTransform(inverse)
      setView((current) =>
        clampView({ ...current, cx: current.cx - (to.x - from.x), cy: current.cy - (to.y - from.y) }),
      )
      return
    }

    // Two fingers: the change in the distance between them is the zoom, taken
    // about the point halfway between them.
    const other = others[0][1]
    const oldSpan = Math.hypot(before.x - other.x, before.y - other.y)
    const newSpan = Math.hypot(after.x - other.x, after.y - other.y)
    if (oldSpan > 0 && newSpan > 0) {
      dragged.current = true
      zoomAt(newSpan / oldSpan, (after.x + other.x) / 2, (after.y + other.y) / 2)
    }
  }

  function onPointerUp(event: React.PointerEvent<SVGSVGElement>) {
    pointers.current.delete(event.pointerId)
  }

  function choose(place: JourneyPlace) {
    if (dragged.current) return
    setTravelError('')
    setPending(place)
  }

  async function confirmDestination() {
    if (!pending) return
    setSettingOut(true)
    setTravelError('')
    try {
      setState(await setDestination(pending.id))
      setPending(null)
    } catch (err) {
      // The server is the one that knows whether a road is open, so its own
      // wording is what gets shown.
      setTravelError(errorText(err))
    } finally {
      setSettingOut(false)
    }
  }

  async function unlock(regionId: string) {
    setUnlocking(true)
    setUnlockError('')
    try {
      setState(await unlockRegion(regionId))
      setConfirmRegion(null)
    } catch (err) {
      setUnlockError(errorText(err))
    } finally {
      setUnlocking(false)
    }
  }

  async function open(chestId: number) {
    setOpeningChest(chestId)
    setChestError('')
    try {
      const result = await openChest(chestId)
      setOpened((current) => ({ ...current, [chestId]: result }))
      setChests((current) => current.filter((chest) => chest.id !== chestId))
      setState((current) =>
        current ? { ...current, unopened_chests: Math.max(0, current.unopened_chests - 1) } : current,
      )
    } catch (err) {
      setChestError(errorText(err))
    } finally {
      setOpeningChest(null)
    }
  }

  const rect = viewRect(view)
  const markerScale = MARKER ? MARKER_SIZE / view.zoom / Math.max(MARKER.box.w, MARKER.box.h) : 0
  const revealed = Object.values(opened)

  return (
    <>
      <section className="card vale-card">
        <div className="vale-frame">
          {MAP ? (
            <svg
              ref={svgRef}
              className="vale-map"
              viewBox={`${rect.x} ${rect.y} ${rect.w} ${rect.h}`}
              style={{ aspectRatio: `${BASE.w} / ${BASE.h}` }}
              role="img"
              aria-label="Map of the Vale"
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            >
              {/* The map file, untouched. */}
              <g dangerouslySetInnerHTML={{ __html: MAP.inner }} />

              {state?.locations.map((place) => {
                const at = anchors[place.id]
                if (!at) return null
                const here = state.position.location_id === place.id
                const target = state.destination?.id === place.id
                return (
                  <g key={place.id}>
                    {(here || target) && (
                      <circle
                        cx={at.x}
                        cy={at.y}
                        r={(TAP_RADIUS * 0.75) / view.zoom}
                        fill="none"
                        stroke="#c2410c"
                        strokeWidth={4 / view.zoom}
                        strokeDasharray={target && !here ? `${8 / view.zoom} ${6 / view.zoom}` : undefined}
                      />
                    )}
                    <circle
                      className="vale-hit"
                      cx={at.x}
                      cy={at.y}
                      r={TAP_RADIUS / view.zoom}
                      fill="transparent"
                      role="button"
                      tabIndex={0}
                      aria-label={`Set out for ${place.name}`}
                      onClick={() => choose(place)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          setPending(place)
                        }
                      }}
                    />
                  </g>
                )
              })}

              {markerAt && MARKER && (
                <g
                  transform={
                    `translate(${markerAt.x} ${markerAt.y}) scale(${markerScale}) ` +
                    `translate(${-(MARKER.box.x + MARKER.box.w / 2)} ${-(MARKER.box.y + MARKER.box.h / 2)})`
                  }
                  dangerouslySetInnerHTML={{ __html: MARKER.inner }}
                />
              )}
            </svg>
          ) : (
            <p className="notice">The map artwork could not be read.</p>
          )}

          <div className="vale-zoom">
            <button
              type="button"
              className="secondary"
              aria-label="Zoom in"
              onClick={() => setView((current) => clampView({ ...current, zoom: current.zoom * 1.4 }))}
            >
              +
            </button>
            <button
              type="button"
              className="secondary"
              aria-label="Zoom out"
              onClick={() => setView((current) => clampView({ ...current, zoom: current.zoom / 1.4 }))}
            >
              -
            </button>
          </div>
        </div>

        {loading && <p className="notice">Loading.</p>}
        {loadError && (
          <p className="error" role="alert">
            {loadError}
          </p>
        )}

        {pending && (
          <div className="vale-confirm">
            <p className="vale-confirm-text">
              Set out for {pending.name}?
              {!pending.reachable && ' There is no open road there yet.'}
            </p>
            {travelError && (
              <p className="error" role="alert">
                {travelError}
              </p>
            )}
            <div className="choice">
              <button
                type="button"
                className="primary"
                disabled={settingOut}
                onClick={() => void confirmDestination()}
              >
                Set out
              </button>
              <button type="button" className="secondary" onClick={() => setPending(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}

        {state && !pending && (
          <p className="hint">
            Drag to move the map, pinch or scroll to zoom, tap a place to set out for it.
          </p>
        )}
      </section>

      {state && (
        <section className="card">
          <div className="hud">
            <div className="hud-cell">
              <span className="hud-label">Position</span>
              <span className="hud-value">{positionText(state)}</span>
            </div>
            <div className="hud-cell">
              <span className="hud-label">Setting out for</span>
              <span className="hud-value">
                {state.destination ? state.destination.name : 'Nowhere yet'}
              </span>
            </div>
            <div className="hud-cell">
              <span className="hud-label">Traveled</span>
              <span className="hud-value">{state.total_traveled_mi.toFixed(1)} Miles</span>
            </div>
            <div className="hud-cell">
              <span className="hud-label">Chests</span>
              <span className="hud-value">{state.unopened_chests} unopened</span>
            </div>
          </div>

          <div className="buckets">
            {ACTIVITY_ORDER.map((activity) => (
              <div className="bucket" key={activity}>
                <span className="bucket-name">{ACTIVITY_NAMES[activity]}</span>
                <span className="bucket-value">{state.buckets[activity].available.toFixed(1)}</span>
                <span className="bucket-unit">Miles</span>
              </div>
            ))}
          </div>
          <p className="hint">
            Miles are the world's own unit. Every synced mile converts at a rate for its activity,
            moves the marker, and banks into these.
          </p>
        </section>
      )}

      {state?.regions
        .filter((region) => !region.unlocked)
        .map((region) => {
          const available = state.buckets.run.available
          const share = Math.min(1, available / region.cost_run_miles)
          const affordable = available >= region.cost_run_miles
          return (
            <section className="card" key={region.id}>
              <h2>{region.name}</h2>
              <p className="hint">{region.detail}</p>
              <div className="meter" aria-hidden="true">
                <div className="meter-fill" style={{ width: `${(share * 100).toFixed(1)}%` }} />
              </div>
              <p className="note">
                {available.toFixed(1)} of {region.cost_run_miles} run Miles.
              </p>

              {unlockError && confirmRegion === region.id && (
                <p className="error" role="alert">
                  {unlockError}
                </p>
              )}

              {confirmRegion === region.id ? (
                <div className="choice">
                  <button
                    type="button"
                    className="primary"
                    disabled={unlocking}
                    onClick={() => void unlock(region.id)}
                  >
                    Spend {region.cost_run_miles} run Miles
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setConfirmRegion(null)}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="primary"
                  disabled={!affordable}
                  onClick={() => {
                    setUnlockError('')
                    setConfirmRegion(region.id)
                  }}
                >
                  {affordable ? 'Open the gate' : 'Not enough run Miles yet'}
                </button>
              )}
            </section>
          )
        })}

      <section className="card">
        <h2>Chests</h2>
        {chests.length === 0 && revealed.length === 0 && (
          <p className="hint">
            Nothing waiting. Chests turn up every few traveled Miles and keep until you open them.
          </p>
        )}

        {chestError && (
          <p className="error" role="alert">
            {chestError}
          </p>
        )}

        <ul className="chests">
          {chests.map((chest) => (
            <li key={chest.id}>
              <span>{chest.set_name} set</span>
              <button
                type="button"
                className="secondary"
                disabled={openingChest === chest.id}
                onClick={() => void open(chest.id)}
              >
                Open
              </button>
            </li>
          ))}
        </ul>

        {revealed.length > 0 && (
          <div className="reveal-grid">
            {revealed.map((result) => (
              <div key={result.card.id + String(result.count)}>
                <CardPlate
                  number={result.card.number}
                  rarity={result.card.rarity}
                  owned
                  cardId={result.card.id}
                  name={result.card.name}
                  flavor={result.card.flavor}
                  count={result.count}
                />
                <p className="hint">
                  {result.card.set_name} set.{' '}
                  {result.duplicate ? 'You already had this one.' : 'New to the album.'}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
