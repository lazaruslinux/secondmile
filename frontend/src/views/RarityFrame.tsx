import type { ReactNode } from 'react'
import type { Rarity } from '../api.ts'
import { rarityTier, rarityWord } from '../labels.ts'

interface Props {
  rarity: Rarity | string
  // What the tab says, where the colour stands for something other than the
  // thing's own rarity: a chest is coloured by the floor of its step and named
  // for the step itself. Left out everywhere else.
  label?: string
  // Extra class for the places that size the square themselves.
  className?: string
  children: ReactNode
}

// The square a plant, a seed, or a tool with a rarity is drawn in: a border in
// its rarity, and the rarity named on a solid tab hanging off the foot of the
// square. Every square that holds something with a rarity uses this, so the
// plot, the satchel, and a chest reveal all say how rare a thing is the same
// way.
export default function RarityFrame({ rarity, label, className, children }: Props) {
  const tier = rarityTier(rarity)
  const classes = `rarity-frame rarity-${tier}${className ? ` ${className}` : ''}`

  return (
    <span className={classes}>
      <span className="rarity-square">{children}</span>
      <span className="rarity-tab">{label ?? rarityWord(tier)}</span>
    </span>
  )
}
