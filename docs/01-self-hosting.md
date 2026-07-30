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
