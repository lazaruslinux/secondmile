import { useEffect, useState, type FormEvent } from 'react'
import {
  changeEmail,
  changePassword,
  errorText,
  getIngestTokenStatus,
  logout,
  reportBug,
  rotateIngestToken,
  setHiddenFromFriends,
  setNotifyWorkoutArrival,
  setUnits,
  type HiddenField,
  type IngestTokenStatus,
  type Units,
} from '../api.ts'
import { instanceTimezone } from '../format.ts'
import {
  deviceState,
  disableThisDevice,
  enableThisDevice,
  isApplePhone,
  type DeviceState,
} from '../push.ts'
import { applyTheme, rememberTheme, type Theme, useTheme } from '../theme.ts'
import Confirm from './Confirm.tsx'

// Said whatever happened. Whether that address belongs to anybody already is
// not this screen's news to give, so the sentence is the same either way.
const EMAIL_SENT =
  'Check that inbox. If the address can be used, a confirmation link is on its way.'

// As much as the server will store of one report, so the box stops where the
// refusal would have been.
const MAX_REPORT = 2000

// Said once a report is stored. There is no history and no status to send
// anybody back to, so this line is the whole of what a reporter gets.
const REPORT_SENT = 'Thank you. That arrived, and there is no reply to wait for.'

// The three switches, in the order the server keeps them. Pace is not among
// them on purpose: it is distance over time, both of which stay on every card,
// so a switch for it would promise something it could not keep.
const HIDEABLE: { field: HiddenField; label: string }[] = [
  { field: 'avg_hr', label: 'Heart rate' },
  { field: 'active_kcal', label: 'Calories' },
  { field: 'route', label: 'Route map' },
]

interface Props {
  username: string
  email: string | null
  emailVerified: boolean
  pendingEmail: string | null
  units: Units
  onUnitsChanged: (units: Units) => void
  // What this account currently keeps back from its friends, and the way to
  // change it. Empty is everybody's starting point: friends see the lot.
  hidden: HiddenField[]
  onHiddenChanged: (hidden: HiddenField[]) => void
  // The account-wide notification switch; the per-device half lives in this
  // browser and needs no prop.
  notifyArrival: boolean
  onNotifyChanged: (on: boolean) => void
  onSignedOut: () => void
  onOpenGuide: () => void
  onBack: () => void
}

export default function Settings({
  username,
  email,
  emailVerified,
  pendingEmail,
  units,
  onUnitsChanged,
  hidden,
  onHiddenChanged,
  notifyArrival,
  onNotifyChanged,
  onSignedOut,
  onOpenGuide,
  onBack,
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
  // Null until a Copy button is used, then which copyable thing it was and
  // whether it worked, so one message never appears under another's button.
  const [copyState, setCopyState] = useState<{ what: string; ok: boolean } | null>(null)
  const ingestUrl = `${window.location.origin}/api/ingest`

  const [unitsError, setUnitsError] = useState('')
  const [savingUnits, setSavingUnits] = useState(false)

  // This browser's own, so there is nothing to save and nothing to fail: the
  // screen changes under the button that was pressed. Read from the theme
  // module rather than held here, because the landing page can change it too.
  const theme = useTheme()

  const [hiddenError, setHiddenError] = useState('')
  const [savingHidden, setSavingHidden] = useState(false)

  // What this browser can do about notifications, asked once on the way in.
  // 'unknown' draws nothing device-side for the moment the answer takes.
  const [device, setDevice] = useState<DeviceState | 'unknown'>('unknown')
  const [changingDevice, setChangingDevice] = useState(false)
  const [savingNotify, setSavingNotify] = useState(false)
  const [pushError, setPushError] = useState('')

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [passwordError, setPasswordError] = useState('')
  const [passwordNote, setPasswordNote] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)

  const [reportText, setReportText] = useState('')
  const [reportError, setReportError] = useState('')
  const [reportNote, setReportNote] = useState('')
  const [sendingReport, setSendingReport] = useState(false)

  const [emailPassword, setEmailPassword] = useState('')
  const [wantedEmail, setWantedEmail] = useState('')
  const [emailError, setEmailError] = useState('')
  const [emailNote, setEmailNote] = useState('')
  const [savingEmail, setSavingEmail] = useState(false)

  useEffect(() => {
    getIngestTokenStatus()
      .then(setTokenStatus)
      .catch((err: unknown) => setTokenError(errorText(err)))
    void deviceState().then(setDevice)
  }, [])

  async function toggleNotify() {
    setSavingNotify(true)
    setPushError('')
    try {
      onNotifyChanged(await setNotifyWorkoutArrival(!notifyArrival))
    } catch (err) {
      setPushError(errorText(err))
    } finally {
      setSavingNotify(false)
    }
  }

  async function turnDeviceOn() {
    setChangingDevice(true)
    setPushError('')
    try {
      setDevice(await enableThisDevice())
    } catch (err) {
      setPushError(errorText(err))
    } finally {
      setChangingDevice(false)
    }
  }

  async function turnDeviceOff() {
    setChangingDevice(true)
    setPushError('')
    try {
      setDevice(await disableThisDevice())
    } catch (err) {
      setPushError(errorText(err))
    } finally {
      setChangingDevice(false)
    }
  }

  // The first token has nothing to break, so only a replacement is confirmed.
  function askRotate() {
    if (tokenStatus?.exists) setConfirmingRotate(true)
    else void rotate()
  }

  async function rotate() {
    setRotating(true)
    setTokenError('')
    setCopyState(null)
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

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopyState({ what, ok: true })
    } catch {
      // No clipboard on an insecure origin, or the browser refused. Nothing is
      // lost: the text is on the screen and can be selected by hand.
      setCopyState({ what, ok: false })
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

  function chooseTheme(next: Theme) {
    if (next === theme) return
    applyTheme(next)
    rememberTheme(next)
  }

  // Drawn from what the server stored rather than from the tap, so a switch
  // never shows something as hidden that is still being sent.
  async function toggleHidden(field: HiddenField) {
    const next = hidden.includes(field)
      ? hidden.filter((one) => one !== field)
      : [...hidden, field]
    setSavingHidden(true)
    setHiddenError('')
    try {
      onHiddenChanged(await setHiddenFromFriends(next))
    } catch (err) {
      setHiddenError(errorText(err))
    } finally {
      setSavingHidden(false)
    }
  }

  async function submitEmail(event: FormEvent) {
    event.preventDefault()
    setSavingEmail(true)
    setEmailError('')
    setEmailNote('')
    try {
      await changeEmail(emailPassword, wantedEmail)
      setEmailPassword('')
      setWantedEmail('')
      setEmailNote(EMAIL_SENT)
    } catch (err) {
      setEmailError(errorText(err))
    } finally {
      setSavingEmail(false)
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

  async function submitReport(event: FormEvent) {
    event.preventDefault()
    setSendingReport(true)
    setReportError('')
    setReportNote('')
    try {
      // The screen is named as 'settings' rather than threaded down from the
      // app: this card is only ever on the Settings screen, and the app's view
      // state reads 'settings' the whole time it is open, so a prop for it
      // would carry the same constant one level down.
      await reportBug(reportText, 'settings')
      setReportText('')
      setReportNote(REPORT_SENT)
    } catch (err) {
      setReportError(errorText(err))
    } finally {
      setSendingReport(false)
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
      <div className="view-head">
        <h1 className="view-title">Settings</h1>
        <button type="button" className="secondary" onClick={onBack}>
          Back
        </button>
      </div>

      {/* Two groups, and everything about this account is in the first one:
          who you are here, how to be reached, and how to leave. */}
      <section className="settings-group">
        <h2 className="label settings-title">Account</h2>

        <div className="card">
          <h3>Email</h3>
          <p className="note">Signed in as {username}.</p>
          {email ? (
            <p className="note">
              {email}{' '}
              <span className={emailVerified ? 'tag' : 'tag tag-flag'}>
                {emailVerified ? 'verified' : 'not verified'}
              </span>
            </p>
          ) : (
            // The command line makes accounts without one, and they work fine.
            <p className="note">No email address on this account.</p>
          )}
          {/* Whatever was just asked for is not drawn here. An address that
              already belongs to somebody else is answered exactly like one that
              does not, and showing it as waiting would undo that silence; it
              appears once the server says it is waiting. */}
          {pendingEmail && (
            <p className="note">
              {pendingEmail} <span className="tag tag-flag">waiting to be confirmed</span>
            </p>
          )}

          <form onSubmit={submitEmail}>
            <p className="hint">
              {email
                ? 'Changing it sends a link to the new address. The old one stays on the account until that link is used.'
                : 'Adding one sends a link to it. The address is on the account once that link is used.'}
            </p>
            <label>
              Current password
              <input
                type="password"
                value={emailPassword}
                onChange={(event) => setEmailPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <label>
              New email address
              <input
                type="email"
                value={wantedEmail}
                onChange={(event) => setWantedEmail(event.target.value)}
                autoComplete="email"
                autoCapitalize="none"
                spellCheck={false}
                required
              />
            </label>

            {emailError && (
              <p className="error" role="alert">
                {emailError}
              </p>
            )}
            {emailNote && (
              <p className="note note-success" role="status">
                {emailNote}
              </p>
            )}

            <button type="submit" className="primary" disabled={savingEmail}>
              {email ? 'Change email' : 'Add email'}
            </button>
          </form>
        </div>

        <div className="card">
          <h3>Password</h3>
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
        </div>

      </section>

      {/* Its own group, above the sync and the units: what friends can see is
          worth finding before the settings that only change your own screen. */}
      <section className="settings-group">
        <h2 className="label settings-title">Privacy</h2>

        <div className="card">
          <h3>Hide from friends</h3>
          <p className="hint">
            Friends see your activities in full. Turn one of these on to keep it off the
            cards they see. Distance and time always show, and so does anything you write.
          </p>

          <ul className="picker-list">
            {HIDEABLE.map(({ field, label }) => (
              <li key={field}>
                <label className="picker-option">
                  <input
                    type="checkbox"
                    checked={hidden.includes(field)}
                    disabled={savingHidden}
                    onChange={() => void toggleHidden(field)}
                  />
                  <span>{label}</span>
                </label>
              </li>
            ))}
          </ul>

          {hiddenError && (
            <p className="error" role="alert">
              {hiddenError}
            </p>
          )}
        </div>
      </section>

      <section className="settings-group">
        <h2 className="label settings-title">Health sync</h2>

        <div className="card">
          <h3>Sync token</h3>
          <p className="hint">
            The bearer token your phone sends with each workout export. Rotating it replaces
            the old one immediately.
          </p>

          {tokenStatus && (
            <p className="note">
              {tokenStatus.exists
                ? `A token exists${
                    tokenStatus.rotated_at
                      ? `, last rotated ${new Date(tokenStatus.rotated_at).toLocaleDateString(
                          undefined,
                          { timeZone: instanceTimezone() },
                        )}`
                      : ''
                  }.`
                : 'No token yet.'}
            </p>
          )}

          {freshToken && (
            <div className="token">
              <p className="warning">
                This is the whole Header Value for your export app. Copy it now; it will
                not be shown again.
              </p>
              {/* The line is handed over assembled, prefix and all, so the thing
                  copied and the thing pasted are the same object: describing the
                  format in words got the description itself pasted once. */}
              <code>{`bearer ${freshToken}`}</code>
              <button
                type="button"
                className="secondary"
                onClick={() => void copy(`bearer ${freshToken}`, 'token')}
              >
                Copy
              </button>
              {copyState?.what === 'token' && copyState.ok && (
                <p className="note note-success" role="status">
                  Copied.
                </p>
              )}
              {copyState?.what === 'token' && !copyState.ok && (
                <p className="note" role="status">
                  This browser would not copy it. Select the token and copy it by hand.
                </p>
              )}
            </div>
          )}

          {/* While the dialog is up it is the one saying what went wrong, so the
              card does not say the same sentence a second time behind it. */}
          {tokenError && !confirmingRotate && (
            <p className="error" role="alert">
              {tokenError}
            </p>
          )}

          <button type="button" className="primary" onClick={askRotate} disabled={rotating}>
            {tokenStatus?.exists ? 'Rotate token' : 'Create token'}
          </button>

          {/* Replacing a working token breaks a phone that is syncing, so it is
              asked in the same dialog every other destructive question is. */}
          {confirmingRotate && (
            <Confirm
              heading="Replace the token?"
              confirmLabel="Replace the token"
              cancelLabel="Cancel"
              busy={rotating}
              error={tokenError}
              onConfirm={() => void rotate()}
              onCancel={() => setConfirmingRotate(false)}
            >
              <p>
                Your phone stops syncing until the new token is pasted into your export app.
              </p>
            </Confirm>
          )}
        </div>

        {/* The short version. The full setup, including what the server does
            with a sync, is in the repository's own documentation. */}
        <div className="card">
          <h3>Setting up your phone</h3>
          {/* One breath and a pointer. The guide owns the walkthrough now; this
              card owns the two things the phone needs, the address below and
              the token above. */}
          <p className="hint">
            Workouts arrive from Health Auto Export, an iPhone app that reads Apple Health
            and posts it to the address below. The setup guide walks through it field by
            field with screenshots.
          </p>

          {/* Built from the address this page was opened on, so it is right for
              whoever is reading it rather than for whoever installed the site. */}
          <div className="endpoint">
            <code>{ingestUrl}</code>
            <button
              type="button"
              className="secondary"
              onClick={() => void copy(ingestUrl, 'url')}
            >
              Copy
            </button>
            {copyState?.what === 'url' && copyState.ok && (
              <p className="note note-success" role="status">
                Copied.
              </p>
            )}
            {copyState?.what === 'url' && !copyState.ok && (
              <p className="note" role="status">
                This browser would not copy it. Select the address and copy it by hand.
              </p>
            )}
          </div>
          {/* Under the address, because the address is what somebody came to
              this card for and the guide is the long way round of the same
              paragraph: every field, named as the app names it, with pictures. */}
          <p className="hint">
            <button type="button" className="link" onClick={onOpenGuide}>
              View the setup guide
            </button>
          </p>
        </div>
      </section>

      {/* Right under the sync that brings workouts in: what the phone says
          when one lands. The switch is the account's; the button is this
          device's. */}
      <section className="settings-group">
        <h2 className="label settings-title">Notifications</h2>

        <div className="card">
          <ul className="picker-list">
            <li>
              <label className="picker-option">
                <input
                  type="checkbox"
                  checked={notifyArrival}
                  disabled={savingNotify}
                  onChange={() => void toggleNotify()}
                />
                <span>Workout arrivals</span>
              </label>
            </li>
          </ul>
          <p className="hint">
            One notification when a sync lands new workouts. Turning it off silences
            every device on this account.
          </p>

          {device === 'unsupported' && (
            <p className="hint">
              {isApplePhone()
                ? 'On an iPhone, add secondmile to your Home Screen first. Notifications work from there.'
                : 'This browser cannot receive notifications.'}
            </p>
          )}
          {device === 'denied' && (
            <p className="hint">
              Notifications are blocked for this site in your browser settings.
            </p>
          )}
          {device === 'off' && (
            <button
              type="button"
              className="secondary"
              disabled={changingDevice}
              onClick={() => void turnDeviceOn()}
            >
              Turn on for this device
            </button>
          )}
          {device === 'on' && (
            <>
              <p className="hint">This device receives notifications.</p>
              <button
                type="button"
                className="secondary"
                disabled={changingDevice}
                onClick={() => void turnDeviceOff()}
              >
                Turn off for this device
              </button>
            </>
          )}
          {pushError && (
            <p className="error" role="alert">
              {pushError}
            </p>
          )}
        </div>
      </section>

      {/* The same three parts the three groups above are built from: the group,
          its title, and the card under it. One card, because one choice is the
          whole of what this section is. */}
      <section className="settings-group">
        <h2 className="label settings-title">Units</h2>

        <div className="card">
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
        </div>
      </section>

      {/* The same shape as Units above it, and with nothing said under the
          heading: the two words are the whole of it, and the proof is the
          screen changing as they are pressed. This browser's choice rather
          than the account's, so no other device follows it. */}
      <section className="settings-group">
        <h2 className="label settings-title">Appearance</h2>

        <div className="card">
          <div className="choice">
            <button
              type="button"
              className={theme === 'light' ? 'choice-option choice-current' : 'choice-option'}
              aria-pressed={theme === 'light'}
              onClick={() => chooseTheme('light')}
            >
              Light
            </button>
            <button
              type="button"
              className={theme === 'dark' ? 'choice-option choice-current' : 'choice-option'}
              aria-pressed={theme === 'dark'}
              onClick={() => chooseTheme('dark')}
            >
              Dark
            </button>
          </div>
        </div>
      </section>

      {/* Second to last, right above sign out: near the end where somebody
          scrolls when something has gone wrong, and not in the way of anything
          they came here to change. */}
      <section className="settings-group">
        <div className="card">
          <h3>Report a bug</h3>
          <form onSubmit={submitReport}>
            <textarea
              value={reportText}
              maxLength={MAX_REPORT}
              rows={4}
              placeholder="What went wrong, and what you were doing"
              onChange={(event) => setReportText(event.target.value)}
              required
            />
            {/* The whole of what is stamped on a report, said before it is
                sent rather than after: nothing about one is collected quietly. */}
            <p className="hint">
              Your account name, the screen you were on, and your browser are sent along
              with this, and nothing else is.
            </p>

            {reportError && (
              <p className="error" role="alert">
                {reportError}
              </p>
            )}
            {reportNote && (
              <p className="note note-success" role="status">
                {reportNote}
              </p>
            )}

            <button type="submit" className="primary" disabled={sendingReport}>
              Send report
            </button>
          </form>
        </div>
      </section>

      {/* Last on the page and in a group of its own, because the end is where
          people scroll to look for it. It used to sit inside Account, between
          the email form and the sync token, where it was findable only by
          somebody who already knew it was there. */}
      <section className="settings-group">
        <div className="card">
          <h3>Sign out</h3>
          <p className="hint">Signs this browser out. Your other devices stay signed in.</p>
          <button type="button" className="secondary" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </section>
    </>
  )
}
