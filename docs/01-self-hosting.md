# Self-hosting

This walks through running secondmile on your own machine or server. It
assumes Docker with the compose plugin and nothing else.

## First run

1. Clone the repository and copy the environment file:

   ```
   cp .env.example .env
   ```

2. Open `.env` and fill in every value. Each variable is documented in the
   file itself, including the command to generate a real password. The
   backend checks for the placeholder values at startup and refuses to run
   until they are gone, so you cannot accidentally deploy with change-me as
   a database password.

3. Build and start everything:

   ```
   docker compose up -d --build
   ```

   The backend waits for Postgres to be healthy, applies any pending
   database migrations, and then starts. First build takes a few minutes.

4. Create the admin account and an invite:

   ```
   docker compose exec backend python manage.py create-admin yourname
   docker compose exec backend python manage.py create-invite
   ```

   The first command asks for a password and, optionally, an email address.
   The account it makes can sign in straight away: it was created by someone
   with a shell on the server, which is a better check than any email.

## How people get accounts

There are two modes, set by `REGISTRATION_OPEN` in `.env`.

**Invite-only (`false`, the default).** Every account after the first one
registers through the web form with a code from `create-invite`. Each code
works once and expires after two weeks by default.

**Open (`true`).** Anyone who can reach the site can sign up, and the invite
field disappears from the form. Worth knowing before you turn it on: a
publicly reachable sign-up form is found by bots, and every account it creates
is a row in your database.

Either way, a new account has to verify its email address before it can sign
in. Registration answers the same way whether or not it created anything, so
nobody can use the form to find out which usernames or addresses are taken.

## Email, or running without it

The verification link is built from `SITE_URL` and mailed through the `SMTP_*`
settings. Set `SITE_URL` to the address people actually type; a link built
from the wrong one opens nothing.

If `SMTP_HOST` is empty, nothing is mailed. The link is written to the backend
log instead:

```
docker compose logs backend | grep "Verification link"
```

That is a supported way to run a small instance: you register someone, read
their link out of the log, and send it to them however you already talk. If
even that is more than you want, mark the account verified directly:

```
docker compose exec backend python manage.py verify-email theirname
```

With a mail provider, the usual settings are the provider's host, port 587,
your SMTP username and password, and a `SMTP_FROM` on a domain the provider
has let you verify. Port 465 works too; the port decides whether TLS is
negotiated with STARTTLS or used from the first byte. Mail failures are logged
and never break a signup, so if a link does not arrive, check the backend log
first and have the person use the resend button on the sign-in screen.

## Progress, and rebuilding it

Experience, levels, chests, and achievements are all derived from the workout
history. Nothing is typed in and nothing is trusted from a browser: every
workout is credited exactly once, whether it arrived from a phone, from the
manual entry form, or was written straight into the database.

If you ever need to rebuild one account's progress from its workouts, for
instance after an upgrade that changed how something is counted, there is a
command for it:

```
docker compose exec backend python manage.py recompute-progress theirname
```

This clears that account's experience, level, chest counter, unopened chests,
and card album, and builds them again from the workouts. The workouts
themselves are never touched, so nothing anybody actually did is at risk.
Earned achievements are left exactly where they are: they are never revoked,
and anything the rebuilt history earns is added on top.

Replaying the same workouts produces the same chests in the same order,
because every roll is seeded on the account and the workout rather than on the
clock. A filled album is still thrown away and refound, though, and the cards
that come back will not be the ones that went in. Take a dump first if that
matters to the person whose account it is.

## Profile pictures

Avatars are files, not database rows. They live in the container at the path
`AVATAR_DIR` names, and the compose file mounts a named volume there so they
survive a rebuild. They are not in the Postgres dump: back the volume up
separately if you want to keep them.

```
docker compose cp backend:/data/avatars ./avatars-backup
```

Every upload is capped at 5 MB, decoded to prove it is really an image, and
re-encoded from its pixels into a 512 by 512 webp. What lands on disk is never
the file that was uploaded, carries no metadata or location, and is named after
the account rather than after anything the uploader chose.

## Putting it behind a domain

The app serves plain HTTP on `127.0.0.1:8110` and expects a reverse proxy in
front of it to terminate HTTPS. Any proxy works; a minimal Caddy site block
is:

```
game.example.com {
    reverse_proxy 127.0.0.1:8110
}
```

If you gate your services behind a forward-auth layer such as Authelia,
exempt `/api/ingest` from it. The phone posts workouts with its own bearer
token and cannot answer an interactive login.

A proxy like the one above adds a hop in front of the bundled nginx, so set
`TRUSTED_PROXY_HOPS=1` in `.env`. Without it the rate limiter sees your
proxy's address for every visitor and they all share one bucket; set it no
higher than the number of proxies you actually run.

## Backups

Everything that matters is in Postgres. A restorable dump:

```
docker compose exec db pg_dump -U secondmile -Fc secondmile > secondmile.dump
```

Restore with `pg_restore` into a fresh database. Take a dump before every
update; it is the difference between an annoying evening and a lost year of
workout history.

## Updating

```
git pull
docker compose up -d --build
```

Migrations run automatically at backend startup. Read the release notes
first; anything that needs more than the two commands above will say so.
