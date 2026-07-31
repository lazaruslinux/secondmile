// Card illustrations, wired up by filename.
//
// Drop an image into src/assets/cards named after the card id, for example
// east_road_heron.png, and it appears on that plate the next time the frontend
// is built. Nothing else has to change: no import, no list, no code. A card
// with no file gets a plain plate instead. See docs/03-artwork.md.

const files = import.meta.glob('./assets/cards/*.{png,webp,svg}', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

const byCardId = new Map<string, string>()
for (const [path, url] of Object.entries(files)) {
  const file = path.slice(path.lastIndexOf('/') + 1)
  byCardId.set(file.slice(0, file.lastIndexOf('.')), url)
}

export function cardArt(cardId: string | undefined): string | null {
  if (!cardId) return null
  return byCardId.get(cardId) ?? null
}
