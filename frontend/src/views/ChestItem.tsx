import { useState } from 'react'
import { errorText, plantSeed, type SatchelItem } from '../api.ts'
import { itemArt } from '../art.ts'
import {
  ITEM_LINES,
  itemName,
  itemRarity,
  itemTabLabel,
  PLANTED,
  REVEAL_LINES,
} from '../labels.ts'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// Everything out of a chest goes the same place, and that is the whole of what
// a reveal says about a tool until the picture is tapped.
const STOWED = 'Added to inventory.'

interface Props {
  item: SatchelItem
  // Called after a seed goes into the ground, so the screen holding this can
  // read the plot again.
  onPlanted?: () => void
}

// What came out of a chest, with the one thing to do with it offered here. A
// seed is planted from where it was found; every tool needs something chosen
// first, so they wait in the satchel and the grove is where they are used.
export default function ChestItem({ item, onPlanted }: Props) {
  const [planted, setPlanted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // A tool says what it is for only when the picture is tapped.
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
  const art = seed ? null : itemArt(item.kind)
  const line = REVEAL_LINES[item.kind] ?? ''

  // The picture of a tool is what is pressed to find out what it is for. The
  // square around it and its border belong to the frame, so the button is only
  // the picture.
  const picture = art && (
    <button
      type="button"
      className="item-art-button"
      aria-expanded={telling}
      aria-label={`What ${itemName(item)} is for`}
      onClick={() => setTelling((shown) => !shown)}
    >
      <img className="item-art" src={art} alt="" />
    </button>
  )

  return (
    <div className="item-reveal">
      {/* A seed is drawn as what it grows into, framed in its rarity. A tool is
          drawn as itself, in a frame of its own. */}
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

      {picture && (
        <RarityFrame
          rarity={itemRarity(item)}
          label={itemTabLabel(item)}
          className="item-frame"
        >
          {picture}
        </RarityFrame>
      )}

      <div className="item-body">
        <p className="item-name">{itemName(item)}</p>
        <p className="hint item-line">{seed ? ITEM_LINES.seed : STOWED}</p>
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
        {planted && <p className="note note-success">{PLANTED}</p>}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
