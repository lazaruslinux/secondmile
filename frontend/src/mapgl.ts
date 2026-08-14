// Everything the renderer needs to draw one of our routes over the self-hosted
// basemap: the worker, the archive, the style, the line. Two callers share it,
// the tapped-open modal and the hidden thumbnail renderer, and neither is
// reachable from the main bundle: importing this file is what pulls maplibre in.

// v6 has no default export, and its Map would shadow the language's own.
import { addProtocol, MapLibreMap, setWorkerUrl, type GeoJSONSource, type StyleSpecification } from 'maplibre-gl'
// maplibre parses tiles in a worker that ships as its own module file, and it
// finds that file by a path the bundler cannot see. Vite is asked for the
// built worker's URL here, so it is emitted and served from our own origin.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { PMTiles, Protocol } from 'pmtiles'
import { type Flavor, layers, namedFlavor } from '@protomaps/basemaps'
import type { RoutePoint } from './api.ts'
import { TILES } from './basemap.ts'
import type { Theme } from './theme.ts'
import 'maplibre-gl/dist/maplibre-gl.css'

setWorkerUrl(workerUrl)

// One archive, served by our own nginx and read in slivers by byte range, so
// the browser never downloads a file that size. Registering the protocol is
// global to maplibre and happens once, when this chunk arrives.
const protocol = new Protocol()
addProtocol('pmtiles', protocol.tile)
export const archive = new PMTiles(TILES)
protocol.add(archive)

// Glyphs and sprites are files in the build, like the app's own fonts: the map
// reaches outside this origin for nothing at all. Written out in full because
// maplibre refuses a relative sprite URL, and our own origin is the only one
// these can ever name. One sprite sheet per ground, the same keys in both; the
// glyphs are the lettering and are shared.
const GLYPHS = `${location.origin}/basemap/fonts/{fontstack}/{range}.pbf`
const SPRITES = `${location.origin}/basemap/sprites`

// The tiles are OpenStreetMap under ODbL, which asks for the credit. It is the
// only fine print in the app, and it stays folded into the compact control
// until somebody asks for it.
const CREDIT =
  '<a href="https://github.com/protomaps/basemaps" target="_blank" rel="noreferrer">Protomaps</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>'

// The map is drawn on the ground the app is: a caller says which, because
// neither of the two builds a map without knowing already.
const GROUNDS: Record<Theme, Flavor> = {
  dark: namedFlavor('dark'),
  light: namedFlavor('light'),
}

// maplibre wants a colour as a string, so the app's own token is read off the
// root rather than written down a second time here.
function accent(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
}

export function basemapStyle(theme: Theme): StyleSpecification {
  return {
    version: 8,
    glyphs: GLYPHS,
    sprite: `${SPRITES}/${theme}`,
    sources: {
      protomaps: {
        type: 'vector',
        url: `pmtiles://${TILES}`,
        attribution: CREDIT,
      },
    },
    // Cast because the flavor's layers are typed against its own copy of the
    // style spec, which is the same shape under a different name.
    layers: layers('protomaps', GROUNDS[theme], { lang: 'en' }),
  } as StyleSpecification
}

// No archive installed: the same ground the basemap would have painted, and the
// route on top of it. The shape still reads, which is the part that was always
// ours.
export function bareStyle(theme: Theme): StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'ground',
        type: 'background',
        paint: { 'background-color': GROUNDS[theme].background },
      },
    ],
  }
}

// The server sends latitude first and maplibre wants longitude first.
export function corners(points: RoutePoint[]): [[number, number], [number, number]] {
  const lats = points.map(([lat]) => lat)
  const lons = points.map(([, lon]) => lon)
  return [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ]
}

function routeData(points: RoutePoint[]) {
  return {
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'LineString' as const,
      coordinates: points.map(([lat, lon]) => [lon, lat]),
    },
  }
}

// The route as one crimson stroke, added once to a loaded map.
export function addRoute(map: MapLibreMap, points: RoutePoint[]): void {
  map.addSource('route', { type: 'geojson', data: routeData(points) })
  map.addLayer({
    id: 'route',
    type: 'line',
    source: 'route',
    layout: { 'line-cap': 'round', 'line-join': 'round' },
    paint: { 'line-color': accent(), 'line-width': 3 },
  })
}

// The same stroke, given a different route: a map that is drawing one workout
// after another keeps its layer and only changes what is in it.
export function setRoute(map: MapLibreMap, points: RoutePoint[]): void {
  ;(map.getSource('route') as GeoJSONSource).setData(routeData(points))
}
