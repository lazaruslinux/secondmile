import { useState } from 'react'
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
        <p className="guide-note">
          Workouts arrive from Health Auto Export, an iPhone app you install from the App
          Store. It reads Apple Health and posts what it finds to an address you give it.
          Setting it up takes about five minutes, and it is done once.
        </p>
        <p className="guide-note">
          Two automations are described below, each field named the way Health Auto Export
          names it. The first one is the whole game. The second one is optional.
        </p>
      </div>

      <section className="settings-group">
        <h2 className="label settings-title guide-title">Before you start</h2>

        <div className="card">
          <h3>Your address and your token</h3>
          <p className="guide-note">Both automations post to this address:</p>

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
            They also need your sync token. Create it now, before you build the
            automations: it is on the Settings screen under Health sync, and when it
            appears, its Copy button copies the whole bearer line, ready to paste straight
            into the Header Value field below. The server keeps only a hash of it, so it
            is shown once and never printed here. If you lose it, rotate it and paste the
            new line into both automations.
          </p>
        </div>
      </section>

      <section className="settings-group">
        <h2 className="label settings-title guide-title">
          Automation 1: Secondmile_Workouts <span className="guide-chip">Required</span>
        </h2>

        <div className="card">
          <h3>What it does</h3>
          <p className="guide-note">
            Walks, runs, rides, and swims arrive through this one, and everything you earn
            is earned here: experience, levels, chests, growth in your plot, and medals.
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

      <section className="settings-group">
        <h2 className="label settings-title guide-title">The days before you joined</h2>

        <div className="card">
          <h3>One manual export brings them in</h3>
          <p className="guide-note">
            The automations only send what happens from now on, but your account accepts
            workouts from up to 14 days before the day it was created. Anything older than
            that is refused, and the window never moves: it is anchored to your signup, so
            time away later costs you nothing.
          </p>
          <p className="guide-note">
            To bring those days in, run one manual export from Health Auto Export: a
            Workouts export with a Date Range covering the days since the window opened.
            Every walk, run, ride, and swim inside it lands with everything it earns,
            exactly as if it had synced on the day.
          </p>
          <p className="guide-note">
            The same window applies to steps. A manual Health Metrics export covers them,
            though steps earn nothing either way.
          </p>
        </div>
      </section>

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

      <section className="settings-group">
        <h2 className="label settings-title guide-title">Once it is running</h2>

        <div className="card">
          <p className="guide-note">
            Every export covers the last seven days, so exports overlap on purpose and
            overlapping exports are safe. A workout is known by who you are, when it
            started, and how long it lasted, so the same one arriving twice changes nothing,
            and a day's step count only ever rises. Anything else in an export is ignored.
          </p>
          <p className="guide-note">
            The first sync can take a minute to appear. After that your workouts show up on
            their own, a few minutes behind the watch.
          </p>
          <p className="guide-note">
            On Android, any app that can post Health Connect data as JSON to the same
            address can try; none is tested and supported yet.
          </p>
        </div>
      </section>
    </>
  )
}
