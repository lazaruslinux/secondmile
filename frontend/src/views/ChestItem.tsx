import { useState } from 'react'
import { errorText, plantSeed, type SatchelItem } from '../api.ts'
import { itemArt } from '../art.ts'
import { itemFramed, itemName, itemRarity } from '../labels.ts'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// What each thing is for, said plainly, and said only when it is asked for.
const KIND_LINES: Record<string, string> = {
  water: 'Pour it onto one plant in the grove.',
  oil: 'Anoint a friend with it from the grove.',
  wish: 'Choose what it will become: any seed you have not yet found.',
}

// Everything out of a chest goes the same place, and that is the whole of what
// a reveal says about a tool until the picture is tapped.
const STOWED = 'Added to satchel.'

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
  const seedLine = 'Plant it and it grows with your miles.'
  const art = seed ? null : itemArt(item.kind)
  const line = KIND_LINES[item.kind] ?? ''
  // Oil and a wish carry a rarity and are framed in it; water carries none.
  const framed = itemFramed(item)

  // The picture of a tool is what is pressed to find out what it is for. Framed
  // or not, it is the same button; the frame only changes what is around it.
  const picture = art && (
    <button
      type="button"
      className={framed ? 'item-art-button' : 'item-square item-square-button'}
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
          drawn as itself, framed only where it has a rarity to name. */}
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

      {framed ? (
        picture && (
          <RarityFrame rarity={itemRarity(item)} className="item-frame">
            {picture}
          </RarityFrame>
        )
      ) : (
        picture
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
