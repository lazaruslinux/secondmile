import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
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
  ANOINT_HINT,
  ANOINTED,
  CHEST_TIER_ORDER,
  chestName,
  chestTierRarity,
  chestTierWord,
  ITEM_LINES,
  itemName,
  itemRarity,
  itemTabLabel,
  NOTHING_HELD,
  OIL_KEPT,
  personName,
  PLANTED,
  plantingName,
  plantStateLine,
  POURED,
  rarityWord,
} from '../labels.ts'
import { pileItems, type Stack, type StackKind } from '../satchel.ts'
import ChestItem from './ChestItem.tsx'
import Chooser, { type Choice } from './Chooser.tsx'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// The order the squares are laid out in, which is the order things are used:
// sown, poured, given, and the one that is spent to be given a seed at all. The
// chests come after all of them, in the ladder's own order.
const KIND_ORDER: Record<ItemKind, number> = { seed: 0, water: 1, oil: 2, wish: 3 }

// One verb each, said as the thing you are about to do. Nothing in here is kept
// to be looked at, so there is no verb for looking.
const VERBS: Record<StackKind, { id: string; label: string }[]> = {
  seed: [{ id: 'plant', label: 'Plant seed' }],
  water: [
    { id: 'water-own', label: 'Water plant' },
    { id: 'water-friend', label: "Water a friend's plant" },
  ],
  oil: [{ id: 'anoint', label: 'Anoint' }],
  wish: [{ id: 'choose', label: 'Choose seed' }],
  chest: [{ id: 'open', label: 'Open chest' }],
}

// Four across at every width, growing downward as things are found. A full case
// is twelve species, three tools and the five steps of the ladder, so nothing
// here counts the squares: the grid is however many there are.
const COLUMNS = 4

// Empty sockets under whatever is held, because a socket says there is room,
// which is half of what an inventory is for. Two rows of them is enough to read
// as one when almost nothing is in it.
const LEAST_ROWS = 2

// The one row a wish offers when there is no seed left to ask for. Its id is the
// empty species, which is what the server reads as "there was nothing to
// choose", and what it answers with water for.
const NO_SPECIES = ''
const COMPLETE = 'You have every seed, so it became water.'

// Whether a plant can still take water: everything but the ones that have run
// out of levels to put on.
function friendGrowing(row: FriendPlanting): boolean {
  return row.gilded !== true
}

// How far along one planting is, for the row that offers it a drink.
function growthLine(row: Planting): string {
  return `Level ${row.level}, ${convertedValue(levelProgress(row).into)} of ${convertedValue(
    row.level_mi,
  )} XP`
}

// What one square is, said in the modal it opens. A chest is described by its
// floor, which is what its colour stands for: the worst it can come up as.
function describe(stack: Stack): string {
  if (stack.kind !== 'chest') return ITEM_LINES[stack.kind]
  const floor = rarityWord(chestTierRarity(stack.tier)).toLowerCase()
  return `At least ${floor}. Open one at a time.`
}

// Everything held, gathered into squares. Seeds are piled by species and every
// tool by its kind; the chests are piled by the step of the ladder that dropped
// them, one square per step, because a Marathon chest and a 5K are not the same
// thing to hold.
function stacksOf(
  items: SatchelItem[],
  chests: Chest[],
  catalog: SpeciesRow[] | null,
  wishName: string,
): Stack[] {
  // Seeds read in catalogue order where the server has said what that is, and
  // by name where it has not, so the grid does not reshuffle as things arrive.
  const rank = new Map((catalog ?? []).map((row, index) => [row.id, index]))
  const held = pileItems(items, wishName).sort((a, b) => {
    if (a.kind !== b.kind) {
      return KIND_ORDER[a.kind as ItemKind] - KIND_ORDER[b.kind as ItemKind]
    }
    const left = rank.get(a.items[0]?.species ?? '') ?? Number.MAX_SAFE_INTEGER
    const right = rank.get(b.items[0]?.species ?? '') ?? Number.MAX_SAFE_INTEGER
    return left === right ? a.name.localeCompare(b.name) : left - right
  })

  // A chest dropped before the ladder existed carries no step and rolls as the
  // first one, so it is piled with the first one.
  const waiting = new Map<string, Chest[]>()
  for (const chest of chests) {
    const tier = (chest.tier ?? '').toLowerCase() || CHEST_TIER_ORDER[0]
    const pile = waiting.get(tier)
    if (pile) pile.push(chest)
    else waiting.set(tier, [chest])
  }
  // The ladder's own order, and then anything the server named that this build
  // has never heard of, so a step added on the server costs its place in the
  // line rather than its square.
  const known = new Set(CHEST_TIER_ORDER)
  const ladder = [...CHEST_TIER_ORDER, ...[...waiting.keys()].filter((one) => !known.has(one))]

  return [
    ...held,
    ...ladder.flatMap((tier) => {
      const pile = waiting.get(tier)
      if (!pile) return []
      return [
        {
          key: `chest:${tier}`,
          kind: 'chest' as const,
          tier,
          name: chestName(tier),
          items: [],
          chests: pile,
        },
      ]
    }),
  ]
}

// The picture on a square: the thing itself, and the count in the corner the way
// every inventory anyone has ever seen puts it. A single of anything carries no
// number, because the square is the one.
function StackArt({ stack }: { stack: Stack }) {
  const count = stack.items.length + stack.chests.length
  const first = stack.items[0]
  const art = stack.kind === 'seed' ? null : itemArt(stack.kind)

  return (
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
}

// The picture in its frame. Everything held is framed, so every square in a row
// is the same height as the one beside it. Drawn the same in the grid and in the
// modal, which is why the sizing class is handed in.
export function StackSquare({ stack, frameClass }: { stack: Stack; frameClass: string }) {
  // A chest is coloured by the floor of its step and named for the step itself,
  // neither of which the thing inside it can say yet.
  if (stack.kind === 'chest') {
    return (
      <RarityFrame
        rarity={chestTierRarity(stack.tier)}
        label={chestTierWord(stack.tier)}
        className={frameClass}
      >
        <StackArt stack={stack} />
      </RarityFrame>
    )
  }

  const first = stack.items[0]

  return (
    <RarityFrame
      rarity={first === undefined ? '' : itemRarity(first)}
      label={first === undefined ? undefined : itemTabLabel(first)}
      className={frameClass}
    >
      <StackArt stack={stack} />
    </RarityFrame>
  )
}

// One square of the grid, which is a button and nothing else: the whole picture
// is the target.
export function Square({ stack, onOpen }: { stack: Stack; onOpen: () => void }) {
  const count = stack.items.length + stack.chests.length

  return (
    <li className="inv-slot">
      <button
        type="button"
        className="inv-cell"
        aria-label={`${stack.name}, ${count}`}
        onClick={onOpen}
      >
        <StackSquare stack={stack} frameClass="inv-frame" />
      </button>
    </li>
  )
}

// What a tapped square opens: the picture still on screen, what the thing is,
// and its verbs as the app's own buttons. The first verb is the one anybody came
// for, so it is the primary; water's second way to spend it stands beside it.
export function ItemDialog({
  stack,
  line,
  verbs,
  busy,
  error,
  cancelLabel,
  children,
  onRun,
  onClose,
}: {
  stack: Stack
  // What is said beside the picture. Left out here, where it is what the thing
  // is for; handed in where the same panel asks a question about spending it,
  // because there the sentence names what it is being spent on.
  line?: string
  // Empty once the last of a stack has been spent, which leaves the picture and
  // whatever came out of it with nothing left to do.
  verbs: { id: string; label: string }[]
  busy: boolean
  error: string
  cancelLabel: string
  children?: ReactNode
  onRun: (id: string) => void
  onClose: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  // Opened as a modal rather than with the open attribute, because only the
  // modal form brings the focus trap, the page behind held still, and Esc.
  useEffect(() => {
    dialog.current?.showModal()
  }, [])

  return (
    <dialog
      className="overlay overlay-middle"
      ref={dialog}
      aria-labelledby="item-title"
      onCancel={(event) => {
        // Esc. Closing is the caller's business, so the browser's own close is
        // left undone and the caller takes this off the screen.
        event.preventDefault()
        onClose()
      }}
    >
      <section className="overlay-panel">
        <header className="overlay-head">
          <h2 id="item-title">{stack.name}</h2>
        </header>

        <div className="item-detail">
          <div className="item-shown">
            <StackSquare stack={stack} frameClass="item-frame" />
            <p className="hint item-line">{line ?? describe(stack)}</p>
          </div>

          {children}

          {verbs.length > 0 ? (
            <div className="item-verbs">
              {verbs.map((verb, index) => (
                <button
                  key={verb.id}
                  type="button"
                  className={index === 0 ? 'primary' : 'secondary'}
                  disabled={busy}
                  onClick={() => onRun(verb.id)}
                >
                  {verb.label}
                </button>
              ))}
            </div>
          ) : (
            <p className="hint">Nothing left.</p>
          )}

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>

        <footer className="overlay-foot">
          <button type="button" className="secondary" onClick={onClose}>
            {cancelLabel}
          </button>
        </footer>
      </section>
    </dialog>
  )
}

// Where the tap on a square has got to. The verbs come first, and two of them
// lead somewhere: water to a plant, a potion to a person, and water on a friend's
// plot to a person and then to their plants.
type Step =
  | { at: 'verbs' }
  | { at: 'plants' }
  | { at: 'people'; then: 'water' | 'anoint' }
  | { at: 'friend'; person: Person; plot: FriendPlanting[] }
  | { at: 'species' }
  // The last thing before an item is gone. Water and potions cannot be got back
  // and cannot be undone, so every path that spends one asks the same question
  // in the same words, whether it started here or on a friend's own page. The
  // deed rides in the step rather than a callback, so the step stays a value
  // that can be read, compared and gone back from.
  | {
      at: 'confirm'
      line: string
      deed: { verb: 'pour'; plantingId: number } | { verb: 'anoint'; userId: number }
      back: Step
    }

interface Props {
  // Something in here changed what the screen around it is showing.
  onChanged: () => void
}

// Everything held and not yet used, as a grid of squares. It is the satchel it
// replaces, read the way a game reads one: the pile, the count, and the one
// thing there is to do with it. It sits on the page rather than behind a
// button, because an inventory nobody can see is a list.
export default function Inventory({ onChanged }: Props) {
  const [items, setItems] = useState<SatchelItem[]>([])
  const [chests, setChests] = useState<Chest[]>([])
  const [plantings, setPlantings] = useState<Planting[]>([])
  const [catalog, setCatalog] = useState<SpeciesRow[] | null>(null)
  const [wishName, setWishName] = useState('')
  const [catalogError, setCatalogError] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  // Which square was tapped, kept whole rather than by key: the last of a stack
  // can be spent and its picture still has to be there to read what came out of
  // it under. What is live is looked up beside it.
  const [tapped, setTapped] = useState<Stack | null>(null)
  const [step, setStep] = useState<Step>({ at: 'verbs' })
  const [busy, setBusy] = useState(false)
  const [stepError, setStepError] = useState('')
  const [note, setNote] = useState('')
  // What came out of the chests opened without leaving this square.
  const [revealed, setRevealed] = useState<SatchelItem[]>([])

  const [friends, setFriends] = useState<Person[]>([])

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
  // What is still there of the square that was tapped, which is nothing once the
  // last of it has been spent.
  const live = tapped === null ? null : (stacks.find((one) => one.key === tapped.key) ?? null)
  const shown = live ?? tapped

  function shut() {
    setTapped(null)
    setStep({ at: 'verbs' })
    setStepError('')
    setRevealed([])
  }

  function tap(stack: Stack) {
    setTapped(stack)
    setStep({ at: 'verbs' })
    setStepError('')
    setRevealed([])
    setNote('')
  }

  // Every act ends the same way: the server is asked again for everything, and
  // the screen around this one is told that what it draws has moved. A refusal
  // is the server's own sentence, with whatever the act wants added to it.
  async function act(work: () => Promise<void>, refused = '') {
    setBusy(true)
    setStepError('')
    try {
      await work()
      await load()
      onChanged()
    } catch (err) {
      const said = errorText(err)
      setStepError(refused === '' ? said : `${said} ${refused}`)
    } finally {
      setBusy(false)
    }
  }

  function plant() {
    const item = live?.items[0]
    if (!item) return
    void act(async () => {
      await plantSeed(item.id)
      setNote(PLANTED)
      shut()
    })
  }

  function pour(plantingId: number) {
    const item = live?.items[0]
    if (!item) return
    void act(async () => {
      await pourWater(item.id, plantingId)
      setNote(POURED)
      shut()
    })
  }

  // Between choosing what it goes on and it being gone. Every path here that
  // spends an item goes through this, so the inventory asks the same question
  // a friend's own page does rather than pouring the moment a name is tapped.
  function askFirst(line: string, deed: Extract<Step, { at: 'confirm' }>['deed']) {
    setStepError('')
    setStep((from) => ({ at: 'confirm', line, deed, back: from }))
  }

  function doDeed(deed: Extract<Step, { at: 'confirm' }>['deed']) {
    if (deed.verb === 'pour') pour(deed.plantingId)
    else anoint(deed.userId)
  }

  // A potion can be turned down: nobody holds more than three gifts at once,
  // and the answer to that is the server's sentence with the potion's own fate
  // added, said where the person was picked rather than anywhere they would
  // have to go looking for it.
  function anoint(userId: number) {
    const item = live?.items[0]
    if (!item) return
    void act(async () => {
      await anointFriend(item.id, userId)
      setNote(ANOINTED)
      shut()
    }, OIL_KEPT)
  }

  // A wish is spent on a species rather than on a row, and what comes back is
  // the seed itself, which takes the wish's place on the grid.
  function spendWish(species: string) {
    const item = live?.items[0]
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
    const chest = live?.chests[0]
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
          // The same line their plot says under the same plant: a friend's
          // row carries its stage rather than the miles behind it.
          detail: plantStateLine(row, row.stage ?? 1),
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

  const rows = Math.max(LEAST_ROWS, Math.ceil(stacks.length / COLUMNS))
  const empties = Array.from(
    { length: Math.max(0, rows * COLUMNS - stacks.length) },
    (_, index) => index,
  )

  // Nothing held at all is an empty state rather than a grid: rows of hollow
  // squares under an instruction to tap them say there is something to do here
  // when there is not. The line is the same one the empty plot beside it says.
  const bare = stacks.length === 0

  return (
    <>
      {/* Held back until the first load has answered, so an inventory that has
          things in it never says for a moment that it has none. */}
      {!loading && <p className="hint">{bare ? NOTHING_HELD : 'Tap a square to use it.'}</p>}

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

      {!bare && (
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
      )}

      {/* The item itself, and whatever came out of a chest opened from it. */}
      {shown !== null && step.at === 'verbs' && (
        <ItemDialog
          stack={shown}
          verbs={live ? VERBS[live.kind] : []}
          busy={busy}
          error={stepError}
          cancelLabel={revealed.length > 0 ? 'Close' : 'Cancel'}
          onRun={runVerb}
          onClose={shut}
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
        </ItemDialog>
      )}

      {step.at === 'plants' && (
        <Chooser
          title="Water plant"
          hint="Pick a plant. It gets 10 XP of growth."
          choices={ownChoices}
          empty="Nothing of yours is growing yet."
          busy={busy}
          error={stepError}
          onChoose={(id) =>
            askFirst(
              `Use 1 water on your ${ownChoices.find((one) => one.id === id)?.label ?? 'plant'}?`,
              { verb: 'pour', plantingId: id },
            )
          }
          onCancel={() => setStep({ at: 'verbs' })}
        />
      )}

      {step.at === 'people' && (
        <Chooser
          title={step.then === 'water' ? "Water a friend's plant" : 'Anoint'}
          hint={step.then === 'water' ? 'Pick a friend.' : ANOINT_HINT}
          choices={friendChoices}
          empty="No friends yet. Invite someone from the You screen."
          busy={busy}
          error={stepError}
          searchPlaceholder="Search friends"
          onChoose={(id) => {
            const person = friends.find((one) => one.user_id === id)
            if (!person) return
            if (step.then === 'anoint') {
              askFirst(`Use 1 potion on ${personName(person)}?`, { verb: 'anoint', userId: id })
            } else void toFriendPlot(person)
          }}
          onCancel={() => setStep({ at: 'verbs' })}
        />
      )}

      {step.at === 'friend' && (
        <Chooser
          title={personName(step.person)}
          hint="Pick one of their plants."
          choices={friendPlot}
          empty="Nothing of theirs is growing yet."
          busy={busy}
          error={stepError}
          onChoose={(id) =>
            askFirst(
              `Use 1 water on their ${friendPlot.find((one) => one.id === id)?.label ?? 'plant'}?`,
              { verb: 'pour', plantingId: id },
            )
          }
          onCancel={() => setStep({ at: 'people', then: 'water' })}
        />
      )}

      {/* The same list the other pickers use, spent on a species instead of a
          row. A grove with every seed in it has one thing left to be given, so
          the list says so plainly rather than being empty. */}
      {/* The same panel the verbs came from, asking the last question. Cancel
          goes back to the list that was being chosen from rather than closing
          everything, because changing your mind about which plant is not
          changing your mind about watering one. */}
      {shown !== null && step.at === 'confirm' && (
        <ItemDialog
          stack={shown}
          line={step.line}
          verbs={[{ id: 'use', label: 'Use' }]}
          busy={busy}
          error={stepError}
          cancelLabel="Cancel"
          onRun={() => doDeed(step.deed)}
          onClose={() => setStep(step.back)}
        />
      )}

      {step.at === 'species' && (
        <Chooser
          title={wishName === '' ? 'Unmarked seed' : wishName}
          hint={
            catalog === null
              ? 'The seed list could not be loaded.'
              : lacking.length > 0
                ? ITEM_LINES.wish
                : 'You have every seed. Nothing left to choose.'
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
