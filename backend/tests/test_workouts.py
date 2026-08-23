"""The history page, the weekly totals, and the words, pictures, and video an
owner puts on a workout.

Nothing here creates a workout over HTTP, because nothing can: the sync path is
the only way one arrives, and it has its own file. The rows these cases read
are written straight into the table.
"""

import datetime as dt
import io
import json
import os
import pathlib
import subprocess
import tempfile
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import activity as activity_rules
from app import bests, models, progress, security
from app.activity import converted_miles
from app.config import MAX_PHOTO_BYTES
from app.main import app as fastapi_app
from conftest import make_user

pytest.importorskip("PIL")


def stored(
    db_session,
    user_id,
    *,
    activity="run",
    start="2026-07-20T06:12:00+00:00",
    duration=1800,
    miles=3.0,
    active_kcal=0.0,
    avg_hr=None,
    source="sync",
    indoor=False,
    elevation_ft=None,
) -> models.Workout:
    """One workout written straight in and credited, the way a sync would.

    The start is a literal so that a case about paging or about a week can put
    a row on the exact day it means. The crediting is not optional: medals are
    read off the table rather than recomputed, and half of what the history
    shows is what a workout was worth.
    """
    row = models.Workout(
        user_id=user_id,
        activity=activity,
        start_ts=dt.datetime.fromisoformat(start),
        duration_s=duration,
        distance_mi=miles,
        active_kcal=active_kcal,
        avg_hr=avg_hr,
        indoor=indoor,
        elevation_gain_ft=elevation_ft,
        source=source,
        flags={},
        created_at=security.now_utc(),
    )
    db_session.add(row)
    db_session.commit()
    progress.process_user(db_session, user_id)
    return row


def test_a_history_row_says_where_the_workout_came_from(signed_in, db_session, member):
    """Provenance outlives the way in. Nothing writes a manual row any more and
    the ones already written still say what they are, because where a workout
    came from is a fact about it rather than a note about a form."""
    stored(db_session, member.id, source="manual", active_kcal=320.0, avg_hr=148.0)
    stored(db_session, member.id, start="2026-07-21T06:12:00+00:00")
    rows = signed_in.get("/api/workouts").json()
    assert [row["source"] for row in rows] == ["sync", "manual"]
    assert rows[1]["active_kcal"] == 320.0
    assert rows[1]["flags"] == {}


def test_a_history_row_is_the_card_the_feed_draws(signed_in, db_session, member):
    """The log draws the feed's own card, so it is served the feed's row: who
    did the workout, what it earned, and what came back for it. The flags ride
    along on top, because they are the one thing the log shows and the feed
    does not."""
    workout = stored(db_session, member.id, active_kcal=320.0, avg_hr=148.0)
    row = signed_in.get("/api/workouts").json()[0]
    assert row["workout_id"] == workout.id
    assert "id" not in row
    assert row["own"] is True
    assert row["user"]["username"] == member.username
    assert row["encouragement"] == {
        "hype_count": 0,
        "note_count": 0,
        "cheered_by_me": False,
        "notes": [],
    }
    # Own rows carry everything: nothing is ever kept back from the person whose
    # workout it is.
    assert (row["avg_hr"], row["active_kcal"], row["flags"]) == (148.0, 320.0, {})


def test_history_is_newest_first_and_pages(signed_in, db_session, member):
    for day in range(1, 6):
        stored(db_session, member.id, start=f"2026-07-0{day}T06:00:00+00:00")

    page = signed_in.get("/api/workouts", params={"limit": 2}).json()
    assert isinstance(page, list)
    assert [row["start_ts"][:10] for row in page] == ["2026-07-05", "2026-07-04"]

    older = signed_in.get("/api/workouts", params={"limit": 2, "offset": 2}).json()
    assert [row["start_ts"][:10] for row in older] == ["2026-07-03", "2026-07-02"]

    # Past the end is an empty page rather than an error: that is how the tab
    # learns there is no more of it.
    assert signed_in.get("/api/workouts", params={"limit": 2, "offset": 5}).json() == []


def test_history_pages_under_every_sort(signed_in, db_session, member):
    """A page boundary lands in the same place whatever the list is ordered by.

    Five rows, three keys, both directions: the second page picks up exactly
    where the first one stopped, with nothing repeated and nothing skipped.
    """
    for day, miles in enumerate([3.0, 1.0, 5.0, 2.0, 4.0], start=1):
        stored(
            db_session,
            member.id,
            start=f"2026-07-0{day}T06:00:00+00:00",
            miles=miles,
            duration=int(miles * 600),
            avg_hr=100.0 + miles,
        )

    for sort in ("date", "distance", "pace", "avg_hr"):
        for order in ("asc", "desc"):
            whole = signed_in.get(
                "/api/workouts", params={"sort": sort, "order": order}
            ).json()
            paged = []
            for offset in (0, 2, 4):
                paged += signed_in.get(
                    "/api/workouts",
                    params={"sort": sort, "order": order, "limit": 2, "offset": offset},
                ).json()
            assert [row["workout_id"] for row in paged] == [
                row["workout_id"] for row in whole
            ], f"{sort} {order}"


def test_the_oldest_first_page_stops_at_the_end_of_the_history(signed_in, db_session, member):
    """The date-sort freeze, pinned at the server.

    His report was of the oldest-first page sticking in April with the controls
    dead. The client half of that was a stale answer landing on top of a fresh
    one; the half that lives here is the paging, which under the old cursor
    could not walk forwards at all: `before` asked for rows earlier than the
    last one on the page, which is the wrong end of an ascending list, so the
    second page was the same page again and the list never left April.

    A history the shape of his, February to August, paged oldest first: every
    page moves forwards, nothing repeats, and the last one is short.
    """
    for day in range(190):
        moment = dt.datetime(2026, 2, 1, 6, 0, tzinfo=dt.timezone.utc) + dt.timedelta(days=day)
        if day % 4 == 3:
            continue
        stored(db_session, member.id, start=moment.isoformat(), miles=1.0 + (day % 7))

    seen: list[int] = []
    dates: list[str] = []
    for offset in range(0, 200, 20):
        page = signed_in.get(
            "/api/workouts",
            params={"sort": "date", "order": "asc", "limit": 20, "offset": offset},
        ).json()
        seen += [row["workout_id"] for row in page]
        dates += [row["start_ts"][:10] for row in page]
        if len(page) < 20:
            break

    assert len(seen) == len(set(seen)) == 143
    # Forwards through the year, February at the top and August at the foot.
    assert dates == sorted(dates)
    assert dates[0].startswith("2026-02") and dates[-1].startswith("2026-08")
    # April is a page in the middle of it rather than the end of it.
    assert any(day.startswith("2026-04") for day in dates[40:80])
    assert any(day.startswith("2026-08") for day in dates[-20:])


def sorted_miles(signed_in, **params) -> list[float]:
    """The distances of a sorted page, which is the shortest way to say what
    order the rows came back in: every case below gives its rows a distance of
    their own."""
    rows = signed_in.get("/api/workouts", params=params).json()
    return [row["distance_mi"] for row in rows]


def a_dashboard_history(db_session, member) -> None:
    """Four workouts that disagree about everything the dashboard can sort by.

    The 2-mile walk is the slowest, the 6-mile run is the longest and the
    fastest, and the 1-mile walk is the shortest and carries no heart rate, so
    each key puts them in a different order and no two cases pass by accident.
    """
    stored(
        db_session,
        member.id,
        activity="run",
        start="2026-07-01T06:00:00+00:00",
        duration=1800,
        miles=3.0,
        avg_hr=150.0,
    )
    stored(
        db_session,
        member.id,
        activity="walk",
        start="2026-07-02T06:00:00+00:00",
        duration=2400,
        miles=2.0,
        avg_hr=110.0,
    )
    stored(
        db_session,
        member.id,
        activity="run",
        start="2026-07-03T06:00:00+00:00",
        duration=2700,
        miles=6.0,
        avg_hr=165.0,
    )
    # No heart rate on this one, and it is the shortest thing here.
    stored(
        db_session,
        member.id,
        activity="walk",
        start="2026-07-04T06:00:00+00:00",
        duration=700,
        miles=1.0,
    )


def test_history_sorts_by_date_both_ways(signed_in, db_session, member):
    """The default is the newest first, and the oldest first is one parameter
    away. Nothing else about the page changes."""
    a_dashboard_history(db_session, member)
    assert sorted_miles(signed_in) == [1.0, 6.0, 2.0, 3.0]
    assert sorted_miles(signed_in, sort="date", order="asc") == [3.0, 2.0, 6.0, 1.0]


def test_history_sorts_by_distance_both_ways(signed_in, db_session, member):
    a_dashboard_history(db_session, member)
    assert sorted_miles(signed_in, sort="distance", order="desc") == [6.0, 3.0, 2.0, 1.0]
    assert sorted_miles(signed_in, sort="distance", order="asc") == [1.0, 2.0, 3.0, 6.0]


def test_history_sorts_by_pace_both_ways(signed_in, db_session, member):
    """Pace is time over distance, so the smallest number is the quickest: the
    6-mile run at 7:30 a mile leads the ascending page and the 2-mile walk at
    20:00 a mile ends it."""
    a_dashboard_history(db_session, member)
    assert sorted_miles(signed_in, sort="pace", order="asc") == [6.0, 3.0, 1.0, 2.0]
    assert sorted_miles(signed_in, sort="pace", order="desc") == [2.0, 1.0, 3.0, 6.0]


def test_a_workout_with_no_distance_has_no_pace_and_sorts_last(signed_in, db_session, member):
    """Never a division, and never first either. A row that covered no ground
    has no pace at all, so it goes to the end of the pace page whichever way
    the page is pointed."""
    a_dashboard_history(db_session, member)
    stored(
        db_session,
        member.id,
        activity="walk",
        start="2026-07-05T06:00:00+00:00",
        duration=900,
        miles=0.0,
    )
    assert sorted_miles(signed_in, sort="pace", order="asc")[-1] == 0.0
    assert sorted_miles(signed_in, sort="pace", order="desc")[-1] == 0.0


def test_history_sorts_by_heart_rate_with_the_missing_ones_last(signed_in, db_session, member):
    """A workout that never carried a heart rate is not a slow one and not a
    fast one: it is at the bottom of both pages."""
    a_dashboard_history(db_session, member)
    high = signed_in.get("/api/workouts", params={"sort": "avg_hr", "order": "desc"}).json()
    assert [row["avg_hr"] for row in high] == [165.0, 150.0, 110.0, None]
    low = signed_in.get("/api/workouts", params={"sort": "avg_hr", "order": "asc"}).json()
    assert [row["avg_hr"] for row in low] == [110.0, 150.0, 165.0, None]


def test_history_filters_to_one_activity(signed_in, db_session, member):
    a_dashboard_history(db_session, member)
    walks = signed_in.get("/api/workouts", params={"activity": "walk"}).json()
    assert [row["activity"] for row in walks] == ["walk", "walk"]
    # The filter and the sort are read together rather than one instead of the
    # other, which is the whole of finding your shortest walk.
    assert sorted_miles(signed_in, activity="walk", sort="distance", order="asc") == [1.0, 2.0]


def test_a_sorted_or_filtered_history_still_leaves_out_deleted_workouts(
    signed_in, db_session, member
):
    """The Deleted section is the one place a deleted workout appears, and no
    parameter on this endpoint is a way round that."""
    a_dashboard_history(db_session, member)
    longest = signed_in.get("/api/workouts", params={"sort": "distance"}).json()[0]
    assert signed_in.delete(f"/api/workouts/{longest['workout_id']}").status_code == 204
    assert sorted_miles(signed_in, sort="distance", order="desc") == [3.0, 2.0, 1.0]
    assert sorted_miles(signed_in, sort="pace", order="asc") == [3.0, 1.0, 2.0]
    assert sorted_miles(signed_in, activity="run") == [3.0]


def test_history_refuses_parameters_it_does_not_have(signed_in):
    """Refused, and said in the one sentence the app's own controls can never
    provoke: these parameters are chosen by the interface rather than typed by
    anybody, so naming the parameter would say nothing to whoever read it."""
    bad_sort = signed_in.get("/api/workouts", params={"sort": "calories"})
    assert bad_sort.status_code == 400
    assert bad_sort.json()["detail"] == "Something went wrong. Try again."

    bad_order = signed_in.get("/api/workouts", params={"order": "sideways"})
    assert bad_order.status_code == 400

    bad_activity = signed_in.get("/api/workouts", params={"activity": "ski"})
    assert bad_activity.status_code == 400


def test_history_is_per_user(signed_in, client, db_session, member, admin):
    from conftest import ADMIN

    stored(db_session, member.id)
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    assert signed_in.get("/api/workouts").json() == []


def test_history_rows_carry_what_each_workout_was_worth(signed_in, db_session, member):
    """The row's xp is the converted distance the pipeline credited."""
    stored(db_session, member.id, duration=1800, miles=3.0)
    # Nine cycled miles are three Miles, so the same credit for a longer ride.
    stored(
        db_session,
        member.id,
        activity="cycle",
        start="2026-07-21T06:12:00+00:00",
        duration=1800,
        miles=9.0,
    )
    rows = signed_in.get("/api/workouts").json()
    assert [row["xp"] for row in rows] == [3.0, 3.0]
    for row in rows:
        assert row["xp"] == converted_miles(row["activity"], row["distance_mi"])


def test_history_rows_name_the_medals_a_run_earned(signed_in, db_session, member):
    stored(db_session, member.id, duration=3300, miles=6.4)
    stored(db_session, member.id, start="2026-07-21T06:12:00+00:00", duration=1800, miles=2.0)
    # An early run earns the distance and the hour both, in catalogue order.
    stored(db_session, member.id, start="2026-07-22T05:30:00+00:00", duration=2700, miles=4.0)
    rows = {row["distance_mi"]: row["medals"] for row in signed_in.get("/api/workouts").json()}
    assert rows[6.4] == ["race_10k"]
    # Two miles is the Second Mile now, and at a quarter past six in the
    # morning it is nothing else.
    assert rows[2.0] == ["race_2mi"]
    assert rows[4.0] == ["race_5k", "early_riser"]


def test_every_row_that_draws_a_sport_mark_says_whether_it_was_indoors(
    signed_in, db_session, member
):
    """The history row, the letter's row and the deleted row all draw the same
    mark, so all three carry the same qualifier."""
    treadmill = stored(db_session, member.id, miles=3.0, indoor=True)
    stored(db_session, member.id, start="2026-07-21T06:12:00+00:00", miles=3.0)

    rows = {row["workout_id"]: row["indoor"] for row in signed_in.get("/api/workouts").json()}
    assert rows[treadmill.id] is True
    assert set(rows.values()) == {True, False}

    letter = signed_in.get("/api/recap").json()["workouts"]
    assert {row["workout_id"]: row["indoor"] for row in letter}[treadmill.id] is True

    signed_in.delete(f"/api/workouts/{treadmill.id}")
    assert signed_in.get("/api/workouts/deleted").json()[0]["indoor"] is True


def test_history_needs_a_session(client):
    assert client.get("/api/workouts").status_code == 401


def _monday_of_this_week() -> dt.date:
    today = security.now_utc().date()
    return today - dt.timedelta(days=today.weekday())


def test_weekly_totals(signed_in, db_session, member):
    monday = _monday_of_this_week()
    stored(
        db_session,
        member.id,
        activity="run",
        start=f"{monday.isoformat()}T06:00:00+00:00",
        duration=1800,
        miles=3.0,
        active_kcal=300.0,
    )
    stored(
        db_session,
        member.id,
        activity="run",
        start=f"{(monday + dt.timedelta(days=1)).isoformat()}T06:00:00+00:00",
        duration=2400,
        miles=4.0,
        active_kcal=400.0,
    )
    stored(
        db_session,
        member.id,
        activity="walk",
        start=f"{(monday + dt.timedelta(days=2)).isoformat()}T06:00:00+00:00",
        duration=2400,
        miles=2.0,
        active_kcal=150.0,
    )

    # Two weeks back as well, so there is a rest week in between.
    stored(
        db_session,
        member.id,
        activity="run",
        start=f"{(monday - dt.timedelta(weeks=2)).isoformat()}T06:00:00+00:00",
        duration=1800,
        miles=1.0,
        active_kcal=90.0,
    )

    weeks = signed_in.get("/api/workouts/weeks").json()
    # This week back to the week the oldest workout is in, and no further.
    assert len(weeks) == 3
    assert weeks[0]["week_start"] == monday.isoformat()
    # Newest first.
    assert weeks[1]["week_start"] == (monday - dt.timedelta(weeks=1)).isoformat()

    current = weeks[0]["activities"]
    assert current["run"] == {"distance_mi": 7.0, "active_kcal": 700.0, "workouts": 2}
    assert current["walk"] == {"distance_mi": 2.0, "active_kcal": 150.0, "workouts": 1}
    # Activities with nothing in them are absent, not zero-filled.
    assert "cycle" not in current
    assert "swim" not in current
    assert weeks[0]["total_active_kcal"] == 850.0
    # A week with no movement is still listed, so rest is visible rather than
    # missing from the Almanac.
    assert weeks[1]["activities"] == {}
    assert weeks[1]["total_active_kcal"] == 0.0
    assert weeks[2]["activities"]["run"] == {
        "distance_mi": 1.0,
        "active_kcal": 90.0,
        "workouts": 1,
    }


def test_weekly_totals_reach_the_oldest_weeks(signed_in, db_session, member):
    """A week far back gets its totals, not just the recent ones.

    The history is paged twenty rows at a time and walks back as far as somebody
    keeps asking, so a heading from months ago needs its totals from here: a
    week half-loaded at a page boundary cannot be added up from the rows on
    screen.
    """
    monday = _monday_of_this_week()
    long_ago = monday - dt.timedelta(weeks=20)
    stored(
        db_session,
        member.id,
        start=f"{long_ago.isoformat()}T06:00:00+00:00",
        miles=5.0,
        active_kcal=999.0,
    )
    weeks = signed_in.get("/api/workouts/weeks").json()
    assert len(weeks) == 21
    assert weeks[-1]["week_start"] == long_ago.isoformat()
    assert weeks[-1]["activities"]["run"] == {
        "distance_mi": 5.0,
        "active_kcal": 999.0,
        "workouts": 1,
    }
    assert weeks[-1]["total_active_kcal"] == 999.0


def test_weekly_totals_of_an_empty_history(signed_in):
    """This week and nothing else: there is no history behind it to list."""
    weeks = signed_in.get("/api/workouts/weeks").json()
    assert len(weeks) == 1
    assert weeks[0]["week_start"] == _monday_of_this_week().isoformat()
    assert weeks[0]["activities"] == {}


def patch_words(client, workout_id, **fields):
    return client.patch(f"/api/workouts/{workout_id}", json=fields)


def test_the_owner_can_title_a_workout_and_write_on_it(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    fresh = signed_in.get("/api/workouts").json()[0]
    assert (fresh["title"], fresh["post"], fresh["photos"]) == (None, None, [])

    patched = patch_words(signed_in, workout.id, title="Morning loop", post="Cold start.")
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Morning loop"
    assert patched.json()["post"] == "Cold start."
    # The whole row comes back, not a fragment of it: the card that sent the
    # edit redraws from this without asking for the history again.
    assert patched.json() == signed_in.get("/api/workouts").json()[0]


def test_words_are_trimmed_and_an_empty_one_clears_the_field(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    trimmed = patch_words(signed_in, workout.id, title="  Morning loop  ", post="\n hi \n")
    assert trimmed.json()["title"] == "Morning loop"
    assert trimmed.json()["post"] == "hi"

    # Whitespace and an explicit null are the same thing: somebody emptied it.
    assert patch_words(signed_in, workout.id, title="   ").json()["title"] is None
    assert patch_words(signed_in, workout.id, post=None).json()["post"] is None


def test_a_field_that_was_not_sent_is_left_alone(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    patch_words(signed_in, workout.id, title="Morning loop", post="Cold start.")
    only_title = patch_words(signed_in, workout.id, title="Evening loop")
    assert only_title.json()["title"] == "Evening loop"
    assert only_title.json()["post"] == "Cold start."


def test_words_past_their_limits_are_refused(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    assert patch_words(signed_in, workout.id, title="x" * 101).status_code == 400
    assert patch_words(signed_in, workout.id, post="x" * 2001).status_code == 400
    # Nothing was written by either refusal.
    assert signed_in.get("/api/workouts").json()[0]["title"] is None

    at_the_line = patch_words(signed_in, workout.id, title="x" * 100, post="x" * 2000)
    assert at_the_line.status_code == 200
    assert len(at_the_line.json()["title"]) == 100
    assert len(at_the_line.json()["post"]) == 2000


def test_an_edit_cannot_change_what_happened(signed_in, db_session, member):
    """Distance, duration, and start time are not editable and never will be."""
    workout = stored(db_session, member.id)
    patched = patch_words(
        signed_in,
        workout.id,
        title="Morning loop",
        distance_mi=99.0,
        duration_s=60,
        start_ts="2020-01-01T00:00:00+00:00",
    )
    assert patched.status_code == 200
    assert patched.json()["distance_mi"] == workout.distance_mi
    assert patched.json()["duration_s"] == workout.duration_s
    assert patched.json()["start_ts"] == signed_in.get("/api/workouts").json()[0]["start_ts"]


def test_only_the_owner_can_write_on_a_workout(signed_in, db_session, member, admin):
    from conftest import ADMIN

    workout = stored(db_session, member.id)
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    # The same answer a workout that does not exist gets.
    assert patch_words(signed_in, workout.id, title="mine now").status_code == 404
    assert patch_words(signed_in, 9999, title="mine now").status_code == 404


def test_editing_is_rate_limited(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    codes = [patch_words(signed_in, workout.id, title="a").status_code for _ in range(31)]
    assert codes.count(200) == 30
    assert codes[-1] == 429


def test_writing_on_a_workout_needs_a_session(client):
    assert client.patch("/api/workouts/1", json={"title": "hello"}).status_code == 401


def photo_bytes(width=2400, height=1200, fmt="JPEG", colour=(120, 60, 30)) -> bytes:
    """A real photograph-shaped image carrying camera metadata, so the test that
    says the metadata is gone has something to lose."""
    exif = Image.Exif()
    exif[0x010F] = "Test Camera"
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format=fmt, exif=exif)
    return out.getvalue()


def attach(client, workout_id, data=None, name="photo.jpg", content_type="image/jpeg"):
    return client.post(
        f"/api/workouts/{workout_id}/photos",
        files={"file": (name, photo_bytes() if data is None else data, content_type)},
    )


def test_an_attached_photo_becomes_a_webp_with_nothing_carried_over(
    signed_in, db_session, member, photo_dir
):
    workout = stored(db_session, member.id)
    # The source really does carry metadata, so what follows means something.
    with Image.open(io.BytesIO(photo_bytes())) as source:
        assert source.info.get("exif")

    created = attach(signed_in, workout.id)
    assert created.status_code == 201, created.text
    photo_id = created.json()["id"]
    assert created.json() == {"id": photo_id}

    # The name on disk comes from the two ids, never from the upload.
    on_disk = photo_dir / f"{workout.id}-{photo_id}.webp"
    assert on_disk.exists()
    assert not (photo_dir / "photo.jpg").exists()
    assert not list(photo_dir.glob("*.tmp"))
    with Image.open(on_disk) as written:
        assert written.format == "WEBP"
        # Scaled to fit, aspect kept.
        assert written.size == (1600, 800)
        assert not written.info.get("exif")

    row = db_session.get(models.WorkoutPhoto, photo_id)
    assert row.workout_id == workout.id
    assert row.created_at.tzinfo is not None


def test_a_small_photo_is_not_scaled_up(signed_in, db_session, member, photo_dir):
    workout = stored(db_session, member.id)
    photo_id = attach(signed_in, workout.id, data=photo_bytes(400, 300)).json()["id"]
    with Image.open(photo_dir / f"{workout.id}-{photo_id}.webp") as written:
        assert written.size == (400, 300)


def test_a_workout_holds_six_photos_and_no_more(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    codes = [attach(signed_in, workout.id).status_code for _ in range(7)]
    assert codes == [201] * 6 + [400]
    full = attach(signed_in, workout.id)
    assert full.json()["detail"] == "A workout can hold 6 photos and videos."
    assert db_session.query(models.WorkoutPhoto).count() == 6


def test_an_oversize_photo_is_refused_before_it_is_decoded(signed_in, db_session, member, photo_dir):
    workout = stored(db_session, member.id)
    oversize = b"\xff\xd8\xff\xe0" + b"0" * (MAX_PHOTO_BYTES + 1024)
    response = attach(signed_in, workout.id, data=oversize)
    assert response.status_code == 413
    assert not photo_dir.exists() or list(photo_dir.glob("*")) == []


def test_a_file_that_is_not_an_image_is_not_a_photo(signed_in, db_session, member, photo_dir):
    workout = stored(db_session, member.id)
    # A convincing name and content type over bytes no decoder will accept.
    assert attach(signed_in, workout.id, data=b"not an image at all").status_code == 400
    assert attach(signed_in, workout.id, data=b"<?php system($_GET['c']); ?>",
                  name="shell.php.jpg").status_code == 400
    assert attach(signed_in, workout.id, data=b"").status_code == 400
    # Neither a row nor a file for any of them.
    assert db_session.query(models.WorkoutPhoto).count() == 0
    assert not photo_dir.exists() or list(photo_dir.glob("*")) == []


def test_photos_are_listed_on_the_workout_in_the_order_they_arrived(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    ids = [attach(signed_in, workout.id).json()["id"] for _ in range(3)]
    assert signed_in.get("/api/workouts").json()[0]["photos"] == ids


def test_an_attached_photo_can_be_fetched_by_its_owner(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    photo_id = attach(signed_in, workout.id).json()["id"]
    served = signed_in.get(f"/api/workouts/{workout.id}/photos/{photo_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert served.headers["cache-control"].startswith("private")
    assert served.content[:4] == b"RIFF"


def test_a_photo_that_is_not_there_is_the_same_404(signed_in, db_session, member, photo_dir):
    workout = stored(db_session, member.id)
    photo_id = attach(signed_in, workout.id).json()["id"]

    missing = signed_in.get(f"/api/workouts/{workout.id}/photos/9999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "No such photo."}
    # A photo asked for under the wrong workout is not found either.
    assert signed_in.get(f"/api/workouts/9999/photos/{photo_id}").status_code == 404

    # A volume that did not come back is not a server error to the caller.
    (photo_dir / f"{workout.id}-{photo_id}.webp").unlink()
    lost = signed_in.get(f"/api/workouts/{workout.id}/photos/{photo_id}")
    assert lost.status_code == 404
    assert lost.json() == {"detail": "No such photo."}


def test_deleting_a_photo_takes_the_row_and_the_file(signed_in, db_session, member, photo_dir):
    workout = stored(db_session, member.id)
    photo_id = attach(signed_in, workout.id).json()["id"]
    on_disk = photo_dir / f"{workout.id}-{photo_id}.webp"
    assert on_disk.exists()

    assert signed_in.delete(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 204
    assert not on_disk.exists()
    assert db_session.query(models.WorkoutPhoto).count() == 0
    assert signed_in.get("/api/workouts").json()[0]["photos"] == []
    # Gone twice is a 404, not a second deletion.
    assert signed_in.delete(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 404


def test_only_the_owner_can_attach_or_delete_a_photo(signed_in, db_session, member, admin):
    from conftest import ADMIN

    workout = stored(db_session, member.id)
    photo_id = attach(signed_in, workout.id).json()["id"]
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    assert attach(signed_in, workout.id).status_code == 404
    assert signed_in.delete(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 404


def test_photo_uploads_are_rate_limited(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    small = photo_bytes(200, 200)
    codes = [attach(signed_in, workout.id, data=small).status_code for _ in range(11)]
    assert codes[-1] == 429


def test_the_photo_endpoints_need_a_session(client):
    assert client.post("/api/workouts/1/photos", files={"file": ("a.jpg", b"x")}).status_code == 401
    assert client.get("/api/workouts/1/photos/1").status_code == 401
    assert client.delete("/api/workouts/1/photos/1").status_code == 401


# --------------------------------------------------------------------------
# The video on a workout
# --------------------------------------------------------------------------
# Every clip these cases use is built here by ffmpeg rather than committed as a
# binary: a fixture nobody can read the source of is a fixture nobody can
# change. They are cached per shape because building one costs a fraction of a
# second and several cases want the same one.

_clips: dict[tuple, bytes] = {}


def clip_bytes(seconds=2, size="320x240", *, tagged=True) -> bytes:
    """A real video carrying real metadata, so the case that says the metadata
    is gone has something to lose."""
    key = (seconds, size, tagged)
    if key not in _clips:
        with tempfile.TemporaryDirectory() as work:
            built = os.path.join(work, "clip.mp4")
            tags = []
            if tagged:
                tags = [
                    "-metadata",
                    "title=where I live",
                    "-metadata",
                    "comment=do not carry me",
                    "-metadata",
                    "location=+40.0-105.0/",
                ]
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc=size={size}:rate=10:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", *tags, built,
                ],
                check=True,
                capture_output=True,
            )
            _clips[key] = pathlib.Path(built).read_bytes()
    return _clips[key]


def probe(path) -> dict:
    """What ffprobe says about a stored file, as a dict."""
    done = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries",
            "stream=codec_name,codec_type,width,height:format=duration:format_tags",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return json.loads(done.stdout)


def attach_video(client, workout_id, data=None, name="clip.mp4", content_type="video/mp4"):
    return client.post(
        f"/api/workouts/{workout_id}/videos",
        files={"file": (name, clip_bytes() if data is None else data, content_type)},
    )


def test_an_attached_video_becomes_an_mp4_with_nothing_carried_over(
    signed_in, db_session, member, video_dir
):
    workout = stored(db_session, member.id)
    # The source really does carry metadata, so what follows means something.
    with tempfile.TemporaryDirectory() as work:
        source = pathlib.Path(work) / "source.mp4"
        source.write_bytes(clip_bytes())
        assert probe(source)["format"]["tags"]["title"] == "where I live"

    created = attach_video(signed_in, workout.id)
    assert created.status_code == 201, created.text
    video_id = created.json()["id"]
    assert created.json() == {"id": video_id}

    # Both names come from the two ids, never from the upload.
    on_disk = video_dir / f"{workout.id}-{video_id}.mp4"
    poster = video_dir / f"{workout.id}-{video_id}.jpg"
    assert on_disk.exists() and poster.exists()
    assert not (video_dir / "clip.mp4").exists()
    assert not list(video_dir.glob("*.tmp"))
    # The working directory the encoder used is cleared up behind it.
    assert not list(video_dir.glob("incoming-*"))

    written = probe(on_disk)
    kinds = {stream["codec_type"]: stream["codec_name"] for stream in written["streams"]}
    assert kinds == {"video": "h264", "audio": "aac"}
    # Nothing the uploader wrote into the file came through. What is left is
    # the container saying what kind of container it is.
    tags = written["format"].get("tags", {})
    assert not {"title", "comment", "location", "location-eng", "encoder"} & set(tags)

    row = db_session.get(models.WorkoutVideo, video_id)
    assert row.workout_id == workout.id
    assert row.created_at.tzinfo is not None


def test_a_small_video_is_not_scaled_up(signed_in, db_session, member, video_dir):
    workout = stored(db_session, member.id)
    video_id = attach_video(signed_in, workout.id).json()["id"]
    stream = probe(video_dir / f"{workout.id}-{video_id}.mp4")["streams"][0]
    assert (stream["width"], stream["height"]) == (320, 240)


def test_a_tall_video_is_capped_on_its_shorter_edge(signed_in, db_session, member, video_dir):
    """720p for a clip held portrait is 720 across, not 720 tall: capping the
    height would leave a phone video 405 wide."""
    workout = stored(db_session, member.id)
    tall = clip_bytes(seconds=1, size="900x1600", tagged=False)
    video_id = attach_video(signed_in, workout.id, data=tall).json()["id"]
    stream = probe(video_dir / f"{workout.id}-{video_id}.mp4")["streams"][0]
    assert (stream["width"], stream["height"]) == (720, 1280)


def test_a_video_longer_than_about_a_minute_is_refused(
    signed_in, db_session, member, video_dir
):
    """Read from the upload before a single frame is encoded, which is the
    point: the duration is the real limit and the byte cap only guards it."""
    workout = stored(db_session, member.id)
    long_one = clip_bytes(seconds=66, size="128x96", tagged=False)
    refused = attach_video(signed_in, workout.id, data=long_one)
    assert refused.status_code == 400
    assert refused.json() == {"detail": "That video is too long. About a minute is the limit."}
    assert db_session.query(models.WorkoutVideo).count() == 0
    assert not list(video_dir.glob("*.mp4"))


def test_a_file_that_is_not_a_video_is_not_a_video(signed_in, db_session, member, video_dir):
    workout = stored(db_session, member.id)
    not_a_video = "That file is not a video this server can read."
    # A convincing name and content type over bytes no decoder will accept.
    junk = attach_video(signed_in, workout.id, data=b"not a video at all")
    assert junk.status_code == 400
    assert junk.json() == {"detail": not_a_video}
    # A still picture opens as a video stream a few hundredths of a second
    # long, and nobody meant to post one as a clip.
    still = attach_video(signed_in, workout.id, data=photo_bytes(320, 240), name="clip.mp4")
    assert still.status_code == 400
    assert still.json() == {"detail": not_a_video}
    assert attach_video(signed_in, workout.id, data=b"").status_code == 400
    # Neither a row nor a file for any of them.
    assert db_session.query(models.WorkoutVideo).count() == 0
    assert not video_dir.exists() or list(video_dir.glob("*.mp4")) == []


def test_a_workout_holds_one_video(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    assert attach_video(signed_in, workout.id).status_code == 201
    second = attach_video(signed_in, workout.id)
    assert second.status_code == 400
    assert second.json() == {"detail": "A workout can hold one video."}
    assert db_session.query(models.WorkoutVideo).count() == 1


def test_photos_and_a_video_share_the_six_slots(signed_in, db_session, member):
    """One cap over two tables. A video takes a slot exactly as a picture
    does, and the sentence a full workout answers with says so."""
    workout = stored(db_session, member.id)
    small = photo_bytes(200, 200)
    assert [attach(signed_in, workout.id, data=small).status_code for _ in range(5)] == [201] * 5
    video_id = attach_video(signed_in, workout.id).json()["id"]

    full = attach(signed_in, workout.id, data=small)
    assert full.status_code == 400
    assert full.json() == {"detail": "A workout can hold 6 photos and videos."}
    assert db_session.query(models.WorkoutPhoto).count() == 5

    # And the other way round: with the clip taken back down there is room for
    # a sixth picture, and once it is there, none for a clip.
    assert signed_in.delete(f"/api/workouts/{workout.id}/videos/{video_id}").status_code == 204
    assert attach(signed_in, workout.id, data=small).status_code == 201
    no_room = attach_video(signed_in, workout.id)
    assert no_room.status_code == 400
    assert no_room.json() == {"detail": "A workout can hold 6 photos and videos."}


def test_the_video_is_listed_on_the_workout_beside_the_photos(signed_in, db_session, member):
    workout = stored(db_session, member.id)
    photo_id = attach(signed_in, workout.id, data=photo_bytes(200, 200)).json()["id"]
    video_id = attach_video(signed_in, workout.id).json()["id"]
    row = signed_in.get("/api/workouts").json()[0]
    assert (row["photos"], row["videos"]) == ([photo_id], [video_id])


def test_an_attached_video_and_its_poster_can_be_fetched_by_their_owner(
    signed_in, db_session, member
):
    workout = stored(db_session, member.id)
    video_id = attach_video(signed_in, workout.id).json()["id"]

    served = signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "video/mp4"
    assert served.headers["cache-control"].startswith("private")
    # The index at the front, which is what lets a browser start playing before
    # it holds the whole file.
    assert served.content[4:8] == b"ftyp"
    assert served.content.find(b"moov") < served.content.find(b"mdat")

    poster = signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}/poster")
    assert poster.status_code == 200
    assert poster.headers["content-type"] == "image/jpeg"
    assert poster.content[:2] == b"\xff\xd8"


def test_a_video_is_served_in_ranges(signed_in, db_session, member):
    """iOS Safari will not play a video at all from a URL that answers a range
    request with the whole file, and a phone is what this app is read on."""
    workout = stored(db_session, member.id)
    video_id = attach_video(signed_in, workout.id).json()["id"]
    address = f"/api/workouts/{workout.id}/videos/{video_id}"

    whole = signed_in.get(address)
    assert whole.headers["accept-ranges"] == "bytes"
    size = len(whole.content)

    part = signed_in.get(address, headers={"Range": "bytes=0-1023"})
    assert part.status_code == 206
    assert part.headers["content-range"] == f"bytes 0-1023/{size}"
    assert part.content == whole.content[:1024]

    tail = signed_in.get(address, headers={"Range": "bytes=-512"})
    assert tail.status_code == 206
    assert tail.content == whole.content[-512:]


def test_a_video_that_is_not_there_is_the_same_404(signed_in, db_session, member, video_dir):
    workout = stored(db_session, member.id)
    video_id = attach_video(signed_in, workout.id).json()["id"]

    missing = signed_in.get(f"/api/workouts/{workout.id}/videos/9999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "No such video."}
    # A video asked for under the wrong workout is not found either.
    assert signed_in.get(f"/api/workouts/9999/videos/{video_id}").status_code == 404

    # A volume that did not come back is not a server error to the caller, and
    # the poster answers the same way for the same reason.
    (video_dir / f"{workout.id}-{video_id}.mp4").unlink()
    (video_dir / f"{workout.id}-{video_id}.jpg").unlink()
    lost = signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}")
    assert lost.status_code == 404
    assert lost.json() == {"detail": "No such video."}
    assert signed_in.get(f"/api/workouts/{workout.id}/videos/{video_id}/poster").status_code == 404


def test_deleting_a_video_takes_the_row_and_both_files(
    signed_in, db_session, member, video_dir
):
    workout = stored(db_session, member.id)
    video_id = attach_video(signed_in, workout.id).json()["id"]
    on_disk = video_dir / f"{workout.id}-{video_id}.mp4"
    poster = video_dir / f"{workout.id}-{video_id}.jpg"
    assert on_disk.exists() and poster.exists()

    assert signed_in.delete(f"/api/workouts/{workout.id}/videos/{video_id}").status_code == 204
    assert not on_disk.exists() and not poster.exists()
    assert db_session.query(models.WorkoutVideo).count() == 0
    assert signed_in.get("/api/workouts").json()[0]["videos"] == []
    # Gone twice is a 404, not a second deletion, and the slot is free again.
    assert signed_in.delete(f"/api/workouts/{workout.id}/videos/{video_id}").status_code == 404
    assert attach_video(signed_in, workout.id).status_code == 201


def test_only_the_owner_can_attach_or_delete_a_video(signed_in, db_session, member, admin):
    from conftest import ADMIN

    workout = stored(db_session, member.id)
    video_id = attach_video(signed_in, workout.id).json()["id"]
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    assert attach_video(signed_in, workout.id).status_code == 404
    assert signed_in.delete(f"/api/workouts/{workout.id}/videos/{video_id}").status_code == 404


def test_video_uploads_are_rate_limited(signed_in, db_session, member):
    """The limiter is spent before the one-video rule refuses, which is the
    order that matters: an upload that was read and encoded has cost the server
    the work whether it was kept or not."""
    workout = stored(db_session, member.id)
    codes = [attach_video(signed_in, workout.id).status_code for _ in range(6)]
    assert codes[0] == 201
    assert codes[-1] == 429


def test_the_video_endpoints_need_a_session(client):
    assert client.post("/api/workouts/1/videos", files={"file": ("a.mp4", b"x")}).status_code == 401
    assert client.get("/api/workouts/1/videos/1").status_code == 401
    assert client.get("/api/workouts/1/videos/1/poster").status_code == 401
    assert client.delete("/api/workouts/1/videos/1").status_code == 401


# --------------------------------------------------------------------------
# The Insights band
# --------------------------------------------------------------------------
# Twelve weeks, twelve months, and the bests behind them, read for the person
# whose history it is and for nobody else. Nothing here is earned or spent:
# every number in the band is a reading of rows that were already there.


def sampled(db_session, workout: models.Workout, distances: list[float]) -> None:
    """One row a minute behind a workout, the way a sync writes them.

    Distance only: the tier records are the one thing that reads these rows for
    anything but the details screen, and a heart rate would say nothing here.

    The workout's best efforts are written from them too, because that is what a
    sync does: app.samples derives them the moment the minutes land, and a helper
    that wrote the minutes without them would be describing a workout no sync
    could produce.
    """
    minutes = list(enumerate(distances))
    for minute, distance in minutes:
        db_session.add(
            models.WorkoutSample(workout_id=workout.id, minute=minute, distance_mi=distance)
        )
    db_session.flush()
    bests.store(db_session, workout.id, minutes)
    db_session.commit()


def test_insights_bucket_a_history_into_weeks_and_months(signed_in, db_session, member):
    """Twelve of each, oldest first, and a bucket with nothing in it is still one.

    The week in progress is the last of them, so the band reads left to right
    the way a season does. Indoor sessions count exactly as the weekly totals
    count them, a climb nobody recorded is left out of the total rather than
    added as zero, and a workout with no distance spends none of the seconds a
    pace is worked out from.
    """
    monday = _monday_of_this_week()
    stored(
        db_session,
        member.id,
        start=f"{monday.isoformat()}T06:00:00+00:00",
        duration=1800,
        miles=3.0,
        elevation_ft=100.0,
    )
    stored(
        db_session,
        member.id,
        start=f"{(monday + dt.timedelta(days=1)).isoformat()}T06:00:00+00:00",
        duration=1200,
        miles=2.0,
    )
    stored(
        db_session,
        member.id,
        start=f"{(monday + dt.timedelta(days=2)).isoformat()}T06:00:00+00:00",
        duration=600,
        miles=1.0,
        indoor=True,
    )
    # A session the export gave no distance for: its climb counts and its
    # minutes do not, because they covered nothing to be a pace over.
    stored(
        db_session,
        member.id,
        start=f"{(monday + dt.timedelta(days=2)).isoformat()}T07:00:00+00:00",
        duration=900,
        miles=0.0,
        elevation_ft=20.0,
    )
    stored(
        db_session,
        member.id,
        start=f"{(monday - dt.timedelta(weeks=1)).isoformat()}T06:00:00+00:00",
        duration=3000,
        miles=5.0,
    )

    band = signed_in.get("/api/workouts/insights").json()
    # Only the sports this account has actually done.
    assert set(band) == {"run"}

    weekly = band["run"]["weekly"]
    assert len(weekly) == 12
    assert weekly[0]["start"] == (monday - dt.timedelta(weeks=11)).isoformat()
    assert weekly[-1] == {
        "start": monday.isoformat(),
        "miles": 6.0,
        "elevation_ft": 120.0,
        "seconds": 3600,
    }
    assert weekly[-2] == {
        "start": (monday - dt.timedelta(weeks=1)).isoformat(),
        "miles": 5.0,
        "elevation_ft": 0.0,
        "seconds": 3000,
    }
    assert weekly[-3] == {
        "start": (monday - dt.timedelta(weeks=2)).isoformat(),
        "miles": 0.0,
        "elevation_ft": 0.0,
        "seconds": 0,
    }

    monthly = band["run"]["monthly"]
    assert len(monthly) == 12
    assert monthly[-1] == {
        "start": security.now_utc().date().replace(day=1).isoformat(),
        "miles": 11.0,
        "elevation_ft": 120.0,
        "seconds": 6600,
    }
    # Eleven months back from the month in progress, which is where a year of
    # them starts.
    assert monthly[0]["start"] == "2025-05-01"


def test_insights_bucket_in_the_instance_timezone(signed_in, db_session, member, monkeypatch):
    """A week and a month both mean what the instance's clock says they mean.

    Two in the morning UTC is seven the previous evening in an instance running
    seven hours behind, so the same instant falls in a different month and a
    different week depending on which clock reads it. The band is grouped in the
    instance zone, the same as the weekly totals in the Almanac, or the two
    disagree about one evening a week.
    """
    monkeypatch.setattr(activity_rules, "SERVER_TZ", ZoneInfo("America/Phoenix"))

    # The first of April, UTC, which is the last evening of March locally.
    stored(db_session, member.id, start="2026-04-01T02:00:00+00:00", duration=2400, miles=4.0)
    # A Monday morning, UTC, which is the Sunday evening before it locally, and
    # so the week before as well.
    stored(db_session, member.id, start="2026-04-06T02:00:00+00:00", duration=1200, miles=2.0)

    band = signed_in.get("/api/workouts/insights").json()["run"]
    months = {row["start"]: row["miles"] for row in band["monthly"]}
    assert months["2026-03-01"] == 4.0
    assert months["2026-04-01"] == 2.0
    weeks = {row["start"]: row["miles"] for row in band["weekly"]}
    # Both of them sit in the week that starts the Monday before the first.
    assert weeks["2026-03-30"] == 6.0
    assert weeks["2026-04-06"] == 0.0


def test_insights_read_a_tier_best_only_from_a_workout_that_covered_it(
    signed_in, db_session, member
):
    """A tier is qualified for by distance, and the time answered is the tier's own.

    The fastest thing in this history is three miles, and three miles is short
    of the shortest tier, so it is nobody's best: a 5K best has to come from a
    session that actually covered a 5K.

    None of these carried per-minute rows, so each qualifier is read at its own
    average pace over the tier's distance, which is everything an export that
    only summarised the session has to say about a stretch inside it.
    """
    # Five minutes a mile, and short of the 5K floor.
    stored(db_session, member.id, start="2026-04-13T06:00:00+00:00", duration=900, miles=3.0)
    # Twelve and a half minutes a mile, and over it.
    stored(db_session, member.id, start="2026-04-13T08:00:00+00:00", duration=2400, miles=3.2)
    # Ten minutes a mile over ten kilometres, which takes both tiers it clears.
    ten_k = stored(
        db_session, member.id, start="2026-04-14T06:00:00+00:00", duration=3900, miles=6.5
    )

    prs = signed_in.get("/api/workouts/insights").json()["run"]["prs"]
    # 3900 seconds for 6.5 miles, said over 3.1 of them.
    assert prs["tiers"]["5k"] == {
        "seconds": 1860.0,
        "start_ts": ten_k.start_ts.isoformat(),
        "workout_id": ten_k.id,
    }
    # And over 6.2 of them, from the same workout.
    assert prs["tiers"]["10k"]["seconds"] == 3720.0
    # Nothing here went half that far, and a best nobody set is nothing rather
    # than the nearest thing to it.
    assert prs["tiers"]["half"] is None
    assert prs["tiers"]["marathon"] is None
    assert prs["longest"]["miles"] == 6.5
    assert prs["longest"]["start_ts"].startswith("2026-04-14T06:00:00")
    # No export here carried a climb, so there is no biggest one.
    assert prs["biggest_climb"] is None


def test_insights_find_the_fastest_stretch_inside_a_longer_workout(
    signed_in, db_session, member
):
    """A personal best is the fastest 5K a body ran, not the fastest 5K it raced.

    A steady ten-miler with twenty quick minutes in the middle of it holds a
    better 5K than a dedicated one does, and the per-minute rows are where that
    can be seen. Read at the whole session's average the ten-miler would have
    answered 1860 seconds and lost to the short one.
    """
    dedicated = stored(
        db_session, member.id, start="2026-04-10T06:00:00+00:00", duration=1600, miles=3.2
    )
    long_run = stored(
        db_session, member.id, start="2026-04-13T06:00:00+00:00", duration=6000, miles=10.0
    )
    # Forty slow minutes, twenty quick ones covering exactly a 5K, forty more.
    sampled(db_session, long_run, [0.08] * 40 + [0.155] * 20 + [0.0925] * 40)

    prs = signed_in.get("/api/workouts/insights").json()["run"]["prs"]
    assert prs["tiers"]["5k"] == {
        "seconds": 1200.0,
        "start_ts": long_run.start_ts.isoformat(),
        "workout_id": long_run.id,
    }
    # The short one is what it would have been without the arrays: 1600 seconds
    # for 3.2 miles is 1550 for 3.1, and it is beaten by four hundred seconds.
    assert dedicated.id != prs["tiers"]["5k"]["workout_id"]


def test_insights_divide_the_minute_a_stretch_ends_in(signed_in, db_session, member):
    """The minutes are whole and the answer is not, so the last one is divided.

    Ten minutes at a fifth of a mile, then thirty at 0.12: the quickest 5K
    starts at the gun, takes the two fast miles in ten minutes, and needs 1.1
    miles more at 0.12 a minute, which is nine minutes and ten seconds. 600 plus
    550 is 1150, and only interpolation inside the last minute produces it: to
    the whole minute it would read 1160.
    """
    workout = stored(
        db_session, member.id, start="2026-04-13T06:00:00+00:00", duration=2400, miles=5.6
    )
    sampled(db_session, workout, [0.2] * 10 + [0.12] * 30)

    prs = signed_in.get("/api/workouts/insights").json()["run"]["prs"]
    assert prs["tiers"]["5k"]["seconds"] == 1150.0


def test_insights_compare_a_sampled_best_against_a_summarised_one(
    signed_in, db_session, member
):
    """Both readings answer the same question, so both are allowed to win.

    A sampled ten-miler holding a twenty-minute 5K against a short fast one the
    export never described minute by minute: 1200 seconds against 3.5 miles in
    1000, which is 885.7 over 3.1. The summarised one is quicker and it takes
    the record.
    """
    long_run = stored(
        db_session, member.id, start="2026-04-11T06:00:00+00:00", duration=6000, miles=10.0
    )
    sampled(db_session, long_run, [0.08] * 40 + [0.155] * 20 + [0.0925] * 40)
    sprint = stored(
        db_session, member.id, start="2026-04-13T06:00:00+00:00", duration=1000, miles=3.5
    )

    prs = signed_in.get("/api/workouts/insights").json()["run"]["prs"]
    assert prs["tiers"]["5k"] == {
        "seconds": 885.7,
        "start_ts": sprint.start_ts.isoformat(),
        "workout_id": sprint.id,
    }


def test_insights_fall_back_where_the_samples_stop_short(signed_in, db_session, member):
    """Arrays that describe a mile of a six-mile run cannot answer for a 5K.

    Exports arrive with the arrays cut short, or with the phone having given up
    part way. What they hold is not a 5K, so nothing is read out of them and the
    workout answers at its own average the way an unsampled one does: 3000
    seconds for 6.0 miles is 1550 for 3.1.
    """
    workout = stored(
        db_session, member.id, start="2026-04-13T06:00:00+00:00", duration=3000, miles=6.0
    )
    sampled(db_session, workout, [0.1] * 10)

    prs = signed_in.get("/api/workouts/insights").json()["run"]["prs"]
    assert prs["tiers"]["5k"] == {
        "seconds": 1550.0,
        "start_ts": workout.start_ts.isoformat(),
        "workout_id": workout.id,
    }


def test_insights_name_the_best_week_and_the_biggest_climb(signed_in, db_session, member):
    """Both are read over the whole history rather than over the twelve weeks on
    screen: a best is a best, and the week it was set in may be a year back."""
    monday = _monday_of_this_week()
    long_ago = monday - dt.timedelta(weeks=30)
    stored(
        db_session,
        member.id,
        start=f"{long_ago.isoformat()}T06:00:00+00:00",
        duration=3600,
        miles=6.0,
        elevation_ft=1200.0,
    )
    stored(
        db_session,
        member.id,
        start=f"{(long_ago + dt.timedelta(days=2)).isoformat()}T06:00:00+00:00",
        duration=2400,
        miles=4.0,
        elevation_ft=300.0,
    )
    stored(
        db_session,
        member.id,
        start=f"{monday.isoformat()}T06:00:00+00:00",
        duration=1800,
        miles=3.0,
    )

    prs = signed_in.get("/api/workouts/insights").json()["run"]["prs"]
    assert prs["best_week"] == {"start": long_ago.isoformat(), "miles": 10.0}
    assert prs["biggest_climb"]["elevation_ft"] == 1200.0
    assert prs["biggest_climb"]["start_ts"].startswith(long_ago.isoformat())


def test_insights_compare_a_month_at_the_same_point_of_the_month_before(
    signed_in, db_session, member
):
    """Halfway through April against the first half of March, not against all of it.

    The comparison is read mid-month, so the month before it is cut at the same
    day of the month. A fortnight against a whole month is a sentence that would
    say somebody had fallen behind on every month of their life until its last
    day.
    """
    stored(db_session, member.id, start="2026-04-05T06:00:00+00:00", duration=2400, miles=4.0)
    stored(db_session, member.id, start="2026-03-05T06:00:00+00:00", duration=1800, miles=3.0)
    # After the day of the month it is today, so it is not part of the same
    # stretch of March and is left out of the comparison.
    stored(db_session, member.id, start="2026-03-25T06:00:00+00:00", duration=6000, miles=10.0)

    band = signed_in.get("/api/workouts/insights").json()["run"]
    assert band["month_now"] == {"start": "2026-04-01", "miles": 4.0}
    assert band["month_prior"] == {"start": "2026-03-01", "miles": 3.0}
    # The bar chart still shows the whole of March, which is what makes the cut
    # above a reading of the comparison rather than of the month.
    months = {row["start"]: row["miles"] for row in band["monthly"]}
    assert months["2026-03-01"] == 13.0


def test_insights_are_read_by_their_owner_and_by_nobody_else(signed_in, db_session, member):
    """Self only, and being a friend does not change it.

    The fence around the feed is drawn around single workouts. A year of
    somebody's weeks added up says more about their days than any one card does,
    so there is no parameter here to point the band at another account and no
    friendship that opens it.
    """
    stored(db_session, member.id, start="2026-04-13T06:00:00+00:00", duration=3600, miles=9.0)

    mate = make_user(db_session, "mate", "mate-password-1")
    db_session.add(
        models.Friendship(
            requester_id=member.id,
            addressee_id=mate.id,
            status="accepted",
            created_at=security.now_utc(),
        )
    )
    db_session.commit()

    other = TestClient(fastapi_app)
    assert (
        other.post(
            "/api/auth/login", json={"username": "mate", "password": "mate-password-1"}
        ).status_code
        == 204
    )
    # Their own band, which is empty, rather than the one they are friends with.
    assert other.get("/api/workouts/insights").json() == {}
    assert signed_in.get("/api/workouts/insights").json()["run"]["prs"]["longest"]["miles"] == 9.0
    # And nobody at all without a session.
    assert TestClient(fastapi_app).get("/api/workouts/insights").status_code == 401


def test_insights_of_an_empty_account(signed_in):
    """No sport done, no sport keyed: an account with nothing in it gets an empty
    band rather than four sports of zeroes to draw."""
    assert signed_in.get("/api/workouts/insights").json() == {}
