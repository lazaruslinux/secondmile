import { useCallback, useEffect, useState } from 'react'
import {
  avatarUrl,
  errorText,
  getProfile,
  listChests,
  listGrove,
  openChest,
  setDisplayedBadges,
  type ActivityStats,
  type Activity,
  type Chest,
  type Planting,
  type Profile as ProfileData,
  type SatchelItem,
  type Units,
} from '../api.ts'
import {
  convertedValue,
  distanceValue,
  formatDate,
  formatDistance,
  unitName,
} from '../format.ts'
import { plantStage } from '../grove.ts'
import {
  ACTIVITY_ICONS,
  ACTIVITY_NAMES,
  ACTIVITY_ORDER,
  chestName,
  chestTierClass,
  MEDAL_ORDER,
  medalName,
  plantingName,
} from '../labels.ts'
import {
  ageOf,
  chestBar,
  displayNameOf,
  lifetimeMiles,
  medalCountsOf,
  SEEDS_TO_FIND,
} from '../profile.ts'
import AvatarFrame from './AvatarFrame.tsx'
import ChestBar from './ChestBar.tsx'
import ChestItem from './ChestItem.tsx'
import EditProfile from './EditProfile.tsx'
import Fellowship from './Fellowship.tsx'
import Icon from './Icon.tsx'
import MedalNest, { MAX_MEDAL_SLOTS } from './MedalNest.tsx'
import Medals, { MedalMark } from './Medals.tsx'
import PlantArt from './PlantArt.tsx'

function totalsOf(stats: Partial<Record<Activity, ActivityStats>>) {
  let converted = 0
  let kcal = 0
  let workouts = 0
  for (const row of Object.values(stats)) {
    converted += row.converted_mi
    kcal += row.active_kcal
    workouts += row.workouts
  }
  return { converted, kcal, workouts }
}

interface StatsProps {
  stats: Partial<Record<Activity, ActivityStats>>
  units: Units
  empty: string
}

// Distance is what the body covered, in whichever unit the account reads in.
// XP is the game's own number, that distance weighted per activity, and it
// reads the same on every account whatever unit is set.
function Stats({ stats, units, empty }: StatsProps) {
  const rows = ACTIVITY_ORDER.filter((name) => stats[name])
  if (rows.length === 0) return <p className="hint">{empty}</p>
  const totals = totalsOf(stats)

  return (
    <table className="stats">
      <thead>
        <tr>
          <th scope="col">Activity</th>
          <th scope="col">Distance</th>
          {/* The weighted number the game runs on, so a swim and a bike ride
              are worth what they cost rather than what they measure. It is
              called XP everywhere it is shown, because miles on screen mean
              the distance itself. */}
          <th scope="col">XP</th>
          <th scope="col">Workouts</th>
          <th scope="col">Calories</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((name) => {
          const row = stats[name]
          if (!row) return null
          return (
            <tr key={name}>
              <th scope="row">
                <span className="sport-icon sport-icon-small">
                  <Icon name={ACTIVITY_ICONS[name]} />
                </span>
                {ACTIVITY_NAMES[name]}
              </th>
              <td>{formatDistance(row.distance_mi, units)}</td>
              <td>{row.converted_mi.toFixed(1)}</td>
              <td>{row.workouts}</td>
              <td>{Math.round(row.active_kcal)}</td>
            </tr>
          )
        })}
      </tbody>
      <tfoot>
        <tr>
          <th scope="row">Total</th>
          <td />
          <td>{totals.converted.toFixed(1)}</td>
          <td>{totals.workouts}</td>
          <td>{Math.round(totals.kcal)}</td>
        </tr>
      </tfoot>
    </table>
  )
}

interface Cached {
  profile: ProfileData
  chests: Chest[]
  plantings: Planting[]
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
      const [mine, waiting, plot] = await Promise.all([
        getProfile(),
        listChests(),
        listGrove(),
      ])
      setProfile(mine)
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
  }, [load, refreshToken])

  // Whatever is on the screen is what a return to this tab should show, edits
  // made here included, so the cache follows the state rather than the fetch.
  useEffect(() => {
    if (profile) cache.set(userId, { profile, chests, plantings })
  }, [userId, profile, chests, plantings])

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
  const ownedMedals = MEDAL_ORDER.filter((id) => (counts.get(id) ?? 0) > 0)

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">You</h1>
        <div className="head-buttons">
          <button
            type="button"
            className="icon-button"
            aria-label="Edit profile"
            onClick={() => setEditing(true)}
          >
            <Icon name="pencil" />
            <span className="tab-label">Edit</span>
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Settings"
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
          stands on the band's floor at the size it has reached; nothing here is
          pressable, and the plot itself is tended, planted, and watered on the
          Grove screen. */}
      <div className="you-banner">
        <div className="you-band">
          {plantings.length > 0 && (
            <ul className="band-grove">
              {plantings.map((row) => (
                <li
                  key={row.id}
                  className={row.mature ? 'band-plant band-plant-grown' : 'band-plant'}
                >
                  <PlantArt
                    species={row.species}
                    name={plantingName(row)}
                    stage={plantStage(row)}
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

            <ul className="profile-counts">
              <li>
                {/* Raw miles, summed across the four activities: the distance
                    this account actually covered. The weighted total is XP and
                    is named as such wherever it is shown. */}
                <span className="count-value">{lifetimeMiles(profile).toFixed(1)}</span>
                <span className="count-label">Miles</span>
              </li>
              <li>
                <span className="count-value">
                  {profile.grove?.seeds_found ?? 0} / {SEEDS_TO_FIND}
                </span>
                <span className="count-label">Seeds found</span>
              </li>
              <li>
                <span className="count-value">{profile.grove?.plant_levels ?? 0}</span>
                <span className="count-label">Plant levels</span>
              </li>
              <li>
                <span className="count-value">
                  {ownedMedals.length} / {MEDAL_ORDER.length}
                </span>
                <span className="count-label">Medals</span>
              </li>
            </ul>

            {/* Lifetime distance in all four sports, always in the same order
                and always all four, a sport never done reading as zero.
                Nothing is ranked against anyone else here. */}
            <div className="sport-totals">
              <ul className="sport-chips">
                {ACTIVITY_ORDER.map((name) => (
                  <li key={name} className="sport-chip">
                    {/* The sport's own mark rather than the diamond every chip
                        used to wear, so the four chips are told apart at a
                        glance. The word underneath is what names it. */}
                    <span className="sport-icon">
                      <Icon name={ACTIVITY_ICONS[name]} />
                    </span>
                    <span className="chip-value">
                      {distanceValue(profile.lifetime[name]?.distance_mi ?? 0, units)}
                      <span className="chip-unit">{unitName(units)}</span>
                    </span>
                    <span className="label">{ACTIVITY_NAMES[name]}</span>
                  </li>
                ))}
              </ul>
            </div>

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
            <h2>This week</h2>
            <Stats stats={profile.week} units={units} empty="Nothing recorded this week yet." />
          </section>

          <section className="card">
            <h2>Lifetime</h2>
            <Stats
              stats={profile.lifetime}
              units={units}
              empty="Nothing recorded yet. Your next sync fills this in."
            />
          </section>

          <section className="card">
            <h2>Chests</h2>
            {chests.length === 0 && opened.length === 0 && (
              // Not "nothing waiting" any more: a gift can be waiting on this
              // card at the same time, and one word cannot mean both.
              <p className="hint">
                No chests to open. They arrive as you earn XP, and they never expire.
              </p>
            )}
            {/* The whole cycle rather than the one line it replaced: where the
                next chest sits on the ladder, how far into that step the XP has
                got, and which chest a friend's oil is waiting on. Only drawn
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

          {/* The centrepiece: the whole catalogue, family by family, with the
              race ladder first since it is the one every run is measured
              against. */}
          <Medals medals={profile.medals} />
        </div>
      </div>
    </>
  )
}
