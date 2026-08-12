import { useCallback, useEffect, useState } from 'react'
import { errorText, listGrove, type Planting } from '../api.ts'
import { convertedValue, fillClass, formatAcquired } from '../format.ts'
import { levelProgress, plantStage } from '../grove.ts'
import { NOTHING_PLANTED, plantingName, plantStateLine } from '../labels.ts'
import Inventory from './Inventory.tsx'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// What the grove is, in three sentences, said once at the top and nowhere else.
// XP rather than miles: growth was always the weighted number, and the grove was
// the one place in the app wearing the word miles for it. Miles are raw distance
// everywhere else and stay that way.
const HEADER =
  "Plants grow with your XP. Water one of yours, or a friend's, for a 10 XP boost. " +
  'Level 33 is fully grown.'

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
        <h2 className="label">Your plants</h2>
        {!loading && plantings.length === 0 && <p className="hint">{NOTHING_PLANTED}</p>}
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
                        {convertedValue(into)} of {convertedValue(step)} XP
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
                  <p className="plant-ready">{plantStateLine(row, plantStage(row))}</p>
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
      </section>
    </>
  )
}
