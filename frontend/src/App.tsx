import { useEffect, useState } from 'react'
import {
  ackRecap,
  ApiError,
  getMe,
  getRecap,
  getStatus,
  setUnauthorizedHandler,
  verifyEmail,
  type FeedItem,
  type Gear,
  type HiddenField,
  type Me,
  type RecapState,
  type Units,
} from './api.ts'
import { ALPHA, ALPHA_LINE } from './alpha.ts'
import { setInstanceTimezone } from './format.ts'
import { recapHasNews } from './recap.ts'
import ActivityView from './views/Activity.tsx'
import AlphaNotice from './views/AlphaNotice.tsx'
import Landing from './views/Landing.tsx'
import Login from './views/Login.tsx'
import FriendProfile from './views/FriendProfile.tsx'
import Friends from './views/Friends.tsx'
import Grove from './views/Grove.tsx'
import Home from './views/Home.tsx'
import Icon from './views/Icon.tsx'
import Profile from './views/Profile.tsx'
import Recap from './views/Recap.tsx'
import Settings from './views/Settings.tsx'
import SetupGuide from './views/SetupGuide.tsx'
import Welcome from './views/Welcome.tsx'
import WorkoutDetails from './views/WorkoutDetails.tsx'

// The one address this app reads: /welcome/<code>, where a link somebody was
// sent lands. Everything else is still which screen is on rather than where
// the browser thinks it is, so this is read once rather than routed.
function welcomeCode(): string {
  const found = /^\/welcome\/([^/]+)\/?$/.exec(window.location.pathname)
  return found ? decodeURIComponent(found[1]) : ''
}

// A handful of screens still do not earn a router: the whole navigation model is
// which of them is on screen, and the URL has nothing to say about it yet.
// Settings is not a tab; it is reached from the You screen. Neither is a
// friend's profile, which is reached from the feed and from the Friends screen,
// nor the phone setup guide, which is reached from Settings, nor the screen
// behind a workout card, which is reached from wherever that card was drawn.
type View =
  | 'home'
  | 'activity'
  | 'grove'
  | 'friends'
  | 'you'
  | 'settings'
  | 'guide'
  | 'friend'
  | 'workout'

const TABS: { id: View; label: string; icon: string }[] = [
  { id: 'home', label: 'Home', icon: 'tab-home' },
  // The mark keeps its file name: the artwork register addresses pictures by
  // name, and only the word under this one changed.
  { id: 'activity', label: 'Activity', icon: 'tab-log' },
  { id: 'grove', label: 'Grove', icon: 'tab-grove' },
  { id: 'friends', label: 'Friends', icon: 'tab-friends' },
  { id: 'you', label: 'You', icon: 'tab-you' },
]

export default function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [checkingSession, setCheckingSession] = useState(true)
  // Which of the two signed-out screens is on. Null is the landing page, and a
  // string is the form, opened on the tab whichever button asked for.
  const [gate, setGate] = useState<'signin' | 'register' | null>(null)
  // The code the browser arrived with, read once: the address is cleaned up
  // after signing in, and the code has to outlive that.
  const [invite] = useState(welcomeCode)
  const [view, setView] = useState<View>('home')
  // Whose profile is open and which screen it was opened from, so Back goes
  // back to the feed or to the Friends screen rather than always to one of them.
  const [friend, setFriend] = useState<{ id: number; from: View } | null>(null)
  // Which workout's details are open and which screen it was opened from, the
  // same way a profile is held. The row itself rather than an id: the card it
  // was opened from already has one, and there is no endpoint that serves a
  // single feed row on its own. The shoes ride along for the same reason: the
  // screen that opened the card is holding the list already.
  const [opened, setOpened] = useState<{ item: FeedItem; gear: Gear[]; from: View } | null>(
    null,
  )
  const [verifyNote, setVerifyNote] = useState('')
  // Whether the chip's notice is up. Nothing remembers it: the chip stays in
  // the bar for as long as the alpha does, and reading it is never owed twice.
  const [alphaOpen, setAlphaOpen] = useState(false)
  const [recap, setRecap] = useState<RecapState | null>(null)
  // Bumped whenever something outside a view changes what it shows, which so
  // far means chests opened from the recap.
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    // One place decides that a lost session means the login screen, so no
    // individual request has to handle it.
    setUnauthorizedHandler(() =>
      setMe((current) => {
        // Only a session that was actually in use goes to the form. Every
        // signed-out visitor's first request is a 401 from the boot-time check
        // below, and sending those to the form would mean nobody ever saw the
        // landing page. Read through the updater rather than the closure,
        // which was captured before anybody signed in.
        if (current) setGate('signin')
        return null
      }),
    )

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

  // Everything that happened while the app was shut, shown once. The letter is
  // never required reading; nothing is awarded by viewing it.
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

  function changeHidden(hidden: HiddenField[]) {
    setMe((current) => (current ? { ...current, hidden_from_friends: hidden } : current))
  }

  function changeNotify(on: boolean) {
    setMe((current) => (current ? { ...current, notify_workout_arrival: on } : current))
  }

  // Every screen scrolls the one document, so a new screen would otherwise open
  // at whatever depth the last one was left at. A screen starts at its top.
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [view])

  // A tap on the tab already showing changes nothing for the effect above to
  // react to, and it still means take me back to the top of this.
  function showTab(next: View) {
    setView(next)
    window.scrollTo(0, 0)
  }

  function openFriend(id: number) {
    setFriend({ id, from: view })
    setView('friend')
  }

  // The account's own shoes come with the row, from whichever screen was
  // holding them. A friend's profile hands over none, and a friend's row
  // carries no pair to name anyway, so its details screen draws no shoe line.
  function openWorkout(item: FeedItem, gear: Gear[] = []) {
    setOpened({ item, gear, from: view })
    setView('workout')
  }

  // Coming off a friend's screen when the friendship has just ended. The feed
  // and the friends list both held that person, so both are asked again on the
  // way back rather than drawing somebody who is no longer there.
  function friendRemoved(from: View) {
    setRefreshToken((count) => count + 1)
    setFriend(null)
    setView(from)
  }

  // Which of the five sections the navigation points at. Four screens hang off
  // a tab rather than being one: Settings and the setup guide behind it sit
  // under You, and a friend's profile and a workout's details sit under
  // whichever screen opened them, so none of them leaves the bar blank.
  //
  // Applied twice, because a workout opened from a friend's profile is under
  // whatever that profile was opened from. One more hop than that is not
  // reachable: nothing on the details screen opens anything.
  function sectionOf(which: View): View {
    if (which === 'settings' || which === 'guide') return 'you'
    if (which === 'friend') return friend?.from ?? 'home'
    return which
  }

  const section: View =
    view === 'workout' ? sectionOf(opened?.from ?? 'home') : sectionOf(view)

  if (checkingSession) return <p className="notice">Loading.</p>

  if (!me) {
    // A verification link goes straight to the form. Its note is about an
    // account that already exists, so showing that person what the app is
    // would be answering a question they did not ask.
    if (gate === null && verifyNote === '') {
      // Somebody who arrived on a link gets the page about the link rather
      // than the page about the app: it names who sent it, which is the whole
      // reason they opened it.
      if (invite !== '') {
        return (
          <Welcome
            code={invite}
            onJoin={() => setGate('register')}
            onSignIn={() => setGate('signin')}
          />
        )
      }
      return <Landing onEnter={(registering) => setGate(registering ? 'register' : 'signin')} />
    }
    return (
      <Login
        notice={verifyNote}
        startRegistering={gate === 'register'}
        // Carried out of the address, so nobody retypes sixty characters they
        // never saw. Empty for everybody who did not arrive on a link.
        inviteCode={invite}
        // No way back from a verification link, because there is nothing
        // behind it: that address was opened from an email, not from the page.
        onBack={verifyNote === '' ? () => setGate(null) : undefined}
        onSignedIn={(user) => {
          setMe(user)
          setGate(null)
          setView('home')
          // The code is spent by now and the address is only confusing on a
          // reload, so what is left is the ordinary app. The same tidy-up the
          // verification link gets.
          if (invite !== '') window.history.replaceState(null, '', '/')
        }}
      />
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        {/* The name and the chip are one thing on the left, so the bar still
            has two children to push apart and the sections stay on the right. */}
        <span className="topbar-brand">
          <span className="wordmark">secondmile</span>
          {ALPHA && (
            <button
              type="button"
              className="alpha-chip"
              aria-haspopup="dialog"
              onClick={() => setAlphaOpen(true)}
            >
              alpha
            </button>
          )}
        </span>
        {/* The same five sections as the bottom bar. Only one of the two is
            ever on screen: this one from 900px up, the bar below it. */}
        <nav className="topnav" aria-label="Sections">
          {TABS.map((tab) => {
            const current = section === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                className={current ? 'topnav-item topnav-current' : 'topnav-item'}
                aria-current={current ? 'page' : undefined}
                onClick={() => showTab(tab.id)}
              >
                <Icon name={tab.icon} />
                <span className="topnav-label">{tab.label}</span>
              </button>
            )
          })}
        </nav>
      </header>

      {alphaOpen && <AlphaNotice onClose={() => setAlphaOpen(false)} />}

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
            onOpenActivity={() => setView('activity')}
            onOpenGrove={() => setView('grove')}
            onOpenProfile={() => setView('you')}
            onOpenPerson={openFriend}
            onOpenWorkout={openWorkout}
          />
        )}
        {view === 'activity' && (
          <ActivityView
            userId={me.id}
            units={me.units}
            onOpenPerson={openFriend}
            onOpenWorkout={openWorkout}
          />
        )}
        {view === 'grove' && <Grove userId={me.id} />}
        {view === 'friends' && <Friends userId={me.id} onOpenPerson={openFriend} />}
        {view === 'you' && (
          <Profile
            userId={me.id}
            units={me.units}
            refreshToken={refreshToken}
            onOpenSettings={() => setView('settings')}
            onOpenPerson={openFriend}
          />
        )}
        {/* Keyed by the person, so opening a second profile is a fresh screen
            rather than one still holding the first one's answers. */}
        {view === 'friend' && friend !== null && (
          <FriendProfile
            key={friend.id}
            userId={friend.id}
            units={me.units}
            onBack={() => setView(friend.from)}
            onRemoved={() => friendRemoved(friend.from)}
            onOpenWorkout={openWorkout}
            selfPreview={friend.id === me.id}
          />
        )}
        {/* Keyed by the workout, for the same reason a profile is: opening a
            second one is a fresh screen rather than one still holding the
            first one's minutes. */}
        {view === 'workout' && opened !== null && (
          <WorkoutDetails
            key={opened.item.workout_id}
            item={opened.item}
            gear={opened.gear}
            units={me.units}
            onBack={() => setView(opened.from)}
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
            hidden={me.hidden_from_friends ?? []}
            onHiddenChanged={changeHidden}
            notifyArrival={me.notify_workout_arrival ?? true}
            onNotifyChanged={changeNotify}
            onSignedOut={() => setMe(null)}
            onOpenGuide={() => setView('guide')}
            onBack={() => setView('you')}
          />
        )}
        {/* Back goes to Settings rather than to You: the card with the token on
            it is what somebody is reading this alongside. */}
        {view === 'guide' && <SetupGuide onBack={() => setView('settings')} />}

        {/* The end of every page: the alpha line beside the line that names
            the licence. The licence stays when the alpha ends. */}
        <footer className="page-foot">
          {ALPHA && <p className="page-foot-alpha">{ALPHA_LINE}</p>}
          <p>secondmile. Open source, AGPL-3.0.</p>
        </footer>
      </main>

      <nav className="tabbar" aria-label="Sections">
        {TABS.map((tab) => {
          const current = section === tab.id
          return (
            <button
              key={tab.id}
              type="button"
              className={current ? 'tab tab-current' : 'tab'}
              aria-current={current ? 'page' : undefined}
              onClick={() => showTab(tab.id)}
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
