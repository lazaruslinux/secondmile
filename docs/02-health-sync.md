# Syncing workouts

secondmile ingests workouts through Health Auto Export, an iPhone app that
reads Apple Health and posts JSON to a URL you choose. Anything that records
a workout to Apple Health (an Apple Watch, most fitness apps) flows through
it.

## Setting it up

The app carries this walkthrough too, with screenshots and every field named the
way Health Auto Export names it: open Settings and follow the link to the setup
guide. What is below is the short version of the same thing.

1. Log in to secondmile, open Settings, and generate your ingest token. Copy
   it now; the server stores only a hash, so it is shown once. You can
   rotate it here any time, which invalidates the old one.

2. In Health Auto Export, create a new REST API automation:

   - URL: `https://your-domain/api/ingest`
   - Method: POST
   - Headers: `Authorization: Bearer <your token>`
   - Data type: Workouts
   - Format: JSON
   - Include Workout Metrics: on. It carries the calories and the heart rate,
     and the per-minute detail the workout's own screen is drawn from.
   - Include Route Data: on, if you want the map line on your workout
     cards. It is optional; everything else works the same without it.

3. Set the automation to run on a schedule (daily is plenty) or trigger it
   manually after a workout.

4. Optionally, add a second automation with the same URL, method, headers and
   format, and the data type Health Metrics; under Select Health Metrics turn
   everything off and pick Step Count and Walking + Running Distance. Set its
   Time Grouping to Day and its Date Range to Previous 7 Days, so it sends one
   finished figure per day rather than every raw sample. Health Auto Export
   takes one data type per automation, which is the only reason there are two.
   This one earns nothing and only feeds the step counts on the screens: see
   Steps below. Everything the app rewards arrives through the workouts
   automation alone.

Your account accepts workouts from up to 14 days before the day it was created,
so one manual export brings in the days before you joined. The window is
anchored to your signup and never moves, and anything older than it is refused
and counted rather than treated as an error.

Only walking, running, cycling, and swimming workouts are imported; other
types in the export are counted in the response but ignored.

The name the export gives a workout is also where "indoor" is read from: a walk
or a run whose name says Indoor wears a treadmill mark instead of its sport's
own, wherever the app draws one. It changes nothing else, and a session whose
name says nothing reads as outdoors. Workouts synced before this was added stay
unmarked unless their sync is still inside the ingest log's 90 day window.

## What the server does with it

- Imports are idempotent. A workout is identified by who you are, when it
  started, and how long it lasted, so overlapping export windows or
  re-running an automation never double-counts anything. The response says
  how many workouts were imported and how many were skipped as already
  known.
- The payload of every ingest call is kept in the database for 90 days, so if a
  parsing bug ever drops a field, the history can be replayed after the fix
  instead of being lost. Its GPS route arrays are taken out before it is
  stored: they are already drawn into a table of their own, and they are the
  one part of an export that says where you live.
- Workouts with impossible numbers (a sub four minute mile, cycling past the
  configured daily cap) are imported but flagged, and the Activity tab shows the
  flag. Nothing is rejected; the flags exist so bad data never silently
  becomes progress.
- Every imported workout is credited to your profile straight away: experience
  toward your level, converted miles toward the next chest on the ladder,
  growth for everything planted in your grove, and whatever medals it has just
  earned: the race distance if the walk or run covered one, the ride or swim
  distance if it was one of those, the hour of the day if it was early or late,
  the week's own medal once the miles add up, and a lifetime milestone the
  first time the total passes one. That
  happens at sync time rather than when
  you next open the app, so the recap waiting for you was already written.
  Each activity converts at its own rate, which is why a mile swum is worth
  more than a mile cycled.

## The detail behind a workout

An export says more about a session than the numbers on its card, and tapping a
card opens a screen for the rest of it. Four arrays are read, one reading a
minute: how far the minute covered, how many steps it took, what the heart was
doing, and the active calories it burned. Four whole-session figures are read
beside them: how much the session climbed, the highest beat it saw, the
temperature, and the humidity.

That is what the splits, the zones, the graph and the line about the air are
drawn from. Two things worth knowing about it:

- There is no cadence array in an export, whatever a watch shows on its own
  screen. Steps in the minute is the reading that stands in for it, which is the
  same number on a walk or a run, so cadence is only ever drawn for those two.
- Nothing is fetched from a weather service, here or anywhere. The temperature
  and the humidity are whatever the export sent with the session, and a session
  that carried neither says nothing about the air.

None of it earns anything. No experience, no chest, no medal, no growth and no
manna reads a single one of these readings: they exist to be looked at. A
reading that is missing, malformed, or past what a body and a day produce is
dropped to nothing, field by field, and a workout never fails to import because
its arrays were odd.

## Steps

If the optional metrics automation is set up, the pedometer is read as well,
and only two of its metrics: your step count and your walking and running
distance.

Neither of them earns anything. Miles are the work put into a recorded
activity, so steps are worth no experience, no level, no chest, no growth in
your grove and no medal, and they are in no miles total on any screen. They are
stored and shown: your step count for the week on your own profile, a count in
the recap letter, and the instance-wide tally on the landing page. What steps
should become is an open question, and nothing is built toward an answer.

Two things follow, and both are deliberate:

- A day's reading only ever rises. Exports overlap, and a later one covering
  the same day keeps the higher number rather than replacing it, so a partial
  export of today cannot undo a fuller one.
- A day's reading is bounded before it is stored, because a confused sensor is
  free to send anything. A day that hit a bound is marked and nothing is
  refused.

Steps make no feed card and never will: they are ambient, and a card is
something somebody did.

Metrics carry no location data of any kind.

## Route data

If the automation sends route data, each workout carries a GPS trace and the
workout card draws it as a plain line. No map tiles are fetched, from here or
from anywhere: the line is the whole picture, and nothing about your workouts
leaves the server.

What is stored is never the trace as it arrived:

- Everything within 200 metres of the first point and within 200 metres of
  the last point is thrown away before anything is written. A stored route
  therefore starts and ends somewhere along the way rather than at a door.
  A loop that starts and ends at home can lose so much that nothing is left,
  and then nothing is stored, which is the right answer rather than a fault.
- The rest is thinned to at most 200 points and rounded to five decimal
  places, which is roughly a metre. A real run arrives with a few thousand
  points and is stored as a few kilobytes.
- A route is never a reason a workout fails to import. If the trace is
  missing, malformed, or unreadable, the workout lands as usual with no line.

Turning route data on later does not fill in the maps behind you. A sync that
sent no trace left none anywhere, and a stored payload has its route arrays
taken out before it is written, so there is nothing to read them back from.
Switch it on and the lines start with your next sync.

An instance old enough to hold payloads from before that stripping began still
has the traces inside them, and its administrator can draw those lines once with
`manage.py backfill-routes`. See [01-self-hosting.md](01-self-hosting.md).

## The only way in

Syncing is the only way a workout arrives. There is no form to type one into,
so anything that never reached Apple Health does not reach your history either.

An older version did have that form, and the workouts it wrote are still in the
history, still counted, and still marked as entered by hand. Where a workout
came from is a fact about it: taking the form away does not rewrite what was
already recorded.

## Android

The same endpoint, the same bearer token, a different shape on the wire.

Android has no Health Auto Export. What it has is bridge apps that read Health
Connect and POST to a webhook, and the one this is written for is [Health
Connect Webhook](https://github.com/mcnaveen/health-connect-webhook): free, open
source under AGPL-3.0 like this app, and on the Play Store. It can attach custom
headers per webhook, which is what lets it send the same `Authorization: bearer
<token>` line an iPhone sends.

Point it at `/api/ingest`, add the Authorization header, and enable five data
types: Exercise Sessions, Heart Rate, Active Calories, Steps, Distance. The
sessions become workouts; the other four fill in the per-minute detail, the heart
rate zones, and the calories manna is converted from.

The server tells the two shapes apart by looking at the payload rather than by
having two endpoints. An export the Apple reader can already understand is never
touched; one it cannot, carrying an array Health Connect names, is translated
into the Apple shape before anything else reads it. That translation lives in
`backend/app/healthconnect.py` and is the only part of the codebase that knows
Android exists. Everything downstream of it, from deduplication to chests to the
grove, cannot tell which phone a mile came from.

Two honest limits. There is no route line on an Android workout: Health Connect
has an exercise route API and the bridge does not export it, so those workouts
arrive without a map. And the bridge sends its arrays independently of its
sessions, at whatever resolution the phone chose, so each workout's detail is the
slice of each array that falls inside its own window, folded into one reading per
minute.

Any other client can sync too. The endpoint is plain JSON over HTTPS with a
bearer token, and it accepts either the Health Auto Export workout export or the
Health Connect Webhook envelope.
