import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  getMe,
  getStatus,
  login,
  register,
  resendVerification,
  type Me,
} from '../api.ts'

interface Props {
  notice: string
  onSignedIn: (me: Me) => void
}

export default function Login({ notice, onSignedIn }: Props) {
  const [registering, setRegistering] = useState(false)
  // Null until the server says which mode it is in, so the invite field is not
  // shown and then yanked away half a second later on an open instance.
  const [inviteRequired, setInviteRequired] = useState<boolean | null>(null)
  const [inviteCode, setInviteCode] = useState('')
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
      // there is nothing useful to say here; asking for an invite is the safe
      // guess because an open instance accepts the field and ignores it.
      .catch(() => setInviteRequired(true))
  }, [])

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
        setNote(await register(email, username, password, inviteCode))
        setRegistering(false)
        setPassword('')
      } else {
        await login(username, password)
        // The session cookie is set by now; ask the server who that is rather
        // than assuming anything about the account we just used.
        onSignedIn(await getMe())
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
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
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
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

      <form className="card" onSubmit={submit}>
        <h2>{registering ? 'Create an account' : 'Sign in'}</h2>

        {registering && inviteRequired && (
          <label>
            Invite code
            <input
              value={inviteCode}
              onChange={(event) => setInviteCode(event.target.value)}
              autoComplete="off"
              required
            />
          </label>
        )}

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
            // Mirrors the server's rule so a typo is caught before a round trip.
            pattern="[a-z0-9_.\-]{3,32}"
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
            Usernames are 3 to 32 characters: lowercase letters, numbers, dot, dash,
            underscore. Passwords are at least 10 characters. You will get an email
            with a link to confirm the address before you can sign in.
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

        <button type="button" className="link" onClick={switchMode}>
          {registering
            ? 'I already have an account'
            : inviteRequired === false
              ? 'Create an account'
              : 'I have an invite code'}
        </button>
      </form>
    </div>
  )
}
