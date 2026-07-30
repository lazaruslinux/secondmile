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

   Registration is invite-only. Every account after the first one registers
   through the web form with a code from `create-invite`; each code works
   once.

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
