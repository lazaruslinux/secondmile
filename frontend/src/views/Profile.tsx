import { useCallback, useEffect, useState, type ChangeEvent } from 'react'
import {
  ApiError,
  avatarUrl,
  deleteAvatar,
  getProfile,
  listAchievements,
  listChests,
  openChest,
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
import { borderArt } from '../art.ts'
import { formatDate, formatDistance } from '../format.ts'
import { ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import Achievements from './Achievements.tsx'
import Badge from './Badge.tsx'
import CardPlate from './CardPlate.tsx'

// Four, and the server says the same. The slots are drawn whether they are
// filled or not, because an empty slot is the invitation to fill it.
const SLOTS = [0, 1, 2, 3]

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Try again.'
}

// The upload endpoint refuses things for reasons a person can act on, and two
// of them can be answered by the proxy in front of the app rather than by the
// server, so the sentence is written here rather than read off the response.
function uploadErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return 'That picture is too large. The limit is 5 MB.'
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
          <th scope="col">Miles</th>
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

interface Props {
  units: Units
  // Bumped by the app when something outside this view changed what it shows,
  // which so far means chests opened from the recap.
  refreshToken: number
}

export default function Profile({ units, refreshToken }: Props) {
  const [profile, setProfile] = useState<ProfileData | null>(null)
  const [achievements, setAchievements] = useState<Achievement[]>([])
  const [chests, setChests] = useState<Chest[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [avatarBusy, setAvatarBusy] = useState(false)
  const [avatarError, setAvatarError] = useState('')

  const [picking, setPicking] = useState(false)
  const [chosen, setChosen] = useState<string[]>([])
  const [badgeBusy, setBadgeBusy] = useState(false)
  const [badgeError, setBadgeError] = useState('')

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

  async function pickAvatar(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    // Cleared either way, so choosing the same file twice still counts as a
    // change and the picker does not sit there naming a spent upload.
    event.target.value = ''
    if (!file) return
    setAvatarBusy(true)
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
      setAvatarBusy(false)
    }
  }

  async function removeAvatar() {
    setAvatarBusy(true)
    setAvatarError('')
    try {
      await deleteAvatar()
      setProfile((current) =>
        current ? { ...current, has_avatar: false, avatar_version: null } : current,
      )
    } catch (err) {
      setAvatarError(uploadErrorText(err))
    } finally {
      setAvatarBusy(false)
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
  const border = borderArt(profile.border_tier)
  const nextLevel = profile.level + 1

  return (
    <>
      <section className="card">
        <div className="profile-head">
          <div className="avatar-block">
            <div className="avatar-frame">
              {profile.has_avatar ? (
                <img
                  className="avatar-shot"
                  src={avatarUrl(profile.user_id, profile.avatar_version)}
                  alt={`${profile.username}'s picture`}
                />
              ) : (
                <span className="avatar-shot avatar-empty" aria-hidden="true">
                  {profile.username.slice(0, 1).toUpperCase()}
                </span>
              )}
              {border && <img className="avatar-border" src={border} alt="" />}
            </div>

            {SLOTS.map((slot) => {
              const badge = byId.get(profile.displayed_badges[slot] ?? '')
              return (
                <span key={slot} className={`badge-slot badge-slot-${slot + 1}`}>
                  {badge ? (
                    <Badge achievement={badge} standalone />
                  ) : (
                    <span className="badge badge-empty" aria-hidden="true" />
                  )}
                </span>
              )
            })}
          </div>

          <div className="profile-meta">
            <h2 className="profile-name">{profile.username}</h2>
            <p className="hint">Here since {formatDate(profile.created_at)}</p>

            <p className="level-line">
              <span className="level-tag">Level {profile.level}</span>
              <span className="muted">
                {profile.xp_into_level} of {profile.xp_for_next_level} XP toward level{' '}
                {nextLevel}
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
              {profile.xp_into_level} of {profile.xp_for_next_level}
            </progress>

            <ul className="profile-counts">
              <li>
                <span className="count-value">{profile.xp}</span>
                <span className="count-label">XP earned</span>
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
          </div>
        </div>

        <div className="profile-edit">
          <label className="file-field">
            Profile picture
            <input type="file" accept="image/*" disabled={avatarBusy} onChange={pickAvatar} />
          </label>
          <div className="choice">
            {profile.has_avatar && (
              <button
                type="button"
                className="secondary"
                disabled={avatarBusy}
                onClick={() => void removeAvatar()}
              >
                Remove picture
              </button>
            )}
            <button
              type="button"
              className="secondary"
              disabled={earned.length === 0}
              onClick={() => (picking ? setPicking(false) : startPicking())}
            >
              {picking ? 'Close badges' : 'Choose badges'}
            </button>
          </div>
          {avatarError && (
            <p className="error" role="alert">
              {avatarError}
            </p>
          )}
          {earned.length === 0 && (
            <p className="hint">Badges fill the slots once you have earned some.</p>
          )}
        </div>

        {picking && (
          <div className="picker">
            <p className="hint">
              Up to {SLOTS.length}, in the slots around your picture. {chosen.length} chosen.
            </p>
            <ul className="picker-list">
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
                Save badges
              </button>
              <button type="button" className="secondary" onClick={() => setPicking(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>

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
          empty="Nothing recorded yet. Sync your phone or add a workout in the Almanac."
        />
      </section>

      <section className="card">
        <h2>Chests</h2>
        {chests.length === 0 && opened.length === 0 && (
          <p className="hint">
            Nothing waiting. Chests turn up every few Miles and keep until you open them.
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

      <Achievements achievements={achievements} />
    </>
  )
}
