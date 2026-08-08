import { useState } from 'react'
import { errorText, plantSeed, type SatchelItem } from '../api.ts'
import { itemArt } from '../art.ts'
import { itemName } from '../labels.ts'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// What each thing is for, said plainly, and said only when it is asked for.
const KIND_LINES: Record<string, string> = {
  water: 'Pour it onto one plant in the grove.',
  oil: 'Anoint a friend with it from the grove.',
}

// Everything out of a chest goes the same place, and that is the whole of what
// a reveal says about water and oil until the picture is tapped.
const STOWED = 'Added to satchel.'

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
  // Water and oil say what they are for only when the picture is tapped.
  const [telling, setTelling] = useState(false)

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
  const seedLine = 'Plant it and it grows with your miles.'
  const art = seed ? null : itemArt(item.kind)
  const line = KIND_LINES[item.kind] ?? ''

  return (
    <div className="item-reveal">
      {/* A seed is drawn as what it grows into, framed in its rarity. Water and
          oil are drawn as themselves, and the picture is what is pressed to
          find out what they are for. */}
      {seed && item.species !== null && (
        <RarityFrame rarity={item.rarity} className="item-frame">
          <PlantArt
            species={item.species}
            name={itemName(item)}
            stage={1}
            className="item-thumb"
          />
        </RarityFrame>
      )}

      {art && (
        <button
          type="button"
          className="item-square item-square-button"
          aria-expanded={telling}
          aria-label={`What ${itemName(item)} is for`}
          onClick={() => setTelling((shown) => !shown)}
        >
          <img src={art} alt="" />
        </button>
      )}

      <div className="item-body">
        <p className="item-name">{itemName(item)}</p>
        <p className="hint item-line">{seed ? seedLine : STOWED}</p>
        {/* Said when the picture is pressed, and said outright where there is
            no picture to press: a missing file costs the drawing, not the one
            line that says what the thing is for. */}
        {!seed && line !== '' && (telling || art === null) && (
          <p className="hint item-line">{line}</p>
        )}
        {/* The one species with a rule of its own says it here, and the app
            explains nothing else about it anywhere. */}
        {item.reveal && <p className="hint item-line">{item.reveal}</p>}

        {seed && !planted && (
          <button type="button" className="secondary" disabled={busy} onClick={() => void plant()}>
            Plant
          </button>
        )}
        {planted && <p className="note note-success">Planted. It is in your grove.</p>}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
