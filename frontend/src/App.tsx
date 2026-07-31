import { useEffect, useState } from 'react'
import {
  ackRecap,
  ApiError,
  getMe,
  getRecap,
  setUnauthorizedHandler,
  verifyEmail,
  type Me,
  type RecapState,
  type Units,
} from './api.ts'
import Login from './views/Login.tsx'
import Profile from './views/Profile.tsx'
import Album from './views/Album.tsx'
import Almanac from './views/Almanac.tsx'
import Recap from './views/Recap.tsx'
import Settings from './views/Settings.tsx'

// Four screens still do not earn a router: the whole navigation model is which
// of them is on screen, and the URL has nothing to say about it yet.
type View = 'profile' | 'album' | 'almanac' | 'settings'

const TABS: { id: View; label: string }[] = [
  { id: 'profile', label: 'Profile' },
  { id: 'album', label: 'Album' },
  { id: 'almanac', label: 'Almanac' },
  { id: 'settings', label: 'Settings' },
]

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)
  const [view, setView] = useState<View>('profile')
  const [verifyNote, setVerifyNote] = useState('')
  const [recap, setRecap] = useState<RecapState | null>(null)
  // Bumped whenever something outside the profile changes what it shows, which
  // so far means chests opened from the recap.
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    // One place decides that a lost session means the login screen, so no
    // individual request has to handle it.
    setUnauthorizedHandler(() => setMe(null))

    async function boot() {
      // The verification mail links here with the token in the URL fragment,
      // which the browser never sends to any server, so it cannot end up in an
      // access log. There is no route for it: the token is read, spent, and
      // taken back out of the address bar, and what is left is the ordinary app.
      const token = new URLSearchParams(window.location.hash.slice(1)).get('token')
      if (token) {
        try {
          await verifyEmail(token)
          setVerifyNote('Email verified. Sign in below.')
        } catch (err) {
          setVerifyNote(
            err instanceof ApiError ? err.message : 'That link did not work. Ask for a new one.',
          )
        }
        // Cleaned even when the call failed. A working link left in the bar is
        // a credential sitting in history, in a bookmark, and in the tab title
        // someone screenshots, and a spent one is only confusing on reload.
        window.history.replaceState(null, '', window.location.pathname)
      }
      try {
        setMe(await getMe())
      } catch {
        setMe(null)
      }
      setCheckingSession(false)
    }

    void boot()
  }, [])

  // Everything that happened while the app was shut, shown once. Opening the
  // app is never required, so this is a letter waiting rather than a reward.
  const userId = me?.id
  useEffect(() => {
    if (userId === undefined) {
      setRecap(null)
      return
    }
    getRecap()
      .then(setRecap)
      .catch(() => setRecap(null))
  }, [userId])

  async function dismissRecap() {
    setRecap(null)
    setRefreshToken((count) => count + 1)
    try {
      await ackRecap()
    } catch {
      // Nothing useful to say: an unacked recap simply comes back next time.
    }
  }

  function changeUnits(units: Units) {
    setMe((current) => (current ? { ...current, units } : current))
  }

  if (checkingSession) return <p className="notice">Loading.</p>

  if (!me) {
    return (
      <Login
        notice={verifyNote}
        onSignedIn={(user) => {
          setMe(user)
          setView('profile')
        }}
      />
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">secondmile</span>
        <nav className="tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={view === tab.id ? 'tab tab-current' : 'tab'}
              aria-current={view === tab.id ? 'page' : undefined}
              onClick={() => setView(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      {/* Nothing to read is not worth interrupting anyone for, so the letter
          only appears when it says something. */}
      {recap !== null &&
        (recap.chests.length > 0 || recap.achievements.length > 0 || recap.miles > 0) && (
          <Recap recap={recap} onDismiss={() => void dismissRecap()} />
        )}

      <main className="page">
        {view === 'profile' && <Profile units={me.units} refreshToken={refreshToken} />}
        {view === 'album' && <Album />}
        {view === 'almanac' && <Almanac units={me.units} />}
        {view === 'settings' && (
          <Settings
            username={me.username}
            email={me.email}
            emailVerified={me.email_verified}
            units={me.units}
            onUnitsChanged={changeUnits}
            onSignedOut={() => setMe(null)}
          />
        )}
      </main>
    </div>
  )
}
