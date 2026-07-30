import { useState, type FormEvent } from 'react'
import { ApiError, getMe, login, register, type Me } from '../api.ts'

interface Props {
  onSignedIn: (me: Me) => void
}

export default function Login({ onSignedIn }: Props) {
  const [registering, setRegistering] = useState(false)
  const [inviteCode, setInviteCode] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (registering) await register(inviteCode, username, password)
      else await login(username, password)
      // The session cookie is set by now; ask the server who that is rather
      // than assuming anything about the account we just used.
      onSignedIn(await getMe())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Try again.')
    } finally {
      setBusy(false)
    }
  }

  function switchMode() {
    setRegistering(!registering)
    setError('')
    setPassword('')
  }

  return (
    <div className="gate">
      <h1 className="wordmark wordmark-large">secondmile</h1>
      <p className="notice">The Vale is being built. Your miles already count.</p>

      <form className="card" onSubmit={submit}>
        <h2>{registering ? 'Create an account' : 'Sign in'}</h2>

        {registering && (
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
            underscore. Passwords are at least 10 characters.
          </p>
        )}

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="primary" disabled={busy}>
          {registering ? 'Create account' : 'Sign in'}
        </button>

        <button type="button" className="link" onClick={switchMode}>
          {registering ? 'I already have an account' : 'I have an invite code'}
        </button>
      </form>
    </div>
  )
}
