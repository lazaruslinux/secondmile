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
