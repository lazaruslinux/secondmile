"""Shared fixtures.

Every test gets the real application wired to its own in-memory SQLite
database, so cases cannot see each other's rows and none of them needs a
running Postgres.
"""

import datetime as dt
import os
import sys

# Set before anything imports the app: settings read the environment once, at
# import, and the startup guard refuses an empty DATABASE_URL. The engine this
# URL builds is never used, because get_db is overridden per test.
os.environ.setdefault("DATABASE_URL", "sqlite://")
# The Secure attribute stops a cookie jar from sending a cookie back over plain
# http, which is every request the test client makes. Off here so sessions work;
# test_hardening turns it on to check the attribute is really emitted.
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("TZ", "UTC")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import activity as activity_rules  # noqa: E402
from app import config, grove, mail, models, progress, security, species, throttle  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

ADMIN = {"username": "admin", "password": "admin-password-1"}
MEMBER = {"username": "runner", "password": "runner-password-1"}

# The moment every test runs at. A Wednesday, so nothing sits on a week
# boundary, and 21:00 UTC because the whole suite's clock arithmetic hangs off
# it: see neutral_start below for why that hour and not another. Change this
# and test_clock.py says so.
FROZEN_NOW = dt.datetime(2026, 4, 15, 21, 0, tzinfo=dt.timezone.utc)

# The recap's keys, in the order it sends them. Shared because three files read
# the letter and a shape written down three times drifts in two of them.
LETTER_KEYS = [
    "since",
    "last_sync_at",
    "miles",
    "miles_total",
    "xp",
    "chests",
    "medals",
    "encouragement",
    "plant_growth",
    "workouts",
    "workouts_total",
    "flourish_stage",
    "flourish_rose",
]


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    """Pin now_utc, everywhere it is reachable, for the whole suite.

    Patching app.security alone would miss the modules that imported now_utc as
    a bound name, so this walks the imported app modules instead and patches
    whichever of them own the attribute. A module bound later picks it up for
    free, which a hand-written list of patch targets would not.

    The rate limiters are not covered and must not be: they read time.time on
    purpose, and their tests measure real windows.
    """
    for name, module in list(sys.modules.items()):
        if (name == "app" or name.startswith("app.")) and hasattr(module, "now_utc"):
            monkeypatch.setattr(module, "now_utc", lambda: FROZEN_NOW)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    # The limiters are process-global. Without clearing them, a test that spends
    # the login allowance makes the next test fail for reasons of its own.
    throttle.reset_limiters()
    yield
    throttle.reset_limiters()


@pytest.fixture()
def db_session():
    # StaticPool keeps one connection, and therefore one database, alive across
    # everything the app opens; without it each connection would get its own
    # empty in-memory database.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    # The sqlite driver manages transactions on its own terms and will not open
    # one until it sees DML, which leaves SAVEPOINT statements outside any
    # transaction and makes the ingest path's per-row rollback silently do
    # nothing. Taking transaction control away from the driver and issuing BEGIN
    # ourselves is the documented fix, and it is what makes the dedupe tests
    # exercise the same code path Postgres runs.
    @event.listens_for(engine, "connect")
    def _no_implicit_begin(dbapi_connection, record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _explicit_begin(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def outbox(monkeypatch) -> list[tuple[str, str]]:
    """Every verification mail the app tried to send, as (address, token).

    Patched at the module the router reaches through, so the background task
    the request schedules lands here instead of at a mail server. The token is
    the plaintext one, which is the only place a test can get it: the database
    keeps the hash.
    """
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mail, "send_verification", lambda address, token: sent.append((address, token))
    )
    return sent


@pytest.fixture()
def change_outbox(monkeypatch) -> list[tuple[str, str]]:
    """Every address-change link the app tried to send, as (address, token).

    A list of its own rather than the verification one: the two messages go to
    different places for different reasons, and a test that means to check one
    of them should not pass because the other was sent.
    """
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        mail, "send_email_change", lambda address, token: sent.append((address, token))
    )
    return sent


def make_user(
    db_session,
    username: str,
    password: str,
    *,
    is_admin: bool = False,
    email: str | None = None,
    verified: bool = True,
) -> models.User:
    # Verified by default: almost every test signs in, and an unverified account
    # cannot. The cases that care about verification ask for it explicitly.
    user = models.User(
        username=username,
        password_hash=security.hash_password(password),
        email=email,
        email_verified=verified,
        is_admin=is_admin,
        units="imperial",
        created_at=security.now_utc(),
    )
    db_session.add(user)
    db_session.commit()
    return user


def make_invite(db_session, created_by: int, *, days: int = 14) -> models.Invite:
    invite = models.Invite(
        code=security.generate_token(),
        created_by=created_by,
        created_at=security.now_utc(),
        expires_at=security.now_utc() + dt.timedelta(days=days),
    )
    db_session.add(invite)
    db_session.commit()
    return invite


@pytest.fixture()
def admin(db_session) -> models.User:
    return make_user(db_session, ADMIN["username"], ADMIN["password"], is_admin=True)


@pytest.fixture()
def invite(db_session, admin) -> models.Invite:
    return make_invite(db_session, admin.id)


@pytest.fixture()
def member(db_session, admin) -> models.User:
    return make_user(db_session, MEMBER["username"], MEMBER["password"])


@pytest.fixture()
def signed_in(client, member) -> TestClient:
    """A client holding a valid session cookie for the member account."""
    response = client.post("/api/auth/login", json=MEMBER)
    assert response.status_code == 204
    return client


@pytest.fixture(autouse=True)
def avatar_dir(tmp_path, monkeypatch):
    """Point avatar storage at a throwaway directory for every test.

    Autouse because the default is a path the compose file mounts a volume at,
    and a test suite that writes there would be writing outside its own sandbox.
    """
    target = tmp_path / "avatars"
    monkeypatch.setattr(config.settings, "avatar_dir", str(target))
    return target


@pytest.fixture(autouse=True)
def photo_dir(tmp_path, monkeypatch):
    """Point workout photo storage at a throwaway directory, autouse for the
    same reason the avatar one is."""
    target = tmp_path / "photos"
    monkeypatch.setattr(config.settings, "photo_dir", str(target))
    return target


@pytest.fixture(autouse=True)
def video_dir(tmp_path, monkeypatch):
    """And the videos, on the same terms. Autouse as well, because the encoder
    writes its working copies here too: a case that uploaded one without this
    would be writing a hundred megabytes into a mounted volume's default path.
    """
    target = tmp_path / "videos"
    monkeypatch.setattr(config.settings, "video_dir", str(target))
    return target


def neutral_start() -> dt.datetime:
    """Half a day ago, snapped to mid-morning in the instance timezone.

    Recent enough to be this week, and at an hour no time-of-day medal is
    earned in, so a case about a distance is never also a case about a clock.

    The formula reads the clock, but the clock is pinned: frozen_clock holds
    now_utc at FROZEN_NOW, 2026-04-15 21:00 UTC, so this lands on Wednesday
    2026-04-15 09:00 UTC every run. 21:00 is what makes the hour work out. The
    largest offset_min any case passes to log_workout is 600, which puts the
    latest start at 19:00, still in the past of now and still short of the
    Night Owl window at [20:00, 04:00); 09:00 itself is clear of Early Riser at
    [04:00, 06:00). Wednesday keeps the start and the frozen now in the same
    Monday-started week, which is what the weekly cases count.

    Clamping the date onto Monday does not fix a Monday and makes it worse. The
    hour then has to move back too, to stay in the past, and everything before
    four in the morning is inside the Night Owl window, so runs start earning a
    time medal and ten cases fail instead of one. Tried 2026-08-09, reverted.
    """
    local = (security.now_utc() - dt.timedelta(hours=12)).astimezone(config.SERVER_TZ)
    return dt.datetime.combine(local.date(), dt.time(9, 0), tzinfo=config.SERVER_TZ)


def let_a_moment_pass(db_session, seconds: int = 1) -> None:
    """Age everything already stored, because the pinned clock cannot move.

    The recap covers what arrived strictly after the last acknowledgement. Real
    time always advances between the request that clears the letter and
    whatever the account does next, so those two moments are never the same
    one. The frozen clock never advances, so a case that means "and then this
    happened" has to say so, and pushing what already exists into the past
    reads the same way round from the app's side.

    Every timestamp column of every table rather than the few the recap looks
    at, so a column added later does not quietly stay behind and make one case
    fail with no visible cause.
    """
    delta = dt.timedelta(seconds=seconds)
    for mapper in Base.registry.mappers:
        columns = [c.key for c in mapper.columns if isinstance(c.type, models.UtcDateTime)]
        if not columns:
            continue
        for row in db_session.query(mapper.class_).all():
            for name in columns:
                stamp = getattr(row, name)
                if stamp is not None:
                    setattr(row, name, stamp - delta)
    db_session.commit()


def log_workout(
    db_session, user_id: int, activity="run", miles=1.0, *, pace_min=12.0, offset_min=0
) -> models.Workout:
    """One workout written straight in and credited, the way a sync would.

    Start times are spread by the offset so two workouts in one test never
    collide on the dedupe key. The flags and the crediting are the ingest
    path's own, in the order it does them: a shortcut that skipped either would
    let cases pass against a row the app itself never produces.
    """
    start = neutral_start() + dt.timedelta(minutes=offset_min)
    duration_s = max(600, int(miles * pace_min * 60))
    flags = {}
    if activity_rules.impossible_pace(activity, duration_s, miles):
        flags["impossible_pace"] = True
    row = models.Workout(
        user_id=user_id,
        activity=activity,
        start_ts=start,
        duration_s=duration_s,
        distance_mi=miles,
        active_kcal=0.0,
        avg_hr=None,
        source="sync",
        flags=flags,
        created_at=security.now_utc(),
    )
    db_session.add(row)
    db_session.commit()
    # Judged after the insert, so the workout that crosses the line is the one
    # marked, exactly as the sync path judges it.
    if activity_rules.over_daily_cap(db_session, user_id, activity, start):
        row.flags = {**flags, "daily_cap": True}
        db_session.commit()
    progress.process_user(db_session, user_id)
    return row


def give_planting(db_session, user_id: int, species_id="strawberry", *, growth=0.0, days_ago=1):
    """One thing already in the ground. Shared because the plot is read from the
    grove, the letter, and the profile, and all three want the same shortcut."""
    row = models.Planting(
        user_id=user_id,
        species=species_id,
        rarity=species.BY_ID[species_id].rarity,
        planted_at=security.now_utc() - dt.timedelta(days=days_ago),
        growth_mi=growth,
        matured_at=None,
        # A plant that has been standing there a while, so whatever it has
        # already grown is old news and only what a case does next is news.
        level_at_ack=grove.level_for(species_id, growth),
    )
    db_session.add(row)
    db_session.commit()
    return row


def give_item(db_session, user_id: int, kind: str, species_id: str | None = None, rarity="common"):
    """One thing in the satchel, however it got there. Shared for the reason
    the planting above is: the letter reads what water did to a plot too."""
    row = models.SatchelItem(
        user_id=user_id,
        kind=kind,
        species=species_id,
        rarity=rarity,
        chest_id=None,
        acquired_at=security.now_utc(),
        used_at=None,
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def ingest_token(signed_in) -> str:
    response = signed_in.post("/api/settings/ingest-token/rotate")
    assert response.status_code == 200
    return response.json()["token"]
