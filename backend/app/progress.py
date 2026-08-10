"""The pipeline: real workouts become experience, levels, chests, and medals.

Everything is server side and idempotent per workout: every path funnels
through process_user, and a credited workout is never credited again. Every
roll comes from a generator seeded on (user id, workout id), so replays are
deterministic.
"""

import datetime as dt
import random
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import grove, medals, models, species
from app.activity import converted_miles, week_start
from app.config import (
    BORDER_LEVELS,
    CHEST_LADDER,
    CHEST_SLOT_ITEMS,
    CHEST_TIER_FLOOR,
    CHEST_UPGRADE_CHANCE,
    LEGACY_CHEST_TIER,
    LEVEL_COSTS_MI,
    LEVEL_STEP_MI,
    MAX_DIAMOND_SPORTS,
    MAX_LEVEL,
    SERVER_TZ,
)
from app.models import ACTIVITIES
from app.security import now_utc

# Distances are floats; "reached the next chest" means within rounding error.
_EPSILON = 1e-9


# --------------------------------------------------------------------------
# Experience and levels
# --------------------------------------------------------------------------


def level_cost(level: int) -> float:
    """What one level costs, in converted Miles, beyond the level below it.

    The first four are the race ladder: 5K, 10K, half, marathon. After that
    each level costs one more marathon than the last, so level five is two
    marathons, level six is three, and the climb keeps its shape forever.
    """
    if level <= 0:
        return 0.0
    if level <= len(LEVEL_COSTS_MI):
        return LEVEL_COSTS_MI[level - 1]
    return LEVEL_STEP_MI * (level - 3)


def xp_to_reach(level: int) -> float:
    """Total converted Miles needed to stand at `level`. Level 0 is free."""
    return sum(level_cost(step) for step in range(1, max(level, 0) + 1))


def level_for_xp(xp: float) -> int:
    """The level a total of experience stands at. A fresh account is level 0.

    Walked rather than solved: the costs are a short table and then an
    arithmetic series, and a closed form over the two of them is more ways to
    be subtly wrong than it is worth. The walk stops at MAX_LEVEL so a
    corrupted total cannot hold a request open.
    """
    level = 0
    spent = 0.0
    while level < MAX_LEVEL:
        cost = spent + level_cost(level + 1)
        # Tolerance: a total summed from floats must still clear a level it
        # has exactly paid for.
        if xp + _EPSILON < cost:
            break
        spent = cost
        level += 1
    return level


def level_bounds(xp: float) -> tuple[int, float, float]:
    """(level, experience into this level, experience this level is worth)."""
    level = level_for_xp(xp)
    floor = xp_to_reach(level)
    return level, max(xp - floor, 0.0), level_cost(level + 1)


def border_tier(level: int) -> int:
    """Which avatar border a level has earned, from 1 to len(BORDER_LEVELS)."""
    return sum(1 for threshold in BORDER_LEVELS if level >= threshold) or 1


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------


def ensure_progress(db: Session, user_id: int) -> models.UserProgress:
    """The account's progress row, created empty if it has none. Lazy so an
    account that predates the table is never left without one."""
    row = db.get(models.UserProgress, user_id)
    if row is not None:
        return row
    row = models.UserProgress(
        user_id=user_id,
        xp=0.0,
        level=0,
        chest_progress_mi=0.0,
        cycle_pos=0,
        last_ack_at=None,
        updated_at=now_utc(),
    )
    db.add(row)
    db.flush()
    return row


def process_user(db: Session, user_id: int) -> models.UserProgress:
    """Credit every workout this account has not been credited for, oldest first."""
    progress = ensure_progress(db, user_id)
    pending = (
        db.execute(
            select(models.Workout)
            .where(
                models.Workout.user_id == user_id,
                models.Workout.id.not_in(select(models.ProcessedWorkout.workout_id)),
            )
            # By id within a timestamp so simultaneous workouts credit in a
            # stable order.
            .order_by(models.Workout.start_ts, models.Workout.id)
        )
        .scalars()
        .all()
    )
    credited = 0
    for workout in pending:
        if not _claim(db, workout.id):
            continue
        _credit(db, progress, workout)
        credited += 1
    if credited:
        progress.updated_at = now_utc()
    db.commit()
    return progress


def _claim(db: Session, workout_id: int) -> bool:
    """Write the processed marker before the work it stands for. The primary
    key decides which of two concurrent requests owns the workout."""
    try:
        with db.begin_nested():
            db.add(models.ProcessedWorkout(workout_id=workout_id))
            db.flush()
    except IntegrityError:
        return False
    return True


def _credit(db: Session, progress: models.UserProgress, workout: models.Workout) -> None:
    miles = converted_miles(workout.activity, workout.distance_mi)
    # Experience is the distance itself. One converted Mile, one XP.
    progress.xp += miles
    progress.level = level_for_xp(progress.xp)
    medals.award_workout_medals(db, progress.user_id, workout)
    # After the workout is credited, so the week it falls in is totalled with
    # this one in it. The whole week is walked again rather than added to, which
    # is what makes a backfill arriving out of order land on the same rows.
    medals.update_week_for(db, progress.user_id, workout)
    # When the workout arrived rather than when it happened, so a week of
    # history synced this morning waters what is in the ground this morning,
    # and so a rebuild replays to the same numbers. Falls back to the start
    # time for a row written without an arrival stamp.
    moment = workout.created_at or workout.start_ts
    _advance_chests(db, progress, miles, moment)
    grove.grow(db, progress.user_id, miles, workout.activity, moment)


# --------------------------------------------------------------------------
# Chests
# --------------------------------------------------------------------------


def ladder_step(cycle_pos: int) -> tuple[str, str, float]:
    """(tier id, tier name, cost in converted Miles) at a point in the cycle."""
    return CHEST_LADDER[cycle_pos % len(CHEST_LADDER)]


def tier_of(chest: models.Chest) -> tuple[str, str]:
    """(tier id, tier name) for a chest, including one from before the ladder.

    A chest that predates the ladder is treated as the first step throughout:
    it rolls the first step's odds, so calling it anything else would be the
    API disagreeing with itself.
    """
    for tier_id, name, _cost in CHEST_LADDER:
        if chest.tier == tier_id:
            return tier_id, name
    return CHEST_LADDER[0][0], CHEST_LADDER[0][1]


def tier_floor(tier: str | None) -> str:
    """The rarity a chest of this tier is worth at worst, legacy chests included."""
    return CHEST_TIER_FLOOR.get(tier or "", CHEST_TIER_FLOOR[LEGACY_CHEST_TIER])


def can_lift(tier: str | None) -> bool:
    """Whether a gift has anywhere to go on a chest of this tier.

    An Ultra floors at legendary and legendary is the top rung, so oil spent on
    one would buy nothing. A gift skips such a chest and waits for the next with
    room rather than being spent on a step it cannot climb.
    """
    return species.RARITY_LADDER.index(tier_floor(tier)) < len(species.RARITY_LADDER) - 1


def next_chest(progress: models.UserProgress, gifts: Sequence[str] = ()) -> dict:
    """Which chest is coming, how far off it is, and whose oil is on it.

    tier is the name to print and tier_id is the stable one to key on, the
    same pair every chest carries.
    """
    tier_id, name, cost = ladder_step(progress.cycle_pos)
    return {
        "tier": name,
        "tier_id": tier_id,
        "miles_away": round(max(cost - progress.chest_progress_mi, 0.0), 2),
        # The friend whose gift this chest will take, oldest gift first. Null
        # when none is waiting, and null on a chest with no room for one: that
        # gift is still waiting, for a later chest.
        "gifted_by": gifts[0] if gifts and can_lift(tier_id) else None,
    }


def _advance_chests(
    db: Session, progress: models.UserProgress, miles: float, moment: dt.datetime
) -> None:
    """Bank converted Miles toward the next chest and drop what falls out.

    The accumulator carries between workouts, so a run that ends short of a
    chest leaves what it covered here rather than losing it, and one long
    workout can climb several steps of the ladder at once.

    Whatever oil has been spent on this account rides along: one gift lifts one
    chest, in the order the gifts arrived, and a chest with no room for one is
    passed over. A gift is never spent on the miles themselves, only on what
    they were already going to bring.
    """
    waiting = grove.pending_anointings(db, progress.user_id)
    remaining = miles
    while True:
        tier_id, _name, cost = ladder_step(progress.cycle_pos)
        room = cost - progress.chest_progress_mi
        if remaining < room - _EPSILON:
            progress.chest_progress_mi += remaining
            return
        remaining -= room
        progress.chest_progress_mi = 0.0
        progress.cycle_pos = (progress.cycle_pos + 1) % len(CHEST_LADDER)
        lifted = waiting.pop(0) if waiting and can_lift(tier_id) else None
        chest = _drop_chest(
            db, progress.user_id, tier_id, lifted.id if lifted is not None else None
        )
        if lifted is not None:
            lifted.consumed_at = moment
            lifted.consumed_chest_id = chest.id


def _drop_chest(
    db: Session, user_id: int, tier: str, from_anointing_id: int | None = None
) -> models.Chest:
    """Drop one chest. What is in it is rolled when it is opened, against the
    odds of the tier stored here: the ladder decides how good a chest is, and
    the roll happens once, on the way out. A gift attached here is the promise
    that the roll will climb; it is kept at the moment the lid comes off."""
    chest = models.Chest(
        user_id=user_id,
        tier=tier,
        from_anointing_id=from_anointing_id,
        dropped_at=now_utc(),
        opened_at=None,
    )
    db.add(chest)
    db.flush()
    return chest


def roll_slot(rng: random.Random, tier: str | None, lifted: bool = False) -> str:
    """Which rarity slot a chest of this tier comes up with.

    The step of the ladder sets the floor and the chest is never worth less
    than it: four times in five it is exactly its own step, and the fifth time
    it is the one above. An Ultra already stands on the top rung, so the roll
    still happens and lands where it started.

    A chest somebody's oil lifted takes that step for certain. The gift is the
    same upgrade, promised rather than risked, which is why it is worth nothing
    on a chest already standing at the top. The roll is still drawn, so a lifted
    chest and a plain one leave the generator in the same place.
    """
    step = species.RARITY_LADDER.index(tier_floor(tier))
    if rng.random() < CHEST_UPGRADE_CHANCE or lifted:
        step = min(step + 1, len(species.RARITY_LADDER) - 1)
    return species.RARITY_LADDER[step]


def roll_loot(
    rng: random.Random,
    tier: str | None,
    first_ever: bool,
    held: frozenset[str] | set[str] = frozenset(),
    lifted: bool = False,
) -> tuple[str, str | None, str]:
    """What one chest holds, as (kind, species id or None, rarity).

    Two rolls: the tier decides the rarity slot, and the slot decides whether
    it is a seed or the tool that shares it. The three seed slots share theirs
    with water; the two above them are tools outright, an epic being half a
    wish and half oil, and a legendary being oil.

    A plot holds one of each species, so a seed of something the account
    already has is rolled again inside its own rarity, among what it is
    missing. The first roll still happens either way, which is what keeps a
    chest that was never a duplicate landing on exactly what it always did.
    With nothing left to want in that rarity the slot pours water instead:
    there is no such thing as an item worth nothing. A wish falls to water by
    the same rule, once there is nothing left anywhere to wish for.

    The first chest an account ever opens ignores all of it. That is never
    explained anywhere, and this is the only line that knows about it.
    """
    if first_ever:
        seed = species.BY_ID[species.FIRST_CHEST_SPECIES]
        return "seed", seed.id, seed.rarity
    rarity = roll_slot(rng, tier, lifted)
    choices = CHEST_SLOT_ITEMS[rarity]
    kind = rng.choices(
        [kind for kind, _weight in choices], weights=[weight for _kind, weight in choices], k=1
    )[0]
    if kind == "wish":
        return ("wish", None, rarity) if species.missing(held) else ("water", None, rarity)
    if kind != "seed":
        return kind, None, rarity
    picked = rng.choice(species.BY_RARITY[rarity]).id
    if picked not in held:
        return "seed", picked, rarity
    # The mustard tree is not in the bag rolled from, so it is not in this one
    # either: it is given once and never made up for.
    lacking = [row.id for row in species.BY_RARITY[rarity] if row.id not in held]
    if not lacking:
        return "water", None, rarity
    return "seed", rng.choice(lacking), rarity


def open_chest(
    db: Session, user_id: int, chest: models.Chest
) -> models.SatchelItem | None:
    """Roll what a chest was carrying and put it in the satchel, or answer None.

    The lid comes off with a conditional update rather than by writing to a row
    that was read a moment ago, and None is what the request that lost that race
    gets. Nothing is rolled and no item is created before it: the roll is seeded
    on the account and the chest, so two openings would agree about what was
    inside, and would then put two of it in the satchel. The claim is what makes
    the roll happen once.

    Flushes but never commits: the caller owns the transaction.

    What the plot already holds is read here, at the moment of opening, which
    is where every other roll has always been decided. A gift attached at the
    drop is kept here too: the promised step up is taken now, with everything
    else the chest decides.
    """
    now = now_utc()
    claimed = db.execute(
        update(models.Chest)
        .where(models.Chest.id == chest.id, models.Chest.opened_at.is_(None))
        .values(opened_at=now)
    )
    if claimed.rowcount != 1:
        return None

    # "First" means the first chest that ever yielded an item, not the first
    # chest row ever opened: an account migrated from the card era has opened
    # chests but holds no items, and its mustard moment is still ahead of it.
    first_ever = (
        db.execute(
            select(models.SatchelItem.id)
            .where(models.SatchelItem.user_id == user_id)
            .limit(1)
        ).first()
        is None
    )
    rng = random.Random(f"{user_id}:chest:{chest.id}")
    kind, species_id, rarity = roll_loot(
        rng,
        chest.tier,
        first_ever,
        grove.held_species(db, user_id),
        chest.from_anointing_id is not None,
    )
    item = models.SatchelItem(
        user_id=user_id,
        kind=kind,
        species=species_id,
        rarity=rarity,
        chest_id=chest.id,
        acquired_at=now,
        used_at=None,
    )
    db.add(item)
    db.flush()
    return item


def recompute(db: Session, user_id: int) -> models.UserProgress:
    """Throw away one account's derived progress and rebuild it from the
    workouts. Workouts are never touched.

    Medals go, and come straight back: every one of them is earned by the
    history rather than held forever, so replaying the history is the only
    thing that rebuilds them, and each one returns with the date it had.

    Nothing anybody chose is rebuilt. The satchel, what is planted, and every
    anointing are actions rather than consequences, so they are left exactly as
    they are; only the growth in the plot is replayed, from the same workouts.

    Every chest goes, lifted ones included, because every chest is a distance
    now: oil raises a chest the miles earned rather than dropping one of its
    own, and holding one back would only have the replay drop it a second time.
    An anointing already spent stays spent. Giving an old gift back to be given
    again would be minting one nobody sent.
    """
    db.execute(delete(models.Chest).where(models.Chest.user_id == user_id))
    grove.reset_growth(db, user_id)
    medals.clear_earns(db, user_id)
    # processed_workouts is keyed by workout; the workout is what has an owner.
    db.execute(
        delete(models.ProcessedWorkout).where(
            models.ProcessedWorkout.workout_id.in_(
                select(models.Workout.id).where(models.Workout.user_id == user_id)
            )
        )
    )
    row = db.get(models.UserProgress, user_id)
    if row is not None:
        row.xp = 0.0
        row.level = 0
        row.chest_progress_mi = 0.0
        row.cycle_pos = 0
    db.commit()
    return process_user(db, user_id)


# --------------------------------------------------------------------------
# Reading the state back
# --------------------------------------------------------------------------


def _totals(
    db: Session, user_id: int, since: dt.datetime | None = None
) -> dict[str, dict]:
    """Per-activity distance, energy, and count, in the Almanac's shape:
    absent activities are missing keys, same as the weekly endpoint."""
    stmt = select(
        models.Workout.activity,
        func.coalesce(func.sum(models.Workout.distance_mi), 0.0),
        func.coalesce(func.sum(models.Workout.active_kcal), 0.0),
        func.count(),
    ).where(models.Workout.user_id == user_id)
    if since is not None:
        stmt = stmt.where(models.Workout.start_ts >= since)
    rows = db.execute(stmt.group_by(models.Workout.activity)).all()
    found = {row[0]: row for row in rows}
    return {
        name: {
            "distance_mi": round(float(found[name][1]), 2),
            "converted_mi": round(converted_miles(name, float(found[name][1])), 2),
            "active_kcal": round(float(found[name][2]), 1),
            "workouts": int(found[name][3]),
        }
        for name in ACTIVITIES
        if name in found
    }


def lifetime_totals(db: Session, user_id: int) -> dict[str, dict]:
    return _totals(db, user_id)


def week_totals(db: Session, user_id: int, week_start_date: dt.date) -> dict[str, dict]:
    """Totals since the given Monday, server timezone: the same Monday the
    Almanac uses, so the two screens can never disagree."""
    cutoff = dt.datetime.combine(week_start_date, dt.time.min, tzinfo=SERVER_TZ)
    return _totals(db, user_id, since=cutoff)


def streak_weeks(db: Session, user_id: int, moment: dt.datetime | None = None) -> int:
    """How many weeks in a row have carried at least one workout.

    Counted back from the current week, over the same server-timezone Mondays
    the Almanac groups by, so the two screens can never disagree about where a
    week starts. A quiet current week does not break the streak: the week is
    still being lived, so the count simply starts from the one behind it. Miles
    are what keep it alive, never opening the app.
    """
    this_week = week_start(moment or now_utc())
    one_week = dt.timedelta(weeks=1)
    stamps = db.execute(
        select(models.Workout.start_ts)
        .where(models.Workout.user_id == user_id)
        # Newest first so the walk below stops at the first gap rather than
        # reading a whole history to answer a question about recent weeks.
        .order_by(models.Workout.start_ts.desc())
    ).scalars()

    count = 0
    cursor = this_week
    for stamp in stamps:
        week = week_start(stamp)
        if week > this_week:
            # Dated ahead of now, which a phone with a wandering clock is free
            # to send. It cannot extend a streak that has not happened yet.
            continue
        if count == 0:
            if week < this_week - one_week:
                return 0
            count = 1
        elif week == cursor - one_week:
            count += 1
        elif week < cursor - one_week:
            break
        else:
            continue  # another workout in a week already counted
        cursor = week
    return count


def week_days(db: Session, user_id: int, moment: dt.datetime | None = None) -> list[bool]:
    """Which days of the current week already carry a workout, Monday first.

    Bucketed by the same server-timezone Monday the streak above is counted
    over, and read from the same column, so the seven diamonds and the number
    of weeks beside them can never disagree about which week it is or which day
    a late-evening run belongs to.

    A workout dated ahead of this week is ignored rather than wrapped into it, a
    phone with a wandering clock being free to send one.
    """
    this_week = week_start(moment or now_utc())
    cutoff = dt.datetime.combine(this_week, dt.time.min, tzinfo=SERVER_TZ)
    days = [False] * 7
    for stamp in db.execute(
        select(models.Workout.start_ts).where(
            models.Workout.user_id == user_id, models.Workout.start_ts >= cutoff
        )
    ).scalars():
        if week_start(stamp) != this_week:
            continue
        days[stamp.astimezone(SERVER_TZ).weekday()] = True
    return days


def diamond_sports(db: Session, user_id: int, chosen: list | None) -> list[str]:
    """The three sports the profile wears, picked or worked out from the miles.

    A stored list is taken as it stands, including an empty one. Null is the
    default and means automatic: the sports with the most lifetime distance,
    which is what a profile should say about somebody nobody has asked yet.
    """
    if chosen is not None:
        return [str(name) for name in chosen]
    totals = lifetime_totals(db, user_id)
    # Only sports that have actually covered ground; a session logged with no
    # distance has no miles to put on a diamond. Ties fall back to the activity
    # order so the same history always produces the same three.
    ranked = sorted(
        (name for name in totals if totals[name]["distance_mi"] > 0),
        key=lambda name: (-totals[name]["distance_mi"], ACTIVITIES.index(name)),
    )
    return ranked[:MAX_DIAMOND_SPORTS]
