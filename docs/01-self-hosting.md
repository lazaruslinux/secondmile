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
registers through the web form with a code. There are two kinds, and both work
exactly once.

- `create-invite` makes one from the command line. It expires after two weeks
  by default, and it is an account gate and nothing more: whoever claims it is
  nobody's friend afterwards.
- Any signed-in member can mint an **invite link** from the Friends screen. It
  never expires, it can be revoked while it is still waiting, and it opens a
  welcome page naming whoever sent it. Claiming one makes the two accounts
  friends, because a member sends it to somebody they already know.

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
their link out of the log, and send it to them however you already talk.

Adding or changing the address on an account, from Settings, works the same
way. The link goes to the new address, it lands in the same log line without a
mail server, and the account keeps the address it has until somebody opens it.

If even that is more than you want, mark the account verified directly:

```
docker compose exec backend python manage.py verify-email theirname
```

With a mail provider, the usual settings are the provider's host, port 587,
your SMTP username and password, and a `SMTP_FROM` on a domain the provider
has let you verify. Port 465 works too; the port decides whether TLS is
negotiated with STARTTLS or used from the first byte. Mail failures are logged
and never break a signup, so if a link does not arrive, check the backend log
first and have the person use the resend button on the sign-in screen.

## Push notifications, or running without them

When a sync lands new workouts, subscribed devices get one notification about
it. The feature needs a VAPID keypair; leave `VAPID_PRIVATE_KEY` empty and
push is simply off, which is a supported way to run. To turn it on, generate a
key once with the command in `.env.example`, set `VAPID_PRIVATE_KEY` and
`VAPID_SUBJECT`, and restart. Each person then turns their own devices on from
Settings. On an iPhone the site has to be added to the Home Screen first;
that is the platform's rule for web push, not this app's.

## Progress, and rebuilding it

Experience, levels, chests, and medals are all derived from the
workout history. Nothing is typed in and nothing is trusted from a browser: every
workout is credited exactly once, whether it arrived from a phone or was
written straight into the database.

If you ever need to rebuild one account's progress from its workouts, for
instance after an upgrade that changed how something is counted, there is a
command for it:

```
docker compose exec backend python manage.py recompute-progress theirname
```

This clears that account's experience, level, chest ladder, earned chests, the
growth in its plot, and its medals, and builds them all again from the
workouts. The workouts themselves are never touched, so nothing anybody
actually did is at risk. Medals come back with the dates of the runs and weeks
that earned them, so running this is also how a history that predates a medal
family earns it.

Nothing anybody chose is rebuilt either. What is in the satchel, what has been
planted, and every anointing given or received stay exactly as they are, and a
chest that came out of somebody else's potion is left alone with them.

Replaying the same workouts produces the same chests in the same order, because
the ladder is fixed. Chests that were already opened do come back closed,
though, and opening them again hands out items all over again. Take a dump
first, and do not run this casually on an account with a full satchel.

There are two narrower commands for the cases where a rebuild is more than you
need. Neither touches chests, the plot, or experience:

```
docker compose exec backend python manage.py backfill-badges theirname
docker compose exec backend python manage.py backfill-routes theirname
```

The first awards the medals an already-credited history has earned, in every
family, and is the tool to reach for after an upgrade that adds one. The second
draws route lines for workouts that have no line yet, from any payloads the
ingest log still holds. Both are safe to run twice.

The ingest log keeps each sync's payload for 90 days and strips the GPS route
arrays before storing, so routes exist only in their own trimmed table. On an
instance that predates this behavior, run backfill-routes first if any history
lacks lines, then once:

```
docker compose exec backend python manage.py strip-ingest-log
```

It strips the route arrays from every stored payload, deletes rows past the
retention window, and prints what it did. Safe to run twice.

Members can report a bug from the bottom of their Settings screen. There is no
web page for what they send: the reports are read from the command line, newest
first, and nothing marks one as seen.

```
docker compose exec backend python manage.py bug-reports --limit 20
```

Each one prints when it arrived, who sent it, which screen they were on, the
front of their browser string, and what they typed. The account, the moment and
the browser string are taken from the request rather than typed, and the
Settings card says exactly that before anybody sends anything.

A deleted workout keeps the same kind of window. Deleting one hides it
everywhere and takes its miles back out of the totals; it waits under Deleted
on the owner's Activity tab for 30 days and can be restored whole until then.
After that, its photos, video, route line, words and everything said about it are
purged on that account's next sync. The workout row itself is kept forever,
holding nothing but the date and duration the sync deduplicates on, so a phone
exporting old history cannot import the same session again.

## Pictures and video

Avatars, workout photos, and workout videos are files, not database rows. They
live in the container at the paths `AVATAR_DIR`, `PHOTO_DIR`, and `VIDEO_DIR`
name, and the compose file mounts a named volume at each so they survive a
rebuild. They are not in the Postgres dump: back all three volumes up
separately if you want to keep them.

```
docker compose cp backend:/data/avatars ./avatars-backup
docker compose cp backend:/data/photos ./photos-backup
docker compose cp backend:/data/videos ./videos-backup
```

Every avatar upload is capped at 5 MB, decoded to prove it is really an image,
and re-encoded from its pixels into a 512 by 512 webp. Workout photos get the
same treatment at 10 MB and a 1600 pixel longest edge. What lands on disk is
never the file that was uploaded, carries no metadata or location, and is
named by the server rather than after anything the uploader chose.

A workout may also carry one video, and photos and videos share six slots
between them. A video is capped at 100 MB and about a minute of running time,
which is measured before anything is encoded, and it is then re-encoded to an
H.264 mp4 no larger than 720p on its shorter edge, with a poster frame cut
beside it. The same rule holds as for the pictures: what lands on disk is a
file this server built, with the camera, the date, and the GPS position gone.

That re-encoding is why **ffmpeg is installed in the backend image**. It is
the only part of the app that is not a Python package, it is installed from
the base image's own distribution, and both `ffmpeg` and `ffprobe` are used:
one to read the length of an upload before accepting it, the other to encode
what is kept. The encode happens while the upload request is still open, so a
slow machine makes the upload button wait rather than failing; a minute of
720p is a couple of seconds of work on an ordinary desktop.

## The basemap behind a route

Optional. Tapping a route in the app opens it on a map, and that map is drawn
from one file you cut yourself and your own nginx serves. Nothing about it
reaches a tile company: no keys, no accounts, no request leaving your server.
Without the file the map still opens, the route still draws, and a quiet line
under it says there is no basemap installed.

The fonts and the icons are already in the build. The tiles are not, because a
useful extract runs to hundreds of megabytes and only you know which part of
the world your routes are in.

Install [pmtiles](https://github.com/protomaps/go-pmtiles/releases), then cut
your area out of a daily planet build. The build is read over the network by
byte range, so this downloads the region rather than the planet:

```
mkdir -p tiles
pmtiles extract https://build.protomaps.com/20260801.pmtiles tiles/basemap.pmtiles \
  --bbox=-115.0,31.3,-109.0,37.1
```

Use a date that exists in the [build list](https://maps.protomaps.com/builds/).
The bbox is west, south, east, north in degrees; the one above is roughly
Arizona and lands near half a gigabyte. Then pick the frontend up again:

```
docker compose up -d frontend
```

The compose file mounts `tiles/` into the frontend container read-only, so the
archive is served without being baked into an image, and the directory is
gitignored so it never reaches a repository. The filename is deliberately
plain: to widen the coverage later, cut a bigger extract, drop it in as
`tiles/basemap.pmtiles`, and restart the frontend. No rebuild, no code.

Coverage is exactly what you cut. A route outside the bbox draws over an empty
background rather than failing, so a wider extract is the only fix for a
holiday.

The tiles are OpenStreetMap data under the ODbL, which asks for the credit. The
map carries it in the corner; leave it there.

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
