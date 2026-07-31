"""The journey engine: real workouts become movement, chests, and accolades.

Everything here is server side and idempotent per workout. A phone syncing
overlapping export windows, a manual entry for a walk that also synced, and
the catch-up sweep at the top of GET /api/journey all funnel through
process_user, and a workout that has already moved the marker never moves it
again.

Every roll is made by a generator seeded on (user id, workout id), so
reprocessing the same workout produces the same chests in the same order, and
a test can assert on an outcome rather than on a range.
"""

import datetime as dt
import random

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, world
from app.config import (
    CHEST_SPACING_MI,
    MILES_PER_RAW,
    UNOWNED_CARD_WEIGHT,
    WALK_BONUS_CHEST_CHANCE,
)
from app.models import ACTIVITIES
from app.security import now_utc

# Distances are floats, so "arrived" has to mean "within a rounding error of
# the end of the road" rather than "exactly equal to it".
_EPSILON = 1e-9

# How many road legs one workout may consume before the loop gives up and
# spends what is left on local rounds. The whole map is three roads, so this is
# a guard against a bug rather than a rule of the game.
_MAX_LEGS = 8


def ensure_journey(
    db: Session,
    user_id: int,
    *,
    started_at: dt.datetime | None = None,
    destination_id: str | None = world.START_DESTINATION,
) -> models.Journey:
    """The account's journey row, created at the Homestead if it has none.

    Called at registration so a new account starts from the moment it was
    made, and again from the engine so an account that predates the journey
    tables is never left without one.
    """
    row = db.get(models.Journey, user_id)
    if row is not None:
        return row
    moment = started_at or now_utc()
    row = models.Journey(
        user_id=user_id,
        location_id=world.START_LOCATION,
        road_id=None,
        position_mi=0.0,
        # A destination from the first day, so the first sync moves the marker
        # instead of walking it in circles at home.
        destination_id=destination_id,
        next_chest_mi=None,
        traveled_mi=0.0,
        started_at=moment,
        updated_at=moment,
    )
    db.add(row)
    db.flush()
    return row


def unlocked_regions(db: Session, user_id: int) -> set[str]:
    return set(
        db.execute(
            select(models.RegionUnlock.region_id).where(models.RegionUnlock.user_id == user_id)
        ).scalars()
    )


def converted_miles(activity: str, distance_mi: float) -> float:
    """What one workout's distance is worth as Miles in the world."""
    return distance_mi * MILES_PER_RAW[activity]


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------


def process_user(db: Session, user_id: int) -> models.Journey:
    """Apply every workout this account has not walked yet, oldest first.

    Returns the journey row, so callers that were going to read it anyway do
    not need a second lookup.
    """
    journey = ensure_journey(db, user_id)
    if journey.location_id is None and journey.road_id is None:
        # Neither at a place nor on a road, which the engine never writes.
        # Only a hand-edited row gets here; put the marker back at the
        # Homestead rather than raise on every request from then on.
        journey.location_id = world.START_LOCATION
        journey.position_mi = 0.0
    pending = (
        db.execute(
            select(models.Workout)
            .where(
                models.Workout.user_id == user_id,
                models.Workout.start_ts >= journey.started_at,
                models.Workout.id.not_in(select(models.ProcessedWorkout.workout_id)),
            )
            # Oldest first, and by id within a timestamp so two workouts that
            # started together are always walked in the same order.
            .order_by(models.Workout.start_ts, models.Workout.id)
        )
        .scalars()
        .all()
    )
    walked = 0
    for workout in pending:
        if not _claim(db, workout.id):
            continue
        _process_one(db, journey, workout)
        walked += 1
    if walked:
        journey.updated_at = now_utc()
    db.commit()
    return journey


def _claim(db: Session, workout_id: int) -> bool:
    """Write the processed marker before doing any of the work it stands for.

    Claiming first is what makes two requests arriving together safe: the
    primary key decides which of them owns the workout, and the loser skips it
    rather than walking the same miles a second time.
    """
    try:
        with db.begin_nested():
            db.add(models.ProcessedWorkout(workout_id=workout_id))
            db.flush()
    except IntegrityError:
        return False
    return True


def _process_one(db: Session, journey: models.Journey, workout: models.Workout) -> None:
    rng = random.Random(f"{journey.user_id}:{workout.id}")
    _advance(db, journey, workout, converted_miles(workout.activity, workout.distance_mi), rng)

    # Walking's gathering role, rolled after the movement so the extra chests
    # come from wherever the walk finished. Whole miles only: the roll is for
    # having covered a mile of ground, and a tenth of a mile is not one.
    if workout.activity == "walk":
        for _ in range(int(workout.distance_mi)):
            if rng.random() < WALK_BONUS_CHEST_CHANCE:
                _drop_chest(db, journey, workout, rng, "walk_bonus")


def _advance(
    db: Session,
    journey: models.Journey,
    workout: models.Workout,
    miles: float,
    rng: random.Random,
) -> None:
    unlocked = unlocked_regions(db, journey.user_id)
    remaining = miles
    for _ in range(_MAX_LEGS):
        if remaining <= _EPSILON:
            return
        if journey.road_id is None:
            road = _next_leg(journey.location_id, journey.destination_id, unlocked)
            if road is None:
                # Nowhere to go: no destination set, already there, or the gate
                # ahead is shut. The miles are not thrown away, they are walked
                # here. Nothing in this game punishes not opening the app, and
                # losing a morning's miles for not having picked a destination
                # would be exactly that.
                _local_rounds(db, journey, workout, remaining, rng)
                return
            journey.road_id = road.id
            journey.position_mi = 0.0 if road.from_id == journey.location_id else road.length_mi
            journey.location_id = None
        remaining = _travel_road(db, journey, workout, remaining, rng, unlocked)
    if remaining > _EPSILON and journey.location_id is not None:
        _local_rounds(db, journey, workout, remaining, rng)


def _next_leg(location_id: str | None, destination_id: str | None, unlocked: set[str]):
    """The first road of the way from here to the destination, if there is one."""
    if location_id is None or destination_id is None or destination_id == location_id:
        return None
    path = world.route(location_id, destination_id, unlocked)
    if not path:
        return None
    return path[0]


def _leg_target(road: world.Road, destination_id: str | None, unlocked: set[str]) -> str:
    """Which end of this road the marker is walking toward.

    Position is always measured from the road's from_id end, so travelling the
    other way counts down instead of up. Working the direction out from the
    destination each time is what lets a player turn around mid-road: the next
    workout simply finds a different answer here.
    """
    if destination_id is None or destination_id == road.to_id:
        return road.to_id
    if destination_id == road.from_id:
        return road.from_id
    ahead = world.route(road.to_id, destination_id, unlocked)
    behind = world.route(road.from_id, destination_id, unlocked)
    if ahead is None:
        return road.from_id if behind is not None else road.to_id
    if behind is None:
        return road.to_id
    return road.to_id if len(ahead) <= len(behind) else road.from_id


def _travel_road(
    db: Session,
    journey: models.Journey,
    workout: models.Workout,
    remaining: float,
    rng: random.Random,
    unlocked: set[str],
) -> float:
    """Walk as much of the current road as the miles allow. Returns the leftover."""
    road = world.ROADS[journey.road_id]
    target = _leg_target(road, journey.destination_id, unlocked)
    forward = target == road.to_id
    start = journey.position_mi
    room = (road.length_mi - start) if forward else start
    if room <= _EPSILON:
        # Standing on one end of a road, facing it. Step off and let the next
        # pass of the loop decide where to go from the place itself.
        _arrive(db, journey, target, announce=False)
        return remaining

    step = min(remaining, room)
    end = start + step if forward else start - step
    journey.position_mi = end
    _event(
        db,
        journey.user_id,
        "travel",
        {
            "workout_id": workout.id,
            "activity": workout.activity,
            "raw_distance_mi": round(workout.distance_mi, 3),
            "miles": round(step, 3),
            "road_id": road.id,
            "road_name": road.name,
            "from_mi": round(start, 3),
            "to_mi": round(end, 3),
            "road_length_mi": road.length_mi,
            "toward_id": target,
            "toward_name": world.LOCATIONS[target].name,
            "local": False,
        },
    )
    _milestones(db, journey, road, start, end, forward)
    _credit_miles(db, journey, workout, step, road.card_set, road.name, rng)

    if abs(end - (road.length_mi if forward else 0.0)) <= _EPSILON:
        _arrive(db, journey, target, announce=True)
    return remaining - step


def _arrive(db: Session, journey: models.Journey, location_id: str, *, announce: bool) -> None:
    journey.location_id = location_id
    journey.road_id = None
    journey.position_mi = 0.0
    reached = journey.destination_id == location_id
    if reached:
        # The destination is spent on arrival. Everything after this is local
        # rounds until the player picks somewhere new, which is the one piece
        # of steering the game asks of them.
        journey.destination_id = None
    if announce:
        _event(
            db,
            journey.user_id,
            "arrival",
            {
                "location_id": location_id,
                "location_name": world.LOCATIONS[location_id].name,
                "was_destination": reached,
            },
        )


def _local_rounds(
    db: Session,
    journey: models.Journey,
    workout: models.Workout,
    miles: float,
    rng: random.Random,
) -> None:
    location = world.LOCATIONS[journey.location_id]
    _event(
        db,
        journey.user_id,
        "travel",
        {
            "workout_id": workout.id,
            "activity": workout.activity,
            "raw_distance_mi": round(workout.distance_mi, 3),
            "miles": round(miles, 3),
            "location_id": location.id,
            "location_name": location.name,
            "local": True,
        },
    )
    _credit_miles(db, journey, workout, miles, location.card_set, location.name, rng)


def _milestones(
    db: Session,
    journey: models.Journey,
    road: world.Road,
    start: float,
    end: float,
    forward: bool,
) -> None:
    """Grant the accolade for every mark this step passed, once per account."""
    for milestone in road.milestones:
        crossed = (start < milestone.mile <= end) if forward else (end <= milestone.mile < start)
        if not crossed:
            continue
        if db.get(models.UserAccolade, (journey.user_id, milestone.id)) is not None:
            continue
        db.add(
            models.UserAccolade(
                user_id=journey.user_id, accolade_id=milestone.id, earned_at=now_utc()
            )
        )
        db.flush()
        _event(
            db,
            journey.user_id,
            "milestone",
            {
                "accolade_id": milestone.id,
                "name": milestone.name,
                "detail": milestone.detail,
                "road_id": road.id,
                "road_name": road.name,
                "mile": milestone.mile,
            },
        )


def _credit_miles(
    db: Session,
    journey: models.Journey,
    workout: models.Workout,
    miles: float,
    set_id: str,
    area_name: str,
    rng: random.Random,
) -> None:
    """Count travelled Miles toward the chest track and drop what falls out.

    The counter carries between workouts. A run that ends a quarter of a mile
    short of a chest leaves that quarter mile on the journey row, so the next
    walk picks it up rather than starting again from a fresh roll.
    """
    journey.traveled_mi += miles
    remaining = miles
    while True:
        if journey.next_chest_mi is None:
            journey.next_chest_mi = rng.uniform(*CHEST_SPACING_MI)
        if remaining < journey.next_chest_mi - _EPSILON:
            journey.next_chest_mi -= remaining
            return
        remaining -= journey.next_chest_mi
        journey.next_chest_mi = None
        _drop_chest(db, journey, workout, rng, "travel", set_id=set_id, area_name=area_name)


def choose_card(
    cards: tuple[world.Card, ...], owned: set[str], rng: random.Random
) -> world.Card:
    """Pick one card from a set, leaning toward the plates still missing.

    A lean rather than a rule. Weighting the unowned means a set can be
    finished by walking rather than by luck, while a duplicate staying
    possible is what keeps the last plate of a set worth waiting for. It is
    also what gives duplicates to trade away, which the whole economy is
    eventually built on.
    """
    weights = [1.0 if card.id in owned else UNOWNED_CARD_WEIGHT for card in cards]
    return rng.choices(cards, weights=weights, k=1)[0]


def _drop_chest(
    db: Session,
    journey: models.Journey,
    workout: models.Workout,
    rng: random.Random,
    source: str,
    *,
    set_id: str | None = None,
    area_name: str | None = None,
) -> models.Chest:
    """Drop one chest carrying a card from the set of wherever the marker is.

    The card is chosen now and stored, not chosen when the chest is opened.
    Opening is a reveal, not a roll: deciding at open time would make the
    outcome depend on when the player got round to tapping it, and this game
    refuses to reward opening the app.
    """
    if set_id is None or area_name is None:
        set_id, area_name = _current_set(journey)
    owned = set(
        db.execute(
            select(models.UserCard.card_id).where(models.UserCard.user_id == journey.user_id)
        ).scalars()
    )
    cards = world.CARDS_BY_SET[set_id]
    card = choose_card(cards, owned, rng)

    chest = models.Chest(
        user_id=journey.user_id, card_id=card.id, dropped_at=now_utc(), opened_at=None
    )
    db.add(chest)
    db.flush()
    _event(
        db,
        journey.user_id,
        "chest",
        {
            # Deliberately no card_id. The recap says a chest dropped and where
            # from; what is inside it is the open endpoint's to tell.
            "chest_id": chest.id,
            "set_id": set_id,
            "set_name": world.CARD_SETS[set_id].name,
            "set_size": len(cards),
            "area_name": area_name,
            "source": source,
            "workout_id": workout.id,
        },
    )
    return chest


def _current_set(journey: models.Journey) -> tuple[str, str]:
    """The card set and the place name for wherever the marker stands."""
    if journey.road_id is not None:
        road = world.ROADS[journey.road_id]
        return road.card_set, road.name
    location = world.LOCATIONS[journey.location_id]
    return location.card_set, location.name


def _event(db: Session, user_id: int, kind: str, data: dict) -> None:
    db.add(
        models.JourneyEvent(
            user_id=user_id, created_at=now_utc(), type=kind, data=data, seen=False
        )
    )
    db.flush()


# --------------------------------------------------------------------------
# Reading the state back
# --------------------------------------------------------------------------


def earned_miles(db: Session, user_id: int, started_at: dt.datetime) -> dict[str, float]:
    """Converted Miles per activity from every workout since the journey began.

    A sum over the workouts rather than a running total in a column, so it
    cannot drift out of step with the history the Almanac shows.
    """
    rows = db.execute(
        select(models.Workout.activity, func.coalesce(func.sum(models.Workout.distance_mi), 0.0))
        .where(models.Workout.user_id == user_id, models.Workout.start_ts >= started_at)
        .group_by(models.Workout.activity)
    ).all()
    raw = dict(rows)
    return {name: converted_miles(name, float(raw.get(name, 0.0))) for name in ACTIVITIES}


def spent_miles(db: Session, user_id: int) -> dict[str, float]:
    rows = db.execute(
        select(models.MileSpend.activity, func.coalesce(func.sum(models.MileSpend.amount_mi), 0.0))
        .where(models.MileSpend.user_id == user_id)
        .group_by(models.MileSpend.activity)
    ).all()
    spent = dict(rows)
    return {name: float(spent.get(name, 0.0)) for name in ACTIVITIES}


def available_miles(db: Session, user_id: int, activity: str, started_at: dt.datetime) -> float:
    """What one bucket has left to spend, unrounded, for the unlock check."""
    return earned_miles(db, user_id, started_at)[activity] - spent_miles(db, user_id)[activity]


def buckets(db: Session, user_id: int, started_at: dt.datetime) -> dict[str, dict]:
    earned = earned_miles(db, user_id, started_at)
    spent = spent_miles(db, user_id)
    return {
        name: {
            "earned": round(earned[name], 2),
            "spent": round(spent[name], 2),
            "available": round(earned[name] - spent[name], 2),
        }
        for name in ACTIVITIES
    }


def _position(journey: models.Journey, unlocked: set[str]) -> dict:
    if journey.road_id is not None:
        road = world.ROADS[journey.road_id]
        target = _leg_target(road, journey.destination_id, unlocked)
        return {
            "location_id": None,
            "location_name": None,
            "road_id": road.id,
            "road_name": road.name,
            "position_mi": round(journey.position_mi, 3),
            # Measured from the road's from_id end, which is the direction the
            # SVG path is drawn in, so the map can hand this straight to
            # getPointAtLength without knowing which way the player is facing.
            "fraction": round(journey.position_mi / road.length_mi, 5),
            "road_length_mi": road.length_mi,
            "road_from_id": road.from_id,
            "road_to_id": road.to_id,
            "heading_to_id": target,
            "heading_to_name": world.LOCATIONS[target].name,
        }
    location = world.LOCATIONS[journey.location_id]
    return {
        "location_id": location.id,
        "location_name": location.name,
        "road_id": None,
        "road_name": None,
        "position_mi": 0.0,
        "fraction": None,
        "road_length_mi": None,
        "road_from_id": None,
        "road_to_id": None,
        "heading_to_id": None,
        "heading_to_name": None,
    }


def serialize_state(db: Session, journey: models.Journey) -> dict:
    """Everything the Vale screen needs in one response.

    The static map goes out with it. The frontend draws the roads itself, but
    the names, lengths, and which gates are shut are decided here, so there is
    one place they are written down.
    """
    unlocked = unlocked_regions(db, journey.user_id)
    unopened = db.execute(
        select(func.count())
        .select_from(models.Chest)
        .where(models.Chest.user_id == journey.user_id, models.Chest.opened_at.is_(None))
    ).scalar_one()
    unseen = db.execute(
        select(func.count())
        .select_from(models.JourneyEvent)
        .where(
            models.JourneyEvent.user_id == journey.user_id,
            models.JourneyEvent.seen.is_(False),
        )
    ).scalar_one()
    open_places = world.reachable(
        journey.location_id or world.ROADS[journey.road_id].from_id, unlocked
    )
    return {
        "started_at": journey.started_at.isoformat(),
        "updated_at": journey.updated_at.isoformat(),
        "position": _position(journey, unlocked),
        "destination": (
            {
                "id": journey.destination_id,
                "name": world.LOCATIONS[journey.destination_id].name,
            }
            if journey.destination_id
            else None
        ),
        "buckets": buckets(db, journey.user_id, journey.started_at),
        "total_traveled_mi": round(journey.traveled_mi, 2),
        "unopened_chests": int(unopened),
        "unseen_events": int(unseen),
        "locations": [
            {
                "id": location.id,
                "name": location.name,
                "reachable": location.id in open_places,
            }
            for location in world.LOCATIONS.values()
        ],
        "roads": [
            {
                "id": road.id,
                "name": road.name,
                "from_id": road.from_id,
                "to_id": road.to_id,
                "length_mi": road.length_mi,
                "region_id": road.region,
                "open": road.region is None or road.region in unlocked,
            }
            for road in world.ROADS.values()
        ],
        "regions": [
            {
                "id": region.id,
                "name": region.name,
                "detail": region.detail,
                "unlocked": region.id in unlocked,
                "cost_run_miles": region.cost_run_miles,
            }
            for region in world.REGIONS.values()
        ],
    }


def serialize_event(event: models.JourneyEvent) -> dict:
    return {
        "id": event.id,
        "type": event.type,
        "created_at": event.created_at.isoformat(),
        "data": event.data or {},
    }
