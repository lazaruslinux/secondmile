// What is held, gathered into squares. The grid on the Grove screen and the item
// popup a friend's plant opens both draw the same square out of the same pile,
// so a square means the same thing wherever it is drawn.

import type { ItemKind, SatchelItem, Chest } from './api.ts'
import { itemName } from './labels.ts'

// A chest is not a satchel item and never sits in one, but it is held and
// unspent, which is the whole of what a square means.
export type StackKind = ItemKind | 'chest'

// One square. Everything of a kind piles onto one square with a count on it, so
// nine seeds are nine squares rather than nine rows.
export interface Stack {
  key: string
  kind: StackKind
  // Which step of the ladder a chest stack came off. Null for everything else.
  tier: string | null
  name: string
  // What is behind the square, oldest first. A chest stack carries chests and
  // nothing else; every other stack carries satchel items.
  items: SatchelItem[]
  chests: Chest[]
}

// Satchel items piled into squares: seeds by species and every tool by its kind.
// A wish is named by the server where it has said what to call one, because the
// word for it is content rather than a label written here.
export function pileItems(items: SatchelItem[], wishName = ''): Stack[] {
  const stacks = new Map<string, Stack>()
  for (const item of items) {
    const key = item.kind === 'seed' ? `seed:${item.species ?? ''}` : item.kind
    const held = stacks.get(key)
    if (held) {
      held.items.push(item)
      continue
    }
    stacks.set(key, {
      key,
      kind: item.kind,
      tier: null,
      name: item.kind === 'wish' && wishName !== '' ? wishName : itemName(item),
      items: [item],
      chests: [],
    })
  }
  return [...stacks.values()]
}
