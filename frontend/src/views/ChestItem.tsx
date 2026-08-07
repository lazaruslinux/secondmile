import { useState } from 'react'
import { errorText, plantSeed, type SatchelItem } from '../api.ts'
import { itemName, rarityWord } from '../labels.ts'
import PlantArt from './PlantArt.tsx'

// What each thing is for, said plainly. Nothing here is display-only: the line
// under the name is what to do with it.
const KIND_LINES: Record<string, string> = {
  water: 'Pour it onto one planting in the grove.',
  oil: 'Anoint a friend with it from the grove.',
}

interface Props {
  item: SatchelItem
  // Called after a seed goes into the ground, so the screen holding this can
  // read the plot again.
  onPlanted?: () => void
}

// What came out of a chest, with the one thing to do with it offered here. A
// seed is planted from where it was found; water and oil need something chosen
// first, so they wait in the satchel and the grove is where they are used.
export default function ChestItem({ item, onPlanted }: Props) {
  const [planted, setPlanted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function plant() {
    setBusy(true)
    setError('')
    try {
      await plantSeed(item.id)
      setPlanted(true)
      onPlanted?.()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const seed = item.kind === 'seed' && item.species !== null
  // How rare it is, then what to do with it. The one rarity with no word to it
  // simply leaves the first half off.
  const rarity = rarityWord(item.rarity)
  const seedLine = `${rarity === '' ? '' : `${rarity}. `}Plant it and it grows with your miles.`

  return (
    <div className="item-reveal">
      {/* A seed is drawn as what it grows into. Water and oil have nothing to
          draw, so nothing is drawn for them. */}
      {seed && item.species !== null && (
        <PlantArt species={item.species} name={item.name} stage={1} className="item-thumb" />
      )}

      <div className="item-body">
        <p className="item-name">{itemName(item)}</p>
        <p className="hint item-line">
          {seed ? seedLine : (KIND_LINES[item.kind] ?? 'In your satchel.')}
        </p>
        {/* The one species with a rule of its own says it here, and the app
            explains nothing else about it anywhere. */}
        {item.reveal && <p className="hint item-line">{item.reveal}</p>}

        {seed && !planted && (
          <button type="button" className="secondary" disabled={busy} onClick={() => void plant()}>
            Plant
          </button>
        )}
        {planted && <p className="note note-success">Planted. It is in your grove.</p>}
        {!seed && <p className="hint">In your satchel.</p>}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
