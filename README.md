# secondmile

A self-hosted fitness app with a game inside it. Miles you actually walk, run,
cycle, or swim sync from your phone and become experience, collectible cards,
and badges on a profile you build over months. The game is early: accounts,
workout sync, the Almanac, the profile with its levels and achievements, and
the card collection work today, and the rest is being built on top of them.

Current version: **0.1.1**. Releases are tagged in git.

## What it does

- **Syncs your workouts.** An ingest endpoint accepts workout exports from
  Health Auto Export on iPhone: walking, running, cycling, and swimming, with
  distance, duration, active calories, and average heart rate. Syncing is
  idempotent, so overlapping export windows never double-count a workout.
  There is a manual entry form for anything that did not come from a watch.
- **Keeps the Almanac.** A history of everything you have done, grouped by
  week, with totals per activity. Manually entered workouts are marked as
  such, and workouts with impossible numbers (a four minute mile, a fifty
  mile walk) are imported but flagged rather than trusted.
- **Turns those miles into a profile.** Experience is the distance itself, and
  each activity converts at its own rate, so an hour in the pool is not an hour
  on a bike and a swimmer is never shortchanged. The levels are the race
  ladder: a 5K, then a 10K, then a half, then a marathon, and a marathon more
  every level after that. Levels grow the border around your picture, and the
  badges you have chosen sit in fixed slots around it. Weekly and lifetime
  totals are worn on the profile. There are no leaderboards of raw miles and
  there never will be: profiles celebrate, they do not rank.
- **Keeps an endless list of things to earn.** Race badges for a single run
  that covers 5K, 10K, half marathon, marathon, or ultra distance, earned again
  every time you do it and counted on the profile. Achievements for a big week
  and for finishing a set of cards. Weekly targets have a second, visibly finer
  version, earned by voluntarily doubling the target inside the same week.
  Achievements are never taken away.
- **Drops chests, and chests hold cards.** Every few converted miles a chest
  appears, carrying one card from one of four nature collections. The album is
  a field guide: plates you have not found yet show only a number and a
  rarity. Walked miles find extra chests, cards cannot be bought with
  anything, chests never expire, and there is no daily anything. Moving your
  body is the only way to fill a page.
- **Multi-user from day one.** Accounts are invite-only out of the box: the
  server admin creates invites from the command line. Flip `REGISTRATION_OPEN`
  and anyone who can reach the site can sign up instead. Either way a new
  account has to verify its email address before it can sign in, and an
  instance with no mail server configured writes the verification link to the
  backend log instead of sending it.

## Where it is going

The synced miles are the fuel for a game in active development. The short
version of the design:

- Friends and a home feed, so the week you had is something you share rather
  than something you rank.
- Each activity has its own role, and no activity substitutes for another.
- The economy is built so that giving feels better than keeping. Serving
  others is meant to be the winning strategy, and the best things in the
  game will be earned by service, not bought.
- Rest is part of the design, not a failure state. Nothing breaks because
  you took a day off, and nothing rewards you for opening the app. Everything
  accrues while you are away.

The name comes from an old teaching about going farther than you were asked
to. The game never explains it, and neither will I.

## How it fits together

```
phone (Health Auto Export) --- POST /api/ingest ---.
                                                   |
browser --- your reverse proxy (HTTPS) --- [ frontend nginx :8110 ]
                                                   |
                                        /api proxied to
                                                   |
                                          [ backend FastAPI ]
                                                   |
                                            [ PostgreSQL ]
```

The compose file publishes two localhost-only ports: 8110 for the app and
8100 for the raw API. Nothing listens on the LAN or the internet until you
put your own reverse proxy in front of it.

## Quick start

1. Install Docker with the compose plugin.
2. `cp .env.example .env` and fill in every value. The backend refuses to
   start while any placeholder is left.
3. `docker compose up -d --build`
4. Create your account:

   ```
   docker compose exec backend python manage.py create-admin yourname
   docker compose exec backend python manage.py create-invite
   ```

   The first command prompts for a password and an optional email address,
   and the account it makes is verified already. Invites are one-time codes
   for the registration page; everyone who registers there gets a
   verification link by email before they can sign in.
5. Open http://127.0.0.1:8110, or point your reverse proxy at that port and
   use your own domain.

To see the app with data in it before any real workout has synced:

```
docker compose exec backend python manage.py seed-demo
```

The demo user and its workouts are fictional, and the seeder refuses to run
on a database that already has real accounts.

## Syncing workouts

See [docs/02-health-sync.md](docs/02-health-sync.md). The short version: the
Settings screen gives you a bearer token, and you point Health Auto Export at
`https://your-domain/api/ingest` with that token in the Authorization header.

## Configuration

Everything configurable lives in `.env`, and every variable is documented in
[.env.example](.env.example). Runtime things that are not secrets (units, your
ingest token) live in the app's Settings screen instead of a file.

Two of them decide how people get accounts:

- `REGISTRATION_OPEN` is false by default, which keeps registration to people
  holding an invite code. Set it to true for an instance anyone may join.
- The `SMTP_*` block and `SITE_URL` are how the verification email gets sent
  and where its link points. Leaving `SMTP_HOST` empty is a supported setup,
  not a broken one: see [docs/01-self-hosting.md](docs/01-self-hosting.md) for
  running without a mail server.

## Security model

- Passwords are hashed with Argon2id. Sessions are opaque random tokens
  stored server-side and delivered in an httpOnly, secure, same-site cookie,
  so a leaked database dump does not contain usable sessions.
- Login, registration, ingest, password changes, and verification resends are
  rate limited per address.
- The ingest endpoint authenticates with a per-user bearer token that can be
  rotated from Settings at any time. Tokens are stored hashed.
- Registration is invite-only unless you open it, and either way an account
  cannot sign in until it has answered a verification link. Verification
  tokens are random, stored hashed, good for 24 hours, and spent on first use.
- Registration answers the same way whether it created an account or the
  username or address was already taken, so the form cannot be used to find
  out who has an account here. Sign in gives one message for every kind of
  failure, and the unverified check runs after the password check so it can
  never confirm a password.
- Suspicious workouts are flagged, never silently trusted: impossible paces
  and days that blow past the configured distance caps are marked in the
  Almanac.
- Uploaded profile pictures are refused above 5 MB before anything decodes
  them, then decoded to prove they really are images, then re-encoded from
  their pixels to a 512 by 512 webp. The original bytes are never stored or
  served, all metadata including location is dropped, and the file name comes
  from the account rather than from the upload.
- Experience, levels, badges, achievements, and chest drops are computed on the
  server from synced workouts alone. There is no client input that can grant
  any of them.
- The containers run unprivileged, base images are digest-pinned, Python
  dependencies are hash-locked, and CI runs a known-vulnerability audit on
  every push.

If you find a security problem, see [SECURITY.md](SECURITY.md).

## Repository layout

```
backend/     FastAPI application, migrations, tests, manage.py CLI
frontend/    Vite + React app, served by nginx in production
docs/        Self-hosting, health sync, and artwork guides
```

## Development

```
cd backend
python -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements.txt
pip install -r requirements-dev.txt
pytest -q

cd frontend
npm ci
npm run dev
```

Tests run against SQLite so they need no running database. CI runs ruff,
pytest, pip-audit, the frontend typecheck and build, and npm audit on every
push.

## License

GNU AGPL-3.0. See [LICENSE](LICENSE). Copyright (c) 2026 Lazarus Labs.

In plain terms: you can run it, change it, and share it, but if you host a
modified version for other people you have to share your changes with them
too. That is the point; this project exists so people can own their own
software.

## A note on how this was built

This project was built with Claude Code. The code was largely written by the
AI; I specified what it should do, reviewed and corrected it, tested it, and
made the design and operational calls. I run it and I am responsible for it.
