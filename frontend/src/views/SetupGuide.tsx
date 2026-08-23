import { useState } from 'react'
// Which set of instructions is being read. Guessed from the browser and then
// left alone: the chips are the answer if the guess is wrong, and a guide
// nobody can switch is worse than one that guesses.
import { guessPlatform, type Platform } from '../platform.ts'
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
  { name: 'Name', value: 'Secondmile_Workouts' },
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
  { name: 'Name', value: 'Secondmile_Steps' },
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
        {apple ? (
          <>
            <p className="guide-note">
              Workouts arrive from Health Auto Export, an iPhone app you install from the
              App Store. It reads Apple Health and posts what it finds to an address you
              give it. Setting it up takes about five minutes, and it is done once.
            </p>
            <p className="guide-note">
              Two automations are described below, each field named the way Health Auto
              Export names it. The first one is the whole game. The second one is optional.
            </p>
          </>
        ) : (
          <>
            <p className="guide-note">
              Workouts arrive from a bridge app that reads Health Connect and posts what it
              finds to an address you give it. Health Connect Webhook is the one this app is
              written for: it is free, open source under the same licence as this app, and
              on the Play Store. Setting it up takes about five minutes, and it is done
              once.
            </p>
            <p className="guide-note">
              One app, one address, one header. Everything you earn comes through it:
              experience, levels, chests, growth in your grove, and medals.
            </p>
          </>
        )}
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
            {apple ? 'They also need' : 'It also needs'} your sync token. Create it now,
            before you set anything else up: it is on the Settings screen under Health sync,
            and when it appears, its Copy button copies the whole bearer line, ready to paste
            straight into the header value below. The server keeps only a hash of it, so it
            is shown once and never printed here. If you lose it, rotate it and paste the new
            line back in.
          </p>
        </div>

        {apple ? (
          <div className="card">
            <h3>Let it read Apple Health</h3>
            <p className="guide-note">
              Health Auto Export can only send what Apple Health lets it read. The first
              time it opens, iOS asks for that access; allow it, and turn on the categories
              it lists.
            </p>
            <p className="guide-note">
              If an automation fails with &quot;authorization not found&quot;, or runs
              without sending anything, this permission is the usual reason: open the
              iPhone's Settings, then Privacy &amp; Security, then Health, then Health Auto
              Export, and turn everything on. Nothing reaches the server until this is
              granted.
            </p>
          </div>
        ) : (
          <div className="card">
            <h3>Let it read Health Connect</h3>
            <p className="guide-note">
              The bridge can only send what Health Connect lets it read, and Health Connect
              only holds what your watch or your fitness app writes into it. Open Health
              Connect, check that whatever records your workouts is connected to it, then
              grant the bridge read access to the five data types listed below.
            </p>
            <p className="guide-note">
              If a sync runs without sending anything, this permission is the usual reason.
              Nothing reaches the server until it is granted.
            </p>
          </div>
        )}
      </section>

      {apple && (
        <section className="settings-group">
          <h2 className="label settings-title guide-title">
            Automation 1: Secondmile_Workouts <span className="guide-chip">Required</span>
          </h2>

          <div className="card">
            <h3>What it does</h3>
            <p className="guide-note">
              Walks, runs, rides, and swims arrive through this one, and everything you earn
              is earned here: experience, levels, chests, growth in your grove, and medals.
            </p>
            <p className="guide-note">
              In Health Auto Export, open Automations, add an automation, and name it
              Secondmile_Workouts. Then set the fields below, top to bottom, and tap Update.
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
        <h2 className="label settings-title guide-title">The days before you joined</h2>

        <div className="card">
          <h3>{apple ? 'One manual export brings them in' : 'One wider sync brings them in'}</h3>
          <p className="guide-note">
            {apple
              ? 'The automations only send what happens from now on,'
              : 'An ordinary sync only reaches back about two days,'}{' '}
            but your account accepts workouts from up to 14 days before the day it was
            created. Anything older than that is refused, and the window never moves: it is
            anchored to your signup, so time away later costs you nothing.
          </p>
          {apple ? (
            <>
              <p className="guide-note">
                To bring those days in, run one manual export from Health Auto Export: a
                Workouts export with a Date Range covering the days since the window opened.
                Every walk, run, ride, and swim inside it lands with everything it earns,
                exactly as if it had synced on the day.
              </p>
              <p className="guide-note">
                The same window applies to steps. A manual Health Metrics export covers
                them, though steps earn nothing either way.
              </p>
            </>
          ) : (
            <p className="guide-note">
              To bring those days in, run one manual sync from the bridge over a range
              covering the days since the window opened, if it offers one. Every walk, run,
              ride, and swim inside it lands with everything it earns, exactly as if it had
              synced on the day.
            </p>
          )}
        </div>
      </section>

      {apple && (
        <section className="settings-group">
          <h2 className="label settings-title guide-title">
            Automation 2: Secondmile_Steps{' '}
            <span className="guide-chip guide-chip-optional">Optional</span>
          </h2>

          <div className="card">
            <h3>Entirely optional</h3>
            <p className="guide-note">
              This one is entirely optional, and it earns nothing. All it does is feed the
              step counts on your screens: the line on your own profile, the count in your
              weekly letter, and the tally on the landing page. Set up only
              Secondmile_Workouts and you have the complete earning experience, with nothing
              missing and nothing to catch up on later.
            </p>
            <p className="guide-note">
              Health Auto Export sends one data type per automation, which is the only reason
              there are two. Duplicate the first automation or add a new one, name it
              Secondmile_Steps, and set the fields below.
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
        <h2 className="label settings-title guide-title">Once it is running</h2>

        <div className="card">
          <p className="guide-note">
            Every export covers a window that reaches back over the last one, so exports
            overlap on purpose and overlapping exports are safe. A workout is known by who
            you are, when it started, and how long it lasted, so the same one arriving twice
            changes nothing, and a day's step count only ever rises. Anything else in an
            export is ignored.
          </p>
          <p className="guide-note">
            The first sync can take a minute to appear. After that your workouts show up on
            their own, a few minutes behind the watch.
          </p>
          {apple ? (
            <p className="guide-note">
              If your workouts stop showing up here, open Health Auto Export and let it
              run. iOS pauses the background automations of an app it has not seen you
              open in a while, and when it does they stop sending without saying so: the
              automation still reads as on. Opening the app is what starts it again, and
              it sends everything it missed. Nothing is lost while it is paused, because
              the workouts are still in Apple Health and they land as soon as it runs.
            </p>
          ) : (
            <p className="guide-note">
              If your workouts stop showing up here, open the bridge and let it run.
              Android puts an app it has not seen you open in a while to sleep, and a
              sleeping app stops sending without saying so. Opening it is what starts it
              again, and it sends what it missed. Nothing is lost while it is asleep,
              because the workouts are still in Health Connect. Allowing the app to run in
              the background, or exempting it from battery optimisation, makes it happen
              less often.
            </p>
          )}
          <p className="guide-note">
            Both phones post to the same address, in their own shapes, and the server reads
            whichever arrives. Nothing about a workout remembers which one it came from, so
            switching phones costs you nothing you have earned.
          </p>
        </div>
      </section>
    </>
  )
}
