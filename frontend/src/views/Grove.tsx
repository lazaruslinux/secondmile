import { useCallback, useEffect, useState } from 'react'
import {
  anointFriend,
  chooseSeed,
  errorText,
  getFriends,
  listFriendGrove,
  listGrove,
  listSatchel,
  plantSeed,
  pourWater,
  type FriendPlanting,
  type ItemKind,
  type Person,
  type Planting,
  type SatchelItem,
} from '../api.ts'
import { itemArt } from '../art.ts'
import { convertedValue } from '../format.ts'
import { levelProgress, plantStage } from '../grove.ts'
import {
  itemFramed,
  itemName,
  itemRarity,
  personName,
  plantingName,
  rarityWord,
  SEED_SPECIES,
} from '../labels.ts'
import Chooser, { type Choice } from './Chooser.tsx'
import PlantArt from './PlantArt.tsx'
import RarityFrame from './RarityFrame.tsx'

// The satchel is grouped in the order things are used: sown, watered, given,
// and last the one that is spent to be given a seed at all.
const KIND_ORDER: ItemKind[] = ['seed', 'water', 'oil', 'wish']

const GROUP_TITLES: Record<ItemKind, string> = {
  seed: 'Seeds',
  water: 'Water',
  oil: 'Oil',
  wish: 'Unmarked seed',
}

// One verb each, and only one. Nothing in the satchel is there to be looked at.
const VERBS: Record<ItemKind, string> = {
  seed: 'Plant',
  water: 'Pour onto...',
  oil: 'Anoint...',
  wish: 'Choose...',
}

// Said after oil is used, and it is the whole of what is said. The point of the
// thing is that the other person finds out later, from the chest itself.
const ANOINTED = 'Done. Nothing is said to them.'

// The one row a wish offers when there is no seed left to ask for. Its id is
// the empty species, which is what the server reads as "there was nothing to
// choose", and what it answers with water for.
const NO_SPECIES = ''
const COMPLETE = 'Your grove is complete. The seed became water.'

// A friend's plot comes back with a stage rather than miles, so the quiet half
// of the row says how far along it is in words.
const STAGE_WORDS = ['Seedling', 'Growing', 'Grown']

// Said under anything that has reached the last level.
const FULLY_GROWN = 'Fully grown.'

// Whether a plant can still take water: everything but the ones that have run
// out of levels to put on.
function friendGrowing(row: FriendPlanting): boolean {
  return row.gilded !== true
}

// How far along one planting is. Everything levels, so this is the same line
// for all of them.
function growthLine(row: Planting): string {
  if (row.gilded) return `Level ${row.level}, fully grown`
  return `Level ${row.level}, ${convertedValue(levelProgress(row).into)} of ${convertedValue(
    row.level_mi,
  )} mi`
}

interface Cached {
  plantings: Planting[]
  items: SatchelItem[]
}

// What this tab last showed, kept by account so a second person signing in on
// the same browser never sees the first one's grove. It lives as long as the
// page does and no longer.
const cache = new Map<number, Cached>()

interface Props {
  userId: number
}

export default function Grove({ userId }: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [plantings, setPlantings] = useState<Planting[]>(
    () => cache.get(userId)?.plantings ?? [],
  )
  const [items, setItems] = useState<SatchelItem[]>(() => cache.get(userId)?.items ?? [])
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  // Which item a button is working on, so only that row goes quiet.
  const [busyId, setBusyId] = useState<number | null>(null)
  const [actionError, setActionError] = useState('')
  const [note, setNote] = useState('')

  // The item waiting for something to be chosen for it, and the friends list,
  // which is only fetched when a chooser asks for it.
  const [choosing, setChoosing] = useState<SatchelItem | null>(null)
  const [friends, setFriends] = useState<Person[]>([])
  // Friends' plots, in the order their owners are listed, fetched only when
  // water asks where it is going.
  const [friendPlots, setFriendPlots] = useState<[Person, FriendPlanting[]][]>([])
  const [chooserError, setChooserError] = useState('')

  const load = useCallback(async () => {
    try {
      const [plot, satchel] = await Promise.all([listGrove(), listSatchel()])
      setPlantings(plot)
      setItems(satchel)
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
    cache.set(userId, { plantings, items })
  }, [userId, plantings, items])

  async function plant(item: SatchelItem) {
    setBusyId(item.id)
    setActionError('')
    setNote('')
    try {
      await plantSeed(item.id)
      await load()
    } catch (err) {
      setActionError(errorText(err))
    } finally {
      setBusyId(null)
    }
  }

  // Both choosers ask who this account's friends are: oil to name them, water
  // because it can be poured on their plots as well as this one's.
  async function startChoosing(item: SatchelItem) {
    setChooserError('')
    setActionError('')
    setNote('')
    setChoosing(item)
    setFriendPlots([])
    // A wish is spent on the catalogue, which is already here: what is missing
    // is worked out from the plot and the satchel, so there is nothing to ask
    // the server for before the list can be drawn.
    if (item.kind === 'wish') return
    try {
      const found = await getFriends()
      setFriends(found.friends)
      if (item.kind !== 'water') return
      // A plot that will not load costs that friend's rows and nothing else.
      const plots = await Promise.all(
        found.friends.map(async (person): Promise<[Person, FriendPlanting[]]> => {
          try {
            return [person, await listFriendGrove(person.user_id)]
          } catch {
            return [person, []]
          }
        }),
      )
      setFriendPlots(plots)
    } catch (err) {
      setChooserError(errorText(err))
    }
  }

  // One handler for both choosers: which call it makes is the item's kind, and
  // the id is whatever the list was listing.
  async function choose(chosenId: number) {
    const item = choosing
    if (!item) return
    setBusyId(item.id)
    setChooserError('')
    try {
      if (item.kind === 'water') {
        await pourWater(item.id, chosenId)
      } else {
        await anointFriend(item.id, chosenId)
        setNote(ANOINTED)
      }
      setChoosing(null)
      await load()
    } catch (err) {
      setChooserError(errorText(err))
    } finally {
      setBusyId(null)
    }
  }

  // A wish is spent on a species rather than on a row, and what comes back is
  // the seed itself, which takes the wish's place in the satchel. Nothing else
  // changed, so the plot is not asked for again.
  async function spendWish(species: string) {
    const item = choosing
    if (!item) return
    setBusyId(item.id)
    setChooserError('')
    try {
      const made = await chooseSeed(item.id, species)
      setItems((held) => held.map((one) => (one.id === item.id ? made : one)))
      setChoosing(null)
      if (species === NO_SPECIES) setNote(COMPLETE)
    } catch (err) {
      // A pick can go stale between the list and the tap: a seed of that
      // species may have arrived in the meantime. Reading everything again is
      // what redraws the list under the message.
      setChooserError(errorText(err))
      await load()
    } finally {
      setBusyId(null)
    }
  }

  const growing = plantings.filter((row) => !row.gilded)

  // This account's plot first, then each friend's under their own name. Nothing
  // fully grown is offered: it has all the growth there is.
  const plantingChoices: Choice[] = [
    ...growing.map((row) => ({
      id: row.id,
      group: 'You',
      label: plantingName(row),
      detail: growthLine(row),
    })),
    ...friendPlots.flatMap(([person, plot]) =>
      plot.filter(friendGrowing).map((row) => ({
        id: row.id,
        group: personName(person),
        label: plantingName(row),
        detail: STAGE_WORDS[(row.stage ?? 1) - 1] ?? 'Growing',
      })),
    ),
  ]

  const friendChoices: Choice[] = friends.map((person) => ({
    id: person.user_id,
    label: personName(person),
  }))

  // What a wish can be spent on: every species that is neither growing in the
  // plot nor already held as a seed. A grove holding all of them offers the one
  // thing left, which is water.
  const owned = new Set<string>([
    ...plantings.map((row) => row.species),
    ...items.flatMap((one) => (one.kind === 'seed' && one.species ? [one.species] : [])),
  ])
  const lacking = SEED_SPECIES.filter((row) => !owned.has(row.id))
  const seedChoices: Choice<string>[] =
    lacking.length > 0
      ? lacking.map((row) => ({ id: row.id, label: row.name, detail: rarityWord(row.rarity) }))
      : [{ id: NO_SPECIES, label: 'Water', detail: 'The wish becomes water.' }]

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">Grove</h1>
      </div>

      <section className="card">
        <p className="hint">
          Everything here grows on the miles you cover. There is nothing to tend and nothing
          to keep up with.
        </p>
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
              const line = growthLine(row)
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
                      this one reads correctly to a screen reader as well. */}
                  {!row.gilded && (
                    <progress className="xp-meter" value={into} max={step}>
                      {line}
                    </progress>
                  )}
                  <p className="plant-growth">{line}</p>
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

      <section className="card">
        <h2 className="label">Satchel</h2>
        {actionError && (
          <p className="error" role="alert">
            {actionError}
          </p>
        )}
        {note && (
          <p className="note note-success" role="status">
            {note}
          </p>
        )}
        {!loading && items.length === 0 && (
          <p className="hint">
            Empty. Chests hold seeds, water, oil, and unmarked seeds.
          </p>
        )}

        {KIND_ORDER.map((kind) => {
          const held = items.filter((item) => item.kind === kind)
          if (held.length === 0) return null
          return (
            <div key={kind} className="satchel-group">
              <h3 className="label">{GROUP_TITLES[kind]}</h3>
              <ul className="satchel-list">
                {held.map((item) => {
                  // A seed is drawn as what it grows into, framed in its
                  // rarity. A tool is drawn as itself, framed where it has a
                  // rarity to name and left plain where it has none.
                  const art = item.kind === 'seed' ? null : itemArt(item.kind)
                  const framed = itemFramed(item)
                  return (
                    <li key={item.id} className="satchel-row">
                      {item.kind === 'seed' && item.species !== null && (
                        <RarityFrame rarity={item.rarity} className="satchel-frame">
                          <PlantArt
                            species={item.species}
                            name={itemName(item)}
                            stage={1}
                            className="satchel-thumb"
                          />
                        </RarityFrame>
                      )}
                      {art && framed && (
                        <RarityFrame rarity={itemRarity(item)} className="satchel-frame">
                          <img className="item-art" src={art} alt="" />
                        </RarityFrame>
                      )}
                      {art && !framed && (
                        <span className="item-square">
                          <img className="item-art" src={art} alt="" />
                        </span>
                      )}
                      <span className="satchel-name">{itemName(item)}</span>
                      <button
                        type="button"
                        className="secondary"
                        disabled={busyId === item.id}
                        onClick={() =>
                          item.kind === 'seed' ? void plant(item) : void startChoosing(item)
                        }
                      >
                        {VERBS[item.kind]}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })}
      </section>

      {choosing?.kind === 'water' && (
        <Chooser
          title="Pour it onto"
          hint="Ten miles of growth, into one plant. Yours or a friend's."
          choices={plantingChoices}
          empty="Nothing is growing yet, here or in a friend's plot."
          busy={busyId !== null}
          error={chooserError}
          onChoose={(id) => void choose(id)}
          onCancel={() => setChoosing(null)}
        />
      )}

      {choosing?.kind === 'oil' && (
        <Chooser
          title="Anoint"
          hint="They are not told. Nothing about this shows in their app."
          choices={friendChoices}
          empty="No friends yet. Invite someone from the You screen."
          busy={busyId !== null}
          error={chooserError}
          onChoose={(id) => void choose(id)}
          onCancel={() => setChoosing(null)}
        />
      )}

      {/* The same list the other two use, spent on a species instead of a row.
          A grove with every seed in it has one thing left to be given, so the
          list says so plainly rather than being empty. */}
      {choosing?.kind === 'wish' && (
        <Chooser
          title="Unmarked seed"
          hint={
            lacking.length > 0
              ? 'Choose what it will become: any seed you have not yet found. One use.'
              : 'Your grove is complete. There is no seed left to ask for.'
          }
          choices={seedChoices}
          empty="Nothing to choose."
          busy={busyId !== null}
          error={chooserError}
          onChoose={(species) => void spendWish(species)}
          onCancel={() => setChoosing(null)}
        />
      )}
    </>
  )
}
