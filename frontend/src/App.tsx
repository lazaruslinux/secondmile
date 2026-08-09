import { useEffect, useState } from 'react'
import {
  ackRecap,
  ApiError,
  getMe,
  getRecap,
  getStatus,
  setUnauthorizedHandler,
  verifyEmail,
  type Me,
  type RecapState,
  type Units,
} from './api.ts'
import { setInstanceTimezone } from './format.ts'
import { recapHasNews } from './recap.ts'
import Login from './views/Login.tsx'
import Grove from './views/Grove.tsx'
import Home from './views/Home.tsx'
import Icon from './views/Icon.tsx'
import Log from './views/Log.tsx'
import Profile from './views/Profile.tsx'
import Recap from './views/Recap.tsx'
import Settings from './views/Settings.tsx'

// A handful of screens still do not earn a router: the whole navigation model is
// which of them is on screen, and the URL has nothing to say about it yet.
// Settings is not a tab; it is reached from the You screen.
type View = 'home' | 'log' | 'grove' | 'you' | 'settings'

const TABS: { id: View; label: string; icon: string }[] = [
  { id: 'home', label: 'Home', icon: 'tab-home' },
  { id: 'log', label: 'Log', icon: 'tab-log' },
  { id: 'grove', label: 'Grove', icon: 'tab-grove' },
  { id: 'you', label: 'You', icon: 'tab-you' },
]

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)
  const [view, setView] = useState<View>('home')
  const [verifyNote, setVerifyNote] = useState('')
  const [recap, setRecap] = useState<RecapState | null>(null)
  // Bumped whenever something outside a view changes what it shows, which so
  // far means chests opened from the recap.
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
      // The instance's zone has to be in hand before the first screen draws,
      // since every time on it is read in that zone rather than the browser's.
      // A status call that fails says nothing useful here: the app falls back
      // to the browser's zone and carries on.
      const [status, user] = await Promise.all([
        getStatus().catch(() => null),
        getMe().catch(() => null),
      ])
      setInstanceTimezone(status?.timezone)
      setMe(user)
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
          setView('home')
        }}
      />
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">secondmile</span>
        {/* The same four sections as the bottom bar. Only one of the two is
            ever on screen: this one from 900px up, the bar below it. */}
        <nav className="topnav" aria-label="Sections">
          {TABS.map((tab) => {
            const current = view === tab.id || (tab.id === 'you' && view === 'settings')
            return (
              <button
                key={tab.id}
                type="button"
                className={current ? 'topnav-item topnav-current' : 'topnav-item'}
                aria-current={current ? 'page' : undefined}
                onClick={() => setView(tab.id)}
              >
                <Icon name={tab.icon} />
                <span className="topnav-label">{tab.label}</span>
              </button>
            )
          })}
        </nav>
      </header>

      {/* Nothing to read is not worth interrupting anyone for, so the letter
          only appears when it says something. */}
      {recap !== null && recapHasNews(recap) && (
        <Recap recap={recap} units={me.units} onDismiss={() => void dismissRecap()} />
      )}

      {/* The view names its own column, which is all the wide layouts need to
          differ: one grid per screen, one width per screen. */}
      <main className={`page page-${view}`}>
        {/* The views keep what they last loaded, per account, so switching tabs
            shows it again at once while a fresh copy is on its way. */}
        {view === 'home' && (
          <Home
            userId={me.id}
            units={me.units}
            refreshToken={refreshToken}
            onOpenLog={() => setView('log')}
            onOpenProfile={() => setView('you')}
          />
        )}
        {view === 'log' && <Log userId={me.id} units={me.units} />}
        {view === 'grove' && <Grove userId={me.id} />}
        {view === 'you' && (
          <Profile
            userId={me.id}
            units={me.units}
            refreshToken={refreshToken}
            onOpenSettings={() => setView('settings')}
          />
        )}
        {view === 'settings' && (
          <Settings
            username={me.username}
            email={me.email}
            emailVerified={me.email_verified}
            pendingEmail={me.pending_email ?? null}
            units={me.units}
            onUnitsChanged={changeUnits}
            onSignedOut={() => setMe(null)}
            onBack={() => setView('you')}
          />
        )}
      </main>

      <nav className="tabbar" aria-label="Sections">
        {TABS.map((tab) => {
          // Settings hangs off the You screen, so the bar keeps pointing there
          // rather than showing nothing as current.
          const current = view === tab.id || (tab.id === 'you' && view === 'settings')
          return (
            <button
              key={tab.id}
              type="button"
              className={current ? 'tab tab-current' : 'tab'}
              aria-current={current ? 'page' : undefined}
              onClick={() => setView(tab.id)}
            >
              <Icon name={tab.icon} />
              <span className="tab-label">{tab.label}</span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
