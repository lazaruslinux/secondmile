"""Workout route lines: reading a GPS trace, trimming its ends, thinning it.

Privacy is why this module has the shape it does. A raw trace starts and ends
where the person lives, so the first thing done to one is to throw both ends
away; what gets stored can never point at a front door. Everything after that
is size: a real run carries a couple of thousand points and a feed card is a
few hundred pixels wide, so the line is thinned to something a card can draw.

Nothing here may raise into an ingest. A route is decoration on a workout, and
a workout that happened must never fail to import because its trace was odd.
"""

import heapq
import logging
import math

from sqlalchemy.orm import Session

from app import models

log = logging.getLogger("secondmile.routemaps")

# Every point this close to the first or the last point is dropped. Two hundred
# metres is a couple of streets: enough that the visible line starts somewhere
# along the route rather than at a door.
TRIM_RADIUS_M = 200.0

# The most points a stored line may carry.
MAX_ROUTE_POINTS = 200

# Below this, what survived the trim is not a shape worth drawing. A loop that
# starts and ends at home can vanish entirely here, which is the correct
# outcome rather than a failure.
MIN_ROUTE_POINTS = 10

# Five decimals is about a metre, which is finer than any line drawn at card
# size can show and coarser than the raw fix.
COORD_DECIMALS = 5

# Points closer to the line than this are never worth keeping, whatever budget
# is left. Roughly a metre in latitude degrees.
MIN_DEVIATION_DEG = 1e-5

# A ceiling on the raw points one route may be read from, applied by taking
# every nth point. The thinning below costs work proportional to the input, and
# a single enormous trace should not be able to hold a sync open. Well past what
# any real workout records.
MAX_RAW_POINTS = 20000

_EARTH_RADIUS_M = 6371008.8


def _number(value) -> float | None:
    """A finite coordinate out of whatever the export wrote, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def read_points(raw) -> list[tuple[float, float]]:
    """The usable latitude and longitude pairs out of a raw route array.

    Only the two coordinates matter; altitude, speed, and accuracy are read by
    nothing here. A point missing either one is skipped rather than guessed at,
    and a route that is not a list of objects simply yields nothing.
    """
    if not isinstance(raw, list):
        return []
    points: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        lat = _number(item.get("latitude"))
        lon = _number(item.get("longitude"))
        if lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        points.append((lat, lon))
    if len(points) > MAX_RAW_POINTS:
        # Uniform stride rather than truncation: it keeps the whole shape,
        # including both ends, which the trim below still has to find.
        stride = len(points) // MAX_RAW_POINTS + 1
        points = points[::stride]
    return points


def haversine_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Great-circle distance between two points, in metres."""
    lat1, lon1 = math.radians(first[0]), math.radians(first[1])
    lat2, lon2 = math.radians(second[0]), math.radians(second[1])
    half = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(half)))


def trim_ends(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drop every point within TRIM_RADIUS_M of either end of the trace.

    A filter over the whole route rather than a prefix and a suffix, so an
    out-and-back that passes the door in the middle loses that stretch too.
    """
    if not points:
        return []
    first, last = points[0], points[-1]
    return [
        point
        for point in points
        if haversine_m(point, first) > TRIM_RADIUS_M and haversine_m(point, last) > TRIM_RADIUS_M
    ]


def _deviation(point, start, end, lon_scale: float) -> float:
    """Distance from a point to the line through start and end, in scaled degrees.

    Longitude is scaled by the cosine of the working latitude so a degree east
    counts for what it is worth on the ground. Flat geometry is exact enough
    over the few miles one workout covers.
    """
    px = (point[1] - start[1]) * lon_scale
    py = point[0] - start[0]
    ex = (end[1] - start[1]) * lon_scale
    ey = end[0] - start[0]
    span = ex * ex + ey * ey
    if span == 0.0:
        return math.hypot(px, py)
    return abs(px * ey - py * ex) / math.sqrt(span)


def simplify(
    points: list[tuple[float, float]], max_points: int = MAX_ROUTE_POINTS
) -> list[tuple[float, float]]:
    """Douglas-Peucker, spending a fixed budget of points on the worst corners.

    The classic algorithm takes a tolerance and returns however many points that
    produces; this one takes a count and keeps splitting at the furthest point
    from the current line until the budget is gone, which is the same set of
    keeps in the same order of importance with an answer that fits a column in
    the database.

    Iterative, with a heap rather than recursion. A ten thousand point trace
    would nest ten thousand deep in the recursive form and take the request down
    with it.
    """
    if len(points) <= max_points or max_points < 2:
        return list(points)
    mean_lat = sum(point[0] for point in points) / len(points)
    lon_scale = math.cos(math.radians(mean_lat))

    kept = {0, len(points) - 1}
    heap: list[tuple[float, int, int, int]] = []

    def consider(first: int, last: int) -> None:
        """Queue the furthest point between two keeps, if it is worth keeping."""
        worst, index = MIN_DEVIATION_DEG, -1
        for candidate in range(first + 1, last):
            distance = _deviation(points[candidate], points[first], points[last], lon_scale)
            if distance > worst:
                worst, index = distance, candidate
        if index >= 0:
            heapq.heappush(heap, (-worst, index, first, last))

    consider(0, len(points) - 1)
    while heap and len(kept) < max_points:
        _, index, first, last = heapq.heappop(heap)
        kept.add(index)
        consider(first, index)
        consider(index, last)
    return [points[index] for index in sorted(kept)]


def route_points(raw) -> list[list[float]] | None:
    """The line to store for one raw route, or None if there is nothing to store."""
    points = read_points(raw)
    if not points:
        return None
    kept = trim_ends(points)
    if len(kept) < MIN_ROUTE_POINTS:
        return None
    return [
        [round(lat, COORD_DECIMALS), round(lon, COORD_DECIMALS)] for lat, lon in simplify(kept)
    ]


def store_route(db: Session, workout_id: int, raw) -> bool:
    """Write the trimmed line for one workout. Returns whether a row was written.

    Never raises. Everything is caught, including the write, because this runs
    inside the sync loop and a route is not worth losing a workout over. The
    savepoint means a failed write rolls back the route alone.
    """
    try:
        points = route_points(raw)
        if points is None:
            return False
        with db.begin_nested():
            db.add(models.WorkoutRoute(workout_id=workout_id, points=points))
            db.flush()
        return True
    except Exception:
        log.warning("Could not store the route for workout %s", workout_id, exc_info=True)
        return False
