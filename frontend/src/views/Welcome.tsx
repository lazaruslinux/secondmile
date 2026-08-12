import { useEffect, useState } from 'react'
import heroImage from '../assets/landing-hero.png'
import { errorText, getWelcome, welcomeAvatarUrl, type Welcome as WelcomeData } from '../api.ts'
import { ACTIVITY_ICONS, ACTIVITY_NAMES, ACTIVITY_ORDER } from '../labels.ts'
import AvatarFrame from './AvatarFrame.tsx'
import Icon from './Icon.tsx'

interface Props {
  // The code out of the address. Everything on this page is answered from it,
  // and it is carried into the form so nobody has to type it.
  code: string
  onJoin: () => void
  onSignIn: () => void
}

// What somebody sees when they open a link they were sent. Signed out, so it
// says only what the person who sent it would have said standing next to them:
// who invited you, what this is, and what it needs to work.
//
// A dead link gets one sentence and nothing else. Claimed, revoked, run out,
// never real: the server answers those four identically, and so does this.
export default function Welcome({ code, onJoin, onSignIn }: Props) {
  const [invite, setInvite] = useState<WelcomeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState('')

  useEffect(() => {
    getWelcome(code)
      .then(setInvite)
      .catch((err: unknown) => setFailed(errorText(err)))
      .finally(() => setLoading(false))
  }, [code])

  if (loading) return <p className="notice">Loading.</p>

  if (!invite) {
    return (
      <div className="landing">
        <header className="landing-bar">
          <span className="wordmark">secondmile</span>
          <button type="button" className="link" onClick={onSignIn}>
            Sign in
          </button>
        </header>
        <section className="landing-hero">
          {/* The server's own sentence, which is the same one for every way a
              link can be dead. Nothing else on the page: a link that no longer
              works does not go on to explain itself. */}
          <p className="notice">{failed}</p>
        </section>
      </div>
    )
  }

  const who = invite.inviter_display_name

  return (
    <div className="landing">
      <header className="landing-bar">
        <span className="wordmark">secondmile</span>
        <img className="welcome-hero-mini" src={heroImage} alt="" />
        <button type="button" className="link" onClick={onSignIn}>
          Sign in
        </button>
      </header>

      <section className="landing-hero">
        {/* Their face in its frame, drawn exactly as it is drawn on every
            screen inside the app. The picture rides on the code rather than on
            a session, because nobody reading this page has one. */}
        <div className="welcome-who">
          <AvatarFrame
            name={who}
            src={invite.inviter_has_avatar ? welcomeAvatarUrl(code) : null}
            borderTier={invite.inviter_border_tier ?? 0}
            flourish={invite.inviter_flourish ?? 0}
            labelled
          />
          <p className="welcome-name">{who} invited you to secondmile.</p>
        </div>

        <p className="landing-sub">
          secondmile is a small, invite-only place for staying active and encouraging the
          people you know. Think of a private, self-hosted Strava that earns XP: walk,
          run, bike, or swim, and every synced workout opens chests along the way and
          grows a grove from your miles.
        </p>

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
          <button type="button" className="primary" onClick={onJoin}>
            Create your account
          </button>
          <p className="hint landing-invite">
            Your invite code is already filled in. You will be friends with {who} once you
            are in.
          </p>
        </div>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">How it works</p>
        <h2>Set it up once, then just move.</h2>
        <p>
          One companion app exports the workouts your phone and watch already record and
          sends them to secondmile as JSON. Set it up once and every walk, run, ride, and
          swim arrives on its own. You never log anything by hand, and you never have to
          keep the app open to earn: your miles sync themselves, and whatever they earn is
          waiting whenever you feel like looking.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">What you need</p>
        <h2>An iPhone, for now.</h2>
        <p>
          The exporter is Health Auto Export, from the App Store. Apple Health is the only
          source tested and supported today, so activities need an iPhone or an Apple
          Watch behind them. No iPhone yet? Create your account anyway and look around:
          you will still be friends with {who} from day one, and your miles start arriving
          whenever an iPhone does.
        </p>
      </section>

      <section className="landing-section">
        <p className="label landing-eyebrow">What it is not</p>
        <h2>A group of friends, not a stadium.</h2>
        <p>
          No follower counts, no leaderboards, nothing to keep alive. Friends see each
          other's activities and can say something about them. You choose what your
          friends can see.
        </p>
      </section>

      <footer className="landing-foot">
        <p>secondmile. Open source, AGPL-3.0.</p>
      </footer>
    </div>
  )
}
