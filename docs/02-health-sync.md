# Syncing workouts from Apple Health

secondmile ingests workouts through Health Auto Export, an iPhone app that
reads Apple Health and posts JSON to a URL you choose. Anything that records
a workout to Apple Health (an Apple Watch, most fitness apps) flows through
it.

## Setting it up

1. Log in to secondmile, open Settings, and generate your ingest token. Copy
   it now; the server stores only a hash, so it is shown once. You can
   rotate it here any time, which invalidates the old one.

2. In Health Auto Export, create a new REST API automation:

   - URL: `https://your-domain/api/ingest`
   - Method: POST
   - Headers: `Authorization: Bearer <your token>`
   - Data type: Workouts
   - Format: JSON
   - Include Route Data: on, if you want the map line on your workout
     cards. It is optional; everything else works the same without it.

3. Set the automation to run on a schedule (daily is plenty) or trigger it
   manually after a workout.

4. Optionally, add a second automation with the same URL, method, headers and
   format, and the data type Health Metrics; under Select Health Metrics turn
   everything off and pick Step Count and Walking + Running Distance. Health
   Auto Export takes one data type per automation, which is the only reason
   there are two. This one earns nothing and only feeds the step counts on the
   screens: see Steps below. Everything the app rewards arrives through the
   workouts automation alone.

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
- The raw payload of every ingest call is kept in the database, so if a
  parsing bug ever drops a field, the history can be replayed after the fix
  instead of being lost.
- Workouts with impossible numbers (a sub four minute mile, cycling past the
  configured daily cap) are imported but flagged, and the Almanac shows the
  flag. Nothing is rejected; the flags exist so bad data never silently
  becomes progress.
- Every imported workout is credited to your profile straight away: experience
  toward your level, converted miles toward the next chest on the ladder,
  growth for everything planted in your plot, and whatever medals it has just
  earned: the race distance if the walk or run covered one, the ride or swim
  distance if it was one of those, the hour of the day if it was early or late,
  the week's own medal once the miles add up, and a lifetime milestone the
  first time the total passes one. That
  happens at sync time rather than when
  you next open the app, so the recap waiting for you was already written.
  Each activity converts at its own rate, which is why a mile swum is worth
  more than a mile cycled.

## Steps

If the optional metrics automation is set up, the pedometer is read as well,
and only two of its metrics: your step count and your walking and running
distance.

Neither of them earns anything. Miles are the work put into a recorded
activity, so steps are worth no experience, no level, no chest, no growth in
your plot and no medal, and they are in no miles total on any screen. They are
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

Turning route data on later does not lose the earlier maps. The raw payload of
every sync is kept, so the lines for workouts already in your history can be
drawn from it:

    docker compose exec backend python manage.py backfill-routes yourname

It only fills in workouts that have no line yet, and it changes nothing else,
so running it twice is the same as running it once.

## The only way in

Syncing is the only way a workout arrives. There is no form to type one into,
so anything that never reached Apple Health does not reach the Almanac either.

An older version did have that form, and the workouts it wrote are still in the
history, still counted, and still marked as entered by hand. Where a workout
came from is a fact about it: taking the form away does not rewrite what was
already recorded.

## Android

I have not built an Android path yet. The endpoint is plain JSON over HTTPS
with a bearer token, so anything that can POST that shape can sync; the
payload format it accepts is the Health Auto Export workout export.
