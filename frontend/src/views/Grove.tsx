import { useCallback, useEffect, useState } from 'react'
import { errorText, listGrove, type Planting } from '../api.ts'
import { convertedValue, fillClass, formatAcquired } from '../format.ts'
import { levelProgress, plantStage } from '../grove.ts'
import { plantingName } from '../labels.ts'
import Inventory from './Inventory.tsx'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// What the grove is, in three sentences, said once at the top and nowhere else.
const HEADER =
  "Your plants grow with your distance covered. Water them (or a friend's) for a 10 mile " +
  'boost. Plants begin bearing fruit once mature (level 1) and are fully grown at level 33.'

// What the oil in the inventory is for, said under the inventory itself. The
// word is oil here rather than olive oil: this is the act, not the item. It
// lifts a chest they earn themselves; it never sends one.
const ANOINT =
  'Anoint a friend with oil and one chest they earn opens one step rarer than it would have.'

// Said under anything that has reached the last level.
const FULLY_GROWN = 'Fully grown.'

interface Props {
  userId: number
}

// What this tab last showed, kept by account so a second person signing in on
// the same browser never sees the first one's grove. It lives as long as the
// page does and no longer.
const cache = new Map<number, Planting[]>()

export default function Grove({ userId }: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [plantings, setPlantings] = useState<Planting[]>(() => cache.get(userId) ?? [])
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  const load = useCallback(async () => {
    try {
      setPlantings(await listGrove())
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    cache.set(userId, plantings)
  }, [userId, plantings])

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">Grove</h1>
      </div>

      <section className="card">
        <p className="hint">{HEADER}</p>
      </section>

      {loading && <p className="notice">Loading.</p>}
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}

      <section className="card">
        <h2 className="label">The plot</h2>
        {!loading && plantings.length === 0 && (
          <p className="hint">Nothing planted yet. Seeds come out of chests.</p>
        )}
        {plantings.length > 0 && (
          <ul className="plot">
            {plantings.map((row) => {
              // Every plant fills the same bar over and over, one level at a
              // time, until the last level, where there is nothing left to fill.
              const { into, step } = levelProgress(row)
              return (
                <li key={row.id} className="plant">
                  <RarityFrame rarity={row.rarity} className="plant-frame">
                    <PlantArt
                      species={row.species}
                      name={plantingName(row)}
                      stage={plantStage(row)}
                      gilded={row.gilded}
                      className="plant-picture"
                    />
                  </RarityFrame>
                  <p className="plant-name">{plantingName(row)}</p>
                  {/* A progress element rather than a div with a width on it:
                      the content security policy allows no inline styles, and
                      this one reads correctly to a screen reader as well. The
                      miles ride under it, the ones covered at the fill point
                      and the ones this level costs at the end of the bar. */}
                  {!row.gilded && (
                    <div className="plant-scale">
                      <progress className="xp-meter" value={into} max={step}>
                        {convertedValue(into)} of {convertedValue(step)} mi
                      </progress>
                      <p className="plant-numbers" aria-hidden="true">
                        <span
                          className={`plant-now ${fillClass(step > 0 ? (into / step) * 100 : 0)}`}
                        >
                          {convertedValue(into)}
                        </span>
                        <span className="plant-target">{convertedValue(step)}</span>
                      </p>
                    </div>
                  )}
                  <p className="plant-growth">Acquired {formatAcquired(row.planted_at)}</p>
                  <p className="plant-growth">Lv {row.level}</p>
                  {row.gilded && <p className="plant-ready">{FULLY_GROWN}</p>}
                  {row.mature && !row.gilded && (
                    <p className="plant-ready">Grown. It waits here to bear fruit.</p>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* The squares sit here on the page rather than behind a button: what is
          held is half of what this screen is about. */}
      <section className="card">
        <h2 className="label">Inventory</h2>
        <Inventory onChanged={() => void load()} />
        <p className="hint inv-explainer">{ANOINT}</p>
      </section>
    </>
  )
}
