import { useEffect, useState } from 'react'
import { getMe, setUnauthorizedHandler, type Me, type Units } from './api.ts'
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

  useEffect(() => {
    // One place decides that a lost session means the login screen, so no
    // individual request has to handle it.
    setUnauthorizedHandler(() => setMe(null))
    getMe()
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setCheckingSession(false))
  }, [])

  function changeUnits(units: Units) {
    setMe((current) => (current ? { ...current, units } : current))
  }

  if (checkingSession) return <p className="notice">Loading.</p>

  if (!me) {
    return (
      <Login
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
            units={me.units}
            onUnitsChanged={changeUnits}
            onSignedOut={() => setMe(null)}
          />
        )}
      </main>
    </div>
  )
}
