"""The Vale: where the marker is, where it is going, and what happened on the way."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import journey as engine
from app import models, security, world
from app.db import get_db

router = APIRouter(tags=["journey"])

# The recap is a story, not a feed. Anything past this many unseen events is
# almost certainly a journey-restart replaying months of history, and nobody
# reads three hundred lines of it; acking still clears the lot, because an
# event nobody is going to read is not worth paginating.
MAX_RECAP = 200


class DestinationBody(BaseModel):
    location_id: str


@router.get("/journey")
def read_journey(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """The whole Vale screen, after walking anything that arrived since last time.

    The sweep runs here rather than only at ingest so a workout that landed
    while the app was closed, or one that was written straight into the
    database, still moves the marker the next time somebody looks.
    """
    return engine.serialize_state(db, engine.process_user(db, user.id))


@router.post("/journey/destination")
def set_destination(
    body: DestinationBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Choose somewhere to set out for. The only steering the game asks for."""
    # Swept first so the choice is made against where the marker really is,
    # not where it was before this morning's sync.
    row = engine.process_user(db, user.id)
    target = world.LOCATIONS.get(body.location_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no such place in the Vale.")
    if target.id == row.location_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You are already there.")

    unlocked = engine.unlocked_regions(db, user.id)
    # From a road, either end counts as a starting point: the marker can turn
    # around, and rerouting from the far end is a legitimate way to get there.
    origins = (
        [row.location_id]
        if row.location_id is not None
        else [world.ROADS[row.road_id].from_id, world.ROADS[row.road_id].to_id]
    )
    if not any(target.id in world.reachable(origin, unlocked) for origin in origins):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"There is no open road to {target.name} yet.",
        )

    row.destination_id = target.id
    row.updated_at = security.now_utc()
    db.commit()
    return engine.serialize_state(db, row)


@router.get("/journey/recap")
def read_recap(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """Everything that happened while the app was closed, oldest first."""
    engine.process_user(db, user.id)
    rows = db.execute(
        select(models.JourneyEvent)
        .where(models.JourneyEvent.user_id == user.id, models.JourneyEvent.seen.is_(False))
        .order_by(models.JourneyEvent.id)
        .limit(MAX_RECAP)
    ).scalars()
    return [engine.serialize_event(row) for row in rows]


@router.post("/journey/recap/ack", status_code=status.HTTP_204_NO_CONTENT)
def ack_recap(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    db.execute(
        update(models.JourneyEvent)
        .where(models.JourneyEvent.user_id == user.id, models.JourneyEvent.seen.is_(False))
        .values(seen=True)
    )
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/regions/{region_id}/unlock")
def unlock_region(
    region_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Open a gated region by spending run Miles.

    Run Miles specifically, and only run Miles. Reach is running's role in the
    world, and letting a long cycle ride pay for it would take that away.
    """
    row = engine.process_user(db, user.id)
    region = world.REGIONS.get(region_id)
    if region is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "There is no such region.")
    if db.get(models.RegionUnlock, (user.id, region_id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{region.name} is already open.")

    available = engine.available_miles(db, user.id, "run", row.started_at)
    # The tolerance is there because the bucket is a sum of floats: somebody
    # who ran exactly the cost should not be refused over the last bit of a
    # rounding error.
    if available + 1e-6 < region.cost_run_miles:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{region.name} costs {region.cost_run_miles} run Miles. "
            f"You have {available:.1f}.",
        )

    now = security.now_utc()
    db.add(models.RegionUnlock(user_id=user.id, region_id=region_id, unlocked_at=now))
    # The spend is a ledger row rather than a subtraction, so the bucket stays
    # the difference between two things that are only ever appended to.
    db.add(
        models.MileSpend(
            user_id=user.id,
            activity="run",
            amount_mi=region.cost_run_miles,
            reason=f"unlock:{region_id}",
            created_at=now,
        )
    )
    db.add(
        models.JourneyEvent(
            user_id=user.id,
            created_at=now,
            type="unlock",
            data={
                "region_id": region.id,
                "region_name": region.name,
                "detail": region.detail,
                "cost_run_miles": region.cost_run_miles,
            },
            seen=False,
        )
    )
    row.updated_at = now
    db.commit()
    return engine.serialize_state(db, row)
