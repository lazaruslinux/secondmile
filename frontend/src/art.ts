// Every picture in the app, wired up by filename.
//
// Drop a file into src/assets named the way docs/03-artwork.md describes and it
// appears at the next build. Nothing else has to change: no import, no list, no
// code. A name with no file falls back to something plain.

import type { Theme } from './theme.ts'

function byName(files: Record<string, string>): Map<string, string> {
  const out = new Map<string, string>()
  for (const [path, url] of Object.entries(files)) {
    const file = path.slice(path.lastIndexOf('/') + 1)
    out.set(file.slice(0, file.lastIndexOf('.')), url)
  }
  return out
}

const grove = byName(
  import.meta.glob('./assets/grove/*.{png,webp,svg}', {
    eager: true,
    query: '?url',
    import: 'default',
  }) as Record<string, string>,
)

// The owner's own paintings, tried before the committed set. The folder is
// git-ignored on purpose: art in progress lives on this instance without
// riding into the repository, and a file here beats its committed namesake at
// the next build. Same names, same rules as assets/grove.
const groveCustom = byName(
  import.meta.glob('./assets/grove-custom/*.{png,webp,svg}', {
    eager: true,
    query: '?url',
    import: 'default',
  }) as Record<string, string>,
)

// One grove picture by name, the owner's version first.
function groveFile(name: string): string | null {
  return groveCustom.get(name) ?? grove.get(name) ?? null
}

const borders = byName(
  import.meta.glob('./assets/borders/*.svg', {
    eager: true,
    query: '?url',
    import: 'default',
  }) as Record<string, string>,
)

const badges = byName(
  import.meta.glob('./assets/badges/*.{png,webp,svg}', {
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

// The two names one species at one of its three stages can read, in the order
// they are tried. Files are named with hyphens, strawberry-s1.png through
// mustard-s3.png, while the ids the server sends may use underscores. A species
// whose id carries a word the files do not, such as a mustard tree against
// mustard-s3.png, falls back to its first word, so a naming difference costs a
// picture rather than the screen.
function groveNames(species: string, stage: number): [string, string] {
  const name = species.toLowerCase().replace(/_/g, '-')
  const step = `-s${Math.min(3, Math.max(1, Math.round(stage)))}`
  return [name + step, name.split('-')[0] + step]
}

export function groveArt(species: string, stage: number): string | null {
  const [name, fallback] = groveNames(species, stage)
  return groveFile(name) ?? groveFile(fallback)
}

// Whether the picture groveArt found is the owner's rather than the committed
// one. The two are scaled differently, so whoever draws it has to know which it
// got.
export function groveArtCustom(species: string, stage: number): boolean {
  const [name, fallback] = groveNames(species, stage)
  return groveCustom.has(groveFile(name) ? name : fallback)
}

// The one gild treatment, laid over anything fully grown. Every species shares
// it until each gets artwork of its own.
export function gildArt(): string | null {
  return groveFile('gild')
}

// The soil the band on a profile stands its plot on. One file for the whole
// strip, stretched to the width of the band.
export function groundArt(): string | null {
  return groveFile('ground')
}

// Everything on the inventory grid that is not a plant: water, oil, the
// unmarked seed, and an unopened chest. Each reads one file named after its
// kind, and a kind with no file of its own draws nothing.
export function itemArt(kind: string): string | null {
  return groveFile(kind)
}

// The art that sits on the page itself rather than in a well exists twice, once
// per ground: name-light.svg beside name.svg, the same drawing with its palette
// turned over. Asking for a twin that was never drawn gets the dark file, so a
// missing twin costs contrast rather than the picture. The theme is passed in
// rather than read from the document, which is what makes it impossible to draw
// one of these without also subscribing to the ground it is drawn on.
function onGround(files: Map<string, string>, name: string, theme: Theme): string | null {
  if (theme === 'light') {
    const light = files.get(`${name}-light`)
    if (light) return light
  }
  return files.get(name) ?? null
}

export function borderArt(tier: number, theme: Theme): string | null {
  return onGround(borders, `border-t${tier}`, theme)
}

// The growth that lies over a border, one file per stage. Stage 0 is bare frame
// and has no file, which is why nothing is drawn for it.
export function flourishArt(stage: number, theme: Theme): string | null {
  if (!(stage > 0)) return null
  return onGround(borders, `flourish-f${stage}`, theme)
}

// The markup of one interface icon, named after its file without the extension.
export function iconArt(name: string): string | null {
  return icons.get(name) ?? null
}

// Which file each medal is drawn from. This mapping is the swap contract: put
// a different drawing in the named file and that medal changes everywhere,
// with nothing else to edit. Ids come from the server with underscores; files
// are named with hyphens, and the time family carries its family in its name.
const MEDAL_FILES: Record<string, string> = {
  race_1mi: 'race-1mi',
  race_2mi: 'race-2mi',
  race_5k: 'race-5k',
  race_10k: 'race-10k',
  race_half: 'race-half',
  race_marathon: 'race-marathon',
  race_ultra: 'race-ultra',
  weekly_10: 'weekly-10',
  weekly_15: 'weekly-15',
  weekly_25: 'weekly-25',
  weekly_40: 'weekly-40',
  early_riser: 'time-early-riser',
  night_owl: 'time-night-owl',
  cycle_10: 'cycle-10',
  cycle_25: 'cycle-25',
  cycle_50: 'cycle-50',
  cycle_100: 'cycle-100',
  swim_half: 'swim-half',
  swim_1: 'swim-1',
  swim_2: 'swim-2',
  lifetime_100: 'lifetime-100',
  lifetime_250: 'lifetime-250',
  lifetime_500: 'lifetime-500',
  lifetime_1000: 'lifetime-1000',
  cycle_lifetime_100: 'cycle-lifetime-100',
  cycle_lifetime_250: 'cycle-lifetime-250',
  cycle_lifetime_500: 'cycle-lifetime-500',
  cycle_lifetime_1000: 'cycle-lifetime-1000',
  swim_lifetime_10: 'swim-lifetime-10',
  swim_lifetime_25: 'swim-lifetime-25',
  swim_lifetime_50: 'swim-lifetime-50',
  swim_lifetime_100: 'swim-lifetime-100',
}

// A medal id this build has never heard of falls back to its id read as a file
// name, so a medal added on the server costs a picture rather than a screen.
export function medalArt(medalId: string, theme: Theme): string | null {
  return onGround(badges, MEDAL_FILES[medalId] ?? medalId.replace(/_/g, '-'), theme)
}
