import { useCallback, useEffect, useState } from 'react'
import {
  avatarUrl,
  errorText,
  getProfile,
  listAchievements,
  listChests,
  listGrove,
  openChest,
  setDiamondSports,
  setDisplayedBadges,
  type Achievement,
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
  ACTIVITY_NAMES,
  ACTIVITY_ORDER,
  chestName,
  plantingName,
  RACE_BADGE_ORDER,
  raceBadgeName,
} from '../labels.ts'
import {
  ageOf,
  diamondsOf,
  displayNameOf,
  MAX_DIAMONDS,
  nextChestLine,
  raceCountsOf,
} from '../profile.ts'
import Achievements from './Achievements.tsx'
import AvatarFrame from './AvatarFrame.tsx'
import Badge from './Badge.tsx'
import ChestItem from './ChestItem.tsx'
import EditProfile from './EditProfile.tsx'
import Fellowship from './Fellowship.tsx'
import Icon from './Icon.tsx'
import MedalNest from './MedalNest.tsx'
import PlantArt from './PlantArt.tsx'
import RaceBadges, { RaceBadgeMark } from './RaceBadges.tsx'

// Four, and the server says the same. The slots are drawn whether they are
// filled or not, because an empty slot is the invitation to fill it.
const SLOTS = [0, 1, 2, 3]

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
// Miles are the game's unit, weighted per activity, and the same number on
// every account.
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
          {/* The weighted number the game counts in, so a swim and a bike ride
              are worth what they cost rather than what they measure. */}
          <th scope="col">Adjusted</th>
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
              <th scope="row">{ACTIVITY_NAMES[name]}</th>
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
  achievements: Achievement[]
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
}

export default function Profile({ userId, units, refreshToken, onOpenSettings }: Props) {
  // Coming back to the tab draws what was here before and asks the server again
  // underneath, so switching tabs is not a blank screen every time.
  const [profile, setProfile] = useState<ProfileData | null>(
    () => cache.get(userId)?.profile ?? null,
  )
  const [achievements, setAchievements] = useState<Achievement[]>(
    () => cache.get(userId)?.achievements ?? [],
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

  const [pickingSports, setPickingSports] = useState(false)
  const [chosenSports, setChosenSports] = useState<Activity[]>([])
  const [sportsBusy, setSportsBusy] = useState(false)
  const [sportsError, setSportsError] = useState('')

  const [opened, setOpened] = useState<SatchelItem[]>([])
  const [openingChest, setOpeningChest] = useState<number | null>(null)
  const [chestError, setChestError] = useState('')

  const load = useCallback(async () => {
    try {
      const [mine, catalog, waiting, plot] = await Promise.all([
        getProfile(),
        listAchievements(),
        listChests(),
        listGrove(),
      ])
      setProfile(mine)
      setAchievements(catalog)
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
    if (profile) cache.set(userId, { profile, achievements, chests, plantings })
  }, [userId, profile, achievements, chests, plantings])

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
        : current.length >= SLOTS.length
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

  function startPickingSports() {
    setChosenSports(profile ? diamondsOf(profile) : [])
    setSportsError('')
    setPickingSports(true)
  }

  function toggleSport(name: Activity) {
    setChosenSports((current) =>
      current.includes(name)
        ? current.filter((held) => held !== name)
        : current.length >= MAX_DIAMONDS
          ? current
          : [...current, name],
    )
  }

  async function saveSports() {
    setSportsBusy(true)
    setSportsError('')
    try {
      // Choosing nothing is a reset rather than an instruction to show nothing,
      // which is what the server reads a null as.
      setProfile(await setDiamondSports(chosenSports.length === 0 ? null : chosenSports))
      setPickingSports(false)
    } catch (err) {
      setSportsError(errorText(err))
    } finally {
      setSportsBusy(false)
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

  const byId = new Map(achievements.map((row) => [row.id, row]))
  const earned = achievements.filter((row) => row.earned)
  const nextLevel = profile.level + 1
  const diamonds = diamondsOf(profile)

  // Race badges are held in the same four slots as achievements, so the two
  // lists are one list wherever a slot or the picker is concerned.
  const raceCounts = raceCountsOf(profile.race_badges)
  const nextChest = nextChestLine(profile)
  const shownName = displayNameOf(profile)
  const age = ageOf(profile)
  const earnedRaces = RACE_BADGE_ORDER.filter((id) => (raceCounts.get(id) ?? 0) > 0)
  const slotChoices = earned.length + earnedRaces.length

  function slotBadge(id: string) {
    const achievement = byId.get(id)
    if (achievement) return <Badge achievement={achievement} standalone />
    if ((raceCounts.get(id) ?? 0) > 0) return <RaceBadgeMark id={id} earned standalone />
    return <span className="badge badge-empty" aria-hidden="true" />
  }

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
              {/* All four positions, filled or not: an empty one here is the
                  invitation to fill it, and this is the only screen that offers
                  the choice. */}
              <MedalNest
                items={SLOTS.map((slot) => slotBadge(profile.displayed_badges[slot] ?? ''))}
              />
            </AvatarFrame>
          </div>

          <div className="you-ident-text">
            {/* The name they gave, with the name they sign in with under it.
                Where no name was given the username stands on its own, exactly
                as it always has. */}
            <h2 className="profile-name">{shownName || profile.username}</h2>
            {shownName !== '' && <p className="profile-username">{profile.username}</p>}
            <p className="you-level">
              Level {profile.level}, {convertedValue(profile.xp)} mi
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

            {/* Miles rather than points on this screen. They are the same number
                the feed counts as XP; the profile is where the app says what it
                is really about. */}
            <p className="level-line">
              <span className="level-tag">Level {profile.level}</span>
              <span className="muted">
                {convertedValue(profile.xp_into_level)} of{' '}
                {convertedValue(profile.xp_for_next_level)} mi toward level {nextLevel}
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
              {convertedValue(profile.xp_for_next_level)}
            </progress>

            <ul className="profile-counts">
              <li>
                <span className="count-value">{convertedValue(profile.xp)}</span>
                <span className="count-label">Miles</span>
              </li>
              <li>
                <span className="count-value">
                  {profile.grove?.mature ?? 0} / {profile.grove?.planted ?? plantings.length}
                </span>
                <span className="count-label">Grown</span>
              </li>
              <li>
                <span className="count-value">
                  {profile.achievements.earned} / {profile.achievements.total}
                </span>
                <span className="count-label">Achievements</span>
              </li>
            </ul>

            {/* Lifetime distance in the sports this account cares about, up to
                three. Nothing is ranked against anyone else here. */}
            <div className="diamonds">
              {diamonds.length === 0 ? (
                <p className="hint">
                  Sync a workout and your sports show up here with their lifetime distance.
                </p>
              ) : (
                <ul className="diamond-chips">
                  {diamonds.map((name) => (
                    <li key={name} className="diamond-chip">
                      <span className="diamond diamond-on">
                        <Icon name="diamond" />
                      </span>
                      <span className="chip-value">
                        {distanceValue(profile.lifetime[name]?.distance_mi ?? 0, units)}
                        <span className="chip-unit">{unitName(units)}</span>
                      </span>
                      <span className="label">{ACTIVITY_NAMES[name]}</span>
                    </li>
                  ))}
                </ul>
              )}
              <button
                type="button"
                className="secondary"
                onClick={() => (pickingSports ? setPickingSports(false) : startPickingSports())}
              >
                {pickingSports ? 'Close sports' : 'Choose sports'}
              </button>
            </div>

            {pickingSports && (
              <div className="picker">
                <p className="hint">
                  Up to {MAX_DIAMONDS} sports. {chosenSports.length} chosen. Choosing none lets
                  the app pick your busiest three.
                </p>
                <ul className="picker-list">
                  {ACTIVITY_ORDER.map((name) => {
                    const held = chosenSports.includes(name)
                    return (
                      <li key={name}>
                        <label className="picker-option">
                          <input
                            type="checkbox"
                            checked={held}
                            disabled={!held && chosenSports.length >= MAX_DIAMONDS}
                            onChange={() => toggleSport(name)}
                          />
                          <span className="diamond diamond-on">
                            <Icon name="diamond" />
                          </span>
                          <span>{ACTIVITY_NAMES[name]}</span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
                {sportsError && (
                  <p className="error" role="alert">
                    {sportsError}
                  </p>
                )}
                <div className="choice">
                  <button
                    type="button"
                    className="primary"
                    disabled={sportsBusy}
                    onClick={() => void saveSports()}
                  >
                    Save sports
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setPickingSports(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="profile-edit">
              <div className="choice">
                <button type="button" className="secondary" onClick={() => setEditing(true)}>
                  Edit profile
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={slotChoices === 0}
                  onClick={() => (picking ? setPicking(false) : startPicking())}
                >
                  {picking ? 'Close medals' : 'Choose medals'}
                </button>
              </div>
              {slotChoices === 0 && (
                <p className="hint">Medals fill the slots once you have earned some.</p>
              )}
            </div>

            {picking && (
              <div className="picker">
                <p className="hint">
                  Up to {SLOTS.length}, in the slots under your picture. {chosen.length} chosen.
                </p>
                <ul className="picker-list">
                  {earnedRaces.map((id) => {
                    const held = chosen.includes(id)
                    return (
                      <li key={id}>
                        <label className="picker-option">
                          <input
                            type="checkbox"
                            checked={held}
                            disabled={!held && chosen.length >= SLOTS.length}
                            onChange={() => toggleBadge(id)}
                          />
                          <RaceBadgeMark id={id} earned />
                          <span>
                            {raceBadgeName(id)}
                            <span className="muted"> {raceCounts.get(id) ?? 0} earned</span>
                          </span>
                        </label>
                      </li>
                    )
                  })}
                  {earned.map((row) => {
                    const held = chosen.includes(row.id)
                    return (
                      <li key={row.id}>
                        <label className="picker-option">
                          <input
                            type="checkbox"
                            checked={held}
                            disabled={!held && chosen.length >= SLOTS.length}
                            onChange={() => toggleBadge(row.id)}
                          />
                          <Badge achievement={row} />
                          <span>{row.name}</span>
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

          <Fellowship userId={userId} />
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
              empty="Nothing recorded yet. Sync your phone or add a workout in Log."
            />
          </section>

          <section className="card">
            <h2>Chests</h2>
            {chests.length === 0 && opened.length === 0 && (
              <p className="hint">
                Nothing waiting. Chests arrive as you cover miles, and they never expire.
              </p>
            )}
            {/* Only drawn when the server says how far off the next one is. */}
            {nextChest !== '' && <p className="hint">{nextChest}</p>}
            {chestError && (
              <p className="error" role="alert">
                {chestError}
              </p>
            )}
            {chests.length > 0 && (
              <ul className="chests">
                {chests.map((chest) => (
                  <li key={chest.id}>
                    <span>{chestName(chest.tier)}</span>
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

          {/* The centrepiece: the race ladder sits above the rest of the
              badges, since it is the one every run is measured against. */}
          <RaceBadges badges={profile.race_badges} />

          <Achievements achievements={achievements} />
        </div>
      </div>
    </>
  )
}
