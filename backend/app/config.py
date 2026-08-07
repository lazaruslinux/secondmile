"""Settings, tunable thresholds, and the guard that refuses a placeholder install."""

import datetime as dt
import logging
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("secondmile.config")

# Reported at GET /api/status and kept in step with the frontend's package.json
# and the README whenever a release round bumps it.
APP_VERSION = "0.1.1"
APP_NAME = "secondmile"


class Settings(BaseSettings):
    # Field names map to upper-case environment variables, so session_hours
    # reads SESSION_HOURS. Every one of these is documented in .env.example;
    # keep the two in step.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""

    # Whether the session cookie carries the Secure attribute. True by default
    # because the wrong default here leaks sessions over plain HTTP, and a
    # self-hoster who has not thought about it should get the safe behaviour.
    cookie_secure: bool = True
    session_hours: int = 720

    # Whether anyone who can reach the site may create an account. False keeps
    # the instance invite-only. It is the default because an open form on a
    # public URL is found by bots within days, and turning it on is a decision
    # the person running the server should have to make on purpose.
    registration_open: bool = False

    # Where the verification link points. Getting this wrong produces links
    # that work from the machine you tested on and nowhere else, so it is the
    # first thing to check when a verification mail arrives and the link does
    # not open the app.
    site_url: str = "http://127.0.0.1:8110"

    # Outbound mail. An empty smtp_host is a supported configuration, not a
    # broken one: the verification link is written to the backend log instead,
    # which is enough for an instance whose accounts are all made by people the
    # admin can hand a link to.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""

    # Timezone used to group workouts into days and weeks. Everything is stored
    # in UTC; this only decides where the day boundaries fall for the Almanac
    # and for the daily distance caps.
    tz: str = "UTC"

    # Where re-encoded profile pictures are written. The default is the path
    # the compose file mounts a named volume at, so avatars survive a rebuild
    # without anybody having to configure anything. Files here are named from
    # the account id and never from anything the uploader sent.
    avatar_dir: str = "/data/avatars"

    daily_cap_walk_mi: float = 40.0
    daily_cap_run_mi: float = 40.0
    daily_cap_cycle_mi: float = 200.0
    daily_cap_swim_mi: float = 10.0

    # How many proxies of your own sit in front of this app. Zero means the one
    # the compose file ships. See client_address in app/throttle.py for what the
    # number does and why getting it wrong is a rate-limiting hole.
    trusted_proxy_hops: int = 0


settings = Settings()


def _load_timezone(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # A missing zone must not take the server down: UTC still groups days
        # correctly, just possibly on the wrong boundary. Warn loudly instead,
        # because silently shifted week totals are hard to notice and harder to
        # explain. Slim base images sometimes ship without the zone database.
        log.warning("Unknown timezone %r; falling back to UTC for day grouping", name)
        return dt.timezone.utc


SERVER_TZ = _load_timezone(settings.tz)


# Soft-flag thresholds. These are not rejections: anything past them is still
# imported, just marked, so a miskeyed manual entry or a confused watch never
# silently becomes progress. Generous on purpose, because a false flag on a
# real effort is worse than a missed flag on a fake one.
MIN_PACE_MIN_PER_MI = 4.0  # applies to walking and running
MAX_CYCLE_SPEED_MPH = 30.0
MAX_SWIM_SPEED_MPH = 5.0


# Hard bounds, which the soft flags above are not. Anything past one of these is
# not a workout somebody had a strange day doing, it is a broken export or a
# deliberate one, and it never becomes a row: the progress pipeline reads every
# row an account owns on every request, so one impossible number stored today is
# an account that cannot load tomorrow. Generous enough that no real effort is
# refused; a 48 hour ultra and a thousand mile day are both already past what a
# body does.
MAX_WORKOUT_DISTANCE_MI = 1000.0
MAX_WORKOUT_DURATION_S = 172800
MAX_WORKOUT_KCAL = 50000.0
MIN_WORKOUT_HR = 20.0
MAX_WORKOUT_HR = 300.0


# How far one raw mile of each activity carries the marker, in Miles. Effort
# equivalence rather than distance: an hour of swimming is not an hour of
# cycling, and the world is priced in effort. These live in code and not in the
# environment on purpose. They are game balance, not deployment configuration,
# and an instance that quietly tripled its own rates would not be playing the
# same game as anybody else.
MILES_PER_RAW = {"walk": 1.0, "run": 1.0, "cycle": 1.0 / 3.0, "swim": 4.0}

# A chest drops every this many travelled Miles, rolled fresh after each one so
# the next is never countable. The low end is what stops a short walk feeling
# pointless; the high end is what stops chests feeling like change from a till.
CHEST_SPACING_MI = (2.0, 4.0)

# Walking's role in the world is gathering, and this is it: every completed
# walked mile rolls once for a chest on top of whatever the distance already
# earned. Running past the same hedge finds nothing.
WALK_BONUS_CHEST_CHANCE = 0.10

# Duplicate protection. A card the player does not own yet is this many times
# more likely to come out of a chest than one they already have. Not a
# guarantee: a set finished by attrition is a different feeling from one
# finished by luck, and the last plate should still be worth waiting for.
UNOWNED_CARD_WEIGHT = 3.0


# Experience. A workout is worth its converted Miles at this rate plus a point
# for every active minute, so an hour in the pool and an hour on a bike are
# both worth an hour even before the distance conversion has its say. Nothing
# but synced or manually entered movement ever produces any of it.
XP_PER_MILE = 10.0
XP_PER_MINUTE = 1.0

# The level curve. Reaching level n costs LEVEL_STEP_XP * n beyond level n - 1,
# so the levels get further apart forever and the border tiers below are spaced
# to match. Everyone starts at level 1 with nothing.
LEVEL_STEP_XP = 100

# The level each border tier arrives at, in order. Six files, six tiers, and a
# player is on the highest tier whose level they have passed.
BORDER_LEVELS = (1, 5, 10, 20, 35, 50)

# How many badges a player may wear around their avatar. Fixed slots, and the
# picture is never covered, so this is a layout constant as much as a rule.
MAX_DISPLAYED_BADGES = 4

# Avatar upload limits. The byte cap is checked against Content-Length and then
# again while reading, because a client is free to lie in the header. The pixel
# cap is the decompression-bomb guard: a small file can declare an enormous
# canvas, and Pillow will happily try to allocate it.
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 25_000_000
AVATAR_SIZE = 512

# Request body ceilings, enforced by the app itself so an install that fronts
# uvicorn with something other than the bundled proxy, or with nothing, still
# has one. The default sits just above the avatar cap so that endpoint keeps
# refusing in its own words; sync gets far more room because a phone's export
# carries sample arrays and a first catch-up can cover years.
MAX_BODY_BYTES = 6 * 1024 * 1024
MAX_INGEST_BODY_BYTES = 15 * 1024 * 1024

# How many workout entries one export may carry. The byte cap above bounds the
# body, not the entry count, and an export of tiny entries is a request that
# asks the server for one savepoint and one insert each. Years of catching up
# for four activities does not come close to this.
MAX_INGEST_WORKOUTS = 2000


def daily_cap_mi(activity: str) -> float:
    """The configured daily distance ceiling for one activity, in miles."""
    return {
        "walk": settings.daily_cap_walk_mi,
        "run": settings.daily_cap_run_mi,
        "cycle": settings.daily_cap_cycle_mi,
        "swim": settings.daily_cap_swim_mi,
    }[activity]


# The placeholder values shipped in .env.example. An install still using one is
# readable by anyone who can read the public source, so startup refuses it.
_PLACEHOLDER = "change-me"


def check_deploy_config() -> None:
    """Refuse to start while .env still holds the placeholder secrets.

    Called once when the app is imported, and again at the top of the migration
    environment, so a misconfigured install gets a plain-language fix rather
    than a database driver traceback several layers down.
    """
    problems = []
    if not settings.database_url:
        problems.append("DATABASE_URL is empty. Copy .env.example to .env and fill it in.")
    elif _PLACEHOLDER in settings.database_url:
        problems.append(
            "DATABASE_URL still contains the placeholder database password.\n"
            "Generate one with: openssl rand -hex 24\n"
            "then put the same value in POSTGRES_PASSWORD and in DATABASE_URL."
        )
    # Not a Settings field: only the database container needs this one, and the
    # backend merely receives it through compose's env_file. Checking it here
    # anyway catches the fix-one-forget-the-other mistake, which matters because
    # Postgres freezes the password it was first initialised with into the
    # volume and changing it afterwards is a chore.
    if os.environ.get("POSTGRES_PASSWORD", "") == _PLACEHOLDER:
        problems.append(
            "POSTGRES_PASSWORD in .env is still the placeholder. Pick a real one\n"
            "and use the same value in DATABASE_URL."
        )
    if problems:
        raise SystemExit(
            f"{APP_NAME} refused to start: insecure or incomplete configuration.\n\n"
            + "\n\n".join(problems)
        )
