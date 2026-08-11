// Is the optional tiles archive installed on this server? Asked once a session,
// with a request for a single byte, and answered before anything decides to
// fetch a renderer the size of maplibre. Nothing here imports the map: a
// self-hoster who skipped the archive never downloads that chunk at all.

export const TILES = '/tiles/basemap.pmtiles'

let asked: Promise<boolean> | undefined

export function basemapInstalled(): Promise<boolean> {
  asked ??= fetch(TILES, { headers: { Range: 'bytes=0-0' } })
    .then((answer) => {
      // A server that honours the range sends 206 and the one byte asked for.
      // One that ignores it answers 200 and starts sending the whole archive,
      // which gets dropped on the spot rather than pulled down.
      if (answer.status !== 206) void answer.body?.cancel()
      return answer.status === 200 || answer.status === 206
    })
    .catch(() => false)
  return asked
}
