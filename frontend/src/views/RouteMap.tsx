import { useEffect, useRef, useState } from 'react'
// v6 has no default export, and its Map would shadow the language's own.
import { MapLibreMap } from 'maplibre-gl'
import type { RoutePoint } from '../api.ts'
import { addRoute, archive, basemapStyle, bareStyle, corners } from '../mapgl.ts'
import { useTheme } from '../theme.ts'

// This file and the map module under it are chunks of their own: no part of
// maplibre is loaded until somebody taps a route or a thumbnail asks for a
// picture of one.

interface Props {
  // Already in hand: these are the points the thumbnail drew, so opening the
  // map asks the server for nothing and a route nobody can see has nothing to
  // tap.
  points: RoutePoint[]
  onClose: () => void
}

// The same modal dialog the letter and the chooser use, with a map in it: the
// focus trap, the page held still behind it, and Esc come with the element.
export default function RouteMap({ points, onClose }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const holder = useRef<HTMLDivElement>(null)
  const [installed, setInstalled] = useState(true)
  // The ground the map is drawn on, settled when the dialog opens and held for
  // as long as it is up: a theme flipped from behind the dialog leaves this map
  // on the ground it was built with, which is cheaper than tearing down a map
  // somebody is looking at, and it is gone at the next tap anyway.
  const theme = useTheme()
  const ground = useRef(theme)

  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  useEffect(() => {
    const box = holder.current
    if (!box) return
    let map: MapLibreMap | undefined
    let live = true

    void (async () => {
      // Asking the archive for its header answers the question once, here,
      // rather than as a hundred failed tile requests in the console.
      let have = true
      try {
        await archive.getHeader()
      } catch {
        have = false
      }
      if (!live) return
      setInstalled(have)

      map = new MapLibreMap({
        container: box,
        style: have ? basemapStyle(ground.current) : bareStyle(ground.current),
        bounds: corners(points),
        fitBoundsOptions: { padding: 40, animate: false },
        // Credit belongs with the tiles; with none drawn there is nobody to
        // credit.
        attributionControl: have && { compact: true },
      })

      map.on('load', () => {
        if (map) addRoute(map, points)
      })
    })()

    return () => {
      live = false
      map?.remove()
    }
  }, [points])

  return (
    <dialog
      className="overlay"
      ref={dialog}
      aria-label="Route map"
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onClose()
      }}
    >
      <section className="overlay-panel route-panel">
        <div className="route-canvas" ref={holder} />

        {/* Said where the route is big enough to be read off: the ends are
            trimmed before a workout is ever stored, so what is drawn here does
            not begin or end where the run did. True with or without an
            archive behind it. */}
        <div className="route-note">
          <p className="hint">Start and end of the route are hidden.</p>
          {!installed && <p className="hint">No basemap installed.</p>}
        </div>

        <footer className="overlay-foot">
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </footer>
      </section>
    </dialog>
  )
}
