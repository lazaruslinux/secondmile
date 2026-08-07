import { useCallback, useEffect, useState } from 'react'
import {
  anointFriend,
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
import { convertedValue } from '../format.ts'
import { plantStage } from '../grove.ts'
import { itemName, rarityWord, speciesName } from '../labels.ts'
import Chooser, { type Choice } from './Chooser.tsx'
import PlantArt from './PlantArt.tsx'

// The satchel is grouped in the order things are used: sown, watered, given.
const KIND_ORDER: ItemKind[] = ['seed', 'water', 'oil']

const GROUP_TITLES: Record<ItemKind, string> = {
  seed: 'Seeds',
  water: 'Water',
  oil: 'Oil',
}

// One verb each, and only one. Nothing in the satchel is there to be looked at.
const VERBS: Record<ItemKind, string> = {
  seed: 'Plant',
  water: 'Pour onto...',
  oil: 'Anoint...',
}

// Said after oil is used, and it is the whole of what is said. The point of the
// thing is that the other person finds out later, from the chest itself.
const ANOINTED = 'Done. Nothing is said to them.'

// A friend's plot comes back with a stage rather than miles, so the quiet half
// of the row says how far along it is in words.
const STAGE_WORDS = ['Seedling', 'Growing']

// Whether a friend's plant can still take water. Anything grown is left out;
// a plant that levels rather than maturing never is, however big it is drawn.
function friendGrowing(row: FriendPlanting): boolean {
  return row.mature !== true
}

// How far along one planting is, in the words its own kind uses: a level for
// anything that levels, and miles toward maturity for the rest.
function growthLine(row: Planting): string {
  if (row.level != null) return `Level ${row.level}`
  return `${convertedValue(row.growth_mi)} of ${convertedValue(row.maturity_mi)} mi`
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

  const growing = plantings.filter((row) => !row.mature)

  // This account's plot first, then each friend's under their own name. Nothing
  // already grown is offered: it has all the growth it needs.
  const plantingChoices: Choice[] = [
    ...growing.map((row) => ({
      id: row.id,
      group: 'You',
      label: speciesName(row.species, row.name),
      detail: growthLine(row),
    })),
    ...friendPlots.flatMap(([person, plot]) =>
      plot.filter(friendGrowing).map((row) => ({
        id: row.id,
        group: person.username,
        label: speciesName(row.species, row.name),
        detail: STAGE_WORDS[(row.stage ?? 1) - 1] ?? 'Growing',
      })),
    ),
  ]

  const friendChoices: Choice[] = friends.map((person) => ({
    id: person.user_id,
    label: person.username,
  }))

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
              const stage = plantStage(row)
              // A plant that levels fills its bar over and over, one level at
              // a time; the rest fill theirs once, on the way to maturity.
              const step = row.level != null ? (row.level_mi ?? 0) : row.maturity_mi
              const into =
                row.level != null && row.level_mi
                  ? row.growth_mi - row.level * row.level_mi
                  : Math.min(row.growth_mi, row.maturity_mi)
              const line = growthLine(row)
              return (
                <li key={row.id} className="plant">
                  <PlantArt
                    species={row.species}
                    name={row.name}
                    stage={stage}
                    className="plant-picture"
                  />
                  <p className="plant-name">{speciesName(row.species, row.name)}</p>
                  {/* A progress element rather than a div with a width on it:
                      the content security policy allows no inline styles, and
                      this one reads correctly to a screen reader as well. */}
                  <progress className="xp-meter" value={into} max={step > 0 ? step : 1}>
                    {line}
                  </progress>
                  <p className="plant-growth">{line}</p>
                  {row.mature && (
                    <p className="plant-ready">Fully grown. It waits here to bear fruit.</p>
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
          <p className="hint">Empty. Chests hold seeds, water, and oil.</p>
        )}

        {KIND_ORDER.map((kind) => {
          const held = items.filter((item) => item.kind === kind)
          if (held.length === 0) return null
          return (
            <div key={kind} className="satchel-group">
              <h3 className="label">{GROUP_TITLES[kind]}</h3>
              <ul className="satchel-list">
                {held.map((item) => (
                  <li key={item.id} className="satchel-row">
                    {/* A seed is drawn as what it grows into. Water and oil
                        have nothing to draw, so nothing is drawn for them. */}
                    {item.kind === 'seed' && item.species !== null && (
                      <PlantArt
                        species={item.species}
                        name={item.name}
                        stage={1}
                        className="satchel-thumb"
                      />
                    )}
                    <span className="satchel-name">
                      {itemName(item)}
                      {rarityWord(item.rarity) !== '' && item.kind === 'seed' && (
                        <span className="muted"> {rarityWord(item.rarity)}</span>
                      )}
                    </span>
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
                ))}
              </ul>
            </div>
          )
        })}
      </section>

      {choosing?.kind === 'water' && (
        <Chooser
          title="Pour it onto"
          hint="Ten miles of growth, into one planting. Yours or a friend's."
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
    </>
  )
}
