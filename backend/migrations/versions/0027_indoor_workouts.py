"""indoor: which sessions happened on a treadmill

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-12

One column, and as much of the history filled in as the ingest log can still
answer for.

The column is additive with a default of false, so it runs on a database that
has been live since 0001 exactly as it runs on a fresh one, and every existing
row is carried by the default rather than by a statement. Nothing reads it but
the sport mark on a card: no medal, no conversion, no flag and no total changes
because a mile was covered indoors.

THE BACKFILL IS DELIBERATELY INCOMPLETE, and this is the honest limit worth
writing down. The only record of what an export called a workout is the payload
in ingest_log, and those rows are pruned at INGEST_LOG_RETENTION_DAYS on the
account's next sync. So a workout still inside that window is matched back to
the entry it came from and marked indoor if the entry's name says so; every
workout older than the window stays false whatever it really was. False is also
what a workout with no name of its own reads as, here and in the sync path
alike. Nobody's history is wrong as a result, only less specific than it could
have been if this column had existed from the start.

Matched on the dedupe key the sync itself writes: the account, the parsed start
time and the whole-second duration. That triple is the unique constraint on
workouts, so a match is exact rather than approximate. The parsing is imported
from app.activity rather than copied in, because the question this asks is
literally "what did the sync make of this entry", and a second copy of the parse
would answer it differently the first time the real one is fixed.

Stepping back drops the column. Nothing else in the schema knows about it and no
number anywhere is derived from it, so the same upgrade run again lands on the
same answer out of the same log rows.
"""

import datetime as dt
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.activity import duration_seconds, is_indoor, parse_start, workout_entries

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Read with types on, so both engines hand back datetimes and parsed JSON rather
# than the strings SQLite stores them as.
_workouts = sa.table(
    "workouts",
    sa.column("id", sa.Integer),
    sa.column("user_id", sa.Integer),
    sa.column("start_ts", sa.DateTime(timezone=True)),
    sa.column("duration_s", sa.Integer),
    sa.column("indoor", sa.Boolean),
)
_ingest_log = sa.table(
    "ingest_log",
    sa.column("user_id", sa.Integer),
    sa.column("payload", sa.JSON),
)


def _utc(moment: dt.datetime) -> dt.datetime:
    """One timestamp as a naive UTC datetime, whichever engine handed it over.

    Postgres returns an aware value and SQLite a naive one that is already UTC,
    and a key built from a mix of the two would never match itself.
    """
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _indoor_keys(connection) -> set[tuple[int, dt.datetime, int]]:
    """Every (account, start, duration) an ingest log entry calls indoor."""
    found: set[tuple[int, dt.datetime, int]] = set()
    for user_id, payload in connection.execute(sa.select(_ingest_log)):
        for entry in workout_entries(payload) or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name") or entry.get("workoutActivityType") or entry.get("type")
            if not isinstance(name, str) or not is_indoor(name):
                continue
            start = parse_start(entry.get("start") or entry.get("startDate"))
            if start is None:
                continue
            found.add((user_id, _utc(start), duration_seconds(entry)))
    return found


def upgrade() -> None:
    op.add_column(
        "workouts",
        sa.Column("indoor", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    connection = op.get_bind()
    keys = _indoor_keys(connection)
    if not keys:
        return
    # Matched in Python over the workout rows rather than as one statement per
    # entry. A history of workouts is small, and the alternative is a round trip
    # for every indoor session anybody has ever recorded.
    matched = [
        row.id
        for row in connection.execute(
            sa.select(
                _workouts.c.id,
                _workouts.c.user_id,
                _workouts.c.start_ts,
                _workouts.c.duration_s,
            )
        )
        if (row.user_id, _utc(row.start_ts), row.duration_s) in keys
    ]
    if matched:
        connection.execute(
            sa.update(_workouts).where(_workouts.c.id.in_(matched)).values(indoor=True)
        )


def downgrade() -> None:
    op.drop_column("workouts", "indoor")
