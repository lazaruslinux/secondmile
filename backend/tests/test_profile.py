"""The profile: what it reports, the badge slots, the diamonds, and the avatar."""

import datetime as dt
import io

import pytest
from conftest import log_workout
from PIL import Image

from app import models, progress, security
from app.config import MAX_AVATAR_BYTES

pytest.importorskip("PIL")


def image_bytes(width=900, height=600, fmt="PNG", colour=(30, 90, 60)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format=fmt)
    return out.getvalue()


def upload(client, data: bytes, name="me.png", content_type="image/png"):
    return client.post("/api/profile/avatar", files={"file": (name, data, content_type)})


def test_a_fresh_profile_reports_the_whole_shape(signed_in, member):
    body = signed_in.get("/api/profile").json()
    assert body["user_id"] == member.id
    assert body["username"] == member.username
    assert body["created_at"]
    assert body["has_avatar"] is False
    assert body["avatar_version"] is None
    assert body["level"] == 1
    assert body["xp"] == 0
    assert body["xp_into_level"] == 0
    assert body["xp_for_next_level"] == 200
    assert body["border_tier"] == 1
    assert body["displayed_badges"] == []
    assert body["diamond_sports"] == []
    assert body["streak_weeks"] == 0
    assert body["week"] == {}
    assert body["lifetime"] == {}
    assert body["cards"] == {"owned": 0, "total": 36}
    assert body["achievements"]["earned"] == 0
    assert body["achievements"]["total"] > 0


def test_the_profile_carries_week_and_lifetime_totals(signed_in):
    log_workout(signed_in, "run", 4.0, pace_min=15, offset_min=0)
    log_workout(signed_in, "swim", 0.5, pace_min=60, offset_min=200)
    body = signed_in.get("/api/profile").json()
    assert body["lifetime"]["run"]["distance_mi"] == 4.0
    assert body["lifetime"]["run"]["workouts"] == 1
    # Converted alongside raw, because the game counts in converted Miles and
    # a swimmer reading raw miles would think they had done almost nothing.
    assert body["lifetime"]["swim"]["converted_mi"] == 2.0
    assert "cycle" not in body["lifetime"]
    assert body["week"]["run"]["distance_mi"] == 4.0


def test_badge_slots_take_only_badges_the_account_owns(signed_in, db_session, member):
    refused = signed_in.patch(
        "/api/profile", json={"displayed_badges": ["lifetime_500"]}
    )
    assert refused.status_code == 400
    assert "not earned" in refused.json()["detail"]

    log_workout(signed_in, "run", 4.0, pace_min=15)
    owned = [row["id"] for row in signed_in.get("/api/achievements").json() if row["earned"]]
    assert owned

    accepted = signed_in.patch("/api/profile", json={"displayed_badges": owned[:1]})
    assert accepted.status_code == 200
    assert accepted.json()["displayed_badges"] == owned[:1]
    assert db_session.get(models.User, member.id).displayed_badges == owned[:1]


def test_badge_slots_are_limited_and_cannot_repeat(signed_in):
    log_workout(signed_in, "run", 4.0, pace_min=15)
    owned = [row["id"] for row in signed_in.get("/api/achievements").json() if row["earned"]]
    assert len(owned) >= 2

    too_many = signed_in.patch("/api/profile", json={"displayed_badges": owned[:1] * 5})
    assert too_many.status_code == 400
    repeated = signed_in.patch("/api/profile", json={"displayed_badges": [owned[0], owned[0]]})
    assert repeated.status_code == 400
    assert signed_in.get("/api/profile").json()["displayed_badges"] == []


def test_uploading_an_avatar_re_encodes_it_to_a_square_webp(
    signed_in, db_session, member, avatar_dir
):
    body = upload(signed_in, image_bytes()).json()
    assert body["has_avatar"] is True
    assert body["avatar_version"]

    # The name on disk comes from the account, never from the upload.
    stored = avatar_dir / f"{member.id}.webp"
    assert stored.exists()
    assert not (avatar_dir / "me.png").exists()
    with Image.open(stored) as written:
        assert written.format == "WEBP"
        assert written.size == (512, 512)
        # Nothing carried over from the original file.
        assert not written.info.get("exif")

    assert db_session.get(models.User, member.id).avatar_path == f"{member.id}.webp"
    profile = signed_in.get("/api/profile").json()
    assert profile["has_avatar"] is True
    assert profile["avatar_version"] == body["avatar_version"]


def test_an_uploaded_avatar_can_be_fetched_and_deleted(signed_in, member, avatar_dir):
    upload(signed_in, image_bytes())
    served = signed_in.get(f"/api/profile/avatar/{member.id}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/webp"
    assert served.headers["cache-control"].startswith("private")
    assert served.content[:4] == b"RIFF"

    assert signed_in.delete("/api/profile/avatar").status_code == 204
    assert not (avatar_dir / f"{member.id}.webp").exists()
    assert signed_in.get(f"/api/profile/avatar/{member.id}").status_code == 404
    assert signed_in.get("/api/profile").json()["has_avatar"] is False


def test_an_avatar_over_the_cap_is_refused_before_it_is_decoded(signed_in, avatar_dir, member):
    oversize = b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_AVATAR_BYTES + 1024)
    response = upload(signed_in, oversize)
    assert response.status_code == 413
    assert not (avatar_dir / f"{member.id}.webp").exists()


def test_a_file_that_is_not_an_image_is_refused(signed_in, avatar_dir, member):
    # A convincing name and content type over bytes no decoder will accept.
    response = upload(signed_in, b"not an image at all", name="me.png")
    assert response.status_code == 400
    assert not (avatar_dir / f"{member.id}.webp").exists()


def test_a_renamed_script_is_still_not_an_image(signed_in, avatar_dir, member):
    payload = b"<?php system($_GET['c']); ?>"
    assert upload(signed_in, payload, name="shell.php.png").status_code == 400
    assert list(avatar_dir.glob("*")) == [] or not (avatar_dir / f"{member.id}.webp").exists()


def test_an_empty_upload_is_refused(signed_in):
    assert upload(signed_in, b"").status_code == 400


def test_avatar_uploads_are_rate_limited(signed_in):
    data = image_bytes(200, 200)
    codes = [upload(signed_in, data).status_code for _ in range(6)]
    assert codes[-1] == 429
    assert codes.count(200) == 5


def test_the_profile_endpoints_need_a_session(client, member):
    assert client.get("/api/profile").status_code == 401
    assert client.patch("/api/profile", json={"displayed_badges": []}).status_code == 401
    assert client.post("/api/profile/avatar", files={"file": ("a.png", b"x")}).status_code == 401
    assert client.delete("/api/profile/avatar").status_code == 401
    assert client.get(f"/api/profile/avatar/{member.id}").status_code == 401
    assert client.get("/api/achievements").status_code == 401


def test_one_account_cannot_overwrite_another_avatar(signed_in, db_session, admin, member):
    """The path is derived from the session, so there is no id to tamper with."""
    upload(signed_in, image_bytes())
    assert db_session.get(models.User, member.id).avatar_path is not None
    assert db_session.get(models.User, admin.id).avatar_path is None
    # Another account's picture is readable to a signed-in player and no more.
    assert signed_in.get(f"/api/profile/avatar/{admin.id}").status_code == 404


def test_an_avatar_the_row_claims_but_the_disk_lost_is_a_404(signed_in, member, avatar_dir):
    """A volume that did not come back is not a server error to the caller.

    The row still says there is a picture; handing that path to FileResponse
    raises inside the response. The same 404 an account with no picture gets is
    both the honest answer and the one that says nothing about who exists.
    """
    upload(signed_in, image_bytes())
    (avatar_dir / f"{member.id}.webp").unlink()
    response = signed_in.get(f"/api/profile/avatar/{member.id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "No picture."}


def test_a_stored_avatar_survives_a_second_upload(signed_in, member, avatar_dir):
    first = upload(signed_in, image_bytes(colour=(10, 10, 10))).json()["avatar_version"]
    stored = avatar_dir / f"{member.id}.webp"
    original = stored.read_bytes()
    # Written and renamed into place, so there is never a half-written file.
    assert not list(avatar_dir.glob("*.tmp"))
    upload(signed_in, image_bytes(colour=(240, 240, 240)))
    assert stored.read_bytes() != original
    assert isinstance(first, int)


def test_an_account_with_no_workouts_still_has_a_progress_row(signed_in, db_session, member):
    signed_in.get("/api/profile")
    assert db_session.get(models.UserProgress, member.id) is not None
    assert db_session.get(models.UserProgress, member.id).updated_at <= security.now_utc()


# --------------------------------------------------------------------------
# The week streak
# --------------------------------------------------------------------------

# A Thursday and the Monday its week starts on. Fixed dates rather than "today"
# so the boundary cases below mean the same thing whatever day the suite runs.
NOW = dt.datetime(2026, 8, 6, 12, 0, tzinfo=dt.timezone.utc)
THIS_MONDAY = dt.date(2026, 8, 3)


def monday(weeks_back: int) -> dt.date:
    return THIS_MONDAY - dt.timedelta(weeks=weeks_back)


def at(day: dt.date, hour: int = 6, minute: int = 0) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=dt.timezone.utc)


def add_workout(db_session, user_id: int, start: dt.datetime) -> models.Workout:
    """One stored workout at an exact instant, past the manual form's clock."""
    row = models.Workout(
        user_id=user_id,
        activity="run",
        start_ts=start,
        duration_s=1800,
        distance_mi=2.0,
        active_kcal=200.0,
        avg_hr=None,
        source="manual",
        flags={},
        created_at=security.now_utc(),
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_the_streak_counts_weeks_back_from_this_one(db_session, member):
    for weeks_back in (0, 1, 2):
        add_workout(db_session, member.id, at(monday(weeks_back) + dt.timedelta(days=2)))
    # Older than the gap at week three, so it cannot join the run.
    add_workout(db_session, member.id, at(monday(4)))
    assert progress.streak_weeks(db_session, member.id, NOW) == 3


def test_several_workouts_in_one_week_are_still_one_week(db_session, member):
    for day in range(4):
        add_workout(db_session, member.id, at(THIS_MONDAY + dt.timedelta(days=day)))
    assert progress.streak_weeks(db_session, member.id, NOW) == 1


def test_an_empty_current_week_does_not_break_the_streak(db_session, member):
    """The week is still being lived, so it does not count and does not end it."""
    for weeks_back in (1, 2):
        add_workout(db_session, member.id, at(monday(weeks_back)))
    assert progress.streak_weeks(db_session, member.id, NOW) == 2


def test_a_quiet_last_week_ends_the_streak(db_session, member):
    add_workout(db_session, member.id, at(monday(2)))
    assert progress.streak_weeks(db_session, member.id, NOW) == 0


def test_the_streak_counts_weeks_at_their_boundaries(db_session, member):
    """A workout in the first minute of a week and one in the last minute of the
    week before are two weeks, not one."""
    add_workout(db_session, member.id, at(monday(1), 0, 0))
    add_workout(db_session, member.id, at(monday(1) - dt.timedelta(days=1), 23, 59))
    assert progress.streak_weeks(db_session, member.id, NOW) == 2


def test_a_workout_at_the_end_of_this_week_counts_this_week(db_session, member):
    add_workout(db_session, member.id, at(THIS_MONDAY + dt.timedelta(days=6), 23, 59))
    assert progress.streak_weeks(db_session, member.id, NOW) == 1


def test_a_workout_dated_ahead_of_now_does_not_start_a_streak(db_session, member):
    add_workout(db_session, member.id, at(monday(-2)))
    assert progress.streak_weeks(db_session, member.id, NOW) == 0
    # It also cannot extend one that a real week is holding up.
    add_workout(db_session, member.id, at(THIS_MONDAY))
    assert progress.streak_weeks(db_session, member.id, NOW) == 1


def test_the_profile_reports_the_streak(signed_in):
    log_workout(signed_in, "run", 2.0)
    assert signed_in.get("/api/profile").json()["streak_weeks"] == 1


# --------------------------------------------------------------------------
# Diamonds
# --------------------------------------------------------------------------


def test_diamonds_are_picked_by_lifetime_distance_until_they_are_chosen(signed_in):
    log_workout(signed_in, "cycle", 9.0, pace_min=5, offset_min=0)
    log_workout(signed_in, "run", 4.0, pace_min=10, offset_min=100)
    log_workout(signed_in, "walk", 1.0, pace_min=20, offset_min=200)
    log_workout(signed_in, "swim", 0.5, pace_min=60, offset_min=300)
    # Three slots, filled by raw miles: the swim is last and misses out.
    assert signed_in.get("/api/profile").json()["diamond_sports"] == ["cycle", "run", "walk"]


def test_diamonds_show_only_the_sports_with_miles(signed_in):
    log_workout(signed_in, "run", 3.0)
    assert signed_in.get("/api/profile").json()["diamond_sports"] == ["run"]


def test_diamonds_can_be_chosen_and_reset(signed_in, db_session, member):
    log_workout(signed_in, "run", 3.0)
    chosen = signed_in.patch("/api/profile", json={"diamond_sports": ["swim", "walk"]})
    assert chosen.status_code == 200
    assert chosen.json()["diamond_sports"] == ["swim", "walk"]
    assert db_session.get(models.User, member.id).diamond_sports == ["swim", "walk"]
    # A sport with no miles yet is a legitimate choice; the diamond reads zero.
    assert signed_in.get("/api/profile").json()["diamond_sports"] == ["swim", "walk"]

    reset = signed_in.patch("/api/profile", json={"diamond_sports": None})
    assert reset.status_code == 200
    assert reset.json()["diamond_sports"] == ["run"]
    assert db_session.get(models.User, member.id).diamond_sports is None


def test_diamonds_refuse_too_many_repeats_and_unknown_sports(signed_in, db_session, member):
    too_many = signed_in.patch(
        "/api/profile", json={"diamond_sports": ["walk", "run", "cycle", "swim"]}
    )
    assert too_many.status_code == 400
    repeated = signed_in.patch("/api/profile", json={"diamond_sports": ["run", "run"]})
    assert repeated.status_code == 400
    unknown = signed_in.patch("/api/profile", json={"diamond_sports": ["skateboard"]})
    assert unknown.status_code == 400
    assert unknown.json()["detail"][-1] == "."
    assert db_session.get(models.User, member.id).diamond_sports is None


def test_patching_one_part_of_the_profile_leaves_the_other_alone(signed_in, db_session, member):
    log_workout(signed_in, "run", 4.0, pace_min=15)
    owned = [row["id"] for row in signed_in.get("/api/achievements").json() if row["earned"]]
    assert signed_in.patch("/api/profile", json={"displayed_badges": owned[:1]}).status_code == 200

    body = signed_in.patch("/api/profile", json={"diamond_sports": ["swim"]}).json()
    assert body["displayed_badges"] == owned[:1]
    assert body["diamond_sports"] == ["swim"]

    back = signed_in.patch("/api/profile", json={"displayed_badges": []}).json()
    assert back["displayed_badges"] == []
    assert back["diamond_sports"] == ["swim"]
    assert db_session.get(models.User, member.id).diamond_sports == ["swim"]
