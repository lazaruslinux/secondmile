import { useCallback, useEffect, useState } from 'react'
import {
  errorText,
  feedPet,
  feedPlant,
  gatherHarvest,
  getFriends,
  getHarvest,
  giveFruit,
  listGrove,
  namePet,
  type FruitBatch,
  type Gathered,
  type HarvestState,
  type Person,
  type Pet,
  type Planting,
} from '../api.ts'
import { itemArt } from '../art.ts'
import { convertedValue, fillClass, formatAcquired } from '../format.ts'
import { levelProgress, plantStage } from '../grove.ts'
import {
  basketLine,
  EMPTY_BASKET,
  FED,
  feedHint,
  fedLine,
  fromPlantsLine,
  FRUIT_GIVEN,
  GATHERED_GOLDEN,
  GIVE_FRUIT_HINT,
  GATHER_HINT,
  harvestHint,
  NOTHING_BORNE,
  NOTHING_PLANTED,
  personName,
  petArrivedLine,
  PET_ASLEEP,
  PET_FED,
  PET_FED_GOLDEN,
  PET_FEED_HINT,
  petGrewLine,
  PET_NAMED,
  PET_PATTED,
  plantingName,
  plantStateLine,
  readyLine,
} from '../labels.ts'
import { asList } from '../recap.ts'
import Chooser, { type Choice } from './Chooser.tsx'
import Confirm from './Confirm.tsx'
import Inventory from './Inventory.tsx'
import PetArt from './PetArt.tsx'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// Says XP, not miles: growth is the weighted number.
const HEADER =
  "Plants grow with your XP. Water one of yours, or a friend's, for a 10 XP boost. " +
  'Level 33 is fully grown.'

// The longest name a pet takes, held to here as well as on the server so the
// box stops rather than the save failing.
const NAME_LIMIT = 60

// LOOK-AND-TUNE. When each half of the set is down, by the clock on this
// device: the night animals sleep through the day and the morning ones sleep
// through the night. Whole hours, the first counted and the last not, and a
// window that runs past midnight is written as it reads.
//
// Nothing is scheduled off these and nothing counts down: they are read while
// the screen is being drawn and that is the whole of it. A sleeping pet can
// still be fed, named and patted.
const NIGHT_SET = ['bat', 'cat', 'wolf']
const NIGHT_SLEEP: [number, number] = [9, 19]
const MORNING_SET = ['dog', 'sheep', 'rooster']
const MORNING_SLEEP: [number, number] = [21, 5]

function withinHours(hour: number, [from, until]: [number, number]): boolean {
  return from <= until ? hour >= from && hour < until : hour >= from || hour < until
}

// Whether this species is asleep at this moment. A species in neither set is
// awake, so a seventh animal costs nothing here.
function asleepNow(species: string, moment: Date): boolean {
  const hour = moment.getHours()
  if (NIGHT_SET.includes(species)) return withinHours(hour, NIGHT_SLEEP)
  if (MORNING_SET.includes(species)) return withinHours(hour, MORNING_SLEEP)
  return false
}

// Marks that accompany words on this screen and never stand in for them. Both
// are looked up once: the set of files is fixed at build time.
const BASKET_MARK = itemArt('basket')
const FRUIT_MARK = itemArt('fruit')

interface Props {
  userId: number
  // Whether the grove has fruit on it, said upward every time this screen
  // learns it. The app draws the mark on the tab and this screen is the only
  // place a harvest is brought in, so the mark clears on the same tap that
  // empties the plants rather than on the next load.
  onFruitReady?: (ready: boolean) => void
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
  | { at: 'give' }
  | { at: 'giveAmount'; person: Person }
  | { at: 'feedPet'; pet: Pet }
  | { at: 'namePet'; pet: Pet }

// The batches this gather brought in. The basket carries whatever was gathered
// in the days before it too, and one gather stamps everything it takes with the
// same moment, so the newest stamp is the whole of what just happened.
function justGathered(brought: Gathered): FruitBatch[] {
  let newest = ''
  for (const row of brought.basket) {
    if (row.gathered_at !== null && row.gathered_at > newest) newest = row.gathered_at
  }
  return newest === '' ? [] : brought.basket.filter((row) => row.gathered_at === newest)
}

// What the gather was, under the count. Named while there are few enough kinds
// to read at a glance, and how many plants bore otherwise. Never a list and
// never a row: one sentence or nothing.
//
// Piled by the name the server wrote rather than by the species, because a
// gilded plant's harvest is a word of its own and two batches that read the
// same are one pile to say.
function gatheredTally(brought: Gathered): string {
  const rows = justGathered(brought)
  if (rows.length === 0) return ''
  const piles = new Map<string, { label: string; count: number; batches: number }>()
  for (const row of rows) {
    const held = piles.get(row.name)
    if (held) {
      held.count += row.count
      held.batches += 1
    } else piles.set(row.name, { label: row.label, count: row.count, batches: 1 })
  }
  if (piles.size > 3) {
    // The server's own count of what bore, which is the number this sentence
    // is about: one batch is one plant's answer to one season.
    const plants = fromPlantsLine(brought.batches)
    // The gilded word is only carried by the names, so where they are not said
    // it gets the one short sentence instead.
    return rows.some((row) => row.golden) ? `${plants} ${GATHERED_GOLDEN}` : plants
  }
  // One batch says the label the server already joined; several of a kind are
  // added up and take the plural word beside it, which two or more always is.
  const parts = [...piles].map(([name, pile]) =>
    pile.batches === 1 ? pile.label : `${pile.count} ${name}`,
  )
  return `${asList(parts)}.`
}

// What one harvest brought in, said in the plainest words there are: the count,
// then the one sentence about what it was.
function gatheredLine(brought: Gathered): string {
  if (brought.fruit === 0) return 'Nothing was ready.'
  const tally = gatheredTally(brought)
  const head = `Harvested ${brought.fruit} fruit.`
  return tally === '' ? head : `${head} ${tally}`
}

export default function Grove({ userId, onFruitReady }: Props) {
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
  // The pet card's own line, so a word about an animal never appears over the
  // harvest above it and the two never talk over each other.
  const [petNote, setPetNote] = useState('')
  // What the growing one's picture is doing: how the last feed answered, or the
  // hop a pat replays. The count is what makes two in a row two movements: the
  // art is drawn fresh on it, which is what starts the keyframes again.
  const [fedMark, setFedMark] = useState({ tick: 0, how: '' })
  // Which resident was last patted and how many times. The same idea as the
  // mark above, kept apart because the ones on the floor move one at a time.
  // Nothing here is sent anywhere and nothing survives the page.
  const [patMark, setPatMark] = useState({ tick: 0, id: 0 })
  // The name being typed, held here because the dialog is redrawn on every key.
  const [typedName, setTypedName] = useState('')
  // How much fruit this gift is for, as it is being typed. The same box the
  // manna gift uses on a friend's screen.
  const [amount, setAmount] = useState('')
  const [friends, setFriends] = useState<Person[]>([])

  const load = useCallback(async () => {
    try {
      // The plot is what this screen is; the harvest rides beside it and is
      // allowed to fail on its own rather than taking the page down.
      const [plot, brought] = await Promise.all([listGrove(), getHarvest().catch(() => null)])
      setPlantings(plot)
      if (brought) {
        setHarvest(brought)
        onFruitReady?.(brought.ready)
      }
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
    // The app hands down a state setter, which never changes identity, so this
    // stays the stable callback the effect below depends on.
  }, [onFruitReady])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    cache.set(userId, { plantings, harvest })
  }, [userId, plantings, harvest])

  const manna = harvest?.manna ?? 0
  const feedCost = harvest?.feed_cost ?? 0
  const feedCap = harvest?.feed_cap ?? 0
  const basket = harvest?.basket ?? []
  // The basket as one number. Batches are still what the server keeps; nothing
  // anybody presses is about one of them any more.
  const inBasket = basket.reduce((total, row) => total + row.count, 0)
  const pets = harvest?.pets ?? []
  // The one still growing, and the ones that have finished. A grove holds at
  // most one of the first and keeps every one of the second.
  const growing = pets.find((row) => !row.grown) ?? null
  const residents = pets.filter((row) => row.grown)
  // The clock as it stands while this is being drawn, read once so every animal
  // on the screen agrees about the hour. It is read again the next time
  // something happens here and never on a timer of its own.
  const now = new Date()
  const growingAsleep = growing !== null && asleepNow(growing.species, now)
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
    setStep({ at: 'gather' })
  }

  function gather() {
    void act(async () => {
      const brought = await gatherHarvest()
      setNote(gatheredLine(brought))
      // Read off what the gather itself answered, so the mark on the tab goes
      // out on this tap rather than when the reload behind it lands.
      onFruitReady?.(brought.ready)
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

  async function toFriends() {
    setNote('')
    setStepError('')
    setStep({ at: 'give' })
    if (friends.length > 0) return
    try {
      setFriends((await getFriends()).friends)
    } catch (err) {
      setStepError(errorText(err))
    }
  }

  function give(person: Person) {
    const sent = Math.trunc(Number(amount) || 0)
    void act(async () => {
      await giveFruit(person.user_id, sent)
      setNote(FRUIT_GIVEN)
      setStep({ at: 'none' })
    })
  }

  // A number of fruit, never a species: the server takes the oldest first. The
  // drawing it stood at before the feed is read here, since the answer carries
  // the one it stands at after and a crossing is the difference between them.
  function feedFruit(count: number) {
    const before = growing?.stage ?? 0
    void act(async () => {
      const { pet, golden } = await feedPet(count)
      const grew = pet.stage > before
      setPetNote(grew ? petGrewLine(pet.name, pet.species) : golden ? PET_FED_GOLDEN : PET_FED)
      setFedMark((mark) => ({
        tick: mark.tick + 1,
        how: `${golden ? 'pet-hop-golden' : 'pet-hop'}${grew ? ' pet-grew' : ''}`,
      }))
      setStep({ at: 'none' })
    })
  }

  function rename(pet: Pet) {
    void act(async () => {
      await namePet(pet.id, typedName)
      setPetNote(PET_NAMED)
      setStep({ at: 'none' })
    })
  }

  // A hand on the animal. Nothing leaves the browser: it hops, the card says
  // one sentence, and that is all a pat has ever been. It lands the same while
  // it is sleeping, where the hop plays over the sleeping drawing.
  function patGrowing() {
    setPetNote(PET_PATTED)
    setFedMark((mark) => ({ tick: mark.tick + 1, how: 'pet-hop' }))
  }

  // The same tap out on the floor, where there is no card to say anything. The
  // animal's own name surfaces under it for a moment instead.
  function patResident(pet: Pet) {
    setPatMark((mark) => ({ tick: mark.tick + 1, id: pet.id }))
  }

  // Both pet verbs open the same way: the card's own line cleared, and the box
  // primed with whatever it is called now.
  function openPetStep(next: Step & { pet: Pet }) {
    setPetNote('')
    setStepError('')
    setTypedName(next.pet.name ?? '')
    setStep(next)
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
          do here, and the plot is the thing to look at. Three colored areas,
          his pick: manna gold, season green, basket tan. */}
      {harvest && (
        <section className="card">
          <h2 className="label">Harvest</h2>
          <p className="hint">{harvestHint(harvest.season_mi)}</p>

          {note && (
            <p className="note note-success" role="status">
              {note}
            </p>
          )}

          <div className="grove-areas">
          <div className="grove-area grove-area-manna">
            <div className="grove-area-head">
              <span className="grove-area-label">Manna</span>
              <span className="grove-area-value">{manna.toLocaleString()}</span>
            </div>
          </div>

          <div className="grove-area grove-area-season">
            <div className="grove-area-head">
              <span className="grove-area-label">Season</span>
              <span className="grove-area-value">
                {convertedValue(harvest.season_progress_mi)} / {harvest.season_mi} XP
              </span>
            </div>
            {harvest.ready ? (
              <div className="choice">
                <button type="button" className="primary" disabled={busy} onClick={openGather}>
                  {FRUIT_MARK && (
                    <img
                      className="word-mark word-mark-small"
                      src={FRUIT_MARK}
                      alt=""
                      aria-hidden="true"
                    />
                  )}
                  Harvest
                </button>
              </div>
            ) : (
              <p className="hint">{NOTHING_BORNE}</p>
            )}
          </div>

          <div className="grove-area grove-area-basket">
            <div className="grove-area-head">
              <span className="grove-area-label">
                {BASKET_MARK && (
                  <img className="word-mark" src={BASKET_MARK} alt="" aria-hidden="true" />
                )}
                Harvest
              </span>
              {/* One number: fruit is fruit wherever anybody acts on it, and
                  which species leave the basket is the server's own rule. */}
              <span className="grove-area-value">{inBasket}</span>
            </div>
            {inBasket === 0 ? (
              <p className="hint">{EMPTY_BASKET}</p>
            ) : (
              <div className="choice">
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => void toFriends()}
                >
                  Give
                </button>
              </div>
            )}
          </div>
          </div>
        </section>
      )}

      {/* The one still growing, beside the harvest because that is where the
          fruit it is fed comes from. Nothing here is a mechanic and nothing
          here is explained: an animal, its name, and a quiet bar. The grown
          ones have moved out to the floor of the plot below, so the card goes
          altogether once there is neither an animal on it nor a word to say. */}
      {(growing !== null || petNote !== '') && (
        <section className="card">
          <h2 className="label">Pets</h2>

          {petNote && (
            <p className="note note-success" role="status">
              {petNote}
            </p>
          )}

          {growing && (
            <div className="pet">
              {/* The picture is the pat. A real button so a keyboard reaches it
                  and so it says whose animal it is out loud; everything a
                  button brings with it is undone in the stylesheet. */}
              <button
                type="button"
                className="pet-pat"
                aria-label={`Pat ${growing.display_name}`}
                onClick={patGrowing}
              >
                {/* Drawn fresh on the count and on the drawing it stands at, so
                    a feed moves the animal that was there and the drawing a
                    crossing swapped in arrives on its own. */}
                <PetArt
                  key={`${fedMark.tick}:${growing.stage}`}
                  species={growing.species}
                  name={growing.display_name}
                  stage={growing.stage}
                  sleeping={growingAsleep}
                  className={fedMark.how === '' ? 'pet-picture' : `pet-picture ${fedMark.how}`}
                />
              </button>
              <div className="pet-body">
                <p className="pet-name">{growing.display_name}</p>
                {/* A progress element rather than a div with a width on it: the
                    content security policy allows no inline styles. It shows
                    how far a pet has come and never how far it has to go. */}
                {growing.next_fruit !== null && (
                  <progress
                    className="xp-meter"
                    value={growing.fruit_fed}
                    max={growing.next_fruit}
                  >
                    Fed {growing.fruit_fed}
                  </progress>
                )}
                {/* A stray that has had nothing yet is following you, which is
                    the truer sentence whatever the hour says, so the arrival
                    line wins and the clock only speaks after the first fruit. */}
                {growing.fruit_fed === 0 ? (
                  <p className="pet-state">{petArrivedLine(growing.species)}</p>
                ) : (
                  growingAsleep && <p className="pet-state">{PET_ASLEEP}</p>
                )}
                <div className="pet-verbs">
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy || inBasket === 0}
                    onClick={() => openPetStep({ at: 'feedPet', pet: growing })}
                  >
                    Feed
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() => openPetStep({ at: 'namePet', pet: growing })}
                  >
                    Name
                  </button>
                </div>
              </div>
            </div>
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
              const name = plantingName(row)
              return (
                <li key={row.id} className="plant">
                  {/* The tab under the square is where the plant is named, so
                      there is no second line saying it again. */}
                  <RarityFrame rarity={row.rarity} label={name} className="plant-frame">
                    <PlantArt
                      species={row.species}
                      name={name}
                      stage={plantStage(row)}
                      gilded={row.gilded}
                      className="plant-picture"
                    />
                    {/* A plant holding fruit wears a mark in its corner, so the
                        one that bore is findable in a plot at a glance. What it
                        is holding is said in words below, and this never
                        repeats the number. */}
                    {carrying.length > 0 && FRUIT_MARK && (
                      <img
                        className="plant-fruit-mark"
                        src={FRUIT_MARK}
                        alt=""
                        aria-hidden="true"
                      />
                    )}
                  </RarityFrame>
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
                  {/* Gone at the cap rather than disabled: a full plant is a
                      finished state, not a wait. Short manna stays a wait. */}
                  {row.mature && fed < feedCap && (
                    <button
                      type="button"
                      className="secondary plant-feed"
                      disabled={busy || manna < feedCost}
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

        {/* The grown ones, standing on the floor of the plot they live in
            rather than listed on a card. No frame, no meter and no verb but a
            hand: they are here for good and there is nothing left to do to
            them. The name surfaces under whichever one was touched and goes
            again on its own. */}
        {residents.length > 0 && (
          <ul className="grove-pets-floor">
            {residents.map((row) => {
              const patted = patMark.id === row.id ? patMark.tick : 0
              return (
                <li key={row.id} className="grove-pet">
                  <button
                    type="button"
                    className="pet-pat"
                    aria-label={`Pat ${row.display_name}`}
                    onClick={() => patResident(row)}
                  >
                    {/* Drawn fresh on the count, the same way a feed moves the
                        one on the card above. */}
                    <PetArt
                      key={patted}
                      species={row.species}
                      name={row.display_name}
                      stage={row.stage}
                      sleeping={asleepNow(row.species, now)}
                      className={patted === 0 ? 'grove-pet-picture' : 'grove-pet-picture pet-hop'}
                    />
                    {/* Over the floor rather than in it, so a name arriving
                        moves nothing. The button already says whose animal this
                        is, so this is a picture of a name and not a second one. */}
                    {patted > 0 && (
                      <span key={patted} className="grove-pet-name" aria-hidden="true">
                        {row.display_name}
                      </span>
                    )}
                  </button>
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

      {/* Asked rather than done on the press, because harvesting starts the
          seven days on everything it brings in. */}
      {step.at === 'gather' && (
        <Confirm
          heading="Harvest"
          confirmLabel="Harvest"
          cancelLabel="Cancel"
          busy={busy}
          error={stepError}
          onConfirm={gather}
          onCancel={() => setStep({ at: 'none' })}
        >
          <p className="hint">{GATHER_HINT}</p>
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
          <p className="hint">{feedHint(feedCost, feedCap)}</p>
        </Confirm>
      )}

      {/* Two plain choices and no species anywhere: one fruit, or the lot. */}
      {step.at === 'feedPet' && (
        <Chooser
          title={`Feed ${step.pet.display_name}`}
          hint={PET_FEED_HINT}
          choices={
            inBasket > 1
              ? [
                  { id: 1, label: 'Feed 1' },
                  { id: inBasket, label: `Feed all ${inBasket}` },
                ]
              : [{ id: 1, label: 'Feed 1' }]
          }
          empty={EMPTY_BASKET}
          busy={busy}
          error={stepError}
          onChoose={(count) => feedFruit(count)}
          onCancel={() => setStep({ at: 'none' })}
        />
      )}

      {step.at === 'namePet' && (
        <Confirm
          heading={`Name your ${step.pet.species}`}
          confirmLabel="Save"
          cancelLabel="Cancel"
          busy={busy}
          error={stepError}
          onConfirm={() => rename(step.pet)}
          onCancel={() => setStep({ at: 'none' })}
        >
          <label>
            Name
            <input
              type="text"
              value={typedName}
              maxLength={NAME_LIMIT}
              disabled={busy}
              onChange={(event) => setTypedName(event.target.value)}
            />
          </label>
        </Confirm>
      )}

      {step.at === 'give' && (
        <Chooser
          title="Give fruit"
          hint={GIVE_FRUIT_HINT}
          choices={friendChoices}
          empty="No friends yet. Invite someone from the You screen."
          busy={busy}
          error={stepError}
          searchPlaceholder="Search friends"
          onChoose={(id) => {
            const person = friends.find((one) => one.user_id === id)
            if (!person) return
            setAmount('')
            setStepError('')
            setStep({ at: 'giveAmount', person })
          }}
          onCancel={() => setStep({ at: 'none' })}
        />
      )}

      {/* How many, in the box the manna gift already uses. The oldest fruit
          goes first, so nobody is asked which. */}
      {step.at === 'giveAmount' && (
        <Confirm
          heading={`Give fruit to ${personName(step.person)}`}
          confirmLabel="Give"
          cancelLabel="Cancel"
          busy={busy}
          error={stepError}
          onConfirm={() => give(step.person)}
          onCancel={() => setStep({ at: 'none' })}
        >
          <label>
            Fruit to give
            <input
              type="number"
              min={1}
              max={inBasket}
              step={1}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
          <p className="hint">{basketLine(inBasket)}</p>
        </Confirm>
      )}
    </>
  )
}
