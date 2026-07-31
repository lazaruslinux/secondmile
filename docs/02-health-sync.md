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

3. Set the automation to run on a schedule (daily is plenty) or trigger it
   manually after a workout.

Only walking, running, cycling, and swimming workouts are imported; other
types in the export are counted in the response but ignored.

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
  toward your level, converted miles toward the next chest, and whatever
  achievements it has just earned. That happens at sync time rather than when
  you next open the app, so the recap waiting for you was already written.
  Each activity converts at its own rate, which is why a mile swum is worth
  more than a mile cycled.

## Manual entry

The Almanac has a manual entry form for workouts that never reached Apple
Health. Manually entered workouts are stored with a marker saying so. They
count the same as synced ones today; the marker exists so that a future
public, multi-player version can treat unverifiable entries differently.

## Android

I have not built an Android path yet. The endpoint is plain JSON over HTTPS
with a bearer token, so anything that can POST that shape can sync; the
payload format it accepts is the Health Auto Export workout export.
