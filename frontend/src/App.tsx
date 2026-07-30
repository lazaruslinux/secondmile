import { useEffect, useState } from 'react'
import {
  ApiError,
  getMe,
  setUnauthorizedHandler,
  verifyEmail,
  type Me,
  type Units,
} from './api.ts'
import Login from './views/Login.tsx'
import Almanac from './views/Almanac.tsx'
import Settings from './views/Settings.tsx'

// Three screens do not earn a router: the whole navigation model is which of
// them is on screen, and the URL has nothing to say about it yet.
type View = 'almanac' | 'settings'

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)
  const [view, setView] = useState<View>('almanac')
  const [verifyNote, setVerifyNote] = useState('')

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
          setView('almanac')
        }}
      />
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">secondmile</span>
        <nav className="tabs">
          <button
            type="button"
            className={view === 'almanac' ? 'tab tab-current' : 'tab'}
            aria-current={view === 'almanac' ? 'page' : undefined}
            onClick={() => setView('almanac')}
          >
            Almanac
          </button>
          <button
            type="button"
            className={view === 'settings' ? 'tab tab-current' : 'tab'}
            aria-current={view === 'settings' ? 'page' : undefined}
            onClick={() => setView('settings')}
          >
            Settings
          </button>
        </nav>
      </header>

      <main className="page">
        {view === 'almanac' ? (
          <Almanac units={me.units} />
        ) : (
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
