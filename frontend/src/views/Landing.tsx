import { useEffect, useState } from 'react'
import { getStatus } from '../api.ts'
import { ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
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
        {/* The name's meaning, said and not explained, which is how this app
            treats everything it means. No chapter and no verse: it reads as a
            line about effort to anybody who does not already know it. */}
        <h1 className="landing-verse">
          If someone forces you to go one mile, go with him two.
        </h1>
        <p className="landing-sub">Walk, run, bike, swim. The choice is yours.</p>

        <ul className="landing-sports">
          {ACTIVITY_ORDER.map((name) => (
            <li key={name}>
              <span className="diamond diamond-on">
                <Icon name="diamond" />
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
              Accounts here are by invite. If you have a code, you can{' '}
              <button type="button" className="link" onClick={() => onEnter(true)}>
                use it now
              </button>
              .
            </p>
          )}
        </div>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Miles</p>
        <h2>Your miles, counted for you.</h2>
        <p>
          Your watch already knows. secondmile takes the walks, runs, rides and swims out
          of Apple Health and keeps them: the distance, the time, and the line you traced.
          There is nothing to remember to press.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Friends</p>
        <h2>A dinner table, not a stadium.</h2>
        <p>
          Friends are mutual and invited by name. No follower counts, no strangers, no
          leaderboards. Your friends see how far you went and the shape of your route.
          They never see your pace or your heart rate.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Rewards</p>
        <h2>The miles are going somewhere.</h2>
        <p>
          Going the distance earns rewards, and something grows behind the numbers. What
          it is, you find by covering ground. Nothing in it can be bought or hurried.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">Rhythm</p>
        <h2>Made to be lived with.</h2>
        <p>
          No streaks to protect and no notifications asking you to come back. Whatever
          happened while you were away is waiting in a letter the next time you open it.
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
