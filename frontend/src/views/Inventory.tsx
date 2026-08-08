import { useCallback, useEffect, useRef, useState } from 'react'
import {
  anointFriend,
  chooseSeed,
  errorText,
  getFriends,
  getSpecies,
  listChests,
  listFriendGrove,
  listGrove,
  listSatchel,
  openChest,
  plantSeed,
  pourWater,
  type Chest,
  type FriendPlanting,
  type ItemKind,
  type Person,
  type Planting,
  type SatchelItem,
  type SpeciesRow,
} from '../api.ts'
import { itemArt } from '../art.ts'
import { convertedValue } from '../format.ts'
import { levelProgress } from '../grove.ts'
import {
  chestName,
  itemFramed,
  itemName,
  itemRarity,
  personName,
  plantingName,
  rarityWord,
} from '../labels.ts'
import ChestItem from './ChestItem.tsx'
import Chooser, { type Choice } from './Chooser.tsx'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// A chest is not a satchel item and never sits in one, but it is held and
// unspent, which is the whole of what a square in here means.
type StackKind = ItemKind | 'chest'

// One square of the grid. Everything of a kind piles onto one square with a
// count on it, so nine seeds are nine squares rather than nine rows.
interface Stack {
  key: string
  kind: StackKind
  name: string
  // What is behind the square, oldest first. A chest stack carries chests and
  // nothing else; every other stack carries satchel items.
  items: SatchelItem[]
  chests: Chest[]
}

// The order the squares are laid out in, which is the order things are used:
// sown, poured, given, the one that is spent to be given a seed at all, and the
// unopened chests they all came out of.
const KIND_ORDER: Record<StackKind, number> = { seed: 0, water: 1, oil: 2, wish: 3, chest: 4 }

// One verb each, said as the thing you are about to do. Nothing in here is kept
// to be looked at, so there is no verb for looking.
const VERBS: Record<StackKind, { id: string; label: string }[]> = {
  seed: [{ id: 'plant', label: 'Plant Seed' }],
  water: [
    { id: 'water-own', label: 'Water Plant' },
    { id: 'water-friend', label: "Water Friend's Plant" },
  ],
  oil: [{ id: 'anoint', label: 'Anoint' }],
  wish: [{ id: 'choose', label: 'Choose Seed' }],
  chest: [{ id: 'open', label: 'Open Chest' }],
}

// What each square is for, said once, where the verb is.
const KIND_LINES: Record<StackKind, string> = {
  seed: 'Plant it and it grows with your miles.',
  water: 'Ten miles of growth, into one plant.',
  oil: 'Given to a friend. Their next workout brings them a bonus chest.',
  wish: 'Spent on any seed you have not yet found. One use.',
  chest: 'Opened one at a time, oldest first.',
}

// A grid is sixteen squares whether or not there is anything to put in them: an
// empty socket says there is room, which is half of what an inventory is for.
const SLOTS = 16
const COLUMNS = 4

// The one row a wish offers when there is no seed left to ask for. Its id is the
// empty species, which is what the server reads as "there was nothing to
// choose", and what it answers with water for.
const NO_SPECIES = ''
const COMPLETE = 'Your grove is complete. The seed became water.'

// Said after oil is given. The chest is a gift of its own, dropped when their
// miles next land, and the letter is where it says who it came from.
const ANOINTED = 'Done. Their next workout brings them a bonus chest.'

// A friend's plot comes back with a stage rather than miles, so the quiet half
// of the row says how far along it is in words.
const STAGE_WORDS = ['Seedling', 'Growing', 'Grown']

// Whether a plant can still take water: everything but the ones that have run
// out of levels to put on.
function friendGrowing(row: FriendPlanting): boolean {
  return row.gilded !== true
}

// How far along one planting is, for the row that offers it a drink.
function growthLine(row: Planting): string {
  return `Level ${row.level}, ${convertedValue(levelProgress(row).into)} of ${convertedValue(
    row.level_mi,
  )} mi`
}

// Everything held, gathered into squares. Seeds are piled by species and every
// tool by its kind; the chests come last as one pile, since what is inside them
// is the same question whichever step of the ladder dropped them.
function stacksOf(
  items: SatchelItem[],
  chests: Chest[],
  catalog: SpeciesRow[] | null,
  wishName: string,
): Stack[] {
  const stacks = new Map<string, Stack>()
  for (const item of items) {
    const key = item.kind === 'seed' ? `seed:${item.species ?? ''}` : item.kind
    const held = stacks.get(key)
    if (held) {
      held.items.push(item)
      continue
    }
    stacks.set(key, {
      key,
      kind: item.kind,
      name: item.kind === 'wish' && wishName !== '' ? wishName : itemName(item),
      items: [item],
      chests: [],
    })
  }

  if (chests.length > 0) {
    // Named for the step that dropped them while they all came off the same
    // one, and called what they are once the pile is mixed.
    const tier = chests[0].tier
    const same = chests.every((chest) => chest.tier === tier)
    stacks.set('chest', {
      key: 'chest',
      kind: 'chest',
      name: same ? chestName(tier) : 'Chests',
      items: [],
      chests,
    })
  }

  // Seeds read in catalogue order where the server has said what that is, and
  // by name where it has not, so the grid does not reshuffle as things arrive.
  const rank = new Map((catalog ?? []).map((row, index) => [row.id, index]))
  return [...stacks.values()].sort((a, b) => {
    if (a.kind !== b.kind) return KIND_ORDER[a.kind] - KIND_ORDER[b.kind]
    const left = rank.get(a.items[0]?.species ?? '') ?? Number.MAX_SAFE_INTEGER
    const right = rank.get(b.items[0]?.species ?? '') ?? Number.MAX_SAFE_INTEGER
    return left === right ? a.name.localeCompare(b.name) : left - right
  })
}

// One square. The picture is the thing itself, framed in its rarity where it has
// one, and the count sits in the corner of the picture the way it does in every
// inventory anyone has ever seen. A single of anything carries no number: the
// square is the one.
function Square({ stack, onOpen }: { stack: Stack; onOpen: () => void }) {
  const count = stack.items.length + stack.chests.length
  const first = stack.items[0]
  const art = stack.kind === 'seed' ? null : itemArt(stack.kind)
  const framed = first !== undefined && (itemFramed(first) || first.species !== null)

  const picture = (
    <span className="inv-art">
      {stack.kind === 'seed' && first?.species ? (
        <PlantArt species={first.species} name={stack.name} stage={1} className="inv-thumb" />
      ) : art ? (
        <img className="item-art" src={art} alt="" />
      ) : (
        <span className="plant-blank" aria-hidden="true" />
      )}
      {count > 1 && <span className="inv-count">x{count}</span>}
    </span>
  )

  return (
    <li className="inv-slot">
      <button
        type="button"
        className="inv-cell"
        aria-label={`${stack.name}, ${count}`}
        onClick={onOpen}
      >
        {framed && first ? (
          <RarityFrame rarity={itemRarity(first)} className="inv-frame">
            {picture}
          </RarityFrame>
        ) : (
          <span className="item-square inv-plain">{picture}</span>
        )}
      </button>
    </li>
  )
}

// Where the tap on a square has got to. The verbs come first, and two of them
// lead somewhere: water to a plant, oil to a person, and water on a friend's
// plot to a person and then to their plants.
type Step =
  | { at: 'verbs' }
  | { at: 'plants' }
  | { at: 'people'; then: 'water' | 'anoint' }
  | { at: 'friend'; person: Person; plot: FriendPlanting[] }
  | { at: 'species' }

interface Props {
  onClose: () => void
  // Something in here changed what the screen behind it is showing.
  onChanged: () => void
}

// Everything held and not yet used, as a grid of squares. It is the satchel it
// replaces, read the way a game reads one: the pile, the count, and the one
// thing there is to do with it.
export default function Inventory({ onClose, onChanged }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)

  const [items, setItems] = useState<SatchelItem[]>([])
  const [chests, setChests] = useState<Chest[]>([])
  const [plantings, setPlantings] = useState<Planting[]>([])
  const [catalog, setCatalog] = useState<SpeciesRow[] | null>(null)
  const [wishName, setWishName] = useState('')
  const [catalogError, setCatalogError] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  // Which square was tapped, what it is called, and how far into it the tapping
  // has got.
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [openName, setOpenName] = useState('')
  const [step, setStep] = useState<Step>({ at: 'verbs' })
  const [busy, setBusy] = useState(false)
  const [stepError, setStepError] = useState('')
  const [note, setNote] = useState('')
  // What came out of the chests opened without leaving this square.
  const [revealed, setRevealed] = useState<SatchelItem[]>([])

  const [friends, setFriends] = useState<Person[]>([])

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  const load = useCallback(async () => {
    try {
      const [satchel, waiting, plot] = await Promise.all([
        listSatchel(),
        listChests(),
        listGrove(),
      ])
      setItems(satchel)
      setChests(waiting)
      setPlantings(plot)
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

  // The catalogue is the server's, asked for once. It is what a wish is spent
  // against, so a catalogue that never arrives costs the wish chooser rather
  // than being guessed at from a copy kept here.
  useEffect(() => {
    getSpecies()
      .then((answer) => {
        setCatalog(answer.species)
        setWishName(answer.wish_name)
      })
      .catch((err) => setCatalogError(errorText(err)))
  }, [])

  const stacks = stacksOf(items, chests, catalog, wishName)
  const active = openKey === null ? null : (stacks.find((one) => one.key === openKey) ?? null)

  function shut() {
    setOpenKey(null)
    setStep({ at: 'verbs' })
    setStepError('')
    setRevealed([])
  }

  function tap(stack: Stack) {
    setOpenKey(stack.key)
    // The name is kept rather than read off the pile, because the last chest
    // can be opened and what came out of it still has to be read under the
    // heading it was opened from.
    setOpenName(stack.name)
    setStep({ at: 'verbs' })
    setStepError('')
    setRevealed([])
    setNote('')
  }

  // Every act ends the same way: the server is asked again for everything, and
  // the screen behind this one is told that what it draws has moved.
  async function act(work: () => Promise<void>) {
    setBusy(true)
    setStepError('')
    try {
      await work()
      await load()
      onChanged()
    } catch (err) {
      setStepError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function plant() {
    const item = active?.items[0]
    if (!item) return
    void act(async () => {
      await plantSeed(item.id)
      setNote('Planted. It is in your grove.')
      shut()
    })
  }

  function pour(plantingId: number) {
    const item = active?.items[0]
    if (!item) return
    void act(async () => {
      await pourWater(item.id, plantingId)
      setNote('Poured. Ten miles of growth.')
      shut()
    })
  }

  function anoint(userId: number) {
    const item = active?.items[0]
    if (!item) return
    void act(async () => {
      await anointFriend(item.id, userId)
      setNote(ANOINTED)
      shut()
    })
  }

  // A wish is spent on a species rather than on a row, and what comes back is
  // the seed itself, which takes the wish's place on the grid.
  function spendWish(species: string) {
    const item = active?.items[0]
    if (!item) return
    void act(async () => {
      const made = await chooseSeed(item.id, species)
      setNote(species === NO_SPECIES ? COMPLETE : `It became a ${itemName(made)}.`)
      shut()
    })
  }

  // The one act that stays where it happened: what was inside is the whole
  // point, so it is read under the verb that opened it rather than behind it.
  function openOne() {
    const chest = active?.chests[0]
    if (!chest) return
    void act(async () => {
      const found = await openChest(chest.id)
      setRevealed((seen) => [...seen, found])
    })
  }

  // Both people pickers ask who this account's friends are, and water asks a
  // second time for whichever plot it is being poured onto.
  async function toPeople(then: 'water' | 'anoint') {
    setStepError('')
    setStep({ at: 'people', then })
    if (friends.length > 0) return
    try {
      setFriends((await getFriends()).friends)
    } catch (err) {
      setStepError(errorText(err))
    }
  }

  async function toFriendPlot(person: Person) {
    setBusy(true)
    setStepError('')
    try {
      setStep({ at: 'friend', person, plot: await listFriendGrove(person.user_id) })
    } catch (err) {
      setStepError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function runVerb(id: string) {
    if (id === 'plant') plant()
    else if (id === 'water-own') setStep({ at: 'plants' })
    else if (id === 'water-friend') void toPeople('water')
    else if (id === 'anoint') void toPeople('anoint')
    else if (id === 'choose') setStep({ at: 'species' })
    else if (id === 'open') openOne()
  }

  // Nothing fully grown is offered a drink: it has all the growth there is.
  const ownChoices: Choice[] = plantings
    .filter((row) => !row.gilded)
    .map((row) => ({ id: row.id, label: plantingName(row), detail: growthLine(row) }))

  const friendChoices: Choice[] = friends.map((person) => ({
    id: person.user_id,
    label: personName(person),
  }))

  const friendPlot: Choice[] =
    step.at === 'friend'
      ? step.plot.filter(friendGrowing).map((row) => ({
          id: row.id,
          label: plantingName(row),
          detail: STAGE_WORDS[(row.stage ?? 1) - 1] ?? 'Growing',
        }))
      : []

  // What a wish can be spent on: every species that is neither growing in the
  // plot nor already held as a seed. A grove holding all of them has one thing
  // left to be given, which is water.
  const owned = new Set<string>([
    ...plantings.map((row) => row.species),
    ...items.flatMap((one) => (one.kind === 'seed' && one.species ? [one.species] : [])),
  ])
  const lacking = (catalog ?? []).filter((row) => !owned.has(row.id))
  const seedChoices: Choice<string>[] =
    catalog === null
      ? []
      : lacking.length > 0
        ? lacking.map((row) => ({
            id: row.id,
            label: row.seed_name,
            detail: rarityWord(row.rarity),
          }))
        : [{ id: NO_SPECIES, label: 'Water', detail: 'The wish becomes water.' }]

  const slots = Math.max(SLOTS, Math.ceil(stacks.length / COLUMNS) * COLUMNS)
  const empties = Array.from({ length: Math.max(0, slots - stacks.length) }, (_, index) => index)

  return (
    <>
      <dialog
        className="overlay"
        ref={dialog}
        aria-labelledby="inventory-title"
        onCancel={(event) => {
          // Esc. Closing is the caller's business, so the browser's own close is
          // left undone and the caller takes this off the screen.
          event.preventDefault()
          onClose()
        }}
      >
        <section className="overlay-panel">
          <header className="overlay-head">
            <h2 id="inventory-title">Inventory</h2>
            <p className="hint">Everything found and not yet used. Tap a square to use it.</p>
          </header>

          <div className="inv-body">
            {loading && <p className="notice">Loading.</p>}
            {loadError && (
              <p className="error" role="alert">
                {loadError}
              </p>
            )}
            {note && (
              <p className="note note-success" role="status">
                {note}
              </p>
            )}

            <ul className="inv-grid">
              {stacks.map((stack) => (
                <Square key={stack.key} stack={stack} onOpen={() => tap(stack)} />
              ))}
              {empties.map((index) => (
                <li key={`empty-${index}`} className="inv-slot">
                  <span className="inv-cell inv-empty" />
                </li>
              ))}
            </ul>
          </div>

          <footer className="overlay-foot">
            <button type="button" className="secondary" onClick={onClose}>
              Close
            </button>
          </footer>
        </section>
      </dialog>

      {/* The verbs, and whatever came out of a chest opened from them. Drawn
          outside the grid's own dialog so the two stack in the order they were
          opened rather than one inside the other. */}
      {openKey !== null && step.at === 'verbs' && (
        <Chooser
          title={openName}
          hint={active ? KIND_LINES[active.kind] : ''}
          choices={active ? VERBS[active.kind] : []}
          empty="Nothing left."
          busy={busy}
          error={stepError}
          cancelLabel={revealed.length > 0 ? 'Close' : 'Cancel'}
          onChoose={runVerb}
          onCancel={shut}
        >
          {revealed.length > 0 && (
            <div className="item-reveals inv-reveals">
              {revealed.map((item) => (
                <ChestItem
                  key={item.id}
                  item={item}
                  onPlanted={() => {
                    void load()
                    onChanged()
                  }}
                />
              ))}
            </div>
          )}
        </Chooser>
      )}

      {step.at === 'plants' && (
        <Chooser
          title="Water Plant"
          hint="Ten miles of growth, into one of yours."
          choices={ownChoices}
          empty="Nothing of yours is growing yet."
          busy={busy}
          error={stepError}
          onChoose={(id) => pour(id)}
          onCancel={() => setStep({ at: 'verbs' })}
        />
      )}

      {step.at === 'people' && (
        <Chooser
          title={step.then === 'water' ? "Water Friend's Plant" : 'Anoint'}
          hint={
            step.then === 'water'
              ? 'Whose plot it goes onto.'
              : 'Their next workout brings them a bonus chest.'
          }
          choices={friendChoices}
          empty="No friends yet. Invite someone from the You screen."
          busy={busy}
          error={stepError}
          searchPlaceholder="Search friends"
          onChoose={(id) => {
            const person = friends.find((one) => one.user_id === id)
            if (!person) return
            if (step.then === 'anoint') anoint(id)
            else void toFriendPlot(person)
          }}
          onCancel={() => setStep({ at: 'verbs' })}
        />
      )}

      {step.at === 'friend' && (
        <Chooser
          title={personName(step.person)}
          hint="Which of their plants it goes onto."
          choices={friendPlot}
          empty="Nothing of theirs is growing yet."
          busy={busy}
          error={stepError}
          onChoose={(id) => pour(id)}
          onCancel={() => setStep({ at: 'people', then: 'water' })}
        />
      )}

      {/* The same list the other pickers use, spent on a species instead of a
          row. A grove with every seed in it has one thing left to be given, so
          the list says so plainly rather than being empty. */}
      {step.at === 'species' && (
        <Chooser
          title={wishName === '' ? 'Unmarked seed' : wishName}
          hint={
            catalog === null
              ? 'The catalogue of seeds could not be read.'
              : lacking.length > 0
                ? 'Choose what it will become: any seed you have not yet found. One use.'
                : 'Your grove is complete. There is no seed left to ask for.'
          }
          choices={seedChoices}
          empty={catalogError || 'Nothing to choose.'}
          busy={busy}
          error={stepError}
          onChoose={(species) => spendWish(species)}
          onCancel={() => setStep({ at: 'verbs' })}
        />
      )}
    </>
  )
}
