"""Manual entry, the history page, the weekly totals, and the words and
pictures an owner puts on a workout."""

import datetime as dt
import io

import pytest
from PIL import Image

from app import models
from app.activity import converted_miles
from app.config import MAX_PHOTO_BYTES

pytest.importorskip("PIL")


def manual(activity="run", start="2026-07-20T06:12:00+00:00", duration=1800, miles=3.0, **extra):
    body = {
        "activity": activity,
        "start_ts": start,
        "duration_s": duration,
        "distance_mi": miles,
    }
    body.update(extra)
    return body


def test_manual_entry_is_marked_manual(signed_in, db_session):
    response = signed_in.post("/api/workouts", json=manual(active_kcal=320, avg_hr=148))
    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["activity"] == "run"
    assert body["distance_mi"] == 3.0
    assert body["active_kcal"] == 320.0
    assert body["flags"] == {}
    assert db_session.query(models.Workout).one().source == "manual"


def test_manual_entry_duplicate_is_a_conflict(signed_in, db_session):
    assert signed_in.post("/api/workouts", json=manual()).status_code == 201
    # Same start and duration, so the same workout by the dedupe key even
    # though the distance differs.
    second = signed_in.post("/api/workouts", json=manual(miles=3.5))
    assert second.status_code == 409
    assert db_session.query(models.Workout).count() == 1


def test_manual_entry_collides_with_a_synced_workout(signed_in, ingest_token, db_session):
    payload = {
        "data": {
            "workouts": [
                {
                    "name": "Outdoor Run",
                    "start": "2026-07-20T06:12:00+00:00",
                    "duration": 1800,
                    "distance": {"qty": 3.0, "units": "mi"},
                }
            ]
        }
    }
    signed_in.post(
        "/api/ingest", json=payload, headers={"Authorization": f"Bearer {ingest_token}"}
    )
    assert signed_in.post("/api/workouts", json=manual()).status_code == 409


def test_manual_entry_validates_its_input(signed_in):
    assert signed_in.post("/api/workouts", json=manual(activity="skateboard")).status_code == 400
    assert signed_in.post("/api/workouts", json=manual(duration=0)).status_code == 400
    assert signed_in.post("/api/workouts", json=manual(miles=-1)).status_code == 400


def raw_manual(client, **numbers):
    """Post a manual entry as text rather than through the JSON encoder.

    The encoder refuses to write a NaN, and Python's parser reads one back
    happily, which is exactly why the endpoint has to refuse them itself.
    """
    fields = {"duration_s": "1800", "distance_mi": "3.0"}
    fields.update(numbers)
    parts = ['"activity": "run"', '"start_ts": "2026-07-20T06:12:00+00:00"']
    parts += [f'"{key}": {value}' for key, value in fields.items()]
    return client.post(
        "/api/workouts",
        content=("{" + ", ".join(parts) + "}").encode(),
        headers={"Content-Type": "application/json"},
    )


def test_manual_entry_refuses_numbers_that_are_not_numbers(signed_in, db_session):
    """NaN and infinity are valid JSON literals and a float field takes both.

    A stored one is not a cosmetic problem: the progress pipeline reads every
    workout the account owns on every request, so one of them turns every later
    request for that account into a 500 that no retry clears.
    """
    for fields in (
        {"distance_mi": "NaN"},
        {"distance_mi": "Infinity"},
        {"active_kcal": "NaN"},
        {"avg_hr": "-Infinity"},
        {"duration_s": "NaN"},
        # A JSON number too large for a float parses to infinity on its own.
        {"distance_mi": "1e400"},
    ):
        response = raw_manual(signed_in, **fields)
        assert response.status_code == 400, response.text
        assert set(response.json()) == {"detail"}
    assert db_session.query(models.Workout).count() == 0
    # The account is still readable, which is the property all of this protects.
    assert signed_in.get("/api/profile").status_code == 200


def test_manual_entry_refuses_absurd_numbers(signed_in, db_session):
    over_bounds = (
        manual(miles=5000.0),
        manual(duration=400000),
        manual(active_kcal=900000.0),
        manual(avg_hr=9000.0),
        manual(avg_hr=2.0),
    )
    for body in over_bounds:
        response = signed_in.post("/api/workouts", json=body)
        assert response.status_code == 400, response.text
        # A plain sentence, not a field dump: the person typed something wrong
        # and has to be told what the rule is.
        assert response.json()["detail"][-1] == "."
    assert db_session.query(models.Workout).count() == 0


def test_manual_entry_takes_the_numbers_just_inside_the_bounds(signed_in):
    accepted = signed_in.post(
        "/api/workouts",
        json=manual(duration=48 * 3600, miles=1000.0, active_kcal=50000.0, avg_hr=300.0),
    )
    assert accepted.status_code == 201, accepted.text


def test_manual_entry_is_rate_limited(signed_in):
    codes = []
    for minute in range(31):
        codes.append(
            signed_in.post(
                "/api/workouts",
                json=manual(start=f"2026-07-20T06:{minute:02d}:00+00:00"),
            ).status_code
        )
    assert codes.count(201) == 30
    assert codes[-1] == 429


def test_manual_entry_flags_an_impossible_pace(signed_in):
    response = signed_in.post("/api/workouts", json=manual(duration=600, miles=4.0))
    assert response.status_code == 201
    assert response.json()["flags"] == {"impossible_pace": True}


def test_manual_entry_flags_the_daily_cap(signed_in):
    signed_in.post(
        "/api/workouts",
        json=manual(activity="walk", start="2026-07-20T06:00:00+00:00", duration=8 * 3600,
                    miles=30.0),
    )
    over = signed_in.post(
        "/api/workouts",
        json=manual(activity="walk", start="2026-07-20T16:00:00+00:00", duration=5 * 3600,
                    miles=15.0),
    )
    assert over.json()["flags"] == {"daily_cap": True}


def test_manual_entry_needs_a_session(client):
    assert client.post("/api/workouts", json=manual()).status_code == 401


def test_history_is_newest_first_and_pages(signed_in):
    for day in range(1, 6):
        signed_in.post("/api/workouts", json=manual(start=f"2026-07-0{day}T06:00:00+00:00"))

    page = signed_in.get("/api/workouts", params={"limit": 2}).json()
    assert isinstance(page, list)
    assert [row["start_ts"][:10] for row in page] == ["2026-07-05", "2026-07-04"]

    older = signed_in.get(
        "/api/workouts", params={"limit": 2, "before": page[-1]["start_ts"]}
    ).json()
    assert [row["start_ts"][:10] for row in older] == ["2026-07-03", "2026-07-02"]


def test_paging_survives_an_unencoded_offset(signed_in):
    """A client that drops the timestamp into the query string without encoding
    it gets the offset back as a space; the second page still has to work."""
    for day in range(1, 4):
        signed_in.post("/api/workouts", json=manual(start=f"2026-07-0{day}T06:00:00+00:00"))
    older = signed_in.get("/api/workouts?limit=2&before=2026-07-03T06:00:00+00:00").json()
    assert [row["start_ts"][:10] for row in older] == ["2026-07-02", "2026-07-01"]


def test_history_rejects_a_bad_cursor(signed_in):
    assert signed_in.get("/api/workouts?before=yesterday").status_code == 400


def test_history_is_per_user(signed_in, client, db_session, admin):
    from conftest import ADMIN

    signed_in.post("/api/workouts", json=manual())
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    assert signed_in.get("/api/workouts").json() == []


def test_history_rows_carry_what_each_workout_was_worth(signed_in):
    """The row's xp is the converted distance the pipeline credited."""
    signed_in.post("/api/workouts", json=manual(duration=1800, miles=3.0))
    # Nine cycled miles are three Miles, so the same credit for a longer ride.
    signed_in.post(
        "/api/workouts",
        json=manual(activity="cycle", start="2026-07-21T06:12:00+00:00", duration=1800, miles=9.0),
    )
    rows = signed_in.get("/api/workouts").json()
    assert [row["xp"] for row in rows] == [3.0, 3.0]
    for row in rows:
        assert row["xp"] == converted_miles(row["activity"], row["distance_mi"])


def test_history_rows_name_the_medals_a_run_earned(signed_in):
    signed_in.post("/api/workouts", json=manual(duration=3300, miles=6.4))
    signed_in.post(
        "/api/workouts",
        json=manual(start="2026-07-21T06:12:00+00:00", duration=1800, miles=2.0),
    )
    # An early run earns the distance and the hour both, in catalogue order.
    signed_in.post(
        "/api/workouts",
        json=manual(start="2026-07-22T05:30:00+00:00", duration=2700, miles=4.0),
    )
    rows = {row["distance_mi"]: row["medals"] for row in signed_in.get("/api/workouts").json()}
    assert rows[6.4] == ["race_10k"]
    assert rows[2.0] == []
    assert rows[4.0] == ["race_5k", "early_riser"]


def test_a_new_entry_reports_its_own_worth(signed_in):
    created = signed_in.post("/api/workouts", json=manual(duration=1800, miles=3.0))
    assert created.json()["xp"] == 3.0
    assert created.json()["medals"] == []


def test_history_needs_a_session(client):
    assert client.get("/api/workouts").status_code == 401


def _monday_of_this_week() -> dt.date:
    today = dt.datetime.now(dt.timezone.utc).date()
    return today - dt.timedelta(days=today.weekday())


def test_weekly_totals(signed_in):
    monday = _monday_of_this_week()
    signed_in.post(
        "/api/workouts",
        json=manual(
            activity="run",
            start=f"{monday.isoformat()}T06:00:00+00:00",
            duration=1800,
            miles=3.0,
            active_kcal=300,
        ),
    )
    signed_in.post(
        "/api/workouts",
        json=manual(
            activity="run",
            start=f"{(monday + dt.timedelta(days=1)).isoformat()}T06:00:00+00:00",
            duration=2400,
            miles=4.0,
            active_kcal=400,
        ),
    )
    signed_in.post(
        "/api/workouts",
        json=manual(
            activity="walk",
            start=f"{(monday + dt.timedelta(days=2)).isoformat()}T06:00:00+00:00",
            duration=2400,
            miles=2.0,
            active_kcal=150,
        ),
    )

    weeks = signed_in.get("/api/workouts/weeks?count=4").json()
    assert len(weeks) == 4
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


def test_weekly_totals_ignore_older_weeks(signed_in):
    monday = _monday_of_this_week()
    long_ago = monday - dt.timedelta(weeks=6)
    signed_in.post(
        "/api/workouts",
        json=manual(start=f"{long_ago.isoformat()}T06:00:00+00:00", active_kcal=999),
    )
    weeks = signed_in.get("/api/workouts/weeks?count=2").json()
    assert len(weeks) == 2
    assert all(week["activities"] == {} for week in weeks)


def test_weekly_totals_reject_a_silly_count(signed_in):
    assert signed_in.get("/api/workouts/weeks?count=0").status_code == 400
    assert signed_in.get("/api/workouts/weeks?count=500").status_code == 400


def patch_words(client, workout_id, **fields):
    return client.patch(f"/api/workouts/{workout_id}", json=fields)


def test_the_owner_can_title_a_workout_and_write_on_it(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    assert workout["title"] is None
    assert workout["post"] is None
    assert workout["photos"] == []

    patched = patch_words(signed_in, workout["id"], title="Morning loop", post="Cold start.")
    assert patched.status_code == 200, patched.text
    assert patched.json()["title"] == "Morning loop"
    assert patched.json()["post"] == "Cold start."
    # The whole row comes back, not a fragment of it: the card that sent the
    # edit redraws from this without asking for the history again.
    assert patched.json() == signed_in.get("/api/workouts").json()[0]


def test_words_are_trimmed_and_an_empty_one_clears_the_field(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    trimmed = patch_words(signed_in, workout["id"], title="  Morning loop  ", post="\n hi \n")
    assert trimmed.json()["title"] == "Morning loop"
    assert trimmed.json()["post"] == "hi"

    # Whitespace and an explicit null are the same thing: somebody emptied it.
    assert patch_words(signed_in, workout["id"], title="   ").json()["title"] is None
    assert patch_words(signed_in, workout["id"], post=None).json()["post"] is None


def test_a_field_that_was_not_sent_is_left_alone(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    patch_words(signed_in, workout["id"], title="Morning loop", post="Cold start.")
    only_title = patch_words(signed_in, workout["id"], title="Evening loop")
    assert only_title.json()["title"] == "Evening loop"
    assert only_title.json()["post"] == "Cold start."


def test_words_past_their_limits_are_refused(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    assert patch_words(signed_in, workout["id"], title="x" * 101).status_code == 400
    assert patch_words(signed_in, workout["id"], post="x" * 2001).status_code == 400
    # Nothing was written by either refusal.
    assert signed_in.get("/api/workouts").json()[0]["title"] is None

    at_the_line = patch_words(signed_in, workout["id"], title="x" * 100, post="x" * 2000)
    assert at_the_line.status_code == 200
    assert len(at_the_line.json()["title"]) == 100
    assert len(at_the_line.json()["post"]) == 2000


def test_an_edit_cannot_change_what_happened(signed_in):
    """Distance, duration, and start time are not editable and never will be."""
    workout = signed_in.post("/api/workouts", json=manual()).json()
    patched = patch_words(
        signed_in,
        workout["id"],
        title="Morning loop",
        distance_mi=99.0,
        duration_s=60,
        start_ts="2020-01-01T00:00:00+00:00",
    )
    assert patched.status_code == 200
    assert patched.json()["distance_mi"] == workout["distance_mi"]
    assert patched.json()["duration_s"] == workout["duration_s"]
    assert patched.json()["start_ts"] == workout["start_ts"]


def test_only_the_owner_can_write_on_a_workout(signed_in, db_session, admin):
    from conftest import ADMIN

    workout = signed_in.post("/api/workouts", json=manual()).json()
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    # The same answer a workout that does not exist gets.
    assert patch_words(signed_in, workout["id"], title="mine now").status_code == 404
    assert patch_words(signed_in, 9999, title="mine now").status_code == 404


def test_editing_is_rate_limited(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    codes = [patch_words(signed_in, workout["id"], title="a").status_code for _ in range(31)]
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
    signed_in, photo_dir, db_session
):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    # The source really does carry metadata, so what follows means something.
    with Image.open(io.BytesIO(photo_bytes())) as source:
        assert source.info.get("exif")

    created = attach(signed_in, workout["id"])
    assert created.status_code == 201, created.text
    photo_id = created.json()["id"]
    assert created.json() == {"id": photo_id}

    # The name on disk comes from the two ids, never from the upload.
    stored = photo_dir / f"{workout['id']}-{photo_id}.webp"
    assert stored.exists()
    assert not (photo_dir / "photo.jpg").exists()
    assert not list(photo_dir.glob("*.tmp"))
    with Image.open(stored) as written:
        assert written.format == "WEBP"
        # Scaled to fit, aspect kept.
        assert written.size == (1600, 800)
        assert not written.info.get("exif")

    row = db_session.get(models.WorkoutPhoto, photo_id)
    assert row.workout_id == workout["id"]
    assert row.created_at.tzinfo is not None


def test_a_small_photo_is_not_scaled_up(signed_in, photo_dir):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    photo_id = attach(signed_in, workout["id"], data=photo_bytes(400, 300)).json()["id"]
    with Image.open(photo_dir / f"{workout['id']}-{photo_id}.webp") as written:
        assert written.size == (400, 300)


def test_a_workout_holds_six_photos_and_no_more(signed_in, db_session):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    codes = [attach(signed_in, workout["id"]).status_code for _ in range(7)]
    assert codes == [201] * 6 + [400]
    full = attach(signed_in, workout["id"])
    assert full.json()["detail"] == "A workout can hold 6 photos."
    assert db_session.query(models.WorkoutPhoto).count() == 6


def test_an_oversize_photo_is_refused_before_it_is_decoded(signed_in, photo_dir):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    oversize = b"\xff\xd8\xff\xe0" + b"0" * (MAX_PHOTO_BYTES + 1024)
    response = attach(signed_in, workout["id"], data=oversize)
    assert response.status_code == 413
    assert not photo_dir.exists() or list(photo_dir.glob("*")) == []


def test_a_file_that_is_not_an_image_is_not_a_photo(signed_in, photo_dir, db_session):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    # A convincing name and content type over bytes no decoder will accept.
    assert attach(signed_in, workout["id"], data=b"not an image at all").status_code == 400
    assert attach(signed_in, workout["id"], data=b"<?php system($_GET['c']); ?>",
                  name="shell.php.jpg").status_code == 400
    assert attach(signed_in, workout["id"], data=b"").status_code == 400
    # Neither a row nor a file for any of them.
    assert db_session.query(models.WorkoutPhoto).count() == 0
    assert not photo_dir.exists() or list(photo_dir.glob("*")) == []


def test_photos_are_listed_on_the_workout_in_the_order_they_arrived(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    ids = [attach(signed_in, workout["id"]).json()["id"] for _ in range(3)]
    assert signed_in.get("/api/workouts").json()[0]["photos"] == ids


def test_an_attached_photo_can_be_fetched_by_its_owner(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    photo_id = attach(signed_in, workout["id"]).json()["id"]
    served = signed_in.get(f"/api/workouts/{workout['id']}/photos/{photo_id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert served.headers["cache-control"].startswith("private")
    assert served.content[:4] == b"RIFF"


def test_a_photo_that_is_not_there_is_the_same_404(signed_in, photo_dir):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    photo_id = attach(signed_in, workout["id"]).json()["id"]

    missing = signed_in.get(f"/api/workouts/{workout['id']}/photos/9999")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "No such photo."}
    # A photo asked for under the wrong workout is not found either.
    assert signed_in.get(f"/api/workouts/9999/photos/{photo_id}").status_code == 404

    # A volume that did not come back is not a server error to the caller.
    (photo_dir / f"{workout['id']}-{photo_id}.webp").unlink()
    lost = signed_in.get(f"/api/workouts/{workout['id']}/photos/{photo_id}")
    assert lost.status_code == 404
    assert lost.json() == {"detail": "No such photo."}


def test_deleting_a_photo_takes_the_row_and_the_file(signed_in, photo_dir, db_session):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    photo_id = attach(signed_in, workout["id"]).json()["id"]
    stored = photo_dir / f"{workout['id']}-{photo_id}.webp"
    assert stored.exists()

    assert signed_in.delete(f"/api/workouts/{workout['id']}/photos/{photo_id}").status_code == 204
    assert not stored.exists()
    assert db_session.query(models.WorkoutPhoto).count() == 0
    assert signed_in.get("/api/workouts").json()[0]["photos"] == []
    # Gone twice is a 404, not a second deletion.
    assert signed_in.delete(f"/api/workouts/{workout['id']}/photos/{photo_id}").status_code == 404


def test_only_the_owner_can_attach_or_delete_a_photo(signed_in, admin):
    from conftest import ADMIN

    workout = signed_in.post("/api/workouts", json=manual()).json()
    photo_id = attach(signed_in, workout["id"]).json()["id"]
    signed_in.post("/api/auth/logout")
    signed_in.post("/api/auth/login", json=ADMIN)
    assert attach(signed_in, workout["id"]).status_code == 404
    assert signed_in.delete(f"/api/workouts/{workout['id']}/photos/{photo_id}").status_code == 404


def test_photo_uploads_are_rate_limited(signed_in):
    workout = signed_in.post("/api/workouts", json=manual()).json()
    small = photo_bytes(200, 200)
    codes = [attach(signed_in, workout["id"], data=small).status_code for _ in range(11)]
    assert codes[-1] == 429


def test_the_photo_endpoints_need_a_session(client):
    assert client.post("/api/workouts/1/photos", files={"file": ("a.jpg", b"x")}).status_code == 401
    assert client.get("/api/workouts/1/photos/1").status_code == 401
    assert client.delete("/api/workouts/1/photos/1").status_code == 401
