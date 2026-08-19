import type { ReactNode } from 'react'
import type { Rarity } from '../api.ts'
import { rarityTier, rarityWord } from '../labels.ts'

interface Props {
  rarity: Rarity | string
  // What the tab says: the name of the thing in the square. Left out only by a
  // caller that has nothing to name.
  label?: string
  // Extra class for the places that size the square themselves.
  className?: string
  children: ReactNode
}

// The square a plant, a seed, or a tool is drawn in: a border in its rarity, and
// the name of the thing itself on a solid tab hanging off the foot of the
// square. The colour is the whole of what says how rare a thing is, so no tab
// ever spends a word on it. Every square that holds something uses this, so the
// plot, the satchel, and a chest reveal all read the same way.
export default function RarityFrame({ rarity, label, className, children }: Props) {
  const tier = rarityTier(rarity)
  const classes = `rarity-frame rarity-${tier}${className ? ` ${className}` : ''}`

  return (
    <span className={classes}>
      <span className="rarity-square">{children}</span>
      {/* The rarity word is what is left for a caller with nothing to name, and
          it beats an empty tab. Only an empty square or a seed that arrived
          without a species gets this far. */}
      <span className="rarity-tab">{label ?? rarityWord(tier)}</span>
    </span>
  )
}
