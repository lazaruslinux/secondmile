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
    # The file name of the re-encoded profile picture, or null for none. A name
    # rather than a full path, joined with AVATAR_DIR when it is read, so moving
    # the directory does not orphan every row. Always derived from the account
    # id: nothing an uploader sends ever reaches this column.
    avatar_path: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The achievement ids the player has chosen to wear, in slot order. A list
    # of at most MAX_DISPLAYED_BADGES, validated against what they own on every
    # write. JSON rather than a join table because it is an ordered list of
    # fixed length that is only ever read and written whole.
    displayed_badges: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    # The sports shown as diamonds on the profile, in slot order, or null for
    # the automatic pick. Nullable rather than defaulted because null and an
    # empty list mean different things: null is "choose for me", an empty list
    # is a player who deliberately wears none.
    diamond_sports: Mapped[list | None] = mapped_column(JSONType, nullable=True)
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


# Card and achievement ids come from app.world and app.achievements rather than
# from a table. They are strings here and no foreign key points at them, because
# the catalogue is authored in the source and a release is the only thing that
# changes it.
_CATALOG_ID = String(48)


class UserProgress(Base):
    __tablename__ = "user_progress"

    # One row per account: experience, level, and where the chest accumulator
    # has got to. Everything in it is rebuildable from the workout history by
    # manage.py recompute-progress, which is the safety hatch for the day a
    # constant changes.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    xp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Converted Miles banked toward the next chest, and the gap that chest is
    # waiting on. The pair carries between workouts, so a run that ends a
    # quarter of a mile short of a chest leaves that quarter mile here rather
    # than starting again from a fresh roll. The gap is null until the first
    # workout's seeded generator rolls one.
    chest_progress_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    next_chest_gap_mi: Mapped[float | None] = mapped_column(Float, nullable=True)
    # When the player last cleared their recap. Everything that arrived after
    # it is what the recap has to tell them about. Null means they have never
    # acknowledged one, so everything counts.
    last_ack_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class ProcessedWorkout(Base):
    __tablename__ = "processed_workouts"

    # The idempotency spine of the pipeline. A workout is credited once and
    # only once, whatever order the ingest, the manual form, and the catch-up
    # sweep arrive in, because the marker row here is claimed before any credit
    # happens and the primary key settles every race.
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), primary_key=True
    )


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    achievement_id: Mapped[str] = mapped_column(_CATALOG_ID, primary_key=True)
    earned_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # The Second Mile rule: doubling a target inside the same window upgrades
    # the badge in place. Achievements are never revoked and gilding is never
    # taken back, so this column only ever goes from false to true.
    gilded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Chest(Base):
    __tablename__ = "chests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Decided when the chest drops, revealed when it is opened. Deciding at
    # open time would let a client learn what is inside by asking twice, and
    # would make the seeded generator's determinism meaningless.
    card_id: Mapped[str] = mapped_column(_CATALOG_ID, nullable=False)
    dropped_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # Null means still closed. Chests never expire, so nothing else ever
    # writes this column.
    opened_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)


class UserCard(Base):
    __tablename__ = "user_cards"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    card_id: Mapped[str] = mapped_column(_CATALOG_ID, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_found_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
