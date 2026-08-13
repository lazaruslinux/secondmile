import { useCallback, useEffect, useState } from 'react'
import {
  errorText,
  feedPlant,
  gatherHarvest,
  getFriends,
  getHarvest,
  giveFruit,
  listGrove,
  type FruitBatch,
  type HarvestState,
  type Person,
  type Planting,
} from '../api.ts'
import { convertedValue, fillClass, formatAcquired } from '../format.ts'
import { levelProgress, plantStage } from '../grove.ts'
import {
  EMPTY_BASKET,
  FED,
  feedHint,
  fedLine,
  FRUIT_GIVEN,
  GATHER_HINT,
  NOTHING_BORNE,
  NOTHING_PLANTED,
  HARVEST_HINT,
  personName,
  plantingName,
  plantStateLine,
  readyLine,
} from '../labels.ts'
import Chooser, { type Choice } from './Chooser.tsx'
import Confirm from './Confirm.tsx'
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
interface Cached {
  plantings: Planting[]
  harvest: HarvestState | null
}

const cache = new Map<number, Cached>()

// Where a tap has got to. Each one ends in a question, because every one of
// them spends something that cannot be got back.
type Step =
  | { at: 'none' }
  | { at: 'gather' }
  | { at: 'feed'; plant: Planting }
  | { at: 'give'; fruit: FruitBatch }

// What one gather brought in, said in the plainest words there are. The two
// halves are named separately because they arrive on different terms: the fruit
// comes whole and the manna comes by the amount that was asked for.
function gatheredLine(fruit: number, manna: number): string {
  const parts = []
  if (fruit > 0) parts.push(`${fruit} fruit`)
  if (manna > 0) parts.push(`${manna.toLocaleString()} manna`)
  return parts.length === 0 ? 'Nothing was ready.' : `Gathered ${parts.join(' and ')}.`
}

export default function Grove({ userId }: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [plantings, setPlantings] = useState<Planting[]>(
    () => cache.get(userId)?.plantings ?? [],
  )
  const [harvest, setHarvest] = useState<HarvestState | null>(
    () => cache.get(userId)?.harvest ?? null,
  )
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  const [step, setStep] = useState<Step>({ at: 'none' })
  const [busy, setBusy] = useState(false)
  const [stepError, setStepError] = useState('')
  const [note, setNote] = useState('')
  // How much of the waiting pile this gather is for. A string while it is being
  // typed, because a half-typed number is not one.
  const [wanted, setWanted] = useState('')
  const [friends, setFriends] = useState<Person[]>([])

  const load = useCallback(async () => {
    try {
      // The plot is what this screen is; the harvest rides beside it and is
      // allowed to fail on its own rather than taking the page down.
      const [plot, brought] = await Promise.all([listGrove(), getHarvest().catch(() => null)])
      setPlantings(plot)
      if (brought) setHarvest(brought)
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
    cache.set(userId, { plantings, harvest })
  }, [userId, plantings, harvest])

  const manna = harvest?.manna ?? 0
  const waiting = harvest?.manna_pending ?? 0
  const feedCost = harvest?.feed_cost ?? 0
  const feedCap = harvest?.feed_cap ?? 0
  const basket = harvest?.basket ?? []
  // What each plant is carrying, by plant, so a tile can say it without the
  // whole list being walked once per tile.
  const borne = new Map<number, FruitBatch[]>()
  for (const row of harvest?.borne ?? []) {
    if (row.planting_id === null) continue
    const held = borne.get(row.planting_id)
    if (held) held.push(row)
    else borne.set(row.planting_id, [row])
  }

  // Every act ends the same way the inventory's do: the server is asked again
  // for everything, and a refusal is the server's own sentence.
  async function act(work: () => Promise<void>) {
    setBusy(true)
    setStepError('')
    try {
      await work()
      await load()
    } catch (err) {
      setStepError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function openGather() {
    setNote('')
    setStepError('')
    // Enough to feed one plant to its cap, or whatever is waiting where that is
    // less. A suggestion and nothing more: the amount is the member's, and what
    // is left behind is safe.
    const suggest = Math.min(waiting, (harvest?.feed_cost ?? 0) * (harvest?.feed_cap ?? 0))
    setWanted(String(suggest))
    setStep({ at: 'gather' })
  }

  function gather() {
    const manna = Math.max(0, Math.min(waiting, Math.trunc(Number(wanted) || 0)))
    void act(async () => {
      const brought = await gatherHarvest(manna)
      setNote(gatheredLine(brought.fruit, brought.gathered_manna))
      setStep({ at: 'none' })
    })
  }

  function feed(plant: Planting) {
    void act(async () => {
      await feedPlant(plant.id)
      setNote(FED)
      setStep({ at: 'none' })
    })
  }

  async function toFriends(fruit: FruitBatch) {
    setNote('')
    setStepError('')
    setStep({ at: 'give', fruit })
    if (friends.length > 0) return
    try {
      setFriends((await getFriends()).friends)
    } catch (err) {
      setStepError(errorText(err))
    }
  }

  function give(fruit: FruitBatch, personId: number) {
    void act(async () => {
      await giveFruit(personId, fruit.id)
      setNote(FRUIT_GIVEN)
      setStep({ at: 'none' })
    })
  }

  const friendChoices: Choice[] = friends.map((person) => ({
    id: person.user_id,
    label: personName(person),
  }))

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

      {/* The harvest: what is ready, what is in the basket, and the one button
          that brings it in. It sits above the plot because it is the thing to
          do here, and the plot is the thing to look at. */}
      {harvest && (
        <section className="card">
          <h2 className="label">Harvest</h2>
          <p className="hint">{HARVEST_HINT}</p>

          <ul className="profile-counts harvest-counts">
            <li>
              <span className="count-value">{manna.toLocaleString()}</span>
              <span className="count-label">Manna gathered</span>
            </li>
            <li>
              <span className="count-value">{waiting.toLocaleString()}</span>
              <span className="count-label">Manna waiting</span>
            </li>
          </ul>

          {note && (
            <p className="note note-success" role="status">
              {note}
            </p>
          )}

          {harvest.ready ? (
            <div className="choice">
              <button type="button" className="primary" disabled={busy} onClick={openGather}>
                Gather
              </button>
            </div>
          ) : (
            <p className="hint">{NOTHING_BORNE}</p>
          )}

          <h3 className="label harvest-sub">Basket</h3>
          {basket.length === 0 ? (
            <p className="hint">{EMPTY_BASKET}</p>
          ) : (
            <ul className="basket">
              {basket.map((row) => (
                <li key={row.id} className="basket-row">
                  <div className="basket-body">
                    <p className="basket-name">{row.label}</p>
                    <p className="hint">{row.provenance}</p>
                  </div>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    aria-label={`Give ${row.label}`}
                    onClick={() => void toFriends(row)}
                  >
                    Give
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      <section className="card">
        <h2 className="label">Your plants</h2>
        {!loading && plantings.length === 0 && <p className="hint">{NOTHING_PLANTED}</p>}
        {plantings.length > 0 && (
          <ul className="plot">
            {plantings.map((row) => {
              // Every plant fills the same bar over and over, one level at a
              // time, until the last level, where there is nothing left to fill.
              const { into, step: span } = levelProgress(row)
              const carrying = borne.get(row.id) ?? []
              const fed = row.fed ?? 0
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
                      <progress className="xp-meter" value={into} max={span}>
                        {convertedValue(into)} of {convertedValue(span)} XP
                      </progress>
                      <p className="plant-numbers" aria-hidden="true">
                        <span
                          className={`plant-now ${fillClass(span > 0 ? (into / span) * 100 : 0)}`}
                        >
                          {convertedValue(into)}
                        </span>
                        <span className="plant-target">{convertedValue(span)}</span>
                      </p>
                    </div>
                  )}
                  <p className="plant-growth">Acquired {formatAcquired(row.planted_at)}</p>
                  <p className="plant-ready">{plantStateLine(row, plantStage(row))}</p>
                  {/* What it is holding and what it has been fed, under the
                      state line. Both are about the fruit and neither is about
                      the growth above them. */}
                  {carrying.map((one) => (
                    <p key={one.id} className="plant-fruit">
                      {readyLine(one.label)}
                    </p>
                  ))}
                  {fed > 0 && <p className="plant-fed">{fedLine(fed)}</p>}
                  {row.mature && (
                    <button
                      type="button"
                      className="secondary plant-feed"
                      disabled={busy || fed >= feedCap || manna < feedCost}
                      onClick={() => {
                        setNote('')
                        setStepError('')
                        setStep({ at: 'feed', plant: row })
                      }}
                    >
                      Feed
                    </button>
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
      </section>

      {/* How much of the waiting pile to bring in. Asked rather than assumed,
          because gathering starts the seven days and a pile built out of a year
          of calories is worth far more than a week of giving spends. */}
      {step.at === 'gather' && (
        <Confirm
          heading="Gather"
          confirmLabel="Gather"
          cancelLabel="Cancel"
          busy={busy}
          error={stepError}
          onConfirm={gather}
          onCancel={() => setStep({ at: 'none' })}
        >
          <p className="hint">{GATHER_HINT}</p>
          <label>
            Manna to gather
            <input
              type="number"
              min={0}
              max={waiting}
              step={1}
              value={wanted}
              onChange={(event) => setWanted(event.target.value)}
            />
          </label>
          <p className="hint">{waiting.toLocaleString()} waiting.</p>
        </Confirm>
      )}

      {step.at === 'feed' && (
        <Confirm
          heading={`Feed ${plantingName(step.plant)}`}
          confirmLabel="Feed"
          cancelLabel="Cancel"
          busy={busy}
          error={stepError}
          onConfirm={() => feed(step.plant)}
          onCancel={() => setStep({ at: 'none' })}
        >
          <p className="hint">{feedHint(feedCost)}</p>
        </Confirm>
      )}

      {step.at === 'give' && (
        <Chooser
          title={`Give ${step.fruit.label}`}
          hint={step.fruit.provenance}
          choices={friendChoices}
          empty="No friends yet. Invite someone from the You screen."
          busy={busy}
          error={stepError}
          searchPlaceholder="Search friends"
          onChoose={(id) => give(step.fruit, id)}
          onCancel={() => setStep({ at: 'none' })}
        />
      )}
    </>
  )
}
