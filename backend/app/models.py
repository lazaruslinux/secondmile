"""The whole schema. Portable on purpose: Postgres runs it in production and
SQLite runs it in the tests, so nothing here may be dialect specific."""

import datetime as dt

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
    func,
    text,
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
# "manual" is still here although nothing writes it any more. There is a history
# of rows carrying it, and where a workout came from is a fact about what
# happened: dropping the value would make those rows unreadable to say that a
# form no longer exists.
SourceEnum = Enum("sync", "manual", name="workout_source", native_enum=False)
FriendshipEnum = Enum("pending", "accepted", name="friendship_status", native_enum=False)
EncouragementEnum = Enum("cheer", "note", name="encouragement_kind", native_enum=False)
# The things a chest can hold. Every one of them is a tool with exactly one
# verb, which is why none of them is something to merely look at. The column is
# a plain string of five characters with no constraint on it, so the wish that
# joined the other three needed no migration to be storable.
ItemKindEnum = Enum("seed", "water", "oil", "wish", name="satchel_kind", native_enum=False)


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
    # An address asked for and not yet confirmed. Deliberately not unique: two
    # accounts may both ask for the same address, and only the one that answers
    # its mail first gets it, checked when the swap happens.
    pending_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The name a person goes by, shown as "First Last" beside the username. Both
    # optional, both clearable, and neither is an identity: the username is
    # still what you sign in with and what an invite is sent to.
    first_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # A date, never an age. The age is worked out from this whenever it is
    # shown, so the two can never drift apart.
    birthdate: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # Free text on purpose. This is a private instance and a fixed list of
    # options would be a decision the app has no business making for anybody.
    gender: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # A line or two somebody writes about themselves, or null for none. Short
    # enough to sit under a name on both profile screens rather than to be an
    # article, and the only free text on an account a friend ever reads.
    bio: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    units: Mapped[str] = mapped_column(String(16), nullable=False, default="imperial")
    # The file name of the re-encoded profile picture, or null for none. A name
    # rather than a full path, joined with AVATAR_DIR when it is read, so moving
    # the directory does not orphan every row. Always derived from the account
    # id: nothing an uploader sends ever reaches this column.
    avatar_path: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The medal ids the player has chosen to wear, in slot order. A list
    # of at most MAX_DISPLAYED_BADGES, validated against what they own on every
    # write. JSON rather than a join table because it is an ordered list of
    # fixed length that is only ever read and written whole.
    displayed_badges: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
    # The sports shown as diamonds on the profile, in slot order, or null for
    # the automatic pick. Nullable rather than defaulted because null and an
    # empty list mean different things: null is "choose for me", an empty list
    # is a player who deliberately wears none.
    diamond_sports: Mapped[list | None] = mapped_column(JSONType, nullable=True)
    # What this account keeps back from its friends, as field names. Empty for
    # everybody until they say otherwise: a friend sees what you did, and this
    # is the list of the few things they need not. The names it may hold are in
    # app.fellowship.HIDEABLE, which is where the rule that reads them lives.
    hidden_from_friends: Mapped[list] = mapped_column(JSONType, nullable=False, default=list)
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
    # Null means it never expires, which is what a link minted from the app is.
    # The command line still dates the codes it makes.
    expires_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Set when somebody took a link back. A revoked code is dead whether or not
    # it was ever claimed, and it is never cleared: taking a link back is not
    # something to undo halfway.
    revoked_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Whether claiming this code also makes the two accounts friends. True for a
    # link minted in the app, because whoever sent it knows who they sent it to;
    # false for a command line code, which is an account gate and nothing more.
    auto_friend: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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
    # What the owner called this workout and what they wrote about it. Both
    # optional, both clearable, and both only ever typed by the person whose
    # workout it is. Nothing is derived from either: the numbers on a workout
    # are not editable, only the words around them.
    title: Mapped[str | None] = mapped_column(String(100), nullable=True)
    post: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime, nullable=False, server_default=func.now()
    )
    # When the owner deleted this, or null for a workout that is simply there.
    # A deleted row is out of every feed, every total and every derivation, and
    # appears only in the Activity tab's own Deleted list until the window in
    # DELETED_WORKOUT_RETENTION_DAYS runs out.
    #
    # The row is never removed, even once its pictures and words have been
    # purged. It is the tombstone the unique key above is written on: the phone
    # exports overlapping windows forever, and a deleted session that left no
    # row would be imported again on the next catch-up sync.
    deleted_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)


class WorkoutPhoto(Base):
    __tablename__ = "workout_photos"

    # One row per stored picture. The file is <workout_id>-<id>.webp under
    # PHOTO_DIR, named from these two ids and never from the upload, so there is
    # nothing here a caller could have chosen. Rows carry no caption and no
    # order column: the id is the order they were added in.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class WorkoutVideo(Base):
    __tablename__ = "workout_videos"

    # One row per stored video, on the photo table's terms. The files are
    # <workout_id>-<id>.mp4 and <workout_id>-<id>.jpg under VIDEO_DIR, named
    # from these two ids and never from the upload. No duration and no size
    # column: neither is asked of a row anywhere, and the file is the truth
    # about both.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class WorkoutRoute(Base):
    __tablename__ = "workout_routes"

    # The line drawn on a workout's card, as [[lat, lon], ...] rounded to five
    # decimals. A separate table rather than a column on workouts because it is
    # the one part of a workout the history views never read, and the history is
    # read on every page.
    #
    # Never the raw trace: both ends are trimmed away before anything gets here,
    # so a stored route cannot say where its owner lives. See app/routemaps.py.
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), primary_key=True
    )
    points: Mapped[list] = mapped_column(JSONType, nullable=False)


class IngestLog(Base):
    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    received_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # The payload as it arrived, less its GPS traces. If a parsing bug ever
    # drops a field, the history can be replayed after the fix instead of being
    # lost, which is the whole reason this table exists.
    #
    # Routes are the one exception, and cannot be replayed from here: they are
    # consumed into workout_routes at arrival and stripped before this row is
    # written, because a raw trace names where its owner lives and a log nothing
    # reads is no place to keep that. Rows past INGEST_LOG_RETENTION_DAYS are
    # deleted on the account's next sync.
    payload: Mapped[dict] = mapped_column(JSONType, nullable=False)
    result: Mapped[dict] = mapped_column(JSONType, nullable=False)


# Species and medal ids come from app.species and app.medals rather than from a
# table. They are strings here and no foreign key points at them, because the
# catalogue is authored in the source and a release is the only thing that
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
    # Experience is lifetime converted Miles, one for one, so it is a distance
    # and not a score. A fresh account stands at level 0 with none of it.
    xp: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Converted Miles banked toward the next chest, and which step of the chest
    # ladder that chest is. The pair carries between workouts, so a run that
    # ends a quarter of a mile short of a chest leaves that quarter mile here.
    # The position wraps back to the 5K step after the Ultra one, and never
    # decays: a quiet fortnight costs nothing.
    chest_progress_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cycle_pos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When the player last cleared their recap. Everything that arrived after
    # it is what the recap has to tell them about. Null means they have never
    # acknowledged one, so everything counts.
    last_ack_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Earned by encouraging other people, never by being encouraged. It is not
    # a score anybody sees: no response carries the number, and the only thing
    # it drives is which flourish grows on the avatar's border.
    renown: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Manna waiting to be gathered: what this account's burned calories came
    # to, one workout at a time, rounded up to the next multiple of five. A
    # currency and never a stat, and the giving lane's alone: it buys nothing
    # in the earning lane, ever. Steps put nothing here, because steps carry no
    # calories the app will spend. Nothing spoils and nothing counts down, so
    # this only ever goes up until there is something to spend it on.
    manna_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class ProcessedWorkout(Base):
    __tablename__ = "processed_workouts"

    # The idempotency spine of the pipeline. A workout is credited once and
    # only once, whatever order the ingest and the catch-up sweep arrive in,
    # because the marker row here is claimed before any credit happens and the
    # primary key settles every race.
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), primary_key=True
    )


class DailySteps(Base):
    __tablename__ = "daily_steps"
    # One row per account per local day. The pair is unique because a day is
    # upserted on every sync: the phone sends overlapping windows of metrics
    # exactly as it does of workouts, and the same day arriving again is the
    # common case rather than the exception.
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_daily_steps"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The local calendar day in the instance timezone, which is the day a
    # reading is bucketed into and the day a week is counted from.
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # What the pedometer claimed, both of it high-water: an export that covers
    # half a day must never take a fuller reading of the same day back down.
    # Neither of them earns anything: steps are stored and shown, and miles are
    # the work put into a recorded activity.
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distance_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # DORMANT. What the round that did credit steps had credited of that day's
    # distance. Nothing writes it any more and nothing reads it; it is frozen
    # together with the step_credits rows that add up to it, so the two still
    # agree. See progress.record_steps.
    credited_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Set the first time a reading was clamped to its ceiling, and never
    # cleared. A soft marker like the workout flags: nothing is refused, the
    # day is simply not stored past what a day can plausibly hold.
    capped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class StepCredit(Base):
    __tablename__ = "step_credits"

    # DORMANT, and kept because a retreat is not an amputation. One row for
    # every time a day's step credit went up, back when step distance earned;
    # the sum of them for a day is that day's credited_mi. Nothing writes a new
    # one and nothing reads them: steps earn nothing, and a rebuild takes no
    # fuel from this table. Pinned by test.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day: Mapped[dt.date] = mapped_column(Date, nullable=False)
    delta_mi: Mapped[float] = mapped_column(Float, nullable=False)
    # When the credit landed, which is the clock rather than the day it is
    # about: a week of steps synced this morning is news this morning, the same
    # reading the letter gives a backfilled workout.
    credited_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class ProcessedStepCredit(Base):
    __tablename__ = "processed_step_credits"

    # DORMANT with the ledger it marks. It was the step half of the idempotency
    # spine, keyed and claimed exactly as processed_workouts is. Nothing claims
    # a marker here any more.
    step_credit_id: Mapped[int] = mapped_column(
        ForeignKey("step_credits.id", ondelete="CASCADE"), primary_key=True
    )


class BadgeEarn(Base):
    __tablename__ = "badge_earns"
    # One workout may hold one medal from each per-workout family, so the pair
    # is the key rather than the workout alone: a 5K run before six in the
    # morning earns the 5K and Early Riser both. Replaying the same history is
    # idempotent for free, because the second attempt collides and is dropped.
    __table_args__ = (
        UniqueConstraint("workout_id", "badge_id", name="uq_badge_earn_workout_medal"),
    )

    # One row every time a workout earns a medal. Repeatable on purpose: a
    # marathon is not a thing you do once and tick off, so this counts them.
    #
    # The race and time families live here, keyed by the catalogue id. The
    # families a week earns rather than a session are in weekly_badge_earns.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    badge_id: Mapped[str] = mapped_column(_CATALOG_ID, nullable=False)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False
    )
    # The workout's own start time, never the clock, so a rebuild writes the
    # same row it wrote the first time.
    earned_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class WeeklyBadgeEarn(Base):
    __tablename__ = "weekly_badge_earns"

    # One row per family per week, which is what lets a week upgrade its medal
    # in place: seven days that reach 25 miles keep the row they earned at 10
    # and change what it holds. The primary key is the whole of the idempotence
    # here, the way the unique pair is next door.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # The Monday of the week, in the instance timezone, the same Monday the
    # Almanac groups by.
    week_start: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    family: Mapped[str] = mapped_column(String(16), primary_key=True)
    badge_id: Mapped[str] = mapped_column(_CATALOG_ID, nullable=False)
    # The workout that crossed the line. Kept so the letter can ask when the
    # medal arrived rather than when it was earned: a January week backfilled
    # this morning is news this morning, whatever date is on it.
    #
    # Nullable, and never written null any more: the rows that carry a null are
    # from the round where step credit could carry a week over the line. They
    # are still read, and the column stays nullable rather than being migrated
    # back under them.
    workout_id: Mapped[int | None] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=True
    )
    # The moment the crossing happened, which is that workout's start time: a
    # stamp a rebuild writes again.
    earned_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class Anointing(Base):
    __tablename__ = "anointings"
    __table_args__ = (
        # One waiting anointing per pair. Partial, so a pair can give to each
        # other again and again over time and only the unspent one is unique.
        # Both databases take this spelling, and the tests run the SQLite one.
        Index(
            "uq_anointing_pending",
            "from_user_id",
            "to_user_id",
            unique=True,
            postgresql_where=text("consumed_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL"),
        ),
    )

    # One person spending oil on another, which lifts one chest the recipient's
    # own miles bring. Nothing is pushed at anybody: no notification and no feed
    # event. It shows on the recipient's profile as the name on the chest ahead,
    # and in the letter once that chest has landed.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # Null until one of the recipient's own chests drops with room to be lifted.
    consumed_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Which chest it lifted. A record rather than a live pointer, and so not a
    # foreign key: a rebuild is allowed to throw chests away, and what one
    # person gave another is not derived from anything and must survive it.
    consumed_chest_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Chest(Base):
    __tablename__ = "chests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which step of the ladder dropped it, which is what its odds are rolled
    # against when it is opened. Null on a chest that predates the ladder;
    # those roll against the first step's odds.
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Set when somebody's oil was spent on this chest, which is the row that
    # says whose. The chest is still a distance: the gift is the guaranteed
    # step up its roll takes when the lid comes off, and the letter is where it
    # says who paid for it. Null for a chest nobody lifted. Not a foreign key,
    # the same as the pointer back the other way: the two tables are records of
    # each other rather than owners, and a migration that can add this column
    # on either database is worth more here than a constraint.
    from_anointing_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dropped_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # Null means still closed. Chests never expire, so nothing else ever
    # writes this column.
    opened_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)


class SatchelItem(Base):
    __tablename__ = "satchel_items"

    # What came out of a chest and has not been spent yet. Every item is a
    # tool: a seed to plant, water to pour, oil to anoint a friend with. There
    # is nothing here to merely own, which is why nothing counts duplicates.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(ItemKindEnum, nullable=False)
    # The species a seed will grow into, decided when the chest was opened.
    # Null for water and oil, which are the same wherever they came from.
    species: Mapped[str | None] = mapped_column(_CATALOG_ID, nullable=True)
    # The slot of the roll this came out of, which is what the item is worth.
    rarity: Mapped[str] = mapped_column(String(16), nullable=False)
    # Which chest it came from, or null once that chest is gone. Nulled rather
    # than cascaded on purpose: a rebuild rerolls chests, and an item somebody
    # is already holding is theirs whatever happens to the box it came in.
    chest_id: Mapped[int | None] = mapped_column(
        ForeignKey("chests.id", ondelete="SET NULL"), nullable=True
    )
    acquired_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # Null while it is still in the satchel. Items are spent, never destroyed:
    # the row stays so the history of what was done with it stays too.
    used_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Who it was spent on, when it was spent on somebody: water poured into a
    # friend's plot, or oil. Null for anything used on your own plot. This is
    # what makes the spent row a record of a gift rather than only of a verb.
    given_to_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Whether giving it paid the giver any renown. Stored rather than worked
    # out again later, exactly as an encouragement stores it, so the seven day
    # window is one lookup and a replay can never pay twice.
    earned_renown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Planting(Base):
    __tablename__ = "plantings"

    # Something growing in the plot. It grows from every credited workout,
    # needs no tending, and cannot die: the only thing that ever happens to it
    # is more miles.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    species: Mapped[str] = mapped_column(_CATALOG_ID, nullable=False)
    rarity: Mapped[str] = mapped_column(String(16), nullable=False)
    planted_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # Converted Miles of growth banked, from workouts and from poured water.
    growth_mi: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # When it came to maturity, or null while it is still growing.
    matured_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # The level this stood at when the letter was last put down, which is what
    # the next letter compares against. Written rather than worked out: growth
    # comes from workouts and from poured water, and only the workouts leave a
    # trail anything could subtract. Null on a plant that predates the column,
    # and that plant says nothing until the next acknowledgement fills it in.
    level_at_ack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The growth it stood at in that same moment, which is what the letter
    # compares stages against. The level cannot answer that: a seed and a plant
    # half way to level one are both level zero, and the drawing changes
    # between them. Backfilled to the growth of the day by 0021, so nothing a
    # plant did before that release reads as a crossing.
    growth_at_ack: Mapped[float | None] = mapped_column(Float, nullable=True)


class Friendship(Base):
    __tablename__ = "friendships"
    # One row per direction asked in, so the invite keeps the memory of who
    # asked. A pair is friends when an accepted row exists either way round,
    # which is why nothing here reads a single "friend of" column.
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friendship"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    addressee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(FriendshipEnum, nullable=False, default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # Null while the invite is still waiting.
    responded_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)


class OutboundInvite(Base):
    __tablename__ = "outbound_invites"
    # One row per name an account has typed into the invite form and has not
    # cancelled. It exists so the list of invites you sent can be answered from
    # what you typed rather than from which of those names turned out to be
    # real: a friendship row is only written when the name resolves, so a list
    # built from those rows is a way to ask whether an account exists.
    __table_args__ = (UniqueConstraint("user_id", "username", name="uq_outbound_invite"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The name as it was typed, cleaned the way the invite form cleans it. No
    # foreign key and no lookup: half of these name nobody, which is the point.
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class Encouragement(Base):
    __tablename__ = "encouragements"
    __table_args__ = (
        # One cheer per person per workout, enforced by the database rather than
        # by a read-then-write. Partial because notes have no such limit: a
        # conversation is allowed to be longer than one line. Both databases
        # take a partial unique index, and the tests run the SQLite spelling.
        Index(
            "uq_encouragement_cheer",
            "workout_id",
            "from_user_id",
            unique=True,
            postgresql_where=text("kind = 'cheer'"),
            sqlite_where=text("kind = 'cheer'"),
        ),
        # The renown window: the newest earning row for one pair and one kind.
        Index("ix_encouragement_pair", "from_user_id", "to_user_id", "kind", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workout_id: Mapped[int] = mapped_column(
        ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The workout's owner, kept here as well so the recap can find everything
    # said to one person without joining the whole history to do it.
    to_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(EncouragementEnum, nullable=False)
    # Plain text, and only ever typed by a person: nothing in this app suggests
    # a phrase to send. Null for a cheer, which is wordless by design.
    body: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Whether this one paid its giver any renown. Stored rather than worked out
    # again later so the seven day window is one indexed lookup, and so a
    # deleted or replayed row can never pay twice.
    earned_renown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)


class BugReport(Base):
    __tablename__ = "bug_reports"

    # A dropbox, and nothing more. There is no status, no read flag and no
    # reply: the app tells whoever sent one that it arrived, and the answer to
    # it is a release rather than a row. manage.py bug-reports is the only
    # thing that reads this table.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    # What they typed, and the only part of the row a person authored.
    text: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Which screen they were on, sent by the client. A short word rather than a
    # route, because the app's navigation is which view is on screen.
    view: Mapped[str] = mapped_column(String(32), nullable=False)
    # The browser string off the request, so a report about something that only
    # happens on one phone says which phone. Null when the request carried no
    # such header, which is honest about a client that sent none.
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
