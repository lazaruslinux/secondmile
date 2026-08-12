import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  errorText,
  getMe,
  getStatus,
  login,
  register,
  resendVerification,
  type Me,
} from '../api.ts'

// The rule the server enforces, written once and said in both the places this
// form states it: the browser's own bubble when the pattern refuses, and the
// hint under the fields. The server's sentence says the same words.
const USERNAME_RULE = '3 to 32 characters: lowercase letters, numbers, dot, dash, underscore.'

interface Props {
  notice: string
  onSignedIn: (me: Me) => void
  // Which of the two the landing page's button promised, so the form opens on
  // the one that was clicked rather than making it the first thing to fix.
  startRegistering?: boolean
  // Carried out of a welcome link's address and submitted without ever being
  // shown: a code is sixty characters nobody reads, and there is no longer a
  // field to type one into. Empty for everybody who arrived any other way.
  inviteCode?: string
  // Back to the landing page. Absent when there is nothing behind this screen,
  // which is the case for a session that expired mid-use.
  onBack?: () => void
}

export default function Login({
  notice,
  onSignedIn,
  startRegistering = false,
  inviteCode: carried = '',
  onBack,
}: Props) {
  const [registering, setRegistering] = useState(startRegistering)
  // Null until the server says which mode it is in, so a way into registering
  // is not offered and then taken back half a second later.
  const [inviteRequired, setInviteRequired] = useState<boolean | null>(null)
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  // Set when a sign in was refused for an unverified account, which is the one
  // failure that has something the person can actually do about it.
  const [unverified, setUnverified] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getStatus()
      .then((status) => setInviteRequired(!status.registration_open))
      // An unreachable status endpoint means the whole app is unreachable, so
      // there is nothing useful to say here; closed is the safe guess, because
      // it offers a sign in rather than a form that would be refused.
      .catch(() => setInviteRequired(true))
  }, [])

  // Registering is reachable two ways and no others: an instance that is open
  // to anybody, or a code carried out of an invite link. A closed instance
  // with no code offers a sign in and nothing else, because there is no longer
  // a code to type and a form that cannot succeed is worse than no form.
  const canRegister = inviteRequired === false || carried !== ''

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNote('')
    setUnverified(false)
    try {
      if (registering) {
        // No session comes back from registering, so this stays on the sign-in
        // screen with the server's answer rather than trying to continue.
        setNote(await register(email, username, password, carried))
        setRegistering(false)
        setPassword('')
      } else {
        await login(username, password)
        // The session cookie is set by now; ask the server who that is rather
        // than assuming anything about the account we just used.
        onSignedIn(await getMe())
      }
    } catch (err) {
      setError(errorText(err))
      if (err instanceof ApiError && err.status === 403) setUnverified(true)
    } finally {
      setBusy(false)
    }
  }

  async function resend() {
    setBusy(true)
    setError('')
    try {
      await resendVerification(email)
      // Worded for what the server actually promises. It answers the same way
      // for an address it has never seen, so claiming a mail was sent would be
      // a claim it never made.
      setNote('If that address is waiting to be verified, a new link is on its way.')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function switchMode() {
    setRegistering(!registering)
    setError('')
    setNote('')
    setUnverified(false)
    setPassword('')
  }

  return (
    <div className="gate">
      <h1 className="wordmark wordmark-large">secondmile</h1>
      <p className="notice">Still being built. Your miles already count.</p>

      {onBack && (
        <button type="button" className="link gate-back" onClick={onBack}>
          Back
        </button>
      )}

      <form className="card" onSubmit={submit}>
        <h2>{registering ? 'Create an account' : 'Sign in'}</h2>

        {registering && (
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              required
            />
          </label>
        )}

        <label>
          Username
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            // A phone capitalises the first letter of a field like this one,
            // and the rule below then refuses what it typed.
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            // Mirrors the server's rule so a typo is caught before a round trip.
            pattern="[a-z0-9_.\-]{3,32}"
            // What the browser's own bubble says when the pattern fails.
            title={USERNAME_RULE}
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={registering ? 'new-password' : 'current-password'}
            minLength={registering ? 10 : undefined}
            required
          />
        </label>

        {registering && (
          <p className="hint">
            Usernames are {USERNAME_RULE} Passwords are at least 10 characters. You
            will get an email with a link to confirm the address before you can sign in.
          </p>
        )}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {(note || notice) && <p className="note">{note || notice}</p>}

        {unverified && (
          <div className="verify">
            <label>
              Email on the account
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
              />
            </label>
            <button
              type="button"
              className="secondary"
              onClick={() => void resend()}
              disabled={busy || !email}
            >
              Send another verification link
            </button>
          </div>
        )}

        <button type="submit" className="primary" disabled={busy}>
          {registering ? 'Create account' : 'Sign in'}
        </button>

        {(registering || canRegister) && (
          <button type="button" className="link" onClick={switchMode}>
            {registering ? 'I already have an account' : 'Create an account'}
          </button>
        )}

        {!registering && (
          <p className="hint">
            Forgot your password? The person who runs this instance can reset it.
          </p>
        )}
      </form>
    </div>
  )
}
