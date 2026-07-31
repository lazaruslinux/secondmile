"""The whole schema. Portable on purpose: Postgres runs it in production and
SQLite runs it in the tests, so nothing here may be dialect specific."""

import datetime as dt

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy import JSON as JSONType
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Every activity the game understands, and the only values the enum accepts.
ACTIVITIES = ("walk", "run", "cycle", "swim")


class UtcDateTime(TypeDecorator):
    """A timestamp column that is always timezone aware in Python.

    SQLite has no timestamp type and hands back naive datetimes no matter what
    the column says, while Postgres hands back aware ones. Mixing the two in a
    comparison raises TypeError at runtime, in whichever branch happened not to
    be covered by a test. Normalising at the column boundary means the rest of
    the code never has to think about which database it is talking to.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            # Refusing is deliberate. Guessing a zone for a naive value is how
            # workouts end up in the wrong week; callers normalise first.
            raise ValueError("naive datetime written to a timestamp column")
        return value.astimezone(dt.timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)


# native_enum is off so both databases store a plain VARCHAR with a check
# constraint. Postgres would otherwise create a real enum type, and altering one
# of those later is a migration chore out of all proportion to the benefit.
ActivityEnum = Enum(*ACTIVITIES, name="activity", native_enum=False)
SourceEnum = Enum("sync", "manual", name="workout_source", native_enum=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable because accounts made from the command line do not need one, and
    # unique as an index rather than a constraint so that both databases treat
    # the missing ones as distinct from each other rather than as one repeated
    # value. Always stored lower-cased, so the uniqueness check cannot be walked
    # around with a capital letter.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    units: Mapped[str] = mapped_column(String(16), nullable=False, default="imperial")
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Null means unclaimed. Registration claims it with a conditional UPDATE, so
    # two people racing the same code cannot both end up with an account.
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class UserSession(Base):
    __tablename__ = "sessions"

    # Only the hash is stored. A database dump therefore contains no usable
    # session, the same reasoning that applies to passwords.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Hashed like a session token, and for the same reason: whoever holds the
    # plaintext can take the action it authorises, so the database must not.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Only "verify" exists today. The column is here because the next token of
    # this kind (a password reset) has a different meaning and must not be
    # accepted by the endpoint that consumes this one.
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="verify")
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class IngestToken(Base):
    __tablename__ = "ingest_tokens"

    # One token per user, so the user id is the key: rotating replaces the row's
    # hash rather than accumulating tokens that are all still valid.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rotated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class Workout(Base):
    __tablename__ = "workouts"
    # The idempotency key. Health Auto Export sends overlapping windows freely,
    # so the same session arrives again and again; the database refuses the
    # duplicate and the ingest loop counts it as skipped instead of crediting it
    # twice.
    __table_args__ = (UniqueConstraint("user_id", "start_ts", "duration_s", name="uq_workout"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity: Mapped[str] = mapped_column(ActivityEnum, nullable=False)
    start_ts: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    duration_s: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    active_kcal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(SourceEnum, nullable=False)
    # Soft flags only, never a reason to reject. JSON rather than JSONB so the
    # same migration runs on SQLite in the tests.
    flags: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )


class IngestLog(Base):
    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    received_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # The payload exactly as it arrived. If a parsing bug ever drops a field,
    # the history can be replayed after the fix instead of being lost, which is
    # the whole reason this table exists.
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    result: Mapped[dict] = mapped_column(JSONType, nullable=False)


# Ids of places, roads, regions, cards, and accolades all come from app.world
# rather than from a table. They are strings here and no foreign key points at
# them, because the world is authored in the source and a release is the only
# thing that changes it.
_WORLD_ID = String(48)


class Journey(Base):
    __tablename__ = "journeys"

    # One row per account, so the key is the account. A journey is a position,
    # not a history: where the marker has been lives in journey_events.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Exactly one of these two is set. At a location the marker is standing
    # somewhere; on a road it is between two places, position_mi along it from
    # the road's from_id end.
    location_id: Mapped[str | None] = mapped_column(_WORLD_ID, nullable=True)
    road_id: Mapped[str | None] = mapped_column(_WORLD_ID, nullable=True)
    position_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Where the marker is headed, cleared on arrival. None means every mile
    # becomes a local round wherever the marker stands.
    destination_id: Mapped[str | None] = mapped_column(_WORLD_ID, nullable=True)
    # Miles still to travel before the next chest. Carried between workouts so
    # a run that ends half a chest short is not rounded away, and null until
    # the first roll, which happens with the first workout's seeded generator.
    next_chest_mi: Mapped[float | None] = mapped_column(Float, nullable=True)
    traveled_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Workouts before this instant are history rather than movement. Set when
    # the account is created, so signing up does not fire a year of old
    # training through the map in one sweep.
    started_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class ProcessedWorkout(Base):
    __tablename__ = "processed_workouts"

    # The idempotency spine of the engine. A workout advances the marker once
    # and only once, whatever order the ingest, the manual form, and the
    # catch-up sweep arrive in, because the marker row here is claimed before
    # any movement happens and the primary key settles every race.
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), primary_key=True
    )


class JourneyEvent(Base):
    __tablename__ = "journey_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # travel, chest, milestone, arrival, unlock.
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Everything the recap needs to narrate this line without another request.
    # JSON rather than JSONB, so the same migration runs on SQLite.
    data: Mapped[dict] = mapped_column(JSONType, nullable=False, default=dict)
    seen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Chest(Base):
    __tablename__ = "chests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Decided when the chest drops, revealed when it is opened. Deciding at
    # open time would let a client learn what is inside by asking twice, and
    # would make the seeded generator's determinism meaningless.
    card_id: Mapped[str] = mapped_column(_WORLD_ID, nullable=False)
    dropped_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # Null means still closed. Chests never expire, so nothing else ever
    # writes this column.
    opened_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)


class UserCard(Base):
    __tablename__ = "user_cards"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[str] = mapped_column(_WORLD_ID, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_found_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class UserAccolade(Base):
    __tablename__ = "user_accolades"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    accolade_id: Mapped[str] = mapped_column(_WORLD_ID, primary_key=True)
    earned_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class RegionUnlock(Base):
    __tablename__ = "region_unlocks"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    region_id: Mapped[str] = mapped_column(_WORLD_ID, primary_key=True)
    unlocked_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class MileSpend(Base):
    __tablename__ = "mile_spends"

    # A ledger rather than a balance column. Converted Miles earned are a sum
    # over workouts, so keeping what was spent as its own list means the two
    # halves of a bucket are each derived from rows that are never rewritten.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity: Mapped[str] = mapped_column(ActivityEnum, nullable=False)
    amount_mi: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
