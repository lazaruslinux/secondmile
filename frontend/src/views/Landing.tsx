import { useEffect, useState } from 'react'
import { getStatus } from '../api.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import Icon from './Icon.tsx'

interface Props {
  // Straight to the form, already on the tab the button promised.
  onEnter: (registering: boolean) => void
}

// What the app says for itself, to somebody who has never seen it. Every
// section is the truth about a decision made inside the app rather than a
// feature list: the miles arrive on their own, the feed is small on purpose,
// the game is real but unexplained, and nothing here asks to be opened.
//
// Deliberately no screenshots and no artwork. The app is dark type on black
// and so is this, which means the page cannot go out of date when a screen
// changes, and there is nothing to load from anywhere else.
export default function Landing({ onEnter }: Props) {
  // Null until the server says which way it is set, so the page does not offer
  // an account and then take the offer back a moment later.
  const [openRegistration, setOpenRegistration] = useState<boolean | null>(null)

  useEffect(() => {
    getStatus()
      .then((status) => setOpenRegistration(status.registration_open))
      // An unreachable status endpoint means the whole app is unreachable, so
      // there is nothing useful to say. Closed is the safe guess: it offers a
      // sign in, which works on either setting, rather than a form that might
      // refuse everybody who fills it in.
      .catch(() => setOpenRegistration(false))
  }, [])

  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="wordmark">secondmile</span>
        <button type="button" className="link" onClick={() => onEnter(false)}>
          Sign in
        </button>
      </header>

      <section className="landing-hero">
        {/* The line the name comes from, quoted and cited. The citation is set
            small and faint on purpose: it belongs to the sentence rather than
            competing with it, and somebody who does not recognise the words
            still reads a line about going further than you were asked. */}
        <h1 className="landing-verse">
          &ldquo;And whoever compels you to go one mile, go with him two.&rdquo;
        </h1>
        <p className="landing-cite">Matthew 5:41 NKJV</p>
        <p className="landing-sub">
          Walk, run, bike, or swim. Grow a garden with your distance traveled, encourage
          others, earn rewards along the way.
        </p>

        {/* The four sports, each with its own mark. The same marks are used
            wherever an activity is named, so this is the first place somebody
            learns them and every screen after it reads the same way. */}
        <ul className="landing-sports">
          {ACTIVITY_ORDER.map((name) => (
            <li key={name}>
              <span className="sport-icon">
                <Icon name={ACTIVITY_ICONS[name]} />
              </span>
              <span className="label">{ACTIVITY_NAMES[name]}</span>
            </li>
          ))}
        </ul>

        <div className="landing-actions">
          {openRegistration ? (
            <button type="button" className="primary" onClick={() => onEnter(true)}>
              Create an account
            </button>
          ) : (
            <button type="button" className="primary" onClick={() => onEnter(false)}>
              Sign in
            </button>
          )}
          {/* Said only once the server has actually said so, and said plainly:
              somebody with no way in should learn that before they have typed
              an email address into a form that was always going to refuse. */}
          {openRegistration === false && (
            <p className="hint landing-invite">
              Invite-Only. If you have an invite code,{' '}
              <button type="button" className="link" onClick={() => onEnter(true)}>
                enter it here
              </button>
              .
            </p>
          )}
        </div>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Miles earn XP</p>
        <h2>The entire purpose of secondmile is to stay active.</h2>
        {/* The two modifiers are stated rather than discovered. Cycling is the
            only one that earns less than its distance, and somebody who finds
            that out by riding trusts the rest of this page less. */}
        <p>
          Miles on feet, on the bike, or in the water earn XP across the entire platform.
          Every mile earns XP. Swimming modifier = 4x. Cycling modifier = 0.33x.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Private by design</p>
        <h2>A group of friends, not a stadium.</h2>
        <p>
          This is a private, invite-only platform. Friends are mutual and invited by name.
          No follower counts, no strangers, no leaderboards. This is not a competition.
          Your friends see what you decide on.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Rewards</p>
        <h2>Going the distance unlocks milestones.</h2>
        <p>
          What those are, you find by covering ground (or road, or water). Nothing here
          can be bought or artificially boosted.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Built for busy people</p>
        <h2>Set up and never open it again, if you want.</h2>
        <p>
          There are no login streaks, no mini games, and nothing built to make you open
          the app for its own sake. Every synced activity earns what it earns, and it will
          be waiting for you in a recap letter whenever you come back.
        </p>
      </section>

      <footer className="landing-foot">
        {/* No repository link while the repository is private: a link to a page
            nobody can open says less than the licence does on its own. */}
        <p>secondmile. Open source, AGPL-3.0.</p>
      </footer>
    </div>
  )
}
