import { useEffect, useState, type FormEvent } from 'react'
import {
  changePassword,
  errorText,
  getIngestTokenStatus,
  logout,
  rotateIngestToken,
  setUnits,
  type IngestTokenStatus,
  type Units,
} from '../api.ts'

interface Props {
  username: string
  email: string | null
  emailVerified: boolean
  units: Units
  onUnitsChanged: (units: Units) => void
  onSignedOut: () => void
}

export default function Settings({
  username,
  email,
  emailVerified,
  units,
  onUnitsChanged,
  onSignedOut,
}: Props) {
  const [tokenStatus, setTokenStatus] = useState<IngestTokenStatus | null>(null)
  // Held in state only until the page is left: the server stores a hash, so
  // this string exists nowhere else once it is gone.
  const [freshToken, setFreshToken] = useState('')
  const [tokenError, setTokenError] = useState('')
  const [rotating, setRotating] = useState(false)
  // Rotating breaks the phone until the new token is pasted, so the button asks
  // once before it does it.
  const [confirmingRotate, setConfirmingRotate] = useState(false)
  // Empty until the Copy button is used, then which way it went.
  const [copyState, setCopyState] = useState<'' | 'copied' | 'failed'>('')

  const [unitsError, setUnitsError] = useState('')
  const [savingUnits, setSavingUnits] = useState(false)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [passwordNote, setPasswordNote] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)

  useEffect(() => {
    getIngestTokenStatus()
      .then(setTokenStatus)
      .catch((err: unknown) => setTokenError(errorText(err)))
  }, [])

  // The first token has nothing to break, so only a replacement is confirmed.
  function askRotate() {
    if (tokenStatus?.exists) setConfirmingRotate(true)
    else void rotate()
  }

  async function rotate() {
    setRotating(true)
    setTokenError('')
    setCopyState('')
    try {
      setFreshToken(await rotateIngestToken())
      setTokenStatus(await getIngestTokenStatus())
      setConfirmingRotate(false)
    } catch (err) {
      setTokenError(errorText(err))
    } finally {
      setRotating(false)
    }
  }

  async function copyToken() {
    try {
      await navigator.clipboard.writeText(freshToken)
      setCopyState('copied')
    } catch {
      // No clipboard on an insecure origin, or the browser refused. Nothing is
      // lost: the token is on the screen and can be selected by hand.
      setCopyState('failed')
    }
  }

  async function chooseUnits(next: Units) {
    if (next === units) return
    setSavingUnits(true)
    setUnitsError('')
    try {
      onUnitsChanged(await setUnits(next))
    } catch (err) {
      setUnitsError(errorText(err))
    } finally {
      setSavingUnits(false)
    }
  }

  async function submitPassword(event: FormEvent) {
    event.preventDefault()
    setSavingPassword(true)
    setPasswordError('')
    setPasswordNote('')
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setPasswordNote('Password changed. Every other signed-in device was signed out.')
    } catch (err) {
      setPasswordError(errorText(err))
    } finally {
      setSavingPassword(false)
    }
  }

  async function signOut() {
    try {
      await logout()
    } catch {
      // A failed logout call still means this browser is done with the
      // session, and there is nothing useful to tell someone who is leaving.
    } finally {
      onSignedOut()
    }
  }

  return (
    <>
      <section className="card">
        <h2>Sync token</h2>
        <p className="hint">
          The bearer token your phone sends with each workout export. Rotating it
          replaces the old one immediately.
        </p>

        {tokenStatus && (
          <p className="note">
            {tokenStatus.exists
              ? `A token exists${
                  tokenStatus.rotated_at
                    ? `, last rotated ${new Date(tokenStatus.rotated_at).toLocaleDateString()}`
                    : ''
                }.`
              : 'No token yet.'}
          </p>
        )}

        {freshToken && (
          <div className="token">
            <p className="warning">
              This is the only time this token is shown. Copy it into your export app
              now. It will not be shown again.
            </p>
            <code>{freshToken}</code>
            <button type="button" className="secondary" onClick={() => void copyToken()}>
              Copy
            </button>
            {copyState === 'copied' && (
              <p className="note note-success" role="status">
                Copied.
              </p>
            )}
            {copyState === 'failed' && (
              <p className="note" role="status">
                This browser would not copy it. Select the token and copy it by hand.
              </p>
            )}
          </div>
        )}

        {tokenError && (
          <p className="error" role="alert">
            {tokenError}
          </p>
        )}

        {confirmingRotate ? (
          <>
            <p className="hint">
              Your phone stops syncing until the new token is pasted into your export
              app.
            </p>
            <div className="choice">
              <button
                type="button"
                className="primary"
                onClick={() => void rotate()}
                disabled={rotating}
              >
                Replace the old token?
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => setConfirmingRotate(false)}
                disabled={rotating}
              >
                Never mind
              </button>
            </div>
          </>
        ) : (
          <button type="button" className="primary" onClick={askRotate} disabled={rotating}>
            {tokenStatus?.exists ? 'Rotate token' : 'Create token'}
          </button>
        )}
      </section>

      <section className="card">
        <h2>Units</h2>
        <p className="hint">How distances are shown and entered.</p>
        <div className="choice">
          <button
            type="button"
            className={units === 'imperial' ? 'choice-option choice-current' : 'choice-option'}
            aria-pressed={units === 'imperial'}
            disabled={savingUnits}
            onClick={() => void chooseUnits('imperial')}
          >
            Miles
          </button>
          <button
            type="button"
            className={units === 'metric' ? 'choice-option choice-current' : 'choice-option'}
            aria-pressed={units === 'metric'}
            disabled={savingUnits}
            onClick={() => void chooseUnits('metric')}
          >
            Kilometers
          </button>
        </div>
        {unitsError && (
          <p className="error" role="alert">
            {unitsError}
          </p>
        )}
      </section>

      <section className="card">
        <h2>Password</h2>
        <form onSubmit={submitPassword}>
          <label>
            Current password
            <input
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label>
            New password
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              autoComplete="new-password"
              minLength={10}
              required
            />
          </label>
          <p className="hint">At least 10 characters.</p>

          {passwordError && (
            <p className="error" role="alert">
              {passwordError}
            </p>
          )}
          {passwordNote && (
            <p className="note note-success" role="status">
              {passwordNote}
            </p>
          )}

          <button type="submit" className="primary" disabled={savingPassword}>
            Change password
          </button>
        </form>
      </section>

      <section className="card">
        <h2>Account</h2>
        <p className="note">Signed in as {username}.</p>
        {email ? (
          <p className="note">
            {email} <span className={emailVerified ? 'tag' : 'tag tag-flag'}>
              {emailVerified ? 'verified' : 'not verified'}
            </span>
          </p>
        ) : (
          // The command line makes accounts without one, and they work fine.
          <p className="note">No email address on this account.</p>
        )}
        <button type="button" className="secondary" onClick={() => void signOut()}>
          Sign out
        </button>
      </section>
    </>
  )
}
