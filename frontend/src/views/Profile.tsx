import { useCallback, useEffect, useState, type ChangeEvent } from 'react'
import {
  ApiError,
  avatarUrl,
  deleteAvatar,
  errorText,
  getProfile,
  listAchievements,
  listChests,
  openChest,
  setDiamondSports,
  setDisplayedBadges,
  uploadAvatar,
  type Achievement,
  type ActivityStats,
  type Activity,
  type Chest,
  type OpenedChest,
  type Profile as ProfileData,
  type Units,
} from '../api.ts'
import {
  convertedValue,
  distanceValue,
  formatDate,
  formatDistance,
  unitName,
} from '../format.ts'
import {
  ACTIVITY_NAMES,
  ACTIVITY_ORDER,
  RACE_BADGE_ORDER,
  raceBadgeName,
} from '../labels.ts'
import { diamondsOf, MAX_DIAMONDS, raceCountsOf } from '../profile.ts'
import Achievements from './Achievements.tsx'
import AvatarFrame from './AvatarFrame.tsx'
import Badge from './Badge.tsx'
import CardPlate from './CardPlate.tsx'
import Fellowship from './Fellowship.tsx'
import Icon from './Icon.tsx'
import MedalNest from './MedalNest.tsx'
import RaceBadges, { RaceBadgeMark } from './RaceBadges.tsx'

// Four, and the server says the same. The slots are drawn whether they are
// filled or not, because an empty slot is the invitation to fill it.
const SLOTS = [0, 1, 2, 3]

// What the server accepts, checked here as well so an oversized picture is
// answered at once instead of after a whole upload.
const MAX_AVATAR_BYTES = 5 * 1024 * 1024
const TOO_LARGE = 'That picture is too large. The limit is 5 MB.'

// The upload endpoint refuses things for reasons a person can act on, and two
// of them can be answered by the proxy in front of the app rather than by the
// server, so the sentence is written here rather than read off the response.
function uploadErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return TOO_LARGE
    if (err.status === 429) return 'Too many uploads just now. Wait a minute and try again.'
    return err.message
  }
  return 'Something went wrong. Try again.'
}

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
  const [loading, setLoading] = useState(() => !cache.has(userId))
  const [loadError, setLoadError] = useState('')

  // Which avatar call is in flight, so the note can say what is happening.
  const [avatarBusy, setAvatarBusy] = useState<'' | 'upload' | 'remove'>('')
  const [avatarError, setAvatarError] = useState('')

  const [picking, setPicking] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const [badgeBusy, setBadgeBusy] = useState(false)
  const [badgeError, setBadgeError] = useState('')

  const [pickingSports, setPickingSports] = useState(false)
  const [chosenSports, setChosenSports] = useState<Activity[]>([])
  const [sportsBusy, setSportsBusy] = useState(false)
  const [sportsError, setSportsError] = useState('')

  const [opened, setOpened] = useState<OpenedChest[]>([])
  const [openingChest, setOpeningChest] = useState<number | null>(null)
  const [chestError, setChestError] = useState('')

  const load = useCallback(async () => {
    try {
      const [mine, catalog, waiting] = await Promise.all([
        getProfile(),
        listAchievements(),
        listChests(),
      ])
      setProfile(mine)
      setAchievements(catalog)
      setChests(waiting)
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
    if (profile) cache.set(userId, { profile, achievements, chests })
  }, [userId, profile, achievements, chests])

  async function pickAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // Cleared either way, so choosing the same file twice still counts as a
    // change and the picker does not sit there naming a spent upload.
    event.target.value = ''
    if (!file) return
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError(TOO_LARGE)
      return
    }
    setAvatarBusy('upload')
    setAvatarError('')
    try {
      const state = await uploadAvatar(file)
      setProfile((current) =>
        current
          ? { ...current, has_avatar: state.has_avatar, avatar_version: state.avatar_version }
          : current,
      )
    } catch (err) {
      setAvatarError(uploadErrorText(err))
    } finally {
      setAvatarBusy('')
    }
  }

  async function removeAvatar() {
    setAvatarBusy('remove')
    setAvatarError('')
    try {
      await deleteAvatar()
      setProfile((current) =>
        current ? { ...current, has_avatar: false, avatar_version: null } : current,
      )
    } catch (err) {
      setAvatarError(uploadErrorText(err))
    } finally {
      setAvatarBusy('')
    }
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
      const result = await openChest(chestId)
      setOpened((current) => [...current, result])
      setChests((current) => current.filter((chest) => chest.id !== chestId))
      // A plate can finish a set, and finishing a set is a badge, so the
      // counts and the catalogue are read again rather than guessed at.
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

      {/* The band across the top is inert and stays empty on purpose: it is the
          space the garden grows into later. Nothing reads it, nothing presses
          it, and it holds no data of its own. */}
      <div className="you-banner">
        <div className="you-band" />
        <div className="you-ident">
          <div className="avatar-block">
            <AvatarFrame
              username={profile.username}
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
            <h2 className="profile-name">{profile.username}</h2>
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
                  {profile.cards.owned} / {profile.cards.total}
                </span>
                <span className="count-label">Cards</span>
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
              <label className="file-field">
                Profile picture
                <input
                  type="file"
                  accept="image/*"
                  disabled={avatarBusy !== ''}
                  onChange={pickAvatar}
                />
              </label>
              <div className="choice">
                {profile.has_avatar && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={avatarBusy !== ''}
                    onClick={() => void removeAvatar()}
                  >
                    Remove picture
                  </button>
                )}
                <button
                  type="button"
                  className="secondary"
                  disabled={slotChoices === 0}
                  onClick={() => (picking ? setPicking(false) : startPicking())}
                >
                  {picking ? 'Close medals' : 'Choose medals'}
                </button>
              </div>
              {avatarBusy === 'upload' && (
                <p className="hint" role="status">
                  Uploading.
                </p>
              )}
              {avatarError && (
                <p className="error" role="alert">
                  {avatarError}
                </p>
              )}
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
            {chestError && (
              <p className="error" role="alert">
                {chestError}
              </p>
            )}
            {chests.length > 0 && (
              <ul className="chests">
                {chests.map((chest) => (
                  <li key={chest.id}>
                    <span>{chest.set_name} set</span>
                    <button
                      type="button"
                      className="secondary"
                      aria-label={`Open ${chest.set_name} chest`}
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
              <div className="reveal-grid">
                {opened.map((result) => (
                  <CardPlate
                    key={`${result.card.id}-${result.count}`}
                    number={result.card.number}
                    rarity={result.card.rarity}
                    owned
                    cardId={result.card.id}
                    name={result.card.name}
                    flavor={result.card.flavor}
                    count={result.count}
                  />
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
