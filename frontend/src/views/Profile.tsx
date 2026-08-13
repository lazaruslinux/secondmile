import { useCallback, useEffect, useState } from 'react'
import {
  avatarUrl,
  errorText,
  getProfile,
  listBasket,
  listChests,
  listGrove,
  openChest,
  setDisplayedBadges,
  type Chest,
  type Keepsake,
  type Planting,
  type Profile as ProfileData,
  type SatchelItem,
  type Units,
} from '../api.ts'
import { convertedValue, formatDate } from '../format.ts'
import { plantStage } from '../grove.ts'
import {
  chestName,
  chestTierClass,
  medalName,
  NOTHING_RECORDED,
  NOTHING_THIS_WEEK,
  plantingName,
} from '../labels.ts'
import {
  ageOf,
  chestBar,
  displayNameOf,
  lifetimeMiles,
  mannaLine,
  medalCountsOf,
  ownedMedalIds,
  weekSteps,
} from '../profile.ts'
import AvatarFrame from './AvatarFrame.tsx'
import BandGrove from './BandGrove.tsx'
import ChestBar from './ChestBar.tsx'
import ChestItem from './ChestItem.tsx'
import EditProfile from './EditProfile.tsx'
import Fellowship from './Fellowship.tsx'
import Icon from './Icon.tsx'
import ItemTallies from './ItemTallies.tsx'
import MedalNest, { MAX_MEDAL_SLOTS } from './MedalNest.tsx'
import Medals, { MedalMark } from './Medals.tsx'
import ProfileCounts from './ProfileCounts.tsx'
import SportChips from './SportChips.tsx'
import Stats from './Stats.tsx'

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
  // Handed straight down to the friends list, whose rows go to a profile. The
  // app owns which screen is up, so nothing below reaches for it itself.
  onOpenPerson: (userId: number) => void
}

export default function Profile({
  userId,
  units,
  refreshToken,
  onOpenSettings,
  onOpenPerson,
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

  const [picking, setPicking] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const [badgeBusy, setBadgeBusy] = useState(false)
  const [badgeError, setBadgeError] = useState('')

  const [opened, setOpened] = useState<SatchelItem[]>([])
  const [openingChest, setOpeningChest] = useState<number | null>(null)
  const [chestError, setChestError] = useState('')

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
      setPlantings(plot)
      setKeepsakes(given)
      setLoadError('')
    } catch (err) {
      setLoadError(errorText(err))
    } finally {
      setLoading(false)
    }
  }, [])

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
      setOpened((current) => [...current, item])
      setChests((current) => current.filter((chest) => chest.id !== chestId))
      // The satchel and the counts on this screen both moved, so they are read
      // again rather than guessed at.
      void load()
    } catch (err) {
      setChestError(errorText(err))
    } finally {
      setOpeningChest(null)
    }
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

  return (
    <>
      <div className="view-head">
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
              seeds={profile.grove?.seeds_found ?? 0}
              plantLevels={profile.grove?.plant_levels ?? 0}
              medalsOwned={ownedMedals.length}
            />

            <SportChips stats={profile.lifetime} units={units} />

            {/* The pedometer's tally and what the calories have come to, worn
                like the counts above rather than whispered: his call, zeros
                included, because a wallet that hides its zero reads as a
                missing feature. Own screen only, as ever. Neither is a stat:
                the steps are in no miles total and earn nothing, and manna is
                a currency that sits nowhere near the XP.

                The manna line carries both of its states, because only the
                gathered half buys anything and only the gathered half is ever
                at risk. What is waiting is safe until it is gathered, so it is
                said plainly rather than left to be discovered. */}
            <ul className="profile-counts own-tallies">
              <li>
                <span className="count-value">{steps.toLocaleString()}</span>
                <span className="count-label">Steps this week</span>
              </li>
              <li>
                <span className="count-value manna-value">{manna}</span>
                <span className="count-label">Manna</span>
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
                    className="primary"
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

          <Fellowship userId={userId} onOpenPerson={onOpenPerson} />
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

          <section className="card">
            <h2 className="label">Chests</h2>
            {chests.length === 0 && opened.length === 0 && (
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
                      className="secondary"
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
            {opened.length > 0 && (
              <div className="item-reveals">
                {opened.map((item) => (
                  <ChestItem key={item.id} item={item} onPlanted={() => void load()} />
                ))}
              </div>
            )}
          </section>

          {/* What friends have grown and given away, kept forever. It has no
              verb and no number anything spends: somebody went out, earned a
              harvest, and handed it over, and this is the record of that. Drawn
              only when there is something in it, because an empty shelf on a
              screen full of counts reads as a feature that is missing. */}
          {keepsakes.length > 0 && (
            <section className="card">
              <h2 className="label">Basket</h2>
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
