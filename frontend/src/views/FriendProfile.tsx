import { useCallback, useEffect, useState } from 'react'
import {
  acceptFriend,
  anointFriend,
  avatarUrl,
  errorText,
  feedPlant,
  getFriendProfile,
  getHarvest,
  giveFruit,
  giveManna,
  inviteFriend,
  listFriendGrove,
  listSatchel,
  pourWater,
  removeFriend,
  workoutPhotoUrl,
  type Activity,
  type ActivityStats,
  type FeedItem,
  type FriendPlanting,
  type FriendProfile as FriendProfileData,
  type HarvestState,
  type MemberCard,
  type RecentPhoto,
  type SatchelItem,
  type Units,
} from '../api.ts'
import {
  convertedValue,
  distanceValue,
  formatClock,
  formatDate,
  formatMonth,
  unitName,
} from '../format.ts'
import {
  activityIcon,
  ANOINT_HINT,
  ANOINTED,
  EMPTY_BASKET,
  FED,
  feedHint,
  FRUIT_GIVEN,
  MANNA_SENT,
  NO_MANNA,
  NO_WATER,
  NOTHING_RECORDED_FRIEND,
  NOTHING_THIS_WEEK,
  OIL_KEPT,
  plantingName,
  plantStateLine,
  POURED,
} from '../labels.ts'
import { fitLine, gearName, gearSubline, milesLine } from '../gear.ts'
import { totalMedalEarns } from '../profile.ts'
import { pileItems, type Stack } from '../satchel.ts'
import AvatarFrame from './AvatarFrame.tsx'
import BandGrove from './BandGrove.tsx'
import Chooser, { type Choice } from './Chooser.tsx'
import Confirm from './Confirm.tsx'
import FeedCard from './FeedCard.tsx'
import Icon from './Icon.tsx'
import ItemPicker from './ItemPicker.tsx'
import ItemTallies from './ItemTallies.tsx'
import MedalNest from './MedalNest.tsx'
import Medals from './Medals.tsx'
import PlantArt from './PlantArt.tsx'
import ProfileCounts from './ProfileCounts.tsx'
import RarityFrame from './RarityFrame.tsx'
import SportChips from './SportChips.tsx'
import Stats from './Stats.tsx'

// What ending a friendship costs, said before it is done rather than after.
const REMOVE_WARNING =
  "You will stop seeing each other's activities and cannot water or anoint each " +
  'other. Either of you can invite again.'

// Which of the three drawings one of their plants is at. Their plot carries the
// stage itself rather than the miles the own plot is read from, so this stands
// in for grove.ts's reading rather than calling it with fields a friend's row
// does not have.
function friendStage(row: FriendPlanting): number {
  if (row.stage != null) return Math.min(3, Math.max(1, row.stage))
  return row.mature === true ? 3 : 1
}

// How full their bar is. The server sends the fraction of the level already
// covered rather than the miles behind it, so this is the whole of what the bar
// can be drawn from, and a row that arrived without it draws empty.
function friendFill(row: FriendPlanting): number {
  const part = row.growth
  if (typeof part !== 'number' || !isFinite(part)) return 0
  return Math.min(1, Math.max(0, part))
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
      encouragement: row.encouragement ?? {
        hype_count: 0,
        note_count: 0,
        cheered_by_me: false,
        notes: [],
      },
    }))
}

// The pictures on the strip, read the same defensive way. A row without the two
// ids its address is built from is dropped rather than pointed at nothing.
function mediaRows(photos: RecentPhoto[] | undefined): RecentPhoto[] {
  if (!Array.isArray(photos)) return []
  return photos.filter(
    (row) =>
      row != null && typeof row.photo_id === 'number' && typeof row.workout_id === 'number',
  )
}

// A set of totals the tables and the chips are willing to read. A server that
// predates them sends nothing, which draws as a card saying so rather than as a
// call into a field that is not there.
function statsOf(
  stats: Partial<Record<Activity, ActivityStats>> | undefined,
): Partial<Record<Activity, ActivityStats>> {
  return stats != null && typeof stats === 'object' ? stats : {}
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

// Where a tap has got to. Watering starts from one of their plants and carries
// it the whole way, so the question at the end can name a real plant rather than
// asking about a picked item on its own. Oil targets the person, so it starts
// from a button beside their name and skips the plant. Ending a friendship asks
// first, on the card rather than in a dialog.
type Step =
  | { at: 'none' }
  | { at: 'water'; plant: FriendPlanting }
  | { at: 'oil' }
  | { at: 'remove' }
  // The three manna verbs. Feeding is aimed at one of their plants, so it picks
  // one first and then asks; the two gifts are aimed at the person, so they ask
  // straight away. All three spend the bank or something grown with it, and none
  // of them can be undone.
  | { at: 'pick-plant' }
  | { at: 'feed'; plant: FriendPlanting }
  | { at: 'manna' }
  | { at: 'fruit' }

// A member of this instance who is not a friend, as much of them as the club
// decided a member may see: their name, their face in its frame, the line they
// wrote about themselves, the month they joined, and one way to ask.
//
// What is not here is everything friendship gates, and the reason there is a
// second component rather than a flag on the first is the same reason there is
// a second serializer on the server: a card that draws whatever it was given
// draws whatever leaks.
function MemberProfile({
  card,
  busy,
  error,
  onAsk,
}: {
  card: MemberCard
  busy: boolean
  error: string
  onAsk: (work: () => Promise<void>) => void
}) {
  const given = words(card.display_name)
  const username = words(card.username)
  const who = given !== '' ? given : username
  const bio = words(card.bio)
  const since =
    typeof card.created_at === 'string' && !isNaN(Date.parse(card.created_at))
      ? formatMonth(card.created_at)
      : ''

  return (
    <section className="card member-card">
      <div className="avatar-block">
        <AvatarFrame
          name={who}
          src={card.has_avatar ? avatarUrl(card.user_id, card.avatar_version ?? null) : null}
          borderTier={card.border_tier ?? 0}
          flourish={card.flourish ?? 0}
          labelled
        />
      </div>

      <h2 className="profile-name">{who}</h2>
      {given !== '' && username !== '' && <p className="profile-username">{username}</p>}
      {bio !== '' && <p className="profile-bio">{bio}</p>}
      {since !== '' && <p className="hint">Member since {since}</p>}

      {/* One button, and which one is decided by where the two of you already
          stand. An invite already sent is a button that has done its job and
          says so; an invite waiting on you is answered here rather than sending
          somebody back to the friends list to find it. */}
      {card.friendship === 'invited_me' ? (
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => onAsk(() => acceptFriend(card.user_id))}
        >
          Accept
        </button>
      ) : card.friendship === 'invited_by_me' ? (
        <button type="button" className="secondary" disabled>
          Invite sent
        </button>
      ) : (
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => onAsk(() => inviteFriend(username))}
        >
          Invite to be friends
        </button>
      )}

      {/* Said plainly, because the card above it is most of what there is to
          see until somebody says yes. */}
      <p className="hint">
        Their activities, medals, and grove are for friends. Invite them to see them.
      </p>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}

interface Props {
  // Whose screen this is. Their own account decides everything on it; this one
  // only decides what may be done to them.
  userId: number
  units: Units
  onBack: () => void
  // Ending a friendship takes the screen with it: what is behind this one is a
  // feed and a list that no longer hold this person.
  onRemoved: () => void
  // The owner looking at themselves through the friend lens. The payload is
  // the same one a friend gets; this only hides the verbs, because nothing
  // here may be done to yourself.
  selfPreview?: boolean
}

// Deliberately absent: chests, ladder, pending gifts, medal picker, editing,
// birthdate, age, gender.
export default function FriendProfile({
  userId,
  units,
  onBack,
  onRemoved,
  selfPreview = false,
}: Props) {
  const [profile, setProfile] = useState<FriendProfileData | MemberCard | null>(null)
  const [plot, setPlot] = useState<FriendPlanting[]>([])
  const [held, setHeld] = useState<SatchelItem[]>([])
  // This account's own harvest, which is what the three manna verbs spend from.
  // Never theirs: what somebody has banked is theirs to know.
  const [harvest, setHarvest] = useState<HarvestState | null>(null)
  // How much manna this gift is for, as it is being typed.
  const [amount, setAmount] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [step, setStep] = useState<Step>({ at: 'none' })
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const [note, setNote] = useState('')

  const load = useCallback(async () => {
    try {
      // Only the profile decides whether there is a screen at all. Their plot
      // and this account's own satchel are what the verbs need, so either
      // failing leaves a verb quiet rather than taking the page down.
      const [person, plants, satchel, mine] = await Promise.all([
        getFriendProfile(userId),
        listFriendGrove(userId).catch(() => []),
        listSatchel().catch(() => []),
        getHarvest().catch(() => null),
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
      setHarvest(mine)
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
      // Nothing to put back on a card that carries no workouts, which is every
      // restricted one.
      current === null || current.restricted
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

  // A square is a pile of the same thing, so spending one means spending the
  // oldest of them; which of the identical jars leaves is nobody's business.
  function pour(stack: Stack, plantingId: number) {
    const item = stack.items[0]
    if (!item) return
    void act(async () => {
      await pourWater(item.id, plantingId)
      setNote(POURED)
      setStep({ at: 'none' })
    })
  }

  // A potion can be turned down: nobody holds more than three gifts at once,
  // and the answer to that is the server's own sentence with the potion's fate
  // added, said where it was picked rather than anywhere anyone has to go
  // looking for it. Nothing is spent on a refusal.
  function anoint(stack: Stack) {
    const item = stack.items[0]
    if (!item) return
    void act(async () => {
      await anointFriend(item.id, userId)
      setNote(ANOINTED)
      setStep({ at: 'none' })
    }, OIL_KEPT)
  }

  // Manna spent on one of their plants. What it buys is fruit on that plant's
  // next bearing and nothing else: it never makes anything grow faster.
  function feed(plant: FriendPlanting) {
    void act(async () => {
      await feedPlant(plant.id)
      setNote(FED)
      setStep({ at: 'none' })
    })
  }

  function sendManna() {
    const sent = Math.trunc(Number(amount) || 0)
    void act(async () => {
      await giveManna(userId, sent)
      setNote(MANNA_SENT)
      setStep({ at: 'none' })
    })
  }

  function give(fruitId: number) {
    void act(async () => {
      await giveFruit(userId, fruitId)
      setNote(FRUIT_GIVEN)
      setStep({ at: 'none' })
    })
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

  // A member of this instance who is not a friend. A different card rather than
  // this one with most of it missing: what they are owed is a name, a face, a
  // line, and a way to ask.
  if (profile.restricted) {
    return (
      <>
        {head}
        <MemberProfile
          card={profile}
          busy={busy}
          error={actionError}
          onAsk={(work) => void act(work)}
        />
      </>
    )
  }

  const given = words(profile.display_name)
  const username = words(profile.username)
  const who = given !== '' ? given : username
  const level = figure(profile.level)
  const miles = figure(profile.miles)
  const xp = figure(profile.xp)
  const intoLevel = figure(profile.xp_into_level)
  const levelSpan = figure(profile.xp_for_next_level)
  const bio = words(profile.bio)
  // Medal ids are read as file names, so anything that is not an id is left out
  // rather than carried into the lookup.
  const chosen = (Array.isArray(profile.displayed_badges) ? profile.displayed_badges : []).filter(
    (id) => words(id) !== '',
  )
  const medals = Array.isArray(profile.medals) ? profile.medals : undefined
  const rows = feedRows(profile.workouts)
  const media = mediaRows(profile.recent_photos)
  // Read defensively like everything else on this screen: a server that
  // predates gear says nothing, which draws no card.
  const shoes = Array.isArray(profile.gear) ? profile.gear : []
  const week = statsOf(profile.week)
  const lifetime = statsOf(profile.lifetime)
  // A stamp that will not parse is left out rather than printed as an invalid
  // date, so the sentence is dropped whole rather than half built.
  const since =
    typeof profile.created_at === 'string' && !isNaN(Date.parse(profile.created_at))
      ? formatDate(profile.created_at)
      : ''

  // While a popup is up it is the one showing what went wrong, so the card does
  // not say the same sentence a second time behind it. Every step but the one
  // that is no step at all opens a popup of its own.
  const choosing = step.at !== 'none'

  // What is held that could be spent on them, as the satchel's own squares.
  const waters = pileItems(held.filter((one) => one.kind === 'water'))
  const oils = pileItems(held.filter((one) => one.kind === 'oil'))
  const hasWater = waters.length > 0

  // And what is banked that could be spent on them. Manna is the half of this
  // app that is meant to go to other people, so all three of its verbs are on
  // this screen and only the quiet one is not.
  const manna = harvest?.manna ?? 0
  const feedCost = harvest?.feed_cost ?? 0
  const feedCap = harvest?.feed_cap ?? 0
  const basketRows = harvest?.basket ?? []
  // Nothing that is not grown, and nothing already fed as far as it goes: a
  // spend that bought nothing is worse than a button that says no.
  const feedable: Choice[] = plot
    .filter((row) => row.mature === true && (row.fed ?? 0) < feedCap)
    .map((row) => ({
      id: row.id,
      label: plantingName(row),
      detail: plantStateLine(row, friendStage(row)),
    }))
  const fruitChoices: Choice[] = basketRows.map((row) => ({
    id: row.id,
    label: row.label,
    detail: row.provenance,
  }))

  return (
    <>
      {head}

      {selfPreview && (
        <p className="hint preview-note">This is your public profile, as friends see it.</p>
      )}

      {/* The band across the top, exactly as the You screen draws one: their
          plot stands on the soil along its floor and their picture rides up
          over its lower edge. It stays decoration and stays unpressable. These
          are silhouettes two thirds of an inch tall with no names on them and
          no room for any, and spending something out of the satchel should not
          begin with a tap on a picture that small. The plot below is where it
          begins, drawn full size with a name under every plant. */}
      <div className="you-banner">
        <BandGrove
          plants={plot.map((row) => ({
            id: row.id,
            species: row.species,
            name: plantingName(row),
            stage: friendStage(row),
            mature: row.mature === true,
            gilded: row.gilded === true,
          }))}
        />
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
            {level !== null && (
              <p className="you-level">
                Level {level}
                {xp !== null && `, ${convertedValue(xp)} XP`}
              </p>
            )}
            {/* What they wrote about themselves, in the same place under the
                name the You screen puts it. */}
            {bio !== '' && <p className="profile-bio">{bio}</p>}
          </div>
        </div>
      </div>

      <section className="card">
        {since !== '' && <p className="hint">Member since {since}</p>}

        {/* The ladder, drawn the way the You screen draws it: the level as the
            headline and the meter under it. Only the parts the server sent are
            drawn, so a payload without the two figures leaves the meter off
            rather than filling it with nothing. */}
        {level !== null && (
          <p className="level-line">
            <span className="level-tag">Level</span>
            <span className="level-number">{level}</span>
            {intoLevel !== null && levelSpan !== null && (
              <span className="muted">
                {convertedValue(intoLevel)} of {convertedValue(levelSpan)} XP toward level{' '}
                {level + 1}
              </span>
            )}
          </p>
        )}
        {/* A progress element rather than a div with a width on it: the content
            security policy allows no inline styles, and this one reads
            correctly to a screen reader as well. */}
        {intoLevel !== null && levelSpan !== null && levelSpan > 0 && (
          <progress className="xp-meter" value={intoLevel} max={levelSpan}>
            {convertedValue(intoLevel)} of {convertedValue(levelSpan)} XP
          </progress>
        )}

        {/* The same four chips the You screen carries. Raw miles: the distance
            they covered, never the weighted number the ladder is climbed on. */}
        <ProfileCounts
          miles={miles ?? 0}
          activities={Object.values(lifetime).reduce((sum, row) => sum + row.workouts, 0)}
          level={level ?? 0}
          medalsEarned={totalMedalEarns(medals)}
        />

        <SportChips stats={lifetime} units={units} />

        {/* What may be done to the person themselves, which is anointing them
            and ending the friendship. Watering is not here any more: it is done
            to a plant rather than to a person, so it starts from the plant, in
            their plot below. */}
        {!selfPreview && (
        <div className="friend-actions">
          <div className="choice">
            <button
              type="button"
              className="secondary"
              disabled={busy || oils.length === 0}
              onClick={() => {
                setNote('')
                setActionError('')
                setStep({ at: 'oil' })
              }}
            >
              Anoint
            </button>
            {/* The three manna verbs, beside the potion because they are the
                same kind of thing: something of yours, spent on them. Feeding
                boosts their next harvest, raw manna joins their bank, and fruit
                is the top of the ladder. None of them touches a mile of
                anybody's growth. */}
            <button
              type="button"
              className="secondary"
              disabled={busy || manna < feedCost || feedable.length === 0}
              onClick={() => {
                setNote('')
                setActionError('')
                setStep({ at: 'pick-plant' })
              }}
            >
              Feed a plant
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy || manna < 1}
              onClick={() => {
                setNote('')
                setActionError('')
                setAmount(String(Math.min(manna, feedCost)))
                setStep({ at: 'manna' })
              }}
            >
              Send manna
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy || basketRows.length === 0}
              onClick={() => {
                setNote('')
                setActionError('')
                setStep({ at: 'fruit' })
              }}
            >
              Give fruit
            </button>
          </div>

          {oils.length === 0 && (
            <p className="hint">No potions in your inventory. They come out of chests.</p>
          )}
          {manna === 0 && <p className="hint">{NO_MANNA}</p>}

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

          {/* Destructive, on a screen opened casually, so it asks first in the
              dialog below and the question says what is lost. */}
          <button
            type="button"
            className="secondary friend-remove"
            disabled={busy}
            onClick={() => {
              setNote('')
              setActionError('')
              setStep({ at: 'remove' })
            }}
          >
            Remove friend
          </button>
        </div>
        )}
      </section>

      {/* The strip: their last few pictures, newest first, one row across the
          card that scrolls sideways on a phone. A picture is not a link yet;
          the tag under it says which activity it came off and how far and how
          long that one was. */}
      {media.length > 0 && (
        <section className="card">
          <h2 className="label">Recent media</h2>
          <ul className="media-strip">
            {media.map((row) => (
              <li key={row.photo_id} className="media-item">
                <span className="photo-thumb media-photo">
                  <img
                    src={workoutPhotoUrl(row.workout_id, row.photo_id)}
                    alt=""
                    loading="lazy"
                  />
                </span>
                <span className="media-tag">
                  <span className="sport-icon sport-icon-small">
                    <Icon name={activityIcon(row.activity, row.indoor)} />
                  </span>
                  <span className="media-figure">
                    {distanceValue(row.distance_mi, units)} {unitName(units)}
                  </span>
                  <span className="media-figure">{formatClock(row.duration_s)}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* The two cards the You screen ends on, in the same order and in the
          same table. A figure they have hidden is simply not in the payload,
          so the column it would fill is not drawn. */}
      <section className="card">
        <h2 className="label">This week</h2>
        <Stats stats={week} units={units} empty={NOTHING_THIS_WEEK} />
      </section>

      <section className="card">
        <h2 className="label">Lifetime</h2>
        <Stats stats={lifetime} units={units} empty={NOTHING_RECORDED_FRIEND} />
      </section>

      {/* The same card in the same place the You screen keeps it: under the two
          tables. Counts with nobody named in them, which is why this one of the
          game's cards is on a screen the rest of the game stays off. */}
      <section className="card">
        <h2 className="label">Items</h2>
        <ItemTallies tallies={profile.item_tallies} />
      </section>

      {/* What they wear and how far it has gone, read-only. The size and the
          width are here deliberately: reading them is the whole reason a friend
          sees somebody's shoes at all. Drawn only when there is a pair, because
          an empty card on somebody else's screen reads as a feature missing
          rather than as a shelf they have not filled. */}
      {shoes.length > 0 && (
        <section className="card">
          <h2 className="label">
            <span className="sport-icon sport-icon-small">
              <Icon name="shoe" />
            </span>
            Shoes
          </h2>
          <ul className="gear-list">
            {shoes.map((pair) => {
              const subline = gearSubline(pair)
              return (
                <li
                  key={pair.id}
                  className={pair.retired ? 'gear-row gear-retired' : 'gear-row'}
                >
                  <div className="gear-what">
                    <p className="gear-name">
                      {gearName(pair)}
                      {pair.retired && <span className="gear-chip gear-chip-quiet">Retired</span>}
                    </p>
                    {subline !== '' && <p className="hint">{subline}</p>}
                    <p className="hint">{fitLine(pair)}</p>
                  </div>
                  <div className="gear-figure">
                    <span className="count-value">{milesLine(pair.miles)}</span>
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <Medals medals={medals} />

      {/* Their plot, drawn properly rather than counted: what is standing in it,
          how far along each one is, and what it is called. Every plant that can
          still take water is the target that starts a watering, which is why
          this is the only place on the screen watering begins.

          What is not here is deliberate. The server sends a level and how full
          the current one is and nothing else, so there are no miles and no
          dates: a level is how a plant is doing, which is what anybody over the
          fence can see, while the miles behind it are their own record of how
          they spent their weeks. */}
      <section className="card">
        {/* The two counts that used to head this card are in the four tiles
            above now, where the You screen keeps them. Twice on one screen is
            once too many. */}
        <h2 className="label">Grove</h2>

        {plot.length === 0 ? (
          <p className="hint">Nothing planted yet.</p>
        ) : (
          <>
            {!selfPreview && (
              <p className="hint">
                {hasWater ? 'Tap one of their plants to water it.' : NO_WATER}
              </p>
            )}
            <ul className="plot">
              {plot.map((row) => {
                const grown = row.gilded === true
                // Nothing fully grown is offered a drink: it has all the growth
                // there is. Everything else is pressable whether there is water
                // to pour or not, because the popup saying the satchel is empty
                // is a better answer than a tile that quietly does nothing.
                const waterable = !grown && !selfPreview
                const name = plantingName(row)
                const tile = (
                  <>
                    {/* The tab under the square is where the plant is named, so
                        there is no second line saying it again. */}
                    <RarityFrame rarity={row.rarity ?? ''} label={name} className="plant-frame">
                      <PlantArt
                        species={row.species}
                        name={name}
                        stage={friendStage(row)}
                        gilded={row.gilded}
                        className="plant-picture"
                      />
                    </RarityFrame>
                    {/* A progress element rather than a div with a width on it:
                        the content security policy allows no inline styles, and
                        this one reads correctly to a screen reader as well.
                        Nothing rides under it here, because what rides under it
                        on their owner's own screen is their own XP. */}
                    {!grown && (
                      <progress className="xp-meter" value={friendFill(row)} max={1}>
                        {Math.round(friendFill(row) * 100)}% of this level
                      </progress>
                    )}
                    <span className="plant-ready">{plantStateLine(row, friendStage(row))}</span>
                  </>
                )

                return (
                  <li key={row.id} className="plot-slot">
                    {waterable ? (
                      <button
                        type="button"
                        className="plant plant-tap"
                        disabled={busy}
                        aria-label={`Water ${name}`}
                        onClick={() => {
                          setNote('')
                          setActionError('')
                          setStep({ at: 'water', plant: row })
                        }}
                      >
                        {tile}
                      </button>
                    ) : (
                      <div className="plant">{tile}</div>
                    )}
                  </li>
                )
              })}
            </ul>
          </>
        )}
      </section>

      {/* The feed's own cards, so what a friend's activity may show is written
          in one place. Nothing on them opens another profile: the way to this
          screen is the feed and the friends list, not another profile. */}
      <div className="friend-feed">
        <h2 className="label">Recent activities</h2>
        {rows.length === 0 ? (
          <p className="hint">{NOTHING_RECORDED_FRIEND}</p>
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

      {/* Started from one of their plants, so the question at the end of it can
          name that plant rather than asking about water in the abstract. */}
      {step.at === 'water' && (
        <ItemPicker
          title="Water"
          hint={`Water for their ${plantingName(step.plant)}.`}
          stacks={waters}
          onto={`their ${plantingName(step.plant)}`}
          empty={NO_WATER}
          busy={busy}
          error={actionError}
          onUse={(stack) => pour(stack, step.plant.id)}
          onCancel={() => {
            setActionError('')
            setStep({ at: 'none' })
          }}
        />
      )}

      {/* A potion goes onto the person rather than onto anything of theirs, so
          there is no plant in front of it and the question names them. */}
      {step.at === 'oil' && (
        <ItemPicker
          title="Anoint"
          hint={ANOINT_HINT}
          stacks={oils}
          onto={who}
          empty="No potions in your inventory. They come out of chests."
          busy={busy}
          error={actionError}
          onUse={(stack) => anoint(stack)}
          onCancel={() => {
            setActionError('')
            setStep({ at: 'none' })
          }}
        />
      )}

      {/* Which of their plants a feeding is for. Their own screen says how far
          along each one is, and so does this. */}
      {step.at === 'pick-plant' && (
        <Chooser
          title="Feed a plant"
          hint="Pick one of their grown plants."
          choices={feedable}
          empty="Nothing of theirs is grown yet."
          busy={busy}
          error={actionError}
          onChoose={(id) => {
            const plant = plot.find((one) => one.id === id)
            if (plant) setStep({ at: 'feed', plant })
          }}
          onCancel={() => {
            setActionError('')
            setStep({ at: 'none' })
          }}
        />
      )}

      {step.at === 'feed' && (
        <Confirm
          heading={`Feed their ${plantingName(step.plant)}`}
          confirmLabel="Feed"
          cancelLabel="Cancel"
          busy={busy}
          error={actionError}
          onConfirm={() => feed(step.plant)}
          onCancel={() => {
            setActionError('')
            setStep({ at: 'pick-plant' })
          }}
        >
          <p className="hint">{feedHint(feedCost, feedCap)}</p>
        </Confirm>
      )}

      {/* Raw manna. It joins their bank, where it is theirs to spend at once and
          keeps for good. */}
      {step.at === 'manna' && (
        <Confirm
          heading={`Send manna to ${who}`}
          confirmLabel="Send"
          cancelLabel="Cancel"
          busy={busy}
          error={actionError}
          onConfirm={sendManna}
          onCancel={() => {
            setActionError('')
            setStep({ at: 'none' })
          }}
        >
          <p className="hint">
            It goes straight into their manna, and their letter says who sent it.
          </p>
          <label>
            Manna to send
            <input
              type="number"
              min={1}
              max={manna}
              step={1}
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
            />
          </label>
          <p className="hint">{manna.toLocaleString()} manna.</p>
        </Confirm>
      )}

      {/* Something out of your own basket, which carries where it came from.
          On their side it is a keepsake and does nothing at all. */}
      {step.at === 'fruit' && (
        <Chooser
          title={`Give fruit to ${who}`}
          hint="Pick something out of your basket. It keeps its story."
          choices={fruitChoices}
          empty={EMPTY_BASKET}
          busy={busy}
          error={actionError}
          onChoose={(id) => give(id)}
          onCancel={() => {
            setActionError('')
            setStep({ at: 'none' })
          }}
        />
      )}

      {/* Ending a friendship, asked in the same dialog every other destructive
          question in the app is asked in. */}
      {step.at === 'remove' && (
        <Confirm
          heading={`Remove ${who}?`}
          confirmLabel={`Remove ${who}`}
          cancelLabel="Cancel"
          busy={busy}
          error={actionError}
          onConfirm={() => void remove()}
          onCancel={() => {
            setActionError('')
            setStep({ at: 'none' })
          }}
        >
          <p>{REMOVE_WARNING}</p>
        </Confirm>
      )}
    </>
  )
}
