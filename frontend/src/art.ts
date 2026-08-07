// Every picture in the app, wired up by filename.
//
// Drop a file into src/assets named the way docs/03-artwork.md describes and it
// appears at the next build. Nothing else has to change: no import, no list, no
// code. A name with no file falls back to something plain.

function byName(files: Record<string, string>): Map<string, string> {
  const out = new Map<string, string>()
  for (const [path, url] of Object.entries(files)) {
    const file = path.slice(path.lastIndexOf('/') + 1)
    out.set(file.slice(0, file.lastIndexOf('.')), url)
  }
  return out
}

const cards = byName(
  import.meta.glob('./assets/cards/*.{png,webp,svg}', {
    eager: true,
    query: '?url',
    import: 'default',
  }) as Record<string, string>,
)

const borders = byName(
  import.meta.glob('./assets/borders/*.svg', {
    eager: true,
    query: '?url',
    import: 'default',
  }) as Record<string, string>,
)

const badges = byName(
  import.meta.glob('./assets/badges/*.svg', {
    eager: true,
    query: '?url',
    import: 'default',
  }) as Record<string, string>,
)

// Interface icons are read as markup rather than as a URL, because they are
// drawn inline: currentColor only means anything inside the page's own tree, and
// an icon that cannot take the colour of the tab holding it is no use here.
const icons = byName(
  import.meta.glob('./assets/icons/*.svg', {
    eager: true,
    query: '?raw',
    import: 'default',
  }) as Record<string, string>,
)

export function cardArt(cardId: string | undefined): string | null {
  if (!cardId) return null
  return cards.get(cardId) ?? null
}

export function borderArt(tier: number): string | null {
  return borders.get(`border-t${tier}`) ?? null
}

// The markup of one interface icon, named after its file without the extension.
export function iconArt(name: string): string | null {
  return icons.get(name) ?? null
}

export interface BadgeArt {
  url: string | null
  // True only when the file being drawn is the achievement's own gilded
  // artwork. When it is false and the badge is gilded, the app adds a gilded
  // treatment of its own instead, so the difference is always visible.
  gildedArt: boolean
}

export function badgeArt(
  achievementId: string,
  kind: string,
  gilded: boolean,
): BadgeArt {
  if (gilded) {
    const finer = badges.get(`${achievementId}-gilded`)
    if (finer) return { url: finer, gildedArt: true }
  }
  return {
    url: badges.get(achievementId) ?? badges.get(`kind-${kind}`) ?? null,
    gildedArt: false,
  }
}
