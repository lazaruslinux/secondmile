import { useCallback, useEffect, useState } from 'react'
import {
  anointFriend,
  avatarUrl,
  errorText,
  getFriendProfile,
  listFriendGrove,
  listSatchel,
  pourWater,
  removeFriend,
  type FeedItem,
  type FriendPlanting,
  type FriendProfile as FriendProfileData,
  type SatchelItem,
  type Units,
} from '../api.ts'
import { formatDate } from '../format.ts'
import { itemName, plantingName } from '../labels.ts'
import { SEEDS_TO_FIND } from '../profile.ts'
import AvatarFrame from './AvatarFrame.tsx'
import Chooser, { type Choice } from './Chooser.tsx'
import FeedCard from './FeedCard.tsx'
import MedalNest from './MedalNest.tsx'
import Medals from './Medals.tsx'
import PlantArt from './PlantArt.tsx'

// The three sentences the inventory says after the same three acts, said the
// same way here so one verb does not read as two different things depending on
// which screen it was run from.
const POURED = 'Poured. Ten miles of growth.'
const ANOINTED = 'Done. One chest they earn will open one step rarer.'
const OIL_KEPT = 'The oil is still in your inventory.'

// A friend's plot comes back with a stage rather than miles, so the quiet half
// of a row says how far along it is in words.
const STAGE_WORDS = ['Seedling', 'Growing', 'Grown']

// What ending a friendship costs, said before it is done rather than after.
const REMOVE_WARNING =
  "You will stop seeing each other's activities, and neither of you can water " +
  'the other or send oil. Either of you can invite the other again.'

// Which of the three drawings one of their plants is at. Their plot carries the
// stage itself rather than the miles the own plot is read from, so this stands
// in for grove.ts's reading rather than calling it with fields a friend's row
// does not have.
function friendStage(row: FriendPlanting): number {
  if (row.stage != null) return Math.min(3, Math.max(1, row.stage))
  return row.mature === true ? 3 : 1
}

// Their activities, read as defensively as anything crossing the seam: a row
// without the parts a card is drawn from is dropped rather than allowed to
// throw, and a row that arrived without its encouragement counts is given
// nought of everything rather than reaching into a field that is not there.
function feedRows(workouts: FeedItem[] | undefined): FeedItem[] {
  if (!Array.isArray(workouts)) return []
  return workouts
    .filter((row) => row != null && typeof row.workout_id === 'number' && row.user != null)
    .map((row) => ({
      ...row,
      encouragement: row.encouragement ?? { cheers: 0, notes: 0, cheered_by_me: false },
    }))
}

// A number the screen is willing to print, which is a finite one and nothing
// else. Anything else draws as nothing rather than as NaN.
function figure(value: number | undefined): number | null {
  return typeof value === 'number' && isFinite(value) ? value : null
}

// A name the screen is willing to print. The artwork is looked up by reading
// strings, so anything that is not one is nothing here rather than a call into
// a method that is not there.
function words(value: string | null | undefined): string {
  return typeof value === 'string' ? value.trim() : ''
}

// Where a tap on one of the three verbs has got to. Water goes through what is
// held and then onto one of their plants; oil is one pick; ending a friendship
// asks first, on the card rather than in a dialog.
type Step = 'none' | 'water' | 'plants' | 'oil' | 'remove'

interface Props {
  // Whose screen this is. Their own account decides everything on it; this one
  // only decides what may be done to them.
  userId: number
  units: Units
  onBack: () => void
  // Ending a friendship takes the screen with it: what is behind this one is a
  // feed and a list that no longer hold this person.
  onRemoved: () => void
}

// One friend, reached by a deliberate tap on their picture, their name, or
// their row in the friends list. It shows who they are and how they are doing
// and nothing about their game state, and it carries the three things one
// person may do to another: water something of theirs, anoint them, or stop
// being friends.
export default function FriendProfile({ userId, units, onBack, onRemoved }: Props) {
  const [profile, setProfile] = useState<FriendProfileData | null>(null)
  const [plot, setPlot] = useState<FriendPlanting[]>([])
  const [held, setHeld] = useState<SatchelItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [step, setStep] = useState<Step>('none')
  // Which water was picked, kept while its plant is being chosen.
  const [watering, setWatering] = useState<SatchelItem | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [note, setNote] = useState('')

  const load = useCallback(async () => {
    try {
      // Only the profile decides whether there is a screen at all. Their plot
      // and this account's own satchel are what the verbs need, so either
      // failing leaves a verb quiet rather than taking the page down.
      const [person, plants, satchel] = await Promise.all([
        getFriendProfile(userId),
        listFriendGrove(userId).catch(() => []),
        listSatchel().catch(() => []),
      ])
      setProfile(person)
      // A plant is drawn and named from its species, both by reading the
      // string, so a row without one is dropped on the way in.
      setPlot(
        Array.isArray(plants)
          ? plants.filter((row) => row != null && typeof row.species === 'string')
          : [],
      )
      setHeld(Array.isArray(satchel) ? satchel : [])
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  // An edited card is put back where it sat. Only ever this account's own row,
  // which is only ever on this screen when it is looking at itself.
  const rowChanged = useCallback((updated: FeedItem) => {
    setProfile((current) =>
      current === null
        ? current
        : {
            ...current,
            workouts: (current.workouts ?? []).map((row) =>
              row.workout_id === updated.workout_id ? updated : row,
            ),
          },
    )
  }, [])

  // Every act ends the same way the inventory's do: the server is asked again
  // for everything this screen holds. A refusal is the server's own sentence,
  // with whatever the act wants added to it.
  async function act(work: () => Promise<void>, refused = '') {
    setBusy(true)
    setActionError('')
    try {
      await work()
      await load()
    } catch (err) {
      const said = errorText(err)
      setActionError(refused === '' ? said : `${said} ${refused}`)
    } finally {
      setBusy(false)
    }
  }

  function pour(plantingId: number) {
    const item = watering
    if (!item) return
    void act(async () => {
      await pourWater(item.id, plantingId)
      setNote(POURED)
      setWatering(null)
      setStep('none')
    })
  }

  // Oil can be turned down: nobody holds more than three gifts at once, and the
  // answer to that is the server's own sentence with the oil's fate added,
  // said where the oil was picked rather than anywhere anyone has to go looking
  // for it. Nothing is spent on a refusal.
  function anoint(itemId: number) {
    void act(async () => {
      await anointFriend(itemId, userId)
      setNote(ANOINTED)
      setStep('none')
    }, OIL_KEPT)
  }

  async function remove() {
    setBusy(true)
    setActionError('')
    try {
      await removeFriend(userId)
      onRemoved()
    } catch (err) {
      setActionError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const head = (
    <div className="view-head">
      <h1 className="view-title">Profile</h1>
      <button type="button" className="secondary" onClick={onBack}>
        Back
      </button>
    </div>
  )

  if (loading) {
    return (
      <>
        {head}
        <p className="notice">Loading.</p>
      </>
    )
  }

  // The way back is drawn even when nothing else could be: a screen reached by
  // a tap has to be leavable by one.
  if (!profile) {
    return (
      <>
        {head}
        <p className="error" role="alert">
          {loadError || 'Something went wrong. Try again.'}
        </p>
      </>
    )
  }

  const given = words(profile.display_name)
  const username = words(profile.username)
  const who = given !== '' ? given : username
  const level = figure(profile.level)
  const miles = figure(profile.miles)
  // Medal ids are read as file names, so anything that is not an id is left out
  // rather than carried into the lookup.
  const chosen = (Array.isArray(profile.displayed_badges) ? profile.displayed_badges : []).filter(
    (id) => words(id) !== '',
  )
  const medals = Array.isArray(profile.medals) ? profile.medals : undefined
  const seeds = figure(profile.grove?.seeds_found) ?? 0
  const plantLevels = figure(profile.grove?.plant_levels) ?? 0
  const rows = feedRows(profile.workouts)
  // A stamp that will not parse is left out rather than printed as an invalid
  // date, so the sentence is dropped whole rather than half built.
  const since =
    typeof profile.created_at === 'string' && !isNaN(Date.parse(profile.created_at))
      ? formatDate(profile.created_at)
      : ''

  // While a picker is up it is the one showing what went wrong, so the card
  // does not say the same sentence a second time behind it.
  const choosing = step === 'water' || step === 'plants' || step === 'oil'

  const waters = held.filter((one) => one.kind === 'water')
  const oils = held.filter((one) => one.kind === 'oil')
  const waterChoices: Choice[] = waters.map((one) => ({ id: one.id, label: itemName(one) }))
  const oilChoices: Choice[] = oils.map((one) => ({ id: one.id, label: itemName(one) }))
  // Nothing fully grown is offered a drink: it has all the growth there is.
  const plantChoices: Choice[] = plot
    .filter((row) => row.gilded !== true)
    .map((row) => ({
      id: row.id,
      label: plantingName(row),
      detail: STAGE_WORDS[friendStage(row) - 1] ?? 'Growing',
    }))

  return (
    <>
      {head}

      {/* The band across the top, exactly as the You screen draws one: their
          plot stands along its floor and their picture rides up over its lower
          edge. Nothing in the band is pressable, here least of all: the plot is
          theirs and the one thing that may be done to it is watering, which is
          a verb on the card below. */}
      <div className="you-banner">
        <div className="you-band">
          {plot.length > 0 && (
            <ul className="band-grove">
              {plot.map((row) => (
                <li
                  key={row.id}
                  className={row.mature ? 'band-plant band-plant-grown' : 'band-plant'}
                >
                  <PlantArt
                    species={row.species}
                    name={plantingName(row)}
                    stage={friendStage(row)}
                    gilded={row.gilded}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="you-ident">
          <div className="avatar-block">
            <AvatarFrame
              name={who}
              src={
                profile.has_avatar
                  ? avatarUrl(profile.user_id ?? userId, profile.avatar_version ?? null)
                  : null
              }
              borderTier={profile.border_tier ?? 0}
              flourish={profile.flourish ?? 0}
              labelled
            >
              {/* What they chose, and no empty slots. An empty slot is an
                  invitation to fill it, and filling these is theirs to do on
                  their own screen. */}
              <MedalNest ids={chosen} />
            </AvatarFrame>
          </div>

          <div className="you-ident-text">
            <h2 className="profile-name">{who}</h2>
            {given !== '' && username !== '' && <p className="profile-username">{username}</p>}
            {level !== null && <p className="you-level">Level {level}</p>}
          </div>
        </div>
      </div>

      <section className="card">
        {since !== '' && <p className="hint">Member since {since}</p>}

        <ul className="profile-counts">
          <li>
            {/* Raw miles: the distance they covered. The weighted number the
                game runs on is XP, it is theirs, and it is not on this screen
                at all. */}
            <span className="count-value">{miles === null ? '--' : miles.toFixed(1)}</span>
            <span className="count-label">Miles</span>
          </li>
        </ul>

        {/* The three things one person may do to another. Two of them spend
            something out of this account's own satchel, so a button with
            nothing behind it says so rather than opening an empty list. */}
        <div className="friend-actions">
          <div className="choice">
            <button
              type="button"
              className="secondary"
              disabled={busy || waters.length === 0}
              onClick={() => {
                setNote('')
                setActionError('')
                setStep('water')
              }}
            >
              Water a plant
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy || oils.length === 0}
              onClick={() => {
                setNote('')
                setActionError('')
                setStep('oil')
              }}
            >
              Anoint
            </button>
          </div>

          {(waters.length === 0 || oils.length === 0) && (
            <p className="hint">
              {waters.length === 0 && oils.length === 0
                ? 'Water and oil come out of chests. You are holding neither.'
                : waters.length === 0
                  ? 'No water in your inventory.'
                  : 'No oil in your inventory.'}
            </p>
          )}

          {note && (
            <p className="note note-success" role="status">
              {note}
            </p>
          )}
          {actionError && !choosing && (
            <p className="error" role="alert">
              {actionError}
            </p>
          )}

          {/* Destructive, on a screen opened casually, so it asks first and the
              question says what is lost. */}
          {step === 'remove' ? (
            <>
              <p className="hint">{REMOVE_WARNING}</p>
              <div className="choice">
                <button
                  type="button"
                  className="primary"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  Remove {who}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => setStep('none')}
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <button
              type="button"
              className="secondary friend-remove"
              disabled={busy}
              onClick={() => {
                setNote('')
                setActionError('')
                setStep('remove')
              }}
            >
              Remove friend
            </button>
          )}
        </div>
      </section>

      <Medals medals={medals} />

      {/* The numbers their plot has come to. The plants themselves are in the
          band at the top, which is where the You screen puts a grove. */}
      <section className="card">
        <h2 className="label">Grove</h2>
        <ul className="profile-counts">
          <li>
            <span className="count-value">
              {seeds} / {SEEDS_TO_FIND}
            </span>
            <span className="count-label">Seeds found</span>
          </li>
          <li>
            <span className="count-value">{plantLevels}</span>
            <span className="count-label">Plant levels</span>
          </li>
        </ul>
        {plot.length === 0 && <p className="hint">Nothing planted yet.</p>}
      </section>

      {/* The feed's own cards, so what a friend's activity may show is written
          in one place. Nothing on them opens another profile: the way to this
          screen is the feed and the friends list, not another profile. */}
      <div className="friend-feed">
        <h2 className="label">Recent activities</h2>
        {rows.length === 0 ? (
          <p className="hint">Nothing recorded yet.</p>
        ) : (
          rows.map((row) => (
            <FeedCard
              key={row.workout_id}
              item={row}
              units={units}
              avatarVersion={null}
              onChanged={rowChanged}
            />
          ))
        )}
      </div>

      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}

      {step === 'water' && (
        <Chooser
          title="Water"
          hint="Which of yours goes onto their plot."
          choices={waterChoices}
          empty="No water in your inventory. It comes out of chests."
          busy={busy}
          error={actionError}
          onChoose={(id) => {
            const item = waters.find((one) => one.id === id)
            if (!item) return
            setWatering(item)
            setActionError('')
            setStep('plants')
          }}
          onCancel={() => {
            setActionError('')
            setStep('none')
          }}
        />
      )}

      {step === 'plants' && (
        <Chooser
          title={who}
          hint="Which of their plants it goes onto."
          choices={plantChoices}
          empty="Nothing of theirs is growing yet."
          busy={busy}
          error={actionError}
          onChoose={(id) => pour(id)}
          onCancel={() => {
            setActionError('')
            setStep('water')
          }}
        />
      )}

      {step === 'oil' && (
        <Chooser
          title="Anoint"
          hint="One chest they earn will open one step rarer."
          choices={oilChoices}
          empty="No oil in your inventory. It comes out of chests."
          busy={busy}
          error={actionError}
          onChoose={(id) => anoint(id)}
          onCancel={() => {
            setActionError('')
            setStep('none')
          }}
        />
      )}
    </>
  )
}
