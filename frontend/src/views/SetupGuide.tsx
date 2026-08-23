import { useEffect, useState } from 'react'
// Which set of instructions is being read. Guessed from the browser and then
// left alone: the chips are the answer if the guess is wrong, and a guide
// nobody can switch is worse than one that guesses.
import { errorText, getIngestTokenStatus, rotateIngestToken } from '../api.ts'
import { guessPlatform, type Platform } from '../platform.ts'
import Confirm from './Confirm.tsx'
import stepsExport from '../assets/guide/steps-automation-export.png'
import stepsTop from '../assets/guide/steps-automation-top.png'
import workoutsExport from '../assets/guide/workouts-automation-export.png'
import workoutsTop from '../assets/guide/workouts-automation-top.png'

// One row of the walkthrough: the field named exactly as Health Auto Export
// names it, and what to set it to.
interface Field {
  name: string
  value: string
}

// The screenshots are 1320 by 2868, and the two numbers are on every image so
// the page keeps its shape while they load.
const SHOT_WIDTH = 1320
const SHOT_HEIGHT = 2868

const WORKOUT_FIELDS: Field[] = [
  { name: 'Name', value: 'Anything you like' },
  { name: 'Enabled', value: 'On' },
  { name: 'Notify on Cache Update', value: 'Off' },
  { name: 'Notify When Run', value: 'Off' },
  { name: 'Automation Type', value: 'REST API' },
  { name: 'URL', value: 'The address above' },
  { name: 'Timeout Interval', value: '60' },
  { name: 'Header Key', value: 'Authorization' },
  { name: 'Header Value', value: 'the bearer line you copied when you created your token' },
  { name: 'Data Type', value: 'Workouts' },
  { name: 'Include Route Data', value: 'On' },
  { name: 'Include Workout Metrics', value: 'On' },
  { name: 'Time Grouping', value: 'Minutes' },
  { name: 'Export Format', value: 'JSON' },
  { name: 'Export Version', value: 'v2' },
  // Default sends whatever appeared since the last sync, today included.
  // Workouts dedupe exactly, so this is safe; a ranged window that excludes
  // today holds every workout back until tomorrow. Steps stay on Previous 7
  // Days deliberately: their daily statistics need finished days.
  { name: 'Date Range', value: 'Default' },
  { name: 'Batch Requests', value: 'Off' },
  { name: 'Sync Cadence Quantity', value: '5' },
  { name: 'Sync Cadence Interval', value: 'Minutes' },
]

const STEP_FIELDS: Field[] = [
  { name: 'Name', value: 'Anything you like' },
  { name: 'Enabled', value: 'On' },
  { name: 'Notify on Cache Update', value: 'Off' },
  { name: 'Notify When Run', value: 'Off' },
  { name: 'Automation Type', value: 'REST API' },
  { name: 'URL', value: 'The same address' },
  { name: 'Timeout Interval', value: '60' },
  { name: 'Header Key', value: 'Authorization' },
  { name: 'Header Value', value: 'the bearer line you copied when you created your token' },
  { name: 'Data Type', value: 'Health Metrics' },
  {
    name: 'Select Health Metrics',
    value: 'Everything off, then Step Count and Walking + Running Distance',
  },
  { name: 'Summarize Data', value: 'On' },
  { name: 'Time Grouping', value: 'Day' },
  { name: 'Export Format', value: 'JSON' },
  { name: 'Export Version', value: 'v2' },
  { name: 'Date Range', value: 'Previous 7 Days' },
  { name: 'Batch Requests', value: 'Off' },
  { name: 'Sync Cadence Quantity', value: '5' },
  { name: 'Sync Cadence Interval', value: 'Minutes' },
]

// The bridge app's settings, named the way its own documentation names them.
// Its screens are not walked through the way the iPhone ones are: nobody here
// has run it, and a tap-by-tap walkthrough written from a manual is a guess
// dressed up as instructions.
const ANDROID_FIELDS: Field[] = [
  { name: 'Webhook URL', value: 'The address above' },
  { name: 'Custom header, name', value: 'Authorization' },
  { name: 'Custom header, value', value: 'the bearer line you copied when you created your token' },
  {
    name: 'Data types',
    value: 'Exercise Sessions, Heart Rate, Active Calories, Steps, Distance',
  },
  { name: 'Sync mode', value: 'Interval' },
  { name: 'Sync interval', value: '15 minutes, its shortest' },
]

function FieldList({ fields }: { fields: Field[] }) {
  return (
    <ul className="guide-fields">
      {fields.map((field) => (
        <li key={field.name} className="guide-field">
          <span className="guide-field-name">{field.name}</span>
          <span className="guide-field-value">{field.value}</span>
        </li>
      ))}
    </ul>
  )
}

function Shot({ src, caption }: { src: string; caption: string }) {
  return (
    <figure className="guide-shot">
      <img
        className="guide-shot-img"
        src={src}
        width={SHOT_WIDTH}
        height={SHOT_HEIGHT}
        loading="lazy"
        alt=""
      />
      <figcaption className="hint">{caption}</figcaption>
    </figure>
  )
}

interface Props {
  onBack: () => void
}

export default function SetupGuide({ onBack }: Props) {
  // Built from the address this page was opened on, the same way the Settings
  // card builds it, so the guide is right for whoever is reading it.
  const ingestUrl = `${window.location.origin}/api/ingest`
  // Null until the Copy button is used, then whether it worked.
  const [copied, setCopied] = useState<boolean | null>(null)
  const [platform, setPlatform] = useState<Platform>(guessPlatform)
  const apple = platform === 'apple'
  // Whether this account has a token already, which decides whether the button
  // below makes one or replaces one. Null while the answer is still coming.
  const [hasToken, setHasToken] = useState<boolean | null>(null)
  // The plaintext token, for the one render it exists in. The server keeps only
  // a hash, so leaving this screen is the end of it.
  const [freshToken, setFreshToken] = useState('')
  const [makingToken, setMakingToken] = useState(false)
  const [tokenError, setTokenError] = useState('')
  const [confirmingRotate, setConfirmingRotate] = useState(false)
  const [tokenCopied, setTokenCopied] = useState<boolean | null>(null)

  useEffect(() => {
    getIngestTokenStatus()
      .then((status) => setHasToken(status.exists))
      .catch(() => setHasToken(null))
  }, [])

  async function copy() {
    try {
      await navigator.clipboard.writeText(ingestUrl)
      setCopied(true)
    } catch {
      // No clipboard on an insecure origin, or the browser refused. The address
      // is on the screen either way.
      setCopied(false)
    }
  }

  async function makeToken() {
    setMakingToken(true)
    setTokenError('')
    try {
      setFreshToken(await rotateIngestToken())
      setHasToken(true)
      setConfirmingRotate(false)
    } catch (err) {
      setTokenError(errorText(err))
    } finally {
      setMakingToken(false)
    }
  }

  async function copyToken() {
    try {
      await navigator.clipboard.writeText(`bearer ${freshToken}`)
      setTokenCopied(true)
    } catch {
      setTokenCopied(false)
    }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">Setup guide</h1>
        <button type="button" className="secondary" onClick={onBack}>
          Back
        </button>
      </div>

      <div className="card">
        <ul className="filter-chips guide-platforms">
          {(['apple', 'android'] as Platform[]).map((choice) => (
            <li key={choice}>
              <button
                type="button"
                className={`filter-chip${platform === choice ? ' filter-chip-on' : ''}`}
                aria-pressed={platform === choice}
                onClick={() => setPlatform(choice)}
              >
                {choice === 'apple' ? 'iPhone' : 'Android'}
              </button>
            </li>
          ))}
        </ul>
        <p className="guide-note">
          A trusted bridge app takes the workouts your phone records and exports them to
          secondmile's ingest link, shown below.{' '}
          {apple ? (
            <>
              The recommended one is Health Auto Export, on the App Store. Manual exporting
              is all secondmile needs; automating it so exports run daily or after every
              workout is a convenience rather than a requirement. Both are paid features of
              that app, and its App Store listing has the current prices.
            </>
          ) : (
            <>
              The recommended one is Health Connect Webhook: a free, open source bridge app
              under the same licence as secondmile, on the Play Store.
            </>
          )}{' '}
          Setting it up takes about five minutes, and is only done once.
        </p>
        <p className="guide-note">There are two kinds of sync secondmile accepts.</p>

        <ul className="guide-kinds">
          <li>
            <span className="guide-chip">Workouts</span>
            <span>Required to sync and earn XP on secondmile</span>
          </li>
          <li>
            <span className="guide-chip guide-chip-optional">Steps</span>
            <span>Visual only, entirely optional</span>
          </li>
        </ul>

        <p className="guide-note">
          This app will ask your phone for permission to read your health data. That
          permission is required for secondmile to work. Once your data reaches secondmile
          it is not shared with or sent to anyone else.
        </p>
      </div>

      <section className="settings-group">
        <h2 className="label settings-title guide-title">Before you start</h2>

        <div className="card">
          <h3>Your address and your token</h3>
          <p className="guide-note">
            {apple ? 'Both automations post to this address:' : 'The bridge posts to this address:'}
          </p>

          {/* Built from the address this page was opened on rather than written
              down, so a copy of the app on another domain is still right. */}
          <div className="endpoint">
            <code>{ingestUrl}</code>
            <button type="button" className="secondary" onClick={() => void copy()}>
              Copy
            </button>
            {copied === true && (
              <p className="note note-success" role="status">
                Copied.
              </p>
            )}
            {copied === false && (
              <p className="note" role="status">
                This browser would not copy it. Select the address and copy it by hand.
              </p>
            )}
          </div>

          <p className="guide-note">
            {apple ? 'They also need' : 'It also needs'} your sync token, which is what
            tells secondmile the workouts are yours. Make it here, then paste the whole
            line into the header field below.
          </p>

          {/* The token itself rather than directions to it. Making a first one
              is safe and asks nothing; replacing one revokes the old, so that
              half goes behind the same guard the Settings card uses. */}
          {freshToken ? (
            <div className="endpoint">
              <code>{`bearer ${freshToken}`}</code>
              <button type="button" className="secondary" onClick={() => void copyToken()}>
                Copy
              </button>
              {tokenCopied === true && (
                <p className="note note-success" role="status">
                  Copied. Paste this whole line, the word bearer included.
                </p>
              )}
              {tokenCopied === false && (
                <p className="note" role="status">
                  This browser would not copy it. Select the line and copy it by hand.
                </p>
              )}
              <p className="hint">
                This is the only time it is shown. If you lose it, come back and make
                another.
              </p>
            </div>
          ) : (
            <>
              <button
                type="button"
                className="secondary"
                disabled={makingToken || hasToken === null}
                onClick={() => (hasToken ? setConfirmingRotate(true) : void makeToken())}
              >
                {hasToken ? 'Make a new token' : 'Make my sync token'}
              </button>
              {hasToken === true && (
                <p className="hint">
                  You already have one. It was shown once when it was made, and making
                  another stops the old one working.
                </p>
              )}
            </>
          )}
          {tokenError && (
            <p className="error" role="alert">
              {tokenError}
            </p>
          )}

          {confirmingRotate && (
            <Confirm
              heading="Replace the token?"
              confirmLabel="Replace the token"
              cancelLabel="Cancel"
              busy={makingToken}
              error={tokenError}
              onConfirm={() => void makeToken()}
              onCancel={() => setConfirmingRotate(false)}
            >
              <p>
                Your phone stops syncing until the new token is pasted into your export
                app.
              </p>
            </Confirm>
          )}
        </div>

      </section>

      {apple && (
        <section className="settings-group">
          <h2 className="label settings-title guide-title">
            Automation 1: Workouts <span className="guide-chip">Recommended</span>
          </h2>

          <div className="card">
            <h3>What it does</h3>
            <p className="guide-note">
              Walks, runs, rides, and swims arrive through this one, and everything you earn
              is earned here: experience, levels, chests, growth in your grove, and medals.
            </p>
            <p className="guide-note">
              In Health Auto Export, open Automations and add one. Call it whatever you
              like; the name is only for you. Then set the fields below, top to bottom, and
              tap Update.
            </p>

            <FieldList fields={WORKOUT_FIELDS} />

            <p className="guide-note">
              Include Route Data is what draws the line on your workout cards. No map tiles
              are fetched, and the beginning and end of every route are trimmed away before
              anything is stored, so a route never starts at your door.
            </p>
            <p className="guide-note">
              Time Grouping does nothing to a workouts export. Leave it wherever it sits.
            </p>

            <div className="guide-shots">
              <Shot src={workoutsTop} caption="The top of the workouts automation." />
              <Shot src={workoutsExport} caption="The rest of the workouts automation." />
            </div>
          </div>
        </section>
      )}

      {!apple && (
        <section className="settings-group">
          <h2 className="label settings-title guide-title">
            The bridge <span className="guide-chip">Required</span>
          </h2>

          <div className="card">
            <h3>What it does</h3>
            <p className="guide-note">
              Walks, runs, rides, and swims arrive through it, and everything you earn is
              earned here: experience, levels, chests, growth in your grove, and medals.
            </p>
            <p className="guide-note">
              Install Health Connect Webhook, add a webhook, and set what is below. Its own
              wording may differ a little from these names; nobody here has run it on a
              phone, so what is written down is what its documentation says rather than a
              walkthrough somebody watched.
            </p>

            <FieldList fields={ANDROID_FIELDS} />

            <p className="guide-note">
              Heart rate, calories, steps, and distance are what fill in a workout's detail
              screen: its per-minute graph, its zones, and the calories your manna is
              converted from. Leave any of them off and the workout still arrives and still
              earns; it just has less to show.
            </p>
            <p className="guide-note">
              There is no route line on an Android workout yet. Health Connect can store one
              and the bridge does not send it, so these workouts arrive without a map. Every
              other thing they earn is the same.
            </p>
          </div>
        </section>
      )}

      <section className="settings-group">
        <h2 className="label settings-title guide-title">Backfill Limits</h2>

        <div className="card">
          <p className="guide-note">
            secondmile accepts workouts from up to 14 days before the day your account was
            created. The window is anchored to your signup and never moves, so one export
            covering those days brings them in, and anything older than that is refused.
          </p>
        </div>
      </section>

      {apple && (
        <section className="settings-group">
          <h2 className="label settings-title guide-title">
            Automation 2: Steps{' '}
            <span className="guide-chip guide-chip-optional">Optional</span>
          </h2>

          <div className="card">
            <h3>Entirely optional</h3>
            <p className="guide-note">
              This one is entirely optional, and it earns nothing. All it does is feed the
              step counts on your screens: the line on your own profile, the count in your
              weekly letter, and the tally on the landing page. Set up the workouts one
              alone and you have the complete earning experience, with nothing missing and
              nothing to catch up on later.
            </p>
            <p className="guide-note">
              Health Auto Export sends one data type per automation, which is the only
              reason there are two. Duplicate the first one or add another, and set the
              fields below.
            </p>

            <FieldList fields={STEP_FIELDS} />

            <p className="guide-note">
              Time Grouping has to be Day. On Minutes the app sends every raw sample, and a
              phone and a watch that both counted the same walk both land, which reads several
              per cent high. On Day it sends one figure per day, which is the figure Apple
              Health itself shows you.
            </p>
            <p className="guide-note">
              Include Route Data and Include Workout Metrics are not on this screen. They
              belong to the Workouts data type, and this one has no use for them. Steps carry
              no location data of any kind.
            </p>
            <p className="guide-note">
              Previous 7 Days stops at yesterday, so today's final count arrives tomorrow
              morning. Nothing is lost by waiting for it.
            </p>

            <div className="guide-shots">
              <Shot src={stepsTop} caption="The top of the steps automation." />
              <Shot src={stepsExport} caption="The rest of the steps automation." />
            </div>
          </div>
        </section>
      )}

      <section className="settings-group">
        <h2 className="label settings-title guide-title">After Setup</h2>

        <div className="card">
          <p className="guide-note">
            Exports overlap on purpose and overlapping exports are safe. A workout is known
            by who you are, when it started, and how long it lasted, so the same one
            arriving twice changes nothing. The first sync can take a minute to appear.
          </p>
          <p className="guide-note">
            If your workouts stop showing up here, open{' '}
            {apple ? 'Health Auto Export' : 'the bridge'} and let it run. A phone pauses the
            background work of an app it has not seen you open in a while, and when it does
            the exports stop without saying so. Opening it starts them again and it sends
            what it missed. Nothing is lost while it is paused.
          </p>
          {apple && (
            <p className="guide-note">
              If an export fails with &quot;authorization not found&quot;, or runs without
              sending anything, the Health permission is the usual reason: open the iPhone's
              Settings, then Privacy &amp; Security, then Health, then Health Auto Export,
              and turn everything on.
            </p>
          )}
        </div>
      </section>
    </>
  )
}
