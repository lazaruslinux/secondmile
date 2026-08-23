"""Where a workout stood in its own account's history the day it arrived.

"This was your second best 5K." A standing is written once, when the workout is
imported, and it is never rewritten. That is the whole design, and it is the
medal's design: what a card said the day it arrived is what it goes on saying,
and a faster run next month does not reach back and demote it. The copy is past
tense for exactly that reason.

Only the top three are stored. A fourth best is not something worth saying on a
card, and not storing it is what keeps this table a few rows a workout.

The reading is per sport, because a walk and a run are not the same record, and
it uses the best efforts app.bests already wrote: the fastest stretch of the
tier's distance the per-minute rows hold, or the session's own average pace over
that distance where the minutes cannot answer. That is the same pair the
insights band's Personal records tiles are read from, so a card and a tile are
answering with the same numbers.

Deleted workouts are left out of the comparison, the way they are left out of
everything else: a session somebody took back does not hold a record and is not
something to be measured against. The consequence is honest and worth stating -
if the best 5K in a history is deleted, a later run can be stamped best as well,
and both cards are telling the truth about their own day.

Nothing earns from any of this. No medal, chest, level, plant or total reads
these rows. The two-lane law is untouched: this is display, drawn from rows that
were already there.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import bests, models
from app.config import PR_TIERS

# How far down the standings a card is willing to speak. Third is the last place
# that still sounds like something; fourth is a number.
TOP = 3

# The tiers longest first, for the one place an order between them is needed:
# picking which standing a card says when a workout holds more than one.
_LONGEST_FIRST = {name: index for index, (name, _) in enumerate(reversed(PR_TIERS))}

# Every time in this app is read and shown to a tenth of a second, so two
# efforts that print the same time are the same time here. Compared at that
# precision rather than as raw floats, because a projected time is a different
# division on every workout: three rides at exactly the same pace over three
# distances produce 868.0 and 868.0000000000001, and without this the noise
# rather than the pace decides who placed where.
_PRECISION = 1


def effort(workout: models.Workout, tier: str, floor: float, measured: dict) -> float | None:
    """This workout's time for a tier, or None where it never covered it.

    The measured stretch where app.bests could read one, and the whole session's
    pace over the tier's distance where it could not. Both are answers to the
    same question, and a workout that was only ever summarised should not be
    kept out of a standing for it - which is the rule the insights band already
    reads records by.
    """
    if workout.distance_mi < floor or workout.distance_mi <= 0 or workout.duration_s <= 0:
        return None
    stored = measured.get((workout.id, tier))
    return stored if stored is not None else workout.duration_s * (floor / workout.distance_mi)


def _history(db: Session, user_id: int) -> list[models.Workout]:
    """Every surviving workout this account could hold a standing for, oldest first.

    Ordered by start and then by id, the feed's own tie-break, so two workouts
    sharing a start time are ranked in the order everything else reads them in.
    """
    return list(
        db.execute(
            select(models.Workout)
            .where(
                models.Workout.user_id == user_id,
                models.Workout.deleted_at.is_(None),
                models.Workout.distance_mi >= PR_TIERS[0][1],
            )
            .order_by(models.Workout.start_ts, models.Workout.id)
        ).scalars()
    )


def _standings(
    candidate: models.Workout, history: list[models.Workout], measured: dict
) -> dict[str, int]:
    """The tiers this workout placed in against what came before it, and where.

    A prior with the same time keeps the better place: it got there first, which
    is the tie-break _records settles its own records by, so a card and a tile
    never disagree about who holds a mark. Same time means the same to a tenth,
    which is the precision every reading of it is shown at.
    """
    placed: dict[str, int] = {}
    for tier, floor in PR_TIERS:
        mine = effort(candidate, tier, floor, measured)
        if mine is None:
            continue
        ahead = 0
        for other in history:
            if other.id == candidate.id or other.activity != candidate.activity:
                continue
            if (other.start_ts, other.id) >= (candidate.start_ts, candidate.id):
                # Later than the candidate, so not something it was measured
                # against: a standing is what was true when the workout landed.
                continue
            theirs = effort(other, tier, floor, measured)
            if theirs is not None and round(theirs, _PRECISION) <= round(mine, _PRECISION):
                ahead += 1
                if ahead >= TOP:
                    break
        if ahead < TOP:
            placed[tier] = ahead + 1
    return placed


def _write(db: Session, workout_id: int, placed: dict[str, int]) -> int:
    db.add_all(
        [
            models.WorkoutPrStamp(workout_id=workout_id, tier=tier, rank=rank)
            for tier, rank in placed.items()
        ]
    )
    return len(placed)


def stamp(db: Session, user_id: int, arrived: list[models.Workout]) -> int:
    """Judge freshly imported workouts against the history they landed in.

    Called once per sync rather than once per workout, and after the whole
    import loop rather than inside it, because an export can carry a week in any
    order: every one of them has to be in the table before any of them can be
    told what it came after.

    The history and the best efforts are read once here and ranked in memory. A
    sync that brings fifty workouts is two queries, not four hundred.
    """
    arrived = [row for row in arrived if row.distance_mi >= PR_TIERS[0][1]]
    if not arrived:
        return 0
    history = _history(db, user_id)
    measured = bests.for_user(db, user_id)
    written = 0
    for candidate in sorted(arrived, key=lambda row: (row.start_ts, row.id)):
        written += _write(db, candidate.id, _standings(candidate, history, measured))
    db.flush()
    return written


def rebuild(db: Session, user_id: int) -> int:
    """Stamp an account's whole existing history, oldest first. Returns how many.

    The one-time filler for a history that predates the table, and the only
    thing in the app that ever writes a stamp a second time. Nothing calls it on
    its own: not a sync, not recompute-progress, not a delete. Safe to run twice
    on an unchanged history, because the same rows in the same order give the
    same answer.

    Run after a workout has been deleted it will restate that account's history
    without it, which is a different thing from what the cards said before. That
    is the deliberate exception to stamps being written once, and it is why this
    is a command somebody types rather than something that happens.
    """
    history = _history(db, user_id)
    measured = bests.for_user(db, user_id)
    db.execute(
        delete(models.WorkoutPrStamp).where(
            models.WorkoutPrStamp.workout_id.in_([row.id for row in history])
        )
    )
    written = 0
    for candidate in history:
        written += _write(db, candidate.id, _standings(candidate, history, measured))
    db.flush()
    return written


def for_workouts(db: Session, workout_ids) -> dict[int, list[dict]]:
    """The standings on each of these workouts, strongest first. One query.

    Strongest means the better place, and between two of the same place the
    longer distance: a run that was a best 5K and a best half says the half,
    because that is the harder thing it did. The order is settled here rather
    than on the card so the card and the details screen agree without either of
    them holding the rule.
    """
    ids = list(workout_ids)
    if not ids:
        return {}
    found: dict[int, list[dict]] = {}
    for workout_id, tier, rank in db.execute(
        select(
            models.WorkoutPrStamp.workout_id,
            models.WorkoutPrStamp.tier,
            models.WorkoutPrStamp.rank,
        ).where(models.WorkoutPrStamp.workout_id.in_(ids))
    ):
        found.setdefault(workout_id, []).append({"tier": tier, "rank": rank})
    for rows in found.values():
        rows.sort(key=lambda row: (row["rank"], _LONGEST_FIRST[row["tier"]]))
    return found
