"""The profile: what it reports, the badge slots, the diamonds, and the avatar."""

import datetime as dt
import io
from zoneinfo import ZoneInfo

import pytest
from conftest import give_item, give_planting, log_workout, neutral_start
from PIL import Image

from app import activity as activity_rules
from app import medals, models, progress, security
from app.config import MAX_AVATAR_BYTES, SERVER_TZ

# The second-account helpers, borrowed rather than written twice: how a
# friendship is made is tested over there, and what a friend may read is
# tested here.
from test_grove import befriend, sign_in

# The same again for the picture on a workout: attaching one is the workout
# suite's business, and the strip on this screen only reads what it made.
from test_workouts import attach, photo_bytes

pytest.importorskip("PIL")


def frozen_today() -> dt.date:
    """The date the app calls today, under the suite's pinned clock.

    The birthdate cases have to agree with the app on which day it is, and the
    app reads the instance timezone rather than the container's. Derived rather
    than written out so moving FROZEN_NOW moves these cases with it.
    """
    return security.now_utc().astimezone(SERVER_TZ).date()


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
    # Nobody has run a 5K yet, so nobody is level one yet.
    assert body["level"] == 0
    assert body["xp"] == 0.0
    assert body["xp_into_level"] == 0.0
    # The first level costs a 5K, in converted miles.
    assert body["xp_for_next_level"] == 3.1
    assert body["border_tier"] == 1
    assert body["displayed_badges"] == []
    assert [row["id"] for row in body["medals"]] == [medal.id for medal in medals.CATALOG]
    assert all(row["count"] == 0 for row in body["medals"])
    assert body["diamond_sports"] == []
    assert body["streak_weeks"] == 0
    assert body["week"] == {}
    assert body["lifetime"] == {}
    # Nothing found and nothing growing: the plot is not a collection.
    assert body["grove"] == {"seeds_found": 0, "plant_levels": 0}
    # Nothing given and nothing received, which is where every account starts.
    assert body["item_tallies"] == {
        "oil": {"used": 0, "received": 0},
        "water": {"used": 0, "received": 0},
    }
    assert body["next_chest"] == {
        "tier": "5K",
        "tier_id": "5k",
        "miles_away": 3.1,
        "gifted_by": None,
    }
    assert body["pending_gifts"] == []


def test_the_profile_carries_week_and_lifetime_totals(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 4.0, pace_min=15, offset_min=0)
    log_workout(db_session, member.id, "swim", 0.5, pace_min=60, offset_min=200)
    body = signed_in.get("/api/profile").json()
    assert body["lifetime"]["run"]["distance_mi"] == 4.0
    assert body["lifetime"]["run"]["workouts"] == 1
    # Converted alongside raw, because the game counts in converted Miles and
    # a swimmer reading raw miles would think they had done almost nothing.
    assert body["lifetime"]["swim"]["converted_mi"] == 2.0
    assert "cycle" not in body["lifetime"]
    assert body["week"]["run"]["distance_mi"] == 4.0


def owned_badges(client) -> list[str]:
    """Every medal this account may put in a slot, which is every earned one."""
    return [
        row["id"] for row in client.get("/api/profile").json()["medals"] if row["count"]
    ]


def test_badge_slots_take_only_badges_the_account_owns(signed_in, db_session, member):
    refused = signed_in.patch("/api/profile", json={"displayed_badges": ["weekly_40"]})
    assert refused.status_code == 400
    assert "not earned" in refused.json()["detail"]

    log_workout(db_session, member.id, "run", 11.0, pace_min=9)
    owned = owned_badges(signed_in)
    assert owned

    accepted = signed_in.patch("/api/profile", json={"displayed_badges": owned[:1]})
    assert accepted.status_code == 200
    assert accepted.json()["displayed_badges"] == owned[:1]
    assert db_session.get(models.User, member.id).displayed_badges == owned[:1]


def test_there_are_three_badge_slots_and_a_fourth_is_refused(signed_in, db_session, member):
    """Three because three was chosen, not because a fourth would not fit: the
    limit is worth asserting at the number rather than at "too many"."""
    log_workout(db_session, member.id, "run", 3.2, pace_min=9, offset_min=0)
    log_workout(db_session, member.id, "run", 7.0, pace_min=9, offset_min=120)
    log_workout(db_session, member.id, "run", 13.2, pace_min=9, offset_min=300)
    owned = owned_badges(signed_in)
    assert len(owned) >= 4

    too_many = signed_in.patch("/api/profile", json={"displayed_badges": owned[:4]})
    assert too_many.status_code == 400
    assert "only 3 medal slots" in too_many.json()["detail"]

    accepted = signed_in.patch("/api/profile", json={"displayed_badges": owned[:3]})
    assert accepted.status_code == 200
    assert accepted.json()["displayed_badges"] == owned[:3]


def test_a_badge_cannot_fill_two_slots(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 11.0, pace_min=9)
    owned = owned_badges(signed_in)
    assert len(owned) >= 2

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


def sideways_portrait_bytes() -> bytes:
    """A portrait photo the way a phone writes one: a landscape frame of pixels
    plus the tag that says to stand it up. Red at the top of the picture the
    person framed, blue at the bottom.

    Orientation 6 is turned back by a quarter anticlockwise, so the pixels are
    stored a quarter clockwise from upright. Built here rather than committed as
    a binary, which nobody could read to check what it claims.
    """
    upright = Image.new("RGB", (400, 600), (20, 20, 220))
    upright.paste((220, 20, 20), (0, 0, 400, 300))
    exif = Image.Exif()
    exif[0x0112] = 6
    out = io.BytesIO()
    upright.transpose(Image.ROTATE_90).save(out, format="JPEG", exif=exif, quality=95)
    return out.getvalue()


def test_a_photo_with_an_orientation_tag_is_stored_the_right_way_up(
    signed_in, member, avatar_dir
):
    """The tag does not survive the strip, so the pixels have to be turned
    before it goes: an avatar stored sideways is sideways forever."""
    assert upload(signed_in, sideways_portrait_bytes(), "me.jpg", "image/jpeg").status_code == 200

    with Image.open(avatar_dir / f"{member.id}.webp") as written:
        # Sampled off the centre line: sideways, the split runs down the middle
        # of the frame, and a sample sitting on it proves nothing either way.
        top = written.getpixel((180, 40))
        bottom = written.getpixel((180, 470))
        # Red above blue, which is only true of the upright picture. Compared
        # channel against channel rather than to exact values: this has been
        # through a JPEG and a webp.
        assert top[0] > top[2], top
        assert bottom[2] > bottom[0], bottom
        # Turning it upright must not smuggle the metadata back in with it.
        assert not written.info.get("exif")


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


def test_one_account_cannot_overwrite_another_avatar(signed_in, db_session, admin, member):
    """The path is derived from the session, so there is no id to tamper with."""
    upload(signed_in, image_bytes())
    assert db_session.get(models.User, member.id).avatar_path is not None
    assert db_session.get(models.User, admin.id).avatar_path is None
    # Another account's picture is readable to a signed-in player and no more.
    assert signed_in.get(f"/api/profile/avatar/{admin.id}").status_code == 404


def test_another_member_can_read_a_picture_and_nobody_outside_can(
    client, signed_in, db_session, member
):
    """The club rule: a session is the gate, and there is nothing narrower.

    Every member may look every other member up by name and read the card that
    comes back, and the face is on that card. What is still refused is anybody
    without a session at all: an unauthenticated URL serving a photograph is an
    invitation to hotlink it.
    """
    upload(signed_in, image_bytes())
    _, other_member = sign_in(db_session, "stranger")
    assert other_member.get(f"/api/profile/avatar/{member.id}").status_code == 200
    # And the owner still sees their own.
    assert signed_in.get(f"/api/profile/avatar/{member.id}").status_code == 200
    # Signed out is still nothing at all.
    client.cookies.clear()
    assert client.get(f"/api/profile/avatar/{member.id}").status_code == 401


def test_a_friend_can_read_a_picture(signed_in, db_session, member):
    upload(signed_in, image_bytes())
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    assert other_client.get(f"/api/profile/avatar/{member.id}").status_code == 200


def test_an_invite_shows_a_face_both_ways_round_now(signed_in, db_session, member):
    """What used to be a one-way rule and is not one any more.

    The old asymmetry existed because an account could create a pending invite
    to any name it liked, and serving the recipient's picture back would have
    made the invite form a way to pull a photograph out of a username. In a
    club with a roster search that rule protects nothing: the same picture is
    one search away, so both ends of an invitation see each other.
    """
    other, other_client = sign_in(db_session, "mate")
    upload(signed_in, image_bytes())
    upload(other_client, image_bytes(colour=(200, 10, 10)))
    assert signed_in.post("/api/friends/invite", json={"username": "mate"}).status_code == 204

    assert other_client.get(f"/api/profile/avatar/{member.id}").status_code == 200
    assert signed_in.get(f"/api/profile/avatar/{other.id}").status_code == 200


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
    """One stored workout at an exact instant, so a streak case can put a week
    exactly where it wants it.

    Marked manual, which nothing writes any more: these are the rows a history
    from before the form was taken away looks like, and they still count.
    """
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


def test_the_profile_reports_the_streak(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 2.0)
    assert signed_in.get("/api/profile").json()["streak_weeks"] == 1


# --------------------------------------------------------------------------
# The seven days under the streak
# --------------------------------------------------------------------------


def test_the_week_days_are_monday_first_and_this_week_only(db_session, member):
    # Tuesday and Saturday of this week, plus one in the week before that must
    # not show up in it.
    add_workout(db_session, member.id, at(THIS_MONDAY + dt.timedelta(days=1)))
    add_workout(db_session, member.id, at(THIS_MONDAY + dt.timedelta(days=5)))
    add_workout(db_session, member.id, at(monday(1) + dt.timedelta(days=1)))
    assert progress.week_days(db_session, member.id, NOW) == [
        False,
        True,
        False,
        False,
        False,
        True,
        False,
    ]


def test_an_empty_week_has_no_days_on_it(db_session, member):
    add_workout(db_session, member.id, at(monday(1)))
    assert progress.week_days(db_session, member.id, NOW) == [False] * 7


def test_a_workout_dated_ahead_of_this_week_lands_on_no_day(db_session, member):
    add_workout(db_session, member.id, at(monday(-1) + dt.timedelta(days=2)))
    assert progress.week_days(db_session, member.id, NOW) == [False] * 7


def test_the_week_days_are_bucketed_in_the_instance_timezone(db_session, member, monkeypatch):
    """The boundary case, and the reason this is worked out on the server.

    Two in the morning on Monday, UTC, is seven in the evening on Sunday in an
    instance running seven hours behind: the same instant is in two different
    weeks depending on which clock reads it. The server counts the streak in the
    instance zone, so the diamonds under it have to be bucketed there too, or the
    two disagree on one evening a week.
    """
    zone = ZoneInfo("America/Phoenix")
    monkeypatch.setattr(progress, "SERVER_TZ", zone)
    monkeypatch.setattr(activity_rules, "SERVER_TZ", zone)

    # Monday 02:00 UTC, which is Sunday evening locally and so last week.
    add_workout(db_session, member.id, at(THIS_MONDAY, 2, 0))
    # Monday 14:00 UTC, which is Monday morning locally.
    add_workout(db_session, member.id, at(THIS_MONDAY, 14, 0))
    assert progress.week_days(db_session, member.id, NOW) == [
        True,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    # The same instant that fell out of this week is on the last day of the week
    # before, which is what the streak counts it as.
    assert progress.streak_weeks(db_session, member.id, NOW) == 2


def test_the_profile_reports_the_week_days(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 2.0)
    days = signed_in.get("/api/profile").json()["week_days"]
    assert len(days) == 7
    assert days.count(True) == 1


# --------------------------------------------------------------------------
# Diamonds
# --------------------------------------------------------------------------


def test_diamonds_are_picked_by_lifetime_distance_until_they_are_chosen(
    signed_in, db_session, member
):
    log_workout(db_session, member.id, "cycle", 9.0, pace_min=5, offset_min=0)
    log_workout(db_session, member.id, "run", 4.0, pace_min=10, offset_min=100)
    log_workout(db_session, member.id, "walk", 1.0, pace_min=20, offset_min=200)
    log_workout(db_session, member.id, "swim", 0.5, pace_min=60, offset_min=300)
    # Three slots, filled by raw miles: the swim is last and misses out.
    assert signed_in.get("/api/profile").json()["diamond_sports"] == ["cycle", "run", "walk"]


def test_diamonds_show_only_the_sports_with_miles(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 3.0)
    assert signed_in.get("/api/profile").json()["diamond_sports"] == ["run"]


def test_diamonds_can_be_chosen_and_reset(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 3.0)
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
    log_workout(db_session, member.id, "run", 11.0, pace_min=9)
    owned = owned_badges(signed_in)
    assert signed_in.patch("/api/profile", json={"displayed_badges": owned[:1]}).status_code == 200

    body = signed_in.patch("/api/profile", json={"diamond_sports": ["swim"]}).json()
    assert body["displayed_badges"] == owned[:1]
    assert body["diamond_sports"] == ["swim"]

    back = signed_in.patch("/api/profile", json={"displayed_badges": []}).json()
    assert back["displayed_badges"] == []
    assert back["diamond_sports"] == ["swim"]
    assert db_session.get(models.User, member.id).diamond_sports == ["swim"]


# --------------------------------------------------------------------------
# The name somebody goes by, and the age worked out from their birthdate
# --------------------------------------------------------------------------


def test_a_fresh_profile_has_no_name_and_no_age(signed_in):
    body = signed_in.get("/api/profile").json()
    assert body["first_name"] is None
    assert body["last_name"] is None
    assert body["display_name"] is None
    assert body["birthdate"] is None
    assert body["age"] is None
    assert body["gender"] is None


def test_the_name_fields_are_saved_and_composed_into_one(signed_in, db_session, member):
    body = signed_in.patch(
        "/api/profile", json={"first_name": " Avery ", "last_name": "Case"}
    ).json()
    assert (body["first_name"], body["last_name"]) == ("Avery", "Case")
    assert body["display_name"] == "Avery Case"
    db_session.refresh(member)
    assert (member.first_name, member.last_name) == ("Avery", "Case")


def test_half_a_name_is_still_a_name(signed_in):
    first = signed_in.patch("/api/profile", json={"first_name": "Avery"}).json()
    assert first["display_name"] == "Avery"
    both = signed_in.patch("/api/profile", json={"last_name": "Case"}).json()
    assert both["display_name"] == "Avery Case"
    # Cleared back to half, and the half that is left is the whole of it.
    last = signed_in.patch("/api/profile", json={"first_name": None}).json()
    assert last["display_name"] == "Case"


def test_every_new_field_can_be_cleared_again(signed_in, db_session, member):
    signed_in.patch(
        "/api/profile",
        json={
            "first_name": "Avery",
            "last_name": "Case",
            "birthdate": "1990-05-04",
            "gender": "Male",
        },
    )
    cleared = signed_in.patch(
        "/api/profile",
        json={"first_name": None, "last_name": "", "birthdate": None, "gender": "   "},
    ).json()
    assert cleared["display_name"] is None
    assert cleared["birthdate"] is None
    assert cleared["age"] is None
    assert cleared["gender"] is None
    db_session.refresh(member)
    # Blank is stored as nothing, so no reader has to treat "" as null too.
    assert (member.first_name, member.last_name) == (None, None)
    assert (member.birthdate, member.gender) == (None, None)


def test_a_birthdate_is_saved_and_reported_with_the_age_it_gives(signed_in, db_session, member):
    # The first of January, so the birthday has already happened whatever day
    # the pinned clock sits on and the age is 34 either way.
    born = dt.date(frozen_today().year - 34, 1, 1)
    body = signed_in.patch("/api/profile", json={"birthdate": born.isoformat()}).json()
    assert body["birthdate"] == born.isoformat()
    assert body["age"] == 34
    db_session.refresh(member)
    assert member.birthdate == born


def test_the_age_counts_full_years_only():
    from app.routers.profile import computed_age

    born = dt.date(1990, 5, 4)
    assert computed_age(born, dt.date(2026, 5, 3)) == 35
    assert computed_age(born, dt.date(2026, 5, 4)) == 36
    assert computed_age(born, dt.date(2026, 5, 5)) == 36
    # A birthday on the 29th of February in a year that has no such day.
    assert computed_age(dt.date(2000, 2, 29), dt.date(2026, 2, 28)) == 25
    assert computed_age(None) is None


def test_a_birthdate_has_to_be_a_real_date_in_the_past(signed_in, db_session, member):
    today = frozen_today()
    for sent in (
        "not-a-date",
        "1990-13-01",
        "1990-02-30",
        today.isoformat(),
        (today + dt.timedelta(days=1)).isoformat(),
        "1900-01-01",
        "1876-04-01",
    ):
        response = signed_in.patch("/api/profile", json={"birthdate": sent})
        assert response.status_code == 400, sent
        assert response.json()["detail"][-1] == "."
    db_session.refresh(member)
    assert member.birthdate is None


def test_a_birthdate_the_day_before_today_is_allowed(signed_in):
    yesterday = frozen_today() - dt.timedelta(days=1)
    body = signed_in.patch("/api/profile", json={"birthdate": yesterday.isoformat()}).json()
    assert body["birthdate"] == yesterday.isoformat()
    assert body["age"] == 0


def test_the_name_fields_have_limits(signed_in, db_session, member):
    too_long = signed_in.patch("/api/profile", json={"first_name": "j" * 41})
    assert too_long.status_code == 400
    assert signed_in.patch("/api/profile", json={"last_name": "c" * 41}).status_code == 400
    # The longest each one will take is stored.
    assert signed_in.patch("/api/profile", json={"first_name": "j" * 40}).status_code == 200
    db_session.refresh(member)
    assert len(member.first_name) == 40


def test_gender_takes_only_the_two_offered_choices(signed_in, db_session, member):
    for choice in ("Male", "Female"):
        body = signed_in.patch("/api/profile", json={"gender": choice}).json()
        assert body["gender"] == choice
    # Anything the dropdown cannot produce is refused, including the free text
    # this field used to take and a right answer in the wrong case.
    for refused in ("prefer not to say", "man", "male", "g" * 33):
        assert signed_in.patch("/api/profile", json={"gender": refused}).status_code == 400
    db_session.refresh(member)
    assert member.gender == "Female"


def test_a_bio_is_saved_trimmed_and_served(signed_in, db_session, member):
    body = signed_in.patch("/api/profile", json={"bio": "  Walks a lot.  "}).json()
    assert body["bio"] == "Walks a lot."
    db_session.refresh(member)
    assert member.bio == "Walks a lot."
    assert signed_in.get("/api/profile").json()["bio"] == "Walks a lot."


def test_a_fresh_profile_has_no_bio(signed_in):
    assert signed_in.get("/api/profile").json()["bio"] is None


def test_a_bio_has_a_limit_and_the_longest_one_fits(signed_in, db_session, member):
    too_long = signed_in.patch("/api/profile", json={"bio": "b" * 201})
    assert too_long.status_code == 400
    assert too_long.json()["detail"][-1] == "."
    db_session.refresh(member)
    assert member.bio is None
    assert signed_in.patch("/api/profile", json={"bio": "b" * 200}).status_code == 200
    db_session.refresh(member)
    assert len(member.bio) == 200


def test_a_blank_bio_clears_it(signed_in, db_session, member):
    signed_in.patch("/api/profile", json={"bio": "Walks a lot."})
    for emptied in ("   ", None):
        assert signed_in.patch("/api/profile", json={"bio": emptied}).json()["bio"] is None
    db_session.refresh(member)
    # Blank is stored as nothing, so no reader has to treat "" as null too.
    assert member.bio is None


def test_patching_a_name_leaves_the_badge_slots_and_diamonds_alone(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 11.0, pace_min=9)
    owned = owned_badges(signed_in)
    signed_in.patch("/api/profile", json={"displayed_badges": owned[:1]})
    signed_in.patch("/api/profile", json={"diamond_sports": ["swim"]})

    body = signed_in.patch("/api/profile", json={"first_name": "Avery"}).json()
    assert body["displayed_badges"] == owned[:1]
    assert body["diamond_sports"] == ["swim"]
    assert body["display_name"] == "Avery"


# --------------------------------------------------------------------------
# Somebody else's profile
# --------------------------------------------------------------------------

# Everything GET /api/profile/{user_id} is allowed to send, asserted as a whole
# set: a field copied across from the private profile out of habit has to fail
# here rather than pass because nobody thought to go looking for it.
FRIEND_PROFILE_KEYS = {
    "user_id",
    "username",
    "display_name",
    "has_avatar",
    "avatar_version",
    "created_at",
    "border_tier",
    "flourish",
    "displayed_badges",
    "level",
    "xp",
    "xp_into_level",
    "xp_for_next_level",
    "bio",
    "miles",
    "medals",
    "grove",
    "item_tallies",
    "week",
    "lifetime",
    "recent_photos",
    "workouts",
    # The shoes, size and width included: reading what a friend wears is the
    # whole reason a friend sees gear at all.
    "gear",
}

# Nothing on this list may appear at any depth of the response. The first group
# is somebody's own business, which the You screen already says of the age and
# the gender; the rest is game state, which is a different thing from how
# somebody is doing.
#
# The heart rate and the calories came off this list in the round that gave
# people switches for them: they are on a friend's row by default now, and what
# happens when somebody turns a switch off is asserted below rather than here.
#
# The three XP figures came off it in the round that made this screen a mirror
# of the You screen: the level and the meter under it are shown now, and a
# meter cannot be drawn without the numbers that fill it. The chest ladder and
# the gifts waiting on it stay off, which is the game state this list is about.
FORBIDDEN_KEYS = {
    "email",
    "birthdate",
    "age",
    "gender",
    "first_name",
    "last_name",
    "pace",
    "next_chest",
    "pending_gifts",
    "chest_progress_mi",
    "cycle_pos",
    "renown",
    "satchel",
    "inventory",
    "items",
    "plantings",
    "ingest_token",
    "flags",
}


def every_key(payload) -> set[str]:
    """Every key anywhere in a response, however deeply it is nested.

    Walked rather than read off the top: an absent-key check that only looks at
    the outside passes happily while a workout row underneath carries a heart
    rate, which is the one thing these cases exist to catch.
    """
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            found.add(key)
            found |= every_key(value)
    elif isinstance(payload, list):
        for value in payload:
            found |= every_key(value)
    return found


@pytest.fixture()
def friend(client, db_session, member):
    """An account the member is already friends with, and its own cookie jar."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    return other, other_client


def add_photo(client, workout_id: int) -> int:
    """One picture on one of that client's own workouts, as small as the
    encoder will take: these cases are about the strip, not the file."""
    created = attach(client, workout_id, data=photo_bytes(200, 200))
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_a_friend_profile_reports_the_whole_shape_and_no_more(signed_in, db_session, friend):
    other, other_client = friend
    other_client.patch("/api/profile", json={"first_name": "Avery", "last_name": "Case"})
    log_workout(db_session, other.id, "run", 4.0, pace_min=9)
    mine = other_client.get("/api/profile").json()

    body = signed_in.get(f"/api/profile/{other.id}").json()
    assert set(body) == FRIEND_PROFILE_KEYS
    assert body["user_id"] == other.id
    assert body["username"] == "mate"
    assert body["display_name"] == "Avery Case"
    assert body["has_avatar"] is False
    assert body["avatar_version"] is None
    assert body["created_at"] == mine["created_at"]
    # The frame, the flourish and the slots are what the feed already draws
    # beside every one of their workouts.
    assert body["border_tier"] == mine["border_tier"]
    assert body["flourish"] == mine["flourish"]
    assert body["displayed_badges"] == []
    # His call: a level and a lifetime are shown, because reaching them takes a
    # deliberate tap on one person rather than a ranked list of everybody.
    assert body["level"] == mine["level"] >= 1
    assert body["miles"] == 4.0
    assert [row["id"] for row in body["medals"]] == [medal.id for medal in medals.CATALOG]
    assert body["grove"] == {"seeds_found": 0, "plant_levels": 0}
    assert len(body["workouts"]) == 1


def test_a_friend_profile_carries_none_of_the_private_fields(signed_in, db_session, friend):
    """The whole point of the endpoint, asserted against the response itself."""
    other, other_client = friend
    other_client.patch(
        "/api/profile", json={"birthdate": "1990-05-04", "gender": "Male"}
    )
    log_workout(db_session, other.id, "run", 5.0, pace_min=9)
    give_planting(db_session, other.id, "strawberry", growth=2.0)

    body = signed_in.get(f"/api/profile/{other.id}").json()
    assert every_key(body) & FORBIDDEN_KEYS == set()
    # And the values are not hiding under other names either.
    assert "1990-05-04" not in signed_in.get(f"/api/profile/{other.id}").text
    assert "Male" not in signed_in.get(f"/api/profile/{other.id}").text


def _measured_workout(db_session, user_id: int) -> None:
    """One workout with a heart rate and calories on it, because a row that
    never carried them would pass the two cases below whatever is served."""
    db_session.add(
        models.Workout(
            user_id=user_id,
            activity="run",
            start_ts=neutral_start(),
            duration_s=2700,
            distance_mi=5.0,
            active_kcal=444.0,
            avg_hr=148.0,
            source="sync",
            flags={},
            created_at=security.now_utc(),
        )
    )
    db_session.commit()


def test_a_workout_row_carries_the_heart_rate_and_the_calories(
    signed_in, db_session, friend
):
    """The feed's rule, reached through the feed's own serializer, and the
    default it now stands at: a friend sees what somebody did, in full."""
    other, _ = friend
    _measured_workout(db_session, other.id)

    row = signed_in.get(f"/api/profile/{other.id}").json()["workouts"][0]
    assert every_key(row) & FORBIDDEN_KEYS == set()
    assert row["distance_mi"] == 5.0
    assert row["duration_s"] == 2700
    assert row["avg_hr"] == 148.0
    assert row["active_kcal"] == 444.0
    # Not your own row, even though it is on a profile you asked for by id:
    # own rows carry the experience they earned and this view sends none.
    assert row["own"] is False


def test_a_hidden_field_is_absent_from_a_friend_profile(signed_in, db_session, friend):
    """The same list the feed honours, honoured by the other serializer that
    sends these rows. Read as text, so a value carried under another name fails
    here rather than passing a check of the keys."""
    other, other_client = friend
    _measured_workout(db_session, other.id)
    assert (
        other_client.patch(
            "/api/settings", json={"hidden_from_friends": ["avg_hr", "active_kcal"]}
        ).status_code
        == 200
    )

    response = signed_in.get(f"/api/profile/{other.id}")
    row = response.json()["workouts"][0]
    assert "avg_hr" not in row
    assert "active_kcal" not in row
    assert "148.0" not in response.text
    assert "444.0" not in response.text
    # The list itself is between them and the server, and is not on the screen
    # of whoever it is being kept from.
    assert "hidden_from_friends" not in response.text


def test_your_own_profile_hides_nothing_from_you(signed_in, db_session, member):
    """This endpoint answers about yourself too, and a hidden field is something
    said about friends rather than about your own screen."""
    _measured_workout(db_session, member.id)
    signed_in.patch("/api/settings", json={"hidden_from_friends": ["avg_hr", "active_kcal"]})

    row = signed_in.get(f"/api/profile/{member.id}").json()["workouts"][0]
    assert row["avg_hr"] == 148.0
    assert row["active_kcal"] == 444.0


def test_lifetime_miles_are_raw_distance_rather_than_experience(signed_in, db_session, friend):
    """A swim is worth four times its distance on the ladder, so the two numbers
    have to disagree here or the miles line is quietly printing a score."""
    other, other_client = friend
    log_workout(db_session, other.id, "swim", 2.0, pace_min=60)
    mine = other_client.get("/api/profile").json()

    body = signed_in.get(f"/api/profile/{other.id}").json()
    assert body["miles"] == 2.0
    assert mine["xp"] == 8.0
    assert body["miles"] < mine["xp"]


def test_a_friend_profile_mirrors_the_you_screen(signed_in, db_session, friend):
    """The parity the round is about: everything the You screen counts, in the
    shape the You screen counts it, so the two draw from one payload."""
    other, other_client = friend
    other_client.patch("/api/profile", json={"bio": "Out most mornings."})
    log_workout(db_session, other.id, "run", 4.0, pace_min=9)
    log_workout(db_session, other.id, "swim", 1.0, pace_min=60, offset_min=90)
    mine = other_client.get("/api/profile").json()

    body = signed_in.get(f"/api/profile/{other.id}").json()
    assert body["bio"] == "Out most mornings."
    # The level and the meter under it, the same three numbers by the same
    # names, so one component fills both screens.
    assert body["level"] == mine["level"]
    assert body["xp"] == mine["xp"]
    assert body["xp_into_level"] == mine["xp_into_level"]
    assert body["xp_for_next_level"] == mine["xp_for_next_level"]
    # The four tiles: miles here, the two grove counts, and the medals the
    # catalogue is already sent for.
    assert body["miles"] == 5.0
    assert body["grove"] == mine["grove"]
    assert len(body["medals"]) == len(mine["medals"])
    # The items grid, the same four numbers under the same names.
    assert body["item_tallies"] == mine["item_tallies"]
    # The sport chips and the two cards read these, and a sport nobody has done
    # is a missing key on both screens rather than a zero row.
    assert body["week"] == mine["week"]
    assert body["lifetime"] == mine["lifetime"]
    assert body["lifetime"]["run"]["distance_mi"] == 4.0
    assert body["lifetime"]["swim"]["distance_mi"] == 1.0
    assert "cycle" not in body["lifetime"]


# --------------------------------------------------------------------------
# The items grid
# --------------------------------------------------------------------------


def test_the_item_tallies_count_what_was_spent_and_what_arrived(
    signed_in, db_session, member, friend
):
    """Both kinds, both directions, driven through the endpoints that spend
    them: what a tally counts is what the verbs actually did."""
    other, other_client = friend
    mine = give_planting(db_session, member.id, "strawberry")
    theirs = give_planting(db_session, other.id, "raspberry")

    # Water into their plot, water into my own, and water back from them. Only
    # the first two are mine to have used, and only the last was given to me.
    first = give_item(db_session, member.id, "water")
    second = give_item(db_session, member.id, "water")
    back = give_item(db_session, other.id, "water")
    assert (
        signed_in.post(f"/api/satchel/{first.id}/pour", json={"planting_id": theirs.id}).status_code
        == 200
    )
    assert (
        signed_in.post(f"/api/satchel/{second.id}/pour", json={"planting_id": mine.id}).status_code
        == 200
    )
    assert (
        other_client.post(
            f"/api/satchel/{back.id}/pour", json={"planting_id": mine.id}
        ).status_code
        == 200
    )

    # Oil each way. Theirs lands on a chest my own miles bring; mine is still
    # waiting on a mile they have not run.
    given = give_item(db_session, member.id, "oil", rarity="rare")
    sent = give_item(db_session, other.id, "oil", rarity="rare")
    assert (
        signed_in.post(f"/api/satchel/{given.id}/anoint", json={"user_id": other.id}).status_code
        == 204
    )
    assert (
        other_client.post(f"/api/satchel/{sent.id}/anoint", json={"user_id": member.id}).status_code
        == 204
    )
    log_workout(db_session, member.id, "run", 4.0)

    body = signed_in.get("/api/profile").json()
    assert body["item_tallies"] == {
        "oil": {"used": 1, "received": 1},
        "water": {"used": 2, "received": 1},
    }
    # Their side of the same four acts, read from their own screen.
    assert other_client.get("/api/profile").json()["item_tallies"] == {
        # The gift they were given has not landed on a chest yet, so their
        # screen says nothing about it. It is not a count until it arrives.
        "oil": {"used": 1, "received": 0},
        "water": {"used": 1, "received": 1},
    }


def test_a_friend_reads_the_same_item_tallies_the_owner_does(
    signed_in, db_session, member, friend
):
    """The grid is on both screens and says the same thing on each: aggregates
    with nobody named in them, so there is nothing here to keep back."""
    other, other_client = friend
    theirs = give_planting(db_session, other.id, "raspberry")
    water = give_item(db_session, member.id, "water")
    assert (
        signed_in.post(f"/api/satchel/{water.id}/pour", json={"planting_id": theirs.id}).status_code
        == 200
    )

    theirs_own = other_client.get("/api/profile").json()["item_tallies"]
    seen = signed_in.get(f"/api/profile/{other.id}").json()["item_tallies"]
    assert seen == theirs_own
    assert seen == {
        "oil": {"used": 0, "received": 0},
        "water": {"used": 0, "received": 1},
    }


def test_an_account_that_has_spent_nothing_tallies_nought_on_both_screens(
    signed_in, db_session, friend
):
    other, _other_client = friend
    # Held rather than spent: an item in the satchel is not a thing anybody did.
    give_item(db_session, other.id, "water")
    give_item(db_session, other.id, "oil", rarity="rare")
    empty = {"oil": {"used": 0, "received": 0}, "water": {"used": 0, "received": 0}}
    assert signed_in.get("/api/profile").json()["item_tallies"] == empty
    assert signed_in.get(f"/api/profile/{other.id}").json()["item_tallies"] == empty


def test_hidden_calories_are_absent_from_every_total_a_friend_reads(
    signed_in, db_session, friend
):
    """The week and the lifetime are calorie figures like any other, so the
    switch has to reach them too. Read as text, so a number carried under
    another name fails here rather than passing a check of the keys."""
    other, other_client = friend
    _measured_workout(db_session, other.id)
    assert (
        other_client.patch(
            "/api/settings", json={"hidden_from_friends": ["active_kcal"]}
        ).status_code
        == 200
    )

    response = signed_in.get(f"/api/profile/{other.id}")
    body = response.json()
    assert "active_kcal" not in body["week"]["run"]
    assert "active_kcal" not in body["lifetime"]["run"]
    assert "444.0" not in response.text
    # Distance and time are the card itself and stay whatever the list says.
    assert body["lifetime"]["run"]["distance_mi"] == 5.0
    assert body["week"]["run"]["workouts"] == 1
    assert body["miles"] == 5.0


def test_your_own_totals_keep_their_calories(signed_in, db_session, member):
    """The friend-shaped view of yourself, which hides nothing: a switch is
    something an account said about its friends rather than about itself."""
    _measured_workout(db_session, member.id)
    signed_in.patch("/api/settings", json={"hidden_from_friends": ["active_kcal"]})

    body = signed_in.get(f"/api/profile/{member.id}").json()
    assert body["lifetime"]["run"]["active_kcal"] == 444.0
    assert body["week"]["run"]["active_kcal"] == 444.0


def test_the_media_strip_is_the_last_six_pictures_newest_first(
    signed_in, db_session, friend
):
    other, other_client = friend
    ridden = log_workout(db_session, other.id, "cycle", 8.0, pace_min=4)
    swum = log_workout(db_session, other.id, "swim", 1.0, pace_min=60, offset_min=90)
    older = [add_photo(other_client, ridden.id) for _ in range(4)]
    newer = [add_photo(other_client, swum.id) for _ in range(3)]

    strip = signed_in.get(f"/api/profile/{other.id}").json()["recent_photos"]
    # Six of the seven, and the one left behind is the oldest.
    assert [row["photo_id"] for row in strip] == list(reversed(older + newer))[:6]
    assert older[0] not in [row["photo_id"] for row in strip]
    # The tag under a picture is the workout it was attached to.
    assert strip[0] == {
        "photo_id": newer[-1],
        "workout_id": swum.id,
        "activity": "swim",
        # The tag draws the sport mark, so it carries what decides which one.
        "indoor": False,
        "distance_mi": 1.0,
        "duration_s": swum.duration_s,
    }
    assert strip[-1]["activity"] == "cycle"


def test_a_profile_with_no_pictures_has_an_empty_strip(signed_in, db_session, friend):
    other, _ = friend
    log_workout(db_session, other.id, "run", 2.0, pace_min=9)
    assert signed_in.get(f"/api/profile/{other.id}").json()["recent_photos"] == []


def test_your_own_strip_is_on_the_friend_shaped_view(signed_in, db_session, member):
    workout = log_workout(db_session, member.id, "run", 2.0, pace_min=9)
    photo_id = add_photo(signed_in, workout.id)
    strip = signed_in.get(f"/api/profile/{member.id}").json()["recent_photos"]
    assert [row["photo_id"] for row in strip] == [photo_id]


def test_a_non_friend_reaches_neither_the_strip_nor_the_pictures_on_it(
    signed_in, db_session, friend
):
    """The ids on the strip are addresses, and the endpoint behind them is
    gated on the same friendship the strip is. A member who is not a friend
    gets the restricted card, which has no strip on it at all, so there are no
    ids to try; asking the photo endpoint anyway is the same 404."""
    other, other_client = friend
    workout = log_workout(db_session, other.id, "run", 2.0, pace_min=9)
    photo_id = add_photo(other_client, workout.id)
    assert signed_in.get(f"/api/workouts/{workout.id}/photos/{photo_id}").status_code == 200

    _, outsider = sign_in(db_session, "nobody")
    card = outsider.get(f"/api/profile/{other.id}")
    assert card.status_code == 200
    assert card.json()["restricted"] is True
    assert "recent_photos" not in card.json()
    refused = outsider.get(f"/api/workouts/{workout.id}/photos/{photo_id}")
    assert refused.status_code == 404
    assert refused.json() == {"detail": "No such photo."}


def test_a_friend_profile_shows_ten_workouts_newest_first(signed_in, db_session, friend):
    other, _ = friend
    made = [
        add_workout(db_session, other.id, NOW - dt.timedelta(hours=hours_back))
        for hours_back in range(12)
    ]

    rows = signed_in.get(f"/api/profile/{other.id}").json()["workouts"]
    assert len(rows) == 10
    # The ten it kept are the ten most recent, newest first; the two oldest are
    # simply not there, and there is no cursor to go and ask for them.
    assert [row["workout_id"] for row in rows] == [row.id for row in made[:10]]
    stamps = [row["start_ts"] for row in rows]
    assert stamps == sorted(stamps, reverse=True)


# Everything the restricted card is allowed to carry, asserted as a whole set
# for the reason the friend shape is: a field copied across out of habit has to
# fail here rather than pass because nobody went looking for it.
MEMBER_CARD_KEYS = {
    "user_id",
    "username",
    "display_name",
    "has_avatar",
    "avatar_version",
    "border_tier",
    "flourish",
    "bio",
    "created_at",
    "restricted",
    "friendship",
}

# Everything friendship still gates, named one by one. This is the list the
# club round is about: a member you have not met is a name, a face, a line and
# a month, and every number the game keeps stays behind an accepted invite.
MEMBER_CARD_ABSENT = {
    "level",
    "miles",
    "xp",
    "xp_into_level",
    "xp_for_next_level",
    "medals",
    "displayed_badges",
    "grove",
    "workouts",
    "recent_photos",
    "item_tallies",
    "week",
    "lifetime",
    "email",
    "birthdate",
    "age",
    "gender",
    # A member you have not met learns nothing about anybody's kit either.
    "gear",
}


def test_a_member_who_is_not_a_friend_gets_the_restricted_card(signed_in, db_session):
    """The club's own answer, which used to be a 404: a member is somebody you
    were let into a room with, so their name and their face are readable."""
    other, other_client = sign_in(db_session, "stranger")
    other_client.patch(
        "/api/profile", json={"first_name": "Ada", "last_name": "Rowe", "bio": "Slow and steady."}
    )
    log_workout(db_session, other.id, "run", 6.0, pace_min=9)

    response = signed_in.get(f"/api/profile/{other.id}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == MEMBER_CARD_KEYS
    assert body["user_id"] == other.id
    assert body["username"] == "stranger"
    assert body["display_name"] == "Ada Rowe"
    assert body["bio"] == "Slow and steady."
    assert body["restricted"] is True
    assert body["friendship"] == "none"
    assert body["has_avatar"] is False


def test_the_restricted_card_carries_none_of_what_friendship_gates(signed_in, db_session):
    """The negative half, and the one that matters. Six miles were run, a plant
    is in the ground and a medal was earned, and none of it is in the card."""
    other, _ = sign_in(db_session, "stranger")
    log_workout(db_session, other.id, "run", 6.5, pace_min=9)
    give_planting(db_session, other.id, "strawberry", growth=4.0)

    response = signed_in.get(f"/api/profile/{other.id}")
    assert every_key(response.json()) & MEMBER_CARD_ABSENT == set()
    assert every_key(response.json()) & FORBIDDEN_KEYS == set()
    # And no number is hiding under another name either.
    assert "6.5" not in response.text


def test_the_restricted_card_says_which_way_an_invite_is_pointing(signed_in, db_session, member):
    """The one field the button on the card is drawn from, and it only ever
    describes a pair the reader is half of."""
    asked, asked_client = sign_in(db_session, "asked")
    assert signed_in.post("/api/friends/invite", json={"username": "asked"}).status_code == 204
    assert signed_in.get(f"/api/profile/{asked.id}").json()["friendship"] == "invited_by_me"
    # And from the other end of the same invite.
    card = asked_client.get(f"/api/profile/{member.id}")
    assert card.status_code == 200
    assert card.json()["friendship"] == "invited_me"


def test_a_pending_invite_is_still_not_a_friendship(signed_in, db_session, member):
    """Asked for, not agreed to. The card opens either way now, and what it
    carries is the restricted shape until somebody says yes."""
    asked, _ = sign_in(db_session, "asked")
    db_session.add(
        models.Friendship(
            requester_id=member.id,
            addressee_id=asked.id,
            status="pending",
            created_at=security.now_utc(),
        )
    )
    db_session.commit()
    body = signed_in.get(f"/api/profile/{asked.id}").json()
    assert set(body) == MEMBER_CARD_KEYS


def test_an_account_that_does_not_exist_is_still_a_404(signed_in, db_session):
    """The only refusal left, and it means one thing: no such account. A member
    is answered, so nothing here is a way to ask which ids are real either --
    every id that is real answers the same way."""
    invented = signed_in.get("/api/profile/9999")
    assert invented.status_code == 404
    assert invented.json() == {"detail": "No such friend."}


def test_removing_a_friend_closes_their_profile_back_to_the_card(signed_in, friend):
    other, _ = friend
    assert set(signed_in.get(f"/api/profile/{other.id}").json()) == FRIEND_PROFILE_KEYS
    assert signed_in.delete(f"/api/friends/{other.id}").status_code == 204
    assert set(signed_in.get(f"/api/profile/{other.id}").json()) == MEMBER_CARD_KEYS


def test_your_own_id_answers_with_the_friend_shaped_view(signed_in, db_session, member):
    """Allowed, the way the friend's grove allows it, and shaped the same as
    anybody else's: the private profile is what GET /api/profile is for."""
    log_workout(db_session, member.id, "run", 3.0)
    body = signed_in.get(f"/api/profile/{member.id}")
    assert body.status_code == 200
    assert set(body.json()) == FRIEND_PROFILE_KEYS
    assert every_key(body.json()) & FORBIDDEN_KEYS == set()
    assert body.json()["user_id"] == member.id


def test_a_friend_profile_needs_a_session(client, member):
    assert client.get(f"/api/profile/{member.id}").status_code == 401
