"""The profile: what it reports, the badge slots, and the avatar upload."""

import io

import pytest
from conftest import log_workout
from PIL import Image

from app import models, security
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
