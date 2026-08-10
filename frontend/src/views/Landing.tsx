import { useEffect, useState } from 'react'
import { getStatus } from '../api.ts'
import heroImage from '../assets/landing-hero.svg'
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
// Deliberately no screenshots. The app is dark type on black and so is this,
// which means the page cannot go out of date when a screen changes, and there
// is nothing to load from anywhere else. The one picture is the four sports
// drawn in the app's own line, which no redesign can date either.
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
        {/* Placeholder art, swapped by replacing the one file. Decorative
            rather than described: the four sports are named in words a few
            lines below, so an alt text here would only say them twice. */}
        <img className="landing-hero-img" src={heroImage} alt="" />

        {/* The line the name comes from, quoted and cited. The citation is set
            small and faint on purpose: it belongs to the sentence rather than
            competing with it, and somebody who does not recognise the words
            still reads a line about going further than you were asked. */}
        <h1 className="landing-verse">
          &ldquo;And whoever compels you to go one mile, go with him two.&rdquo;
        </h1>
        <p className="landing-cite">Matthew 5:41 NKJV</p>
        <p className="landing-sub">
          Whether it's your first walk around the block or your next marathon, every mile
          counts the same here. Walk, run, bike, or swim.
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

        {/* Said at the top, beside the way in, rather than discovered after
            signing up. Every activity arrives from Apple Health, so a phone
            without that app has no way to put anything in and somebody should
            learn that before they make an account rather than after. */}
        <p className="landing-requires">
          <span className="label">Requires</span>
          Health Auto Export for iOS, from the App Store. Every activity comes from
          Apple Health; there is no other way in.
        </p>
      </section>

      {/* First, because the requirement above raises the question this answers:
          what a person actually has to do, said before anything about what they
          get for it. */}
      <section className="landing-section">
        <p className="label landing-eyebrow">How it works</p>
        <h2>Set it up once, then just move.</h2>
        <p>
          Install Health Auto Export on your iPhone and point it at secondmile. After
          that, every walk, run, ride, and swim you record via Workout on your Apple
          devices flows in on its own. You never log anything by hand, or even open the
          app. Your miles are here waiting whenever you want to look.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Miles earn XP</p>
        <h2>Every mile counts.</h2>
        {/* The two modifiers are stated rather than discovered. Cycling is the
            only one that earns less than its distance, and somebody who finds
            that out by riding trusts the rest of this page less. */}
        <p>
          Every mile earns XP the moment your workout syncs. Swimming counts 4x, cycling
          0.33x.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Private by design</p>
        <h2>A group of friends, not a stadium.</h2>
        {/* What each person shows to whom is not said here on purpose: the
            controls for it are not built yet, and the page does not describe a
            feature the app lacks. */}
        <p>
          secondmile is invite-only. Friends are mutual and invited by name. No follower
          counts, no leaderboards. Nobody here is a stranger, and nothing here is a
          competition.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Rewards</p>
        <h2>Distance is the only currency.</h2>
        <p>
          Cover ground and you earn medals, chests, and a garden that grows from your
          miles. Nothing here can be bought or rushed.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Built for busy people</p>
        <h2>Come back when you feel like it.</h2>
        <p>
          No streaks, no notifications, no reason to open the app just to keep something
          alive. Whatever you earn is waiting in a recap letter whenever you come back.
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
