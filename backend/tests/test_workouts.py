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

import pytest
from PIL import Image

from app import models, progress, security
from app.activity import converted_miles
from app.config import MAX_PHOTO_BYTES

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
    assert row["encouragement"] == {"cheers": 0, "notes": 0, "cheered_by_me": False}
    # Own rows carry everything: nothing is ever kept back from the person whose
    # workout it is.
    assert (row["avg_hr"], row["active_kcal"], row["flags"]) == (148.0, 320.0, {})


def test_history_is_newest_first_and_pages(signed_in, db_session, member):
    for day in range(1, 6):
        stored(db_session, member.id, start=f"2026-07-0{day}T06:00:00+00:00")

    page = signed_in.get("/api/workouts", params={"limit": 2}).json()
    assert isinstance(page, list)
    assert [row["start_ts"][:10] for row in page] == ["2026-07-05", "2026-07-04"]

    older = signed_in.get(
        "/api/workouts", params={"limit": 2, "before": page[-1]["start_ts"]}
    ).json()
    assert [row["start_ts"][:10] for row in older] == ["2026-07-03", "2026-07-02"]


def test_paging_survives_an_unencoded_offset(signed_in, db_session, member):
    """A client that drops the timestamp into the query string without encoding
    it gets the offset back as a space; the second page still has to work."""
    for day in range(1, 4):
        stored(db_session, member.id, start=f"2026-07-0{day}T06:00:00+00:00")
    older = signed_in.get("/api/workouts?limit=2&before=2026-07-03T06:00:00+00:00").json()
    assert [row["start_ts"][:10] for row in older] == ["2026-07-02", "2026-07-01"]


def test_history_rejects_a_bad_cursor(signed_in):
    assert signed_in.get("/api/workouts?before=yesterday").status_code == 400


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
    assert rows[2.0] == []
    assert rows[4.0] == ["race_5k", "early_riser"]


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


def test_weekly_totals_ignore_older_weeks(signed_in, db_session, member):
    monday = _monday_of_this_week()
    long_ago = monday - dt.timedelta(weeks=6)
    stored(db_session, member.id, start=f"{long_ago.isoformat()}T06:00:00+00:00", active_kcal=999.0)
    weeks = signed_in.get("/api/workouts/weeks?count=2").json()
    assert len(weeks) == 2
    assert all(week["activities"] == {} for week in weeks)


def test_weekly_totals_reject_a_silly_count(signed_in):
    assert signed_in.get("/api/workouts/weeks?count=0").status_code == 400
    assert signed_in.get("/api/workouts/weeks?count=500").status_code == 400


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
