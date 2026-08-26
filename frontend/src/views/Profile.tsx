import { useCallback, useEffect, useRef, useState } from 'react'
import {
  avatarUrl,
  errorText,
  getProfile,
  listBasket,
  listChests,
  listGrove,
  namePet,
  openChest,
  setDisplayedBadges,
  type Chest,
  type Keepsake,
  type OwnPet,
  type Planting,
  type Profile as ProfileData,
  type SatchelItem,
  type Units,
} from '../api.ts'
import { itemArt } from '../art.ts'
import { convertedValue, formatDate } from '../format.ts'
import { plantStage } from '../grove.ts'
import {
  chestName,
  chestTierClass,
  HARVEST_WAITING,
  medalName,
  NOTHING_RECORDED,
  NOTHING_THIS_WEEK,
  plantingName,
} from '../labels.ts'
import {
  ageOf,
  chestBar,
  displayNameOf,
  lifetimeActivities,
  lifetimeMiles,
  mannaLine,
  medalCountsOf,
  ownedMedalIds,
  totalMedalEarns,
  weekSteps,
} from '../profile.ts'
import AvatarFrame from './AvatarFrame.tsx'
import BandGrove from './BandGrove.tsx'
import ChestBar from './ChestBar.tsx'
import ChestReveal from './ChestReveal.tsx'
import Confirm from './Confirm.tsx'
import EditProfile from './EditProfile.tsx'
import GearCard from './GearCard.tsx'
import Icon from './Icon.tsx'
import ItemTallies from './ItemTallies.tsx'
import MedalNest, { MAX_MEDAL_SLOTS } from './MedalNest.tsx'
import Medals, { MedalMark } from './Medals.tsx'
import PetArt from './PetArt.tsx'
import ProfileCounts, { GroveTallies } from './ProfileCounts.tsx'
import SportChips from './SportChips.tsx'
import Stats from './Stats.tsx'

// A mark that accompanies the shelf's heading and never stands in for it.
const BASKET_MARK = itemArt('basket')

// The longest name a pet takes, held to here as well as on the server so the
// box stops rather than the save failing. The same number the Grove holds.
const NAME_LIMIT = 60

interface Cached {
  profile: ProfileData
  chests: Chest[]
  plantings: Planting[]
  keepsakes: Keepsake[]
}

// What this tab last showed, kept by account so a second person signing in on
// the same browser never sees the first one's profile. It lives as long as the
// page does and no longer.
const cache = new Map<number, Cached>()

interface Props {
  userId: number
  units: Units
  // Bumped by the app when something outside this view changed what it shows,
  // which so far means chests opened from the recap.
  refreshToken: number
  onOpenSettings: () => void
  // Opens a profile, which on this screen only ever means your own through the
  // friend lens. The app owns which screen is up, so nothing here reaches for it.
  onOpenPerson: (userId: number) => void
  // How many chests are still unopened, said upward every time this screen
  // learns it. The app draws the mark on the tab and this screen is the only
  // place that opens one, so the mark clears on the same tap that empties the
  // list rather than on the next load.
  onChestsWaiting: (waiting: number) => void
  // The same two things the tab's dot is lit by, handed back down so the top of
  // this screen can name what the dot only points at.
  chestsWaiting: number
  fruitReady: boolean
  onGoGrove: () => void
}

export default function Profile({
  userId,
  units,
  refreshToken,
  onOpenSettings,
  onOpenPerson,
  onChestsWaiting,
  chestsWaiting,
  fruitReady,
  onGoGrove,
}: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [profile, setProfile] = useState<ProfileData | null>(
    () => cache.get(userId)?.profile ?? null,
  )
  const [chests, setChests] = useState<Chest[]>(() => cache.get(userId)?.chests ?? [])
  const [plantings, setPlantings] = useState<Planting[]>(
    () => cache.get(userId)?.plantings ?? [],
  )
  // What friends have given, which is a record and nothing else: nothing here
  // is spent, nothing spoils, and nothing in the game reads it.
  const [keepsakes, setKeepsakes] = useState<Keepsake[]>(
    () => cache.get(userId)?.keepsakes ?? [],
  )
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  const [editing, setEditing] = useState(false)
  // The resident being renamed from the You row, and the box being typed into.
  // The same dialog the Grove opens for a growing pet, acting on the id the
  // own-profile payload carries for exactly this.
  const [naming, setNaming] = useState<OwnPet | null>(null)
  const [typedName, setTypedName] = useState('')
  const [nameBusy, setNameBusy] = useState(false)
  const [nameError, setNameError] = useState('')

  const [picking, setPicking] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const [badgeBusy, setBadgeBusy] = useState(false)
  const [badgeError, setBadgeError] = useState('')

  const [opened, setOpened] = useState<{ tier: string | null; item: SatchelItem } | null>(null)
  const [openingChest, setOpeningChest] = useState<number | null>(null)
  const [chestError, setChestError] = useState('')

  // The chests card sits a long way down the phone column, so the callout at
  // the top walks somebody to it rather than only telling them it is there.
  const chestsCard = useRef<HTMLElement | null>(null)

  const load = useCallback(async () => {
    try {
      const [mine, waiting, plot, given] = await Promise.all([
        getProfile(),
        listChests(),
        listGrove(),
        // The basket is a keepsake shelf rather than part of the profile, so a
        // server that cannot answer for it leaves the shelf empty rather than
        // taking the screen down.
        listBasket().catch(() => []),
      ])
      setProfile(mine)
      setChests(waiting)
      onChestsWaiting(waiting.length)
      setPlantings(plot)
      setKeepsakes(given)
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
    // The app hands down a state setter, which never changes identity, so this
    // stays the stable callback the effect below depends on.
  }, [onChestsWaiting])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  // Whatever is on the screen is what a return to this tab should show, edits
  // made here included, so the cache follows the state rather than the fetch.
  useEffect(() => {
    if (profile) cache.set(userId, { profile, chests, plantings, keepsakes })
  }, [userId, profile, chests, plantings, keepsakes])

  // The picture is uploaded from the edit panel and saved there and then, so
  // this only has to redraw what is already on the server.
  function avatarChanged(hasAvatar: boolean, version: number | null) {
    setProfile((current) =>
      current ? { ...current, has_avatar: hasAvatar, avatar_version: version } : current,
    )
  }

  function startPicking() {
    setChosen(profile ? [...profile.displayed_badges] : [])
    setBadgeError('')
    setPicking(true)
  }

  function toggleBadge(id: string) {
    setChosen((current) =>
      current.includes(id)
        ? current.filter((held) => held !== id)
        : current.length >= MAX_MEDAL_SLOTS
          ? current
          : [...current, id],
    )
  }

  async function saveBadges() {
    setBadgeBusy(true)
    setBadgeError('')
    try {
      setProfile(await setDisplayedBadges(chosen))
      setPicking(false)
    } catch (err) {
      setBadgeError(errorText(err))
    } finally {
      setBadgeBusy(false)
    }
  }

  async function open(chestId: number) {
    setOpeningChest(chestId)
    setChestError('')
    try {
      const item = await openChest(chestId)
      const tier = chests.find((chest) => chest.id === chestId)?.tier ?? null
      setOpened({ tier, item })
      setChests((current) => {
        const left = current.filter((chest) => chest.id !== chestId)
        onChestsWaiting(left.length)
        return left
      })
      // The satchel and the counts on this screen both moved, so they are read
      // again rather than guessed at.
      void load()
    } catch (err) {
      setChestError(errorText(err))
    } finally {
      setOpeningChest(null)
    }
  }

  // Centred rather than aligned to the top: two sticky bars sit over the top of
  // the column and would otherwise cover the heading it lands on.
  function goToChests() {
    chestsCard.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  if (loading) return <p className="notice">Loading.</p>
  if (!profile) {
    return (
      <p className="error" role="alert">
        {loadError || 'Something went wrong. Try again.'}
      </p>
    )
  }

  const nextLevel = profile.level + 1

  // Any medal that has been earned can go in a slot, so the picker and the
  // strip below read the same catalogue and the same counts.
  const counts = medalCountsOf(profile.medals)
  const ladder = chestBar(profile)
  const shownName = displayNameOf(profile)
  const age = ageOf(profile)
  const ownedMedals = ownedMedalIds(profile.medals)
  const bio = profile.bio?.trim() ?? ''
  const steps = weekSteps(profile)
  const manna = mannaLine(profile)
  // The grove's animals, read defensively: a server that predates them says
  // nothing, which draws no row.
  const myPets = Array.isArray(profile.pets) ? profile.pets : []

  // Naming from the row: save, reload the payload the row is drawn from, and
  // only then put the dialog away, so the row never shows a stale word.
  async function rename(pet: OwnPet) {
    setNameBusy(true)
    try {
      await namePet(pet.id, typedName)
      await load()
      setNaming(null)
      setNameError('')
    } catch (err) {
      setNameError(errorText(err))
    } finally {
      setNameBusy(false)
    }
  }

  return (
    <>
      <div className="view-head view-head-sticky">
        <h1 className="view-title">You</h1>
        <div className="head-buttons">
          <button
            type="button"
            className="icon-button"
            aria-label="Edit profile"
            title="Edit profile"
            onClick={() => setEditing(true)}
          >
            <Icon name="pencil" />
            <span className="tab-label">Edit</span>
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Settings"
            title="Settings"
            onClick={onOpenSettings}
          >
            <Icon name="gear" />
            <span className="tab-label">Settings</span>
          </button>
        </div>
      </div>

      {editing && (
        <EditProfile
          profile={profile}
          onAvatarChanged={avatarChanged}
          onSaved={setProfile}
          onClose={() => setEditing(false)}
        />
      )}

      {naming !== null && (
        <Confirm
          heading={`Name your ${naming.species}`}
          confirmLabel="Save"
          cancelLabel="Cancel"
          busy={nameBusy}
          error={nameError}
          onConfirm={() => void rename(naming)}
          onCancel={() => setNaming(null)}
        >
          <label>
            Name
            <input
              type="text"
              value={typedName}
              maxLength={NAME_LIMIT}
              disabled={nameBusy}
              onChange={(event) => setTypedName(event.target.value)}
            />
          </label>
        </Confirm>
      )}

      {/* What the tab's dot is lit by, named at the top of the screen it points
          at. The dot says something is here; this says what, and hands over the
          walk to it. Nothing is opened or gathered from here: the errand is the
          reward, so it is still done in the place it belongs to. */}
      {(chestsWaiting > 0 || fruitReady) && (
        <section className="you-callout" role="status">
          {chestsWaiting > 0 && (
            <div className="you-callout-line">
              <p>
                {chestsWaiting === 1
                  ? 'A chest is waiting.'
                  : `${chestsWaiting} chests are waiting.`}
              </p>
              <button type="button" className="primary" onClick={goToChests}>
                {chestsWaiting === 1 ? 'Open it' : 'Open them'}
              </button>
            </div>
          )}
          {fruitReady && (
            <div className="you-callout-line">
              <p>{HARVEST_WAITING}</p>
              <button type="button" className="primary" onClick={onGoGrove}>
                Go to the grove
              </button>
            </div>
          )}
        </section>
      )}

      {/* The band across the top is where the grove lives. Everything in it
          stands on the strip of soil along the band's floor at the size it has
          reached; nothing here is pressable, and the plot itself is tended,
          planted, and watered on the Grove screen. */}
      <div className="you-banner">
        <BandGrove
          plants={plantings.map((row) => ({
            id: row.id,
            species: row.species,
            name: plantingName(row),
            stage: plantStage(row),
            mature: row.mature,
            gilded: row.gilded,
          }))}
        />
        <div className="you-ident">
          <div className="avatar-block">
            <AvatarFrame
              name={shownName || profile.username}
              src={
                profile.has_avatar ? avatarUrl(profile.user_id, profile.avatar_version) : null
              }
              borderTier={profile.border_tier}
              flourish={profile.flourish}
              labelled
            >
              {/* All three positions, filled or not: an empty one here is the
                  invitation to fill it, and this is the only screen that offers
                  the choice. */}
              <MedalNest ids={profile.displayed_badges} slots={MAX_MEDAL_SLOTS} />
            </AvatarFrame>
          </div>

          <div className="you-ident-text">
            {/* The name they gave, with the name they sign in with under it.
                Where no name was given the username stands on its own, exactly
                as it always has. */}
            <h2 className="profile-name">{shownName || profile.username}</h2>
            {shownName !== '' && <p className="profile-username">{profile.username}</p>}
            <p className="you-level">
              Level {profile.level}, {convertedValue(profile.xp)} XP
            </p>
            {/* What they wrote about themselves, under the name it belongs to.
                The same paragraph in the same place on a friend's profile. */}
            {bio !== '' && <p className="profile-bio">{bio}</p>}
          </div>
        </div>
        <GroveTallies
          seeds={profile.grove?.seeds_found ?? 0}
          plantLevels={profile.grove?.plant_levels ?? 0}
        />
        {/* The animals, at the band's foot with the plot they live in. Drawn
            and named and nothing else, which is exactly what a friend sees of
            them: the fruit and the feeding are on the Grove screen. */}
        {myPets.length > 0 && (
          <ul className="pet-residents">
            {myPets.map((row) => (
              <li key={row.id} className="pet-resident">
                <PetArt
                  species={row.species}
                  name={row.name}
                  stage={row.stage ?? 1}
                  className="pet-resident-picture"
                />
                <span className="pet-resident-name">{row.name}</span>
                {/* The one verb a settled animal keeps, here rather than on
                    the grove floor, and on the owner's row alone: a friend's
                    copy of this markup carries no button. */}
                <button
                  type="button"
                  className="secondary"
                  disabled={nameBusy}
                  onClick={() => {
                    setNameError('')
                    setTypedName(row.name === row.species ? '' : row.name)
                    setNaming(row)
                  }}
                >
                  Name
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Two columns from 900px up and one below it: the picture and its card on
          one side, everything counted on the other. */}
      <div className="you">
        <div className="you-col you-left">
          <section className="card">
            <p className="hint">Member since {formatDate(profile.created_at)}</p>
            {/* Yours to see and nobody else's: neither of these is sent with
                anything a friend can read. */}
            {(age !== null || (profile.gender ?? '') !== '') && (
              <p className="hint">
                {[age === null ? '' : `Age ${age}`, profile.gender ?? '']
                  .filter((part) => part !== '')
                  .join(', ')}
              </p>
            )}

            {/* XP rather than miles on this line, because the ladder is climbed
                on the weighted number and miles on screen only ever mean the
                distance a body covered. The level itself is the headline of the
                card, so it is drawn at the size the recap gives the one number
                it is about, and the word stays small beside it. */}
            <p className="level-line">
              <span className="level-tag">Level</span>
              <span className="level-number">{profile.level}</span>
              <span className="muted">
                {convertedValue(profile.xp_into_level)} of{' '}
                {convertedValue(profile.xp_for_next_level)} XP toward level {nextLevel}
              </span>
            </p>
            {/* A progress element rather than a div with a width on it: the
                content security policy allows no inline styles, and this one
                reads correctly to a screen reader as well. */}
            <progress
              className="xp-meter"
              value={profile.xp_into_level}
              max={profile.xp_for_next_level}
            >
              {convertedValue(profile.xp_into_level)} of{' '}
              {convertedValue(profile.xp_for_next_level)} XP
            </progress>

            <ProfileCounts
              miles={lifetimeMiles(profile)}
              activities={lifetimeActivities(profile)}
              level={profile.level}
              medalsEarned={totalMedalEarns(profile.medals)}
            />

            <SportChips stats={profile.lifetime} units={units} />

            {/* Manna worn as the currency it is, not as a statistic: one gold
                band, own screen only, zero included because a wallet that hides
                its zero reads as a missing feature. */}
            <div className="manna-band">
              <span className="grove-area-label">Manna</span>
              <span className="manna-band-value">{manna}</span>
            </div>

            {/* The pedometer's tally, zeros included. Own screen only; steps
                are in no miles total and earn nothing. */}
            <ul className="profile-counts own-tallies">
              <li>
                <span className="count-value">{steps.toLocaleString()}</span>
                <span className="count-label">Steps this week</span>
              </li>
            </ul>

            <div className="profile-edit">
              <div className="choice">
                <button type="button" className="secondary" onClick={() => setEditing(true)}>
                  Edit profile
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={ownedMedals.length === 0}
                  onClick={() => (picking ? setPicking(false) : startPicking())}
                >
                  {picking ? 'Close medals' : 'Choose medals'}
                </button>
                {/* Yourself through the friend lens, served by the same
                    endpoint a friend reads. What it hides, it hides for real. */}
                <button
                  type="button"
                  className="secondary preview-button"
                  onClick={() => onOpenPerson(userId)}
                >
                  <Icon name="eye" /> View public profile
                </button>
              </div>
              {ownedMedals.length === 0 && (
                <p className="hint">Earn a medal to fill these slots.</p>
              )}
            </div>

            {picking && (
              <div className="picker">
                <p className="hint">
                  Pick up to {MAX_MEDAL_SLOTS} for the slots under your picture. {chosen.length}{' '}
                  chosen.
                </p>
                {/* Only medals already earned, in catalogue order. The server
                    refuses anything else, and the two agreeing is what keeps a
                    slot from being offered and then rejected. */}
                <ul className="picker-list">
                  {ownedMedals.map((id) => {
                    const held = chosen.includes(id)
                    return (
                      <li key={id}>
                        <label className="picker-option">
                          <input
                            type="checkbox"
                            checked={held}
                            disabled={!held && chosen.length >= MAX_MEDAL_SLOTS}
                            onChange={() => toggleBadge(id)}
                          />
                          <MedalMark id={id} earned />
                          <span>
                            {medalName(id)}
                            <span className="muted"> {counts.get(id) ?? 0} earned</span>
                          </span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
                {badgeError && (
                  <p className="error" role="alert">
                    {badgeError}
                  </p>
                )}
                <div className="choice">
                  <button
                    type="button"
                    className="secondary"
                    disabled={badgeBusy}
                    onClick={() => void saveBadges()}
                  >
                    Save medals
                  </button>
                  <button type="button" className="secondary" onClick={() => setPicking(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* Under the tallies. Maintenance rather than game: nothing on this
              card is earned, and nothing on it moves a number anywhere else on
              the screen. */}
          <GearCard
            gear={profile.gear ?? []}
            onChanged={(gear) =>
              setProfile((current) => (current ? { ...current, gear } : current))
            }
          />
        </div>

        <div className="you-col you-right">
          {loadError && (
            <p className="error" role="alert">
              {loadError}
            </p>
          )}

          <section className="card">
            <h2 className="label">This week</h2>
            <Stats stats={profile.week} units={units} empty={NOTHING_THIS_WEEK} />
          </section>

          <section className="card">
            <h2 className="label">Lifetime</h2>
            <Stats stats={profile.lifetime} units={units} empty={NOTHING_RECORDED} />
          </section>

          {/* What the satchel has been spent on and what has come the other
              way. It sits under the two tables and over the chests the items
              came out of, which is the order the things themselves happen in. */}
          <section className="card">
            <h2 className="label">Items</h2>
            <ItemTallies tallies={profile.item_tallies} />
          </section>

          {/* Lit at its edge while there is something on it, so the card the
              callout sends you to reads as the errand rather than as one more
              card in the stack. */}
          <section className={chests.length > 0 ? 'card card-waiting' : 'card'} ref={chestsCard}>
            <h2 className="label">
              Chests
              {chests.length > 0 && (
                <span className="tag tag-wait">{chests.length} waiting</span>
              )}
            </h2>
            {chests.length === 0 && (
              // Not "nothing waiting" any more: a gift can be waiting on this
              // card at the same time, and one word cannot mean both.
              <p className="hint">
                No chests to open. They arrive as you earn XP, and they never expire.
              </p>
            )}
            {/* The whole cycle rather than the one line it replaced: where the
                next chest sits on the ladder, how far into that step the XP has
                got, and which chest a friend's potion is waiting on. Only drawn
                when the server has said which chest is coming. */}
            {ladder && <ChestBar bar={ladder} />}
            {chestError && (
              <p className="error" role="alert">
                {chestError}
              </p>
            )}
            {chests.length > 0 && (
              <ul className="chests">
                {chests.map((chest) => (
                  <li key={chest.id}>
                    {/* Named in the colour of the step it dropped on. */}
                    <span className={chestTierClass(chest.tier)}>{chestName(chest.tier)}</span>
                    <button
                      type="button"
                      className="primary"
                      aria-label={`Open ${chestName(chest.tier)}`}
                      disabled={openingChest === chest.id}
                      onClick={() => void open(chest.id)}
                    >
                      Open
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* What was in it, given the screen for a moment. It used to appear
              as a quiet strip under the list above, which is easy to open a
              chest and never see. Planting from inside reloads the plot the
              same way it always did. */}
          {opened !== null && (
            <ChestReveal
              tier={opened.tier}
              item={opened.item}
              onPlanted={() => void load()}
              onClose={() => setOpened(null)}
            />
          )}

          {/* What friends have grown and given away, kept forever. It has no
              verb and no number anything spends: somebody went out, earned a
              harvest, and handed it over, and this is the record of that. Drawn
              only when there is something in it, because an empty shelf on a
              screen full of counts reads as a feature that is missing. */}
          {keepsakes.length > 0 && (
            <section className="card">
              <h2 className="label">
                {BASKET_MARK && (
                  <img className="word-mark" src={BASKET_MARK} alt="" aria-hidden="true" />
                )}
                Basket
              </h2>
              <ul className="keepsakes">
                {keepsakes.map((row) => (
                  <li key={row.id} className="keepsake">
                    <p className="keepsake-who">From {row.from}</p>
                    <p className="keepsake-what">{row.provenance}</p>
                    <p className="hint">{formatDate(row.received_at)}</p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* The centrepiece: the whole catalogue, family by family, with the
              race ladder first since it is the one every run is measured
              against. */}
          <Medals medals={profile.medals} />
        </div>
      </div>
    </>
  )
}
