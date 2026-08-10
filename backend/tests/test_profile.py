"""The profile: what it reports, the badge slots, the diamonds, and the avatar."""

import datetime as dt
import io

import pytest
from conftest import give_planting, log_workout, neutral_start
from PIL import Image

from app import medals, models, progress, security
from app.config import MAX_AVATAR_BYTES

# The second-account helpers, borrowed rather than written twice: how a
# friendship is made is tested over there, and what a friend may read is
# tested here.
from test_grove import befriend, sign_in

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
    assert "only 3 badge slots" in too_many.json()["detail"]

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
    # The first of January, so this reads the same whatever day the suite runs:
    # that birthday has always already happened this year.
    born = dt.date(dt.date.today().year - 34, 1, 1)
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
    today = dt.date.today()
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
    yesterday = dt.date.today() - dt.timedelta(days=1)
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
    "miles",
    "medals",
    "grove",
    "workouts",
}

# Nothing on this list may appear at any depth of the response. The first group
# is somebody's own business, which the You screen already says of the age and
# the gender; the second is the two numbers a friend's row has never carried;
# the rest is game state, which is a different thing from how somebody is doing.
FORBIDDEN_KEYS = {
    "email",
    "birthdate",
    "age",
    "gender",
    "first_name",
    "last_name",
    "avg_hr",
    "heart_rate",
    "pace",
    "active_kcal",
    "calories",
    "xp",
    "xp_into_level",
    "xp_for_next_level",
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


def test_a_workout_row_carries_no_pace_and_no_heart_rate(signed_in, db_session, friend):
    """The feed's rule, reached through the feed's own serializer: a row says
    what somebody did, not how their body was doing while they did it."""
    other, _ = friend
    # Written in with a heart rate on it, because a row that never carried one
    # would pass this whatever the serializer sends.
    db_session.add(
        models.Workout(
            user_id=other.id,
            activity="run",
            start_ts=neutral_start(),
            duration_s=2700,
            distance_mi=5.0,
            active_kcal=400.0,
            avg_hr=148.0,
            source="sync",
            flags={},
            created_at=security.now_utc(),
        )
    )
    db_session.commit()
    row = signed_in.get(f"/api/profile/{other.id}").json()["workouts"][0]
    assert every_key(row) & FORBIDDEN_KEYS == set()
    assert row["distance_mi"] == 5.0
    assert row["duration_s"] == 2700
    # Not your own row, even though it is on a profile you asked for by id:
    # own rows carry the experience they earned and this view sends none.
    assert row["own"] is False


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


def test_a_stranger_and_an_account_that_does_not_exist_answer_identically(
    signed_in, db_session, client
):
    """404 rather than 403 on purpose, and the same 404 either way: an endpoint
    that told the two apart would be a way to ask whether somebody has an
    account here, which is exactly what the invite form refuses to answer."""
    stranger, _ = sign_in(db_session, "stranger")
    real = signed_in.get(f"/api/profile/{stranger.id}")
    invented = signed_in.get("/api/profile/9999")

    assert real.status_code == invented.status_code == 404
    assert real.json() == {"detail": "No such friend."}
    assert real.content == invented.content


def test_a_pending_invite_is_not_a_friendship(signed_in, db_session, member):
    """Asked for, not agreed to. Everything in this app is mutual, and a profile
    a request alone opened would be the one thing that is not."""
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
    assert signed_in.get(f"/api/profile/{asked.id}").status_code == 404


def test_removing_a_friend_closes_their_profile_again(signed_in, friend):
    other, _ = friend
    assert signed_in.get(f"/api/profile/{other.id}").status_code == 200
    assert signed_in.delete(f"/api/friends/{other.id}").status_code == 204
    assert signed_in.get(f"/api/profile/{other.id}").status_code == 404


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
