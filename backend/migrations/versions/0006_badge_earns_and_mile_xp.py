"""repeatable badges, and experience measured in miles

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07

Three changes, all of them about what a badge and a level mean.

badge_earns is new. Achievements are earned once ever and never revoked;
badges are earned again every time the thing happens, which is why they need
rows rather than a flag. The race family is the only one in the catalogue
today, and another family is catalogue rows plus an awarding rule rather than
a second table.

user_progress.xp becomes a float, because experience is now converted miles
one for one rather than a score built from distance and time. The old totals
are an order of magnitude too large under the new level curve, so they are
recomputed here from the credited history rather than left to be reinterpreted.

The dropped achievements go with their rows. Single-workout duration, lifetime
distance, and first-of-each-activity are all replaced by the race badges;
week-distance keeps its gilding rule and the collection badges keep their
cards. Any dropped id sitting in a badge slot is pruned out of it, because a
slot naming an achievement no release defines renders as nothing.

Race badges are NOT backfilled here: they belong to individual runs, and
awarding them means replaying the runs. Do that per account with

    docker compose exec backend python manage.py recompute-progress theirname

which also rebuilds that account's chests and album from scratch.
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_ID = sa.String(48)

# Written out rather than imported, for the reason 0004 gives: a migration has
# to keep doing what it did on the day it ran, and these are constants that
# will be retuned again.
_MILES_PER_RAW = {"walk": 1.0, "run": 1.0, "cycle": 1.0 / 3.0, "swim": 4.0}
_LEVEL_COSTS_MI = (3.1, 6.2, 13.1, 26.2)
_LEVEL_STEP_MI = 26.2

# The kinds this round drops, listed as ids because the kinds themselves are
# gone from the source.
_DROPPED_ACHIEVEMENTS = (
    "duration_15",
    "duration_30",
    "duration_60",
    "duration_90",
    "lifetime_50",
    "lifetime_100",
    "lifetime_250",
    "lifetime_500",
    "first_walk",
    "first_run",
    "first_cycle",
    "first_swim",
)


def _level_for_xp(xp: float) -> int:
    """The same curve as app.progress: the race ladder, then a marathon more
    each level."""
    level = 0
    spent = 0.0
    while level < 500:
        if level < len(_LEVEL_COSTS_MI):
            cost = _LEVEL_COSTS_MI[level]
        else:
            cost = _LEVEL_STEP_MI * (level - 2)
        if xp + 1e-9 < spent + cost:
            break
        spent += cost
        level += 1
    return level


def upgrade() -> None:
    op.create_table(
        "badge_earns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("badge_id", _CATALOG_ID, nullable=False),
        # Unique: one workout earns one badge, which is what makes replaying a
        # history idempotent without a second key.
        sa.Column(
            "workout_id",
            sa.Integer(),
            sa.ForeignKey("workouts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
    )

    # batch_alter_table so this file also runs on SQLite, which cannot alter a
    # column in place. On Postgres it is a plain ALTER.
    with op.batch_alter_table("user_progress") as batch:
        batch.alter_column(
            "xp",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using="xp::double precision",
        )

    connection = op.get_bind()

    # Experience is now the converted miles of everything already credited.
    # Summed over the credited workouts rather than over all of them, so a
    # workout the pipeline has not reached yet is still worth crediting after
    # this runs instead of being counted twice.
    totals = connection.execute(
        sa.text(
            "SELECT w.user_id, w.activity, SUM(w.distance_mi) "
            "FROM workouts w JOIN processed_workouts p ON p.workout_id = w.id "
            "GROUP BY w.user_id, w.activity"
        )
    ).all()
    miles: dict[int, float] = {}
    for user_id, activity, distance_mi in totals:
        miles[user_id] = miles.get(user_id, 0.0) + float(distance_mi or 0.0) * _MILES_PER_RAW.get(
            activity, 1.0
        )

    for (user_id,) in connection.execute(sa.text("SELECT user_id FROM user_progress")).all():
        xp = miles.get(user_id, 0.0)
        connection.execute(
            sa.text("UPDATE user_progress SET xp = :xp, level = :level WHERE user_id = :user_id")
            .bindparams(user_id=user_id, xp=xp, level=_level_for_xp(xp))
        )

    connection.execute(
        sa.text("DELETE FROM user_achievements WHERE achievement_id IN :ids").bindparams(
            sa.bindparam("ids", value=_DROPPED_ACHIEVEMENTS, expanding=True)
        )
    )

    # Badge slots are a JSON list, so this is read, filtered, and written back
    # rather than done in SQL: the two databases spell JSON array surgery
    # differently and neither spelling is worth learning for twelve ids.
    dropped = set(_DROPPED_ACHIEVEMENTS)
    for user_id, raw in connection.execute(
        sa.text("SELECT id, displayed_badges FROM users")
    ).all():
        current = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(current, list):
            continue
        kept = [badge for badge in current if badge not in dropped]
        if len(kept) != len(current):
            connection.execute(
                sa.text("UPDATE users SET displayed_badges = :badges WHERE id = :user_id")
                .bindparams(user_id=user_id, badges=json.dumps(kept))
            )


def downgrade() -> None:
    """Back to an integer experience on the old curve.

    The dropped achievements cannot come back: their rows were deleted, and
    only the workouts they were earned from could say who held them. Running
    the older release's evaluator awards them again from the same history.
    """
    connection = op.get_bind()
    # The old formula, so an older release reads a total it understands:
    # ten a converted mile plus one an active minute.
    totals = connection.execute(
        sa.text(
            "SELECT w.user_id, w.activity, SUM(w.distance_mi), SUM(w.duration_s) "
            "FROM workouts w JOIN processed_workouts p ON p.workout_id = w.id "
            "GROUP BY w.user_id, w.activity"
        )
    ).all()
    experience: dict[int, float] = {}
    for user_id, activity, distance_mi, duration_s in totals:
        experience[user_id] = experience.get(user_id, 0.0) + (
            float(distance_mi or 0.0) * _MILES_PER_RAW.get(activity, 1.0) * 10.0
            + float(duration_s or 0) / 60.0
        )
    for (user_id,) in connection.execute(sa.text("SELECT user_id FROM user_progress")).all():
        xp = round(experience.get(user_id, 0.0))
        level = 1
        while xp >= 100 * ((level + 1) * (level + 2) // 2 - 1):
            level += 1
        connection.execute(
            sa.text("UPDATE user_progress SET xp = :xp, level = :level WHERE user_id = :user_id")
            .bindparams(user_id=user_id, xp=xp, level=level)
        )

    with op.batch_alter_table("user_progress") as batch:
        batch.alter_column(
            "xp",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="xp::integer",
        )
    op.drop_table("badge_earns")
