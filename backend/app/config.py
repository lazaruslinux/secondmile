"""Settings, tunable thresholds, and the guard that refuses a placeholder install."""

import datetime as dt
import logging
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("secondmile.config")

# Reported at GET /api/status and kept in step with the frontend's package.json
# and the README whenever a release round bumps it.
APP_VERSION = "0.1.0"
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

    # Timezone used to group workouts into days and weeks. Everything is stored
    # in UTC; this only decides where the day boundaries fall for the Almanac
    # and for the daily distance caps.
    tz: str = "UTC"

    daily_cap_walk_mi: float = 40.0
    daily_cap_run_mi: float = 40.0
    daily_cap_cycle_mi: float = 200.0
    daily_cap_swim_mi: float = 10.0


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
