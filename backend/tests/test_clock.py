"""The suite's pinned clock, and the properties the rest of the cases assume.

Nothing here exercises the app. It exists so that moving FROZEN_NOW fails
right here, with a sentence saying what broke, instead of surfacing later as a
handful of medal and weekly-total cases failing for no visible reason.
"""

import datetime as dt

from conftest import FROZEN_NOW, neutral_start

from app.config import SERVER_TZ
from app.medals import EARLY_RISER_FROM, EARLY_RISER_UNTIL, NIGHT_OWL_FROM

# The largest offset any case passes to log_workout. A bigger one would need
# the reasoning in neutral_start's docstring redone.
MAX_OFFSET_MIN = 600


def monday_of(moment: dt.datetime) -> dt.date:
    local = moment.astimezone(SERVER_TZ).date()
    return local - dt.timedelta(days=local.weekday())


def test_the_frozen_clock_is_an_aware_utc_moment():
    assert FROZEN_NOW.tzinfo is not None
    assert FROZEN_NOW.utcoffset() == dt.timedelta(0)


def test_the_neutral_start_sits_where_the_suite_needs_it():
    start = neutral_start()
    # Same Monday-started week, or every case that counts what this week holds
    # reads an empty week.
    assert monday_of(start) == monday_of(FROZEN_NOW)
    # In the past, including the workout furthest along the offset.
    latest = start + dt.timedelta(minutes=MAX_OFFSET_MIN)
    assert latest < FROZEN_NOW
    # Clear of both time-of-day medal windows, at each end of the offset range,
    # so a case about a distance is never also a case about an hour.
    for moment in (start, latest):
        hour = moment.astimezone(SERVER_TZ).hour
        assert not EARLY_RISER_FROM <= hour < EARLY_RISER_UNTIL
        assert not (hour >= NIGHT_OWL_FROM or hour < EARLY_RISER_FROM)
