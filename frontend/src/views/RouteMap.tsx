import { useEffect, useRef, useState } from 'react'
// v6 has no default export, and its Map would shadow the language's own.
import { addProtocol, MapLibreMap, setWorkerUrl, type StyleSpecification } from 'maplibre-gl'
// maplibre parses tiles in a worker that ships as its own module file, and it
// finds that file by a path the bundler cannot see. Vite is asked for the
// built worker's URL here, so it is emitted and served from our own origin.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { PMTiles, Protocol } from 'pmtiles'
import { layers, namedFlavor } from '@protomaps/basemaps'
import type { RoutePoint } from '../api.ts'
import 'maplibre-gl/dist/maplibre-gl.css'

// The whole of this file, maplibre included, is a chunk of its own: nothing
// here is loaded until somebody taps a route.

setWorkerUrl(workerUrl)

// One archive, served by our own nginx and read in slivers by byte range, so
// the browser never downloads a file that size. Registering the protocol is
// global to maplibre and happens once, when this chunk arrives.
const TILES = '/tiles/basemap.pmtiles'
const protocol = new Protocol()
addProtocol('pmtiles', protocol.tile)
const archive = new PMTiles(TILES)
protocol.add(archive)

// Glyphs and sprites are files in the build, like the app's own fonts: the map
// reaches outside this origin for nothing at all. Written out in full because
// maplibre refuses a relative sprite URL, and our own origin is the only one
// these can ever name.
const GLYPHS = `${location.origin}/basemap/fonts/{fontstack}/{range}.pbf`
const SPRITE = `${location.origin}/basemap/sprites/dark`

// The tiles are OpenStreetMap under ODbL, which asks for the credit. It is the
// only fine print in the app, and it stays folded into the compact control
// until somebody asks for it.
const CREDIT =
  '<a href="https://github.com/protomaps/basemaps" target="_blank" rel="noreferrer">Protomaps</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'

const DARK = namedFlavor('dark')

// maplibre wants a colour as a string, so the app's own token is read off the
// root rather than written down a second time here.
function accent(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
}

function basemapStyle(): StyleSpecification {
  return {
    version: 8,
    glyphs: GLYPHS,
    sprite: SPRITE,
    sources: {
      protomaps: {
        type: 'vector',
        url: `pmtiles://${TILES}`,
        attribution: CREDIT,
      },
    },
    // Cast because the flavor's layers are typed against its own copy of the
    // style spec, which is the same shape under a different name.
    layers: layers('protomaps', DARK, { lang: 'en' }),
  } as StyleSpecification
}

// No archive installed: the same dark ground the basemap would have painted,
// and the route on top of it. The shape still reads, which is the part that
// was always ours.
function bareStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      { id: 'ground', type: 'background', paint: { 'background-color': DARK.background } },
    ],
  }
}

// The server sends latitude first and maplibre wants longitude first.
function corners(points: RoutePoint[]): [[number, number], [number, number]] {
  const lats = points.map(([lat]) => lat)
  const lons = points.map(([, lon]) => lon)
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ]
}

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
        style: have ? basemapStyle() : bareStyle(),
        bounds: corners(points),
        fitBoundsOptions: { padding: 40, animate: false },
        // Credit belongs with the tiles; with none drawn there is nobody to
        // credit.
        attributionControl: have && { compact: true },
      })

      map.on('load', () => {
        map?.addSource('route', {
          type: 'geojson',
          data: {
            type: 'Feature',
            properties: {},
            geometry: {
              type: 'LineString',
              coordinates: points.map(([lat, lon]) => [lon, lat]),
            },
          },
        })
        map?.addLayer({
          id: 'route',
          type: 'line',
          source: 'route',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': accent(), 'line-width': 3 },
        })
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

        {!installed && <p className="hint route-missing">No basemap installed.</p>}

        <footer className="overlay-foot">
          <button type="button" className="secondary" onClick={onClose}>
            Close
          </button>
        </footer>
      </section>
    </dialog>
  )
}
