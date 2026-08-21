import { useEffect, useState } from 'react'
import { errorText, getWelcome, type Welcome as WelcomeData } from '../api.ts'
import mastheadShoe from '../assets/masthead-shoe.png'
import Landing from './Landing.tsx'

interface Props {
  // The code out of the address. Everything the invite adds to the page is
  // answered from it, and it is carried into the form so nobody types it.
  code: string
  onJoin: () => void
  onSignIn: () => void
}

// What somebody sees when they open a link they were sent. It is the landing
// page, handed the invite: the same words about the app, with the action block
// naming the person who sent the link instead of offering a sign in.
//
// What lives here rather than there is everything about the code: the ask, the
// wait, and the dead link. A dead link gets one sentence and nothing else.
// Claimed, revoked, run out, never real: the server answers those four
// identically, and so does this.
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
          <span className="landing-brand">
            <img className="masthead-shoe" src={mastheadShoe} alt="" />
            <span className="wordmark">secondmile</span>
          </span>
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

  return (
    <Landing
      onEnter={(registering) => (registering ? onJoin() : onSignIn())}
      invite={{ data: invite, code }}
    />
  )
}
