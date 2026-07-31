import { cardArt } from '../cardArt.ts'
import type { Rarity } from '../api.ts'

const RARITY_NAMES: Record<Rarity, string> = {
  common: 'Common',
  uncommon: 'Uncommon',
  rare: 'Rare',
}

interface Props {
  number: number
  rarity: Rarity
  owned: boolean
  cardId?: string
  name?: string
  flavor?: string
  count?: number
  // The reveal after opening a chest shows the same plate, only bigger.
  large?: boolean
}

// One plate, used by the album, the recap, and the Vale. An unowned plate is
// deliberately almost empty: the number and the rarity are the only things the
// server tells us about a card nobody has found yet, and that is the point.
export default function CardPlate({
  number,
  rarity,
  owned,
  cardId,
  name,
  flavor,
  count,
  large = false,
}: Props) {
  const art = owned ? cardArt(cardId) : null
  const classes = ['plate']
  if (!owned) classes.push('plate-empty')
  if (large) classes.push('plate-large')

  return (
    <article className={classes.join(' ')}>
      <div className="plate-art">
        {art ? <img src={art} alt="" /> : <span className="plate-slot" aria-hidden="true" />}
      </div>
      <div className="plate-head">
        <span className="plate-number">No. {number}</span>
        <span className={`plate-rarity plate-${rarity}`}>{RARITY_NAMES[rarity]}</span>
      </div>
      {owned ? (
        <>
          <h3 className="plate-name">{name}</h3>
          {flavor && <p className="plate-flavor">{flavor}</p>}
          {count !== undefined && count > 1 && (
            <p className="plate-count">{count} copies</p>
          )}
        </>
      ) : (
        <p className="plate-unfound">Not found yet</p>
      )}
    </article>
  )
}
