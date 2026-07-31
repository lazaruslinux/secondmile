"""Shared fixtures.

Every test gets the real application wired to its own in-memory SQLite
database, so cases cannot see each other's rows and none of them needs a
running Postgres.
"""

import datetime as dt
import os

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

from app import mail, models, security, throttle, world  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

ADMIN = {"username": "admin", "password": "admin-password-1"}
MEMBER = {"username": "runner", "password": "runner-password-1"}


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


def start_journey(
    db_session,
    user_id: int,
    *,
    days_ago: float = 1.0,
    destination_id: str | None = world.START_DESTINATION,
) -> models.Journey:
    """Give an account a journey that began before the test's workouts.

    Registration does this for real accounts. Tests that make a user directly
    have to ask for it, because a journey starting now would ignore every
    workout the test then posts, which is exactly the behaviour the engine is
    supposed to have.
    """
    started = security.now_utc() - dt.timedelta(days=days_ago)
    row = models.Journey(
        user_id=user_id,
        location_id=world.START_LOCATION,
        road_id=None,
        position_mi=0.0,
        destination_id=destination_id,
        next_chest_mi=None,
        traveled_mi=0.0,
        started_at=started,
        updated_at=started,
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def traveller(signed_in, db_session, member) -> TestClient:
    """A signed-in member whose journey started yesterday at the Homestead."""
    start_journey(db_session, member.id)
    return signed_in


def log_workout(client, activity="run", miles=1.0, *, pace_min=12.0, offset_min=0) -> dict:
    """Post one manual workout inside the journey window, and return it.

    Start times are spread by the offset so two workouts in one test never
    collide on the dedupe key.
    """
    start = security.now_utc() - dt.timedelta(hours=12) + dt.timedelta(minutes=offset_min)
    response = client.post(
        "/api/workouts",
        json={
            "activity": activity,
            "start_ts": start.isoformat(),
            "duration_s": max(600, int(miles * pace_min * 60)),
            "distance_mi": miles,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def ingest_token(signed_in) -> str:
    response = signed_in.post("/api/settings/ingest-token/rotate")
    assert response.status_code == 200
    return response.json()["token"]
