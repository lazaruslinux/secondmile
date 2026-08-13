"""Gear: the shoes a walk or a run was done in, and the miles on them.

The law this file pins, in one sentence: gear is maintenance and never game, so
nothing in it earns experience, a chest, a medal, growth, renown, manna or
fruit, and taking a workout away takes its miles off the shoe rather than off
anything anybody earned.

Every pair here is invented. The mileage is a sum computed on every read, so the
cases below check it against deletions and restores rather than against a stored
number, because there is no stored number to check.
"""

import pytest

from app import gear, models, progress
from conftest import log_workout
from test_fellowship import befriend, sign_in
from test_ingest import export, post, workout as entry

# One invented pair, in the shape the form sends. No real shoe anybody owns is
# in this file: the sizes and the names are made up to exercise the rules.
PAIR = {
    "style": "mens",
    "brand": "Testbrand",
    "model": "Trail 3",
    "size": 10.0,
    "width": "D",
}
WOMENS_PAIR = {
    "style": "womens",
    "brand": "Testbrand",
    "model": "Road 2",
    "size": 8.5,
    "width": "B",
}


def add(client, **overrides) -> dict:
    """One pair recorded, and the list that comes back."""
    response = client.post("/api/gear", json={**PAIR, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def only(rows: list[dict]) -> dict:
    assert len(rows) == 1, rows
    return rows[0]


def gear_rows(client) -> list[dict]:
    response = client.get("/api/profile")
    assert response.status_code == 200, response.text
    return response.json()["gear"]


def wear(client, workout_id: int, gear_id: int | None):
    return client.patch(f"/api/workouts/{workout_id}", json={"gear_id": gear_id})


# --------------------------------------------------------------------------
# The pair itself
# --------------------------------------------------------------------------


def test_a_recorded_pair_comes_back_with_everything_it_was_given(signed_in):
    rows = add(signed_in, nickname="Trainers", starting_mi=42.5, replace_around_mi=400)
    pair = only(rows)
    assert pair["brand"] == "Testbrand"
    assert pair["model"] == "Trail 3"
    assert pair["nickname"] == "Trainers"
    assert (pair["style"], pair["size"], pair["width"]) == ("mens", 10.0, "D")
    # Nothing has been walked in them here, so the miles are what they arrived
    # with and nothing else.
    assert pair["miles"] == 42.5
    assert pair["starting_mi"] == 42.5
    assert pair["replace_around_mi"] == 400
    assert pair["is_default"] is False
    assert pair["retired"] is False
    # Said nothing about, so they are for both, which is what every pair
    # recorded before the choice existed is.
    assert pair["applies_to"] == "both"


def test_a_pair_with_no_starting_miles_starts_at_nothing(signed_in):
    assert only(add(signed_in))["miles"] == 0.0


def test_the_width_defaults_to_the_standard_one_for_the_style(signed_in, db_session):
    """His reason, in his words: almost nobody understands width. A form that
    sends none gets the standard one rather than a refusal."""
    mens = only(add(signed_in, width=None))
    assert mens["width"] == "D"

    other, other_client = sign_in(db_session, "mate")
    response = other_client.post("/api/gear", json={**WOMENS_PAIR, "width": None})
    assert response.status_code == 201, response.text
    assert only(response.json())["width"] == "B"


@pytest.mark.parametrize(
    "bad",
    [
        {"style": "unisex"},
        {"style": ""},
        # Not a half step, and not on the men's list at all.
        {"size": 10.25},
        {"size": 3.0},
        {"size": 17.0},
        # A women's width on a men's pair.
        {"width": "2A"},
        {"width": "ZZ"},
        {"brand": "   "},
        {"model": ""},
        {"starting_mi": -1},
        {"replace_around_mi": -400},
        # A scope the three buttons cannot produce.
        {"applies_to": "runs"},
        {"applies_to": "cycle"},
        {"applies_to": ""},
    ],
)
def test_a_pair_the_pickers_could_not_have_produced_is_refused(signed_in, bad):
    response = signed_in.post("/api/gear", json={**PAIR, **bad})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]


def test_the_womens_lists_are_their_own(signed_in):
    """A women's 4 and a 2A width are real choices, and neither is on the men's
    list; the two ladders overlap without being the same one."""
    response = signed_in.post(
        "/api/gear", json={**WOMENS_PAIR, "size": 4.0, "width": "2A"}
    )
    assert response.status_code == 201, response.text
    assert only(response.json())["size"] == 4.0

    assert gear.is_size("womens", 4.0) and not gear.is_size("mens", 4.0)
    assert gear.is_width("womens", "2A") and not gear.is_width("mens", "2A")
    assert gear.is_width("mens", "4E") and not gear.is_width("womens", "4E")


def test_a_style_change_takes_the_size_and_the_width_with_it(signed_in):
    pair = only(add(signed_in, size=12.5, width="4E"))
    # 12.5 is on both lists; 4E is not a women's width, so it falls to the
    # women's standard rather than being stored as something unpickable.
    response = signed_in.patch(f"/api/gear/{pair['id']}", json={"style": "womens"})
    assert response.status_code == 200, response.text
    changed = only(response.json())
    assert (changed["style"], changed["size"], changed["width"]) == ("womens", 12.5, "B")


def test_a_size_the_new_style_does_not_offer_is_refused(signed_in):
    pair = only(add(signed_in, size=16.0))
    response = signed_in.patch(f"/api/gear/{pair['id']}", json={"style": "womens"})
    assert response.status_code == 400, response.text


def test_an_emptied_nickname_goes_back_to_the_brand_and_model(signed_in, db_session):
    pair = only(add(signed_in, nickname="Trainers"))
    changed = only(signed_in.patch(f"/api/gear/{pair['id']}", json={"nickname": ""}).json())
    assert changed["nickname"] is None
    row = db_session.get(models.Gear, pair["id"])
    assert gear.display_name(row) == "Testbrand Trail 3"


def test_nobody_reaches_another_accounts_gear(signed_in, db_session):
    other, other_client = sign_in(db_session, "mate")
    theirs = only(add(other_client))["id"]
    for call in (
        signed_in.patch(f"/api/gear/{theirs}", json={"brand": "Mine"}),
        signed_in.post(f"/api/gear/{theirs}/default"),
        signed_in.post(f"/api/gear/{theirs}/retire"),
        signed_in.delete(f"/api/gear/{theirs}"),
    ):
        assert call.status_code == 404, call.text
    assert only(gear_rows(other_client))["brand"] == "Testbrand"


# --------------------------------------------------------------------------
# One default per account
# --------------------------------------------------------------------------


def test_only_one_pair_at_a_time_is_the_default(signed_in):
    first = only(add(signed_in))["id"]
    second = add(signed_in, model="Road 5")[1]["id"]

    signed_in.post(f"/api/gear/{first}/default")
    signed_in.post(f"/api/gear/{second}/default")
    flags = {row["id"]: row["is_default"] for row in gear_rows(signed_in)}
    assert flags == {first: False, second: True}


def test_retiring_a_pair_takes_the_default_with_it(signed_in, db_session, member):
    """A default out of the pickers would still be put on tomorrow's walk, which
    is the one thing retiring is supposed to stop."""
    pair = only(add(signed_in))["id"]
    signed_in.post(f"/api/gear/{pair}/default")
    signed_in.post(f"/api/gear/{pair}/retire")

    row = only(gear_rows(signed_in))
    assert (row["retired"], row["is_default"]) == (True, False)
    assert gear.default_pair(db_session, member.id) is None

    # Coming back out of retirement is not the same as being chosen again.
    assert only(signed_in.post(f"/api/gear/{pair}/unretire").json())["is_default"] is False


def test_a_retired_pair_cannot_be_made_the_default(signed_in):
    pair = only(add(signed_in))["id"]
    signed_in.post(f"/api/gear/{pair}/retire")
    response = signed_in.post(f"/api/gear/{pair}/default")
    assert response.status_code == 400, response.text


# --------------------------------------------------------------------------
# What a sync puts them on
# --------------------------------------------------------------------------


def sync_four(client, token):
    """One of each activity, in the export's own shape."""
    return post(
        client,
        token,
        export(
            entry("Outdoor Walk", "2026-07-20T06:12:00-07:00", 2400.0, 2.0, 190),
            entry("Running", "2026-07-20T07:30:00-07:00", 1800.0, 3.0, 350),
            entry("Indoor Cycle", "2026-07-20T18:00:00-07:00", 2700, 9.5, 400),
            entry("Pool Swim", "2026-07-21T06:00:00-07:00", 1500, 0.6, 240),
        ),
    )


def worn(db_session, user_id: int) -> dict[str, int | None]:
    db_session.expire_all()
    return {
        row.activity: row.gear_id
        for row in db_session.query(models.Workout).filter(
            models.Workout.user_id == user_id
        )
    }


def test_the_default_pair_goes_on_new_walks_and_runs_only(signed_in, ingest_token, db_session, member):
    pair = only(add(signed_in))["id"]
    signed_in.post(f"/api/gear/{pair}/default")

    assert sync_four(signed_in, ingest_token).status_code == 200
    # Feet only. A ride and a swim never take shoes, and a step reading is not
    # an activity at all.
    assert worn(db_session, member.id) == {
        "walk": pair,
        "run": pair,
        "cycle": None,
        "swim": None,
    }


def test_with_no_default_a_sync_puts_nothing_on_anything(signed_in, ingest_token, db_session, member):
    add(signed_in)
    assert sync_four(signed_in, ingest_token).status_code == 200
    assert set(worn(db_session, member.id).values()) == {None}


def test_a_rebuild_never_writes_a_shoe_over_a_choice(signed_in, ingest_token, db_session, member):
    """The default is put on where a workout is born and nowhere else, so
    replaying the history leaves every assignment exactly as somebody left it.
    """
    pair = only(add(signed_in))["id"]
    signed_in.post(f"/api/gear/{pair}/default")
    assert sync_four(signed_in, ingest_token).status_code == 200
    run = db_session.query(models.Workout).filter(models.Workout.activity == "run").one()
    assert wear(signed_in, run.id, None).status_code == 200

    progress.rebuild_from_surviving(db_session, member.id)
    progress.recompute(db_session, member.id)
    assert worn(db_session, member.id)["run"] is None
    # And the walk that was never touched still has them on.
    assert worn(db_session, member.id)["walk"] == pair


# --------------------------------------------------------------------------
# What a pair is put on by itself
# --------------------------------------------------------------------------


def default_pair_for(client, scope: str) -> int:
    """One default pair, recorded for runs, walks, or both."""
    pair = only(add(client, applies_to=scope))["id"]
    client.post(f"/api/gear/{pair}/default")
    return pair


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("both", {"walk": True, "run": True}),
        ("run", {"walk": False, "run": True}),
        ("walk", {"walk": True, "run": False}),
    ],
)
def test_the_scope_decides_which_new_activities_are_stamped(
    signed_in, ingest_token, db_session, member, scope, expected
):
    """His pair is for runs: a walk in something else must not arrive wearing
    them. A ride and a swim are out of it either way."""
    pair = default_pair_for(signed_in, scope)

    assert sync_four(signed_in, ingest_token).status_code == 200
    carried = worn(db_session, member.id)
    assert carried["walk"] == (pair if expected["walk"] else None)
    assert carried["run"] == (pair if expected["run"] else None)
    assert (carried["cycle"], carried["swim"]) == (None, None)


def test_the_scope_gates_the_sync_and_never_a_choice_made_by_hand(
    signed_in, db_session, member
):
    """The setting says where a pair goes on its own, not where it may go. A
    run-only pair still goes on any walk somebody puts it on."""
    pair = default_pair_for(signed_in, "run")
    walk = log_workout(db_session, member.id, "walk", 2.0)

    row = wear(signed_in, walk.id, pair)
    assert row.status_code == 200, row.text
    assert row.json()["gear_id"] == pair


def test_the_scope_is_changed_on_the_pair_itself(signed_in):
    pair = only(add(signed_in))["id"]
    changed = only(signed_in.patch(f"/api/gear/{pair}", json={"applies_to": "walk"}).json())
    assert changed["applies_to"] == "walk"
    # And an edit that says nothing about it leaves it where it was.
    assert only(signed_in.patch(f"/api/gear/{pair}", json={"model": "Road 5"}).json())[
        "applies_to"
    ] == "walk"


# --------------------------------------------------------------------------
# Changing a pair on one activity
# --------------------------------------------------------------------------


def test_any_walk_or_run_can_be_put_in_another_pair(signed_in, db_session, member):
    first = only(add(signed_in))["id"]
    second = add(signed_in, model="Road 5")[1]["id"]
    old = log_workout(db_session, member.id, "run", 5.0)

    row = wear(signed_in, old.id, first).json()
    assert row["gear_id"] == first
    row = wear(signed_in, old.id, second).json()
    assert row["gear_id"] == second
    # And off again, which is the None the picker offers.
    assert wear(signed_in, old.id, None).json()["gear_id"] is None


def test_a_ride_and_a_swim_refuse_shoes(signed_in, db_session, member):
    pair = only(add(signed_in))["id"]
    for offset, activity in enumerate(("cycle", "swim")):
        row = log_workout(db_session, member.id, activity, 5.0, offset_min=offset * 90)
        response = wear(signed_in, row.id, pair)
        assert response.status_code == 400, response.text
        assert response.json()["detail"] == "Shoes go on walks and runs."


def test_somebody_elses_pair_is_the_same_404_as_one_that_does_not_exist(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    theirs = only(add(other_client))["id"]
    run = log_workout(db_session, member.id, "run", 3.0)
    assert wear(signed_in, run.id, theirs).status_code == 404
    assert wear(signed_in, run.id, 9999).status_code == 404


def test_a_retired_pair_takes_nothing_new_and_keeps_what_it_has(signed_in, db_session, member):
    pair = only(add(signed_in))["id"]
    old = log_workout(db_session, member.id, "run", 4.0)
    assert wear(signed_in, old.id, pair).status_code == 200
    signed_in.post(f"/api/gear/{pair}/retire")

    # Still on the workout it was already on, miles and all.
    row = signed_in.get("/api/workouts").json()[0]
    assert row["gear_id"] == pair
    assert only(gear_rows(signed_in))["miles"] == 4.0

    fresh = log_workout(db_session, member.id, "walk", 1.0, offset_min=60)
    response = wear(signed_in, fresh.id, pair)
    assert response.status_code == 400, response.text


# --------------------------------------------------------------------------
# The miles on a pair
# --------------------------------------------------------------------------


def test_the_miles_are_what_it_started_with_plus_what_it_has_covered(
    signed_in, db_session, member
):
    pair = only(add(signed_in, starting_mi=100.0))["id"]
    first = log_workout(db_session, member.id, "run", 6.0)
    second = log_workout(db_session, member.id, "walk", 2.5, offset_min=120)
    # Not this account's shoes' business: a ride covers ground and wears no
    # pair, so its miles are nowhere in the number below.
    log_workout(db_session, member.id, "cycle", 20.0, offset_min=240)
    wear(signed_in, first.id, pair)
    wear(signed_in, second.id, pair)

    assert only(gear_rows(signed_in))["miles"] == 108.5


def test_deleting_a_workout_takes_its_miles_off_the_shoe_and_a_restore_brings_them_back(
    signed_in, db_session, member
):
    """Self-healing, with no rebuild hook anywhere: the number is a sum over the
    workouts that are still there."""
    pair = only(add(signed_in, starting_mi=10.0))["id"]
    run = log_workout(db_session, member.id, "run", 4.0)
    wear(signed_in, run.id, pair)
    assert only(gear_rows(signed_in))["miles"] == 14.0

    assert signed_in.delete(f"/api/workouts/{run.id}").status_code == 204
    assert only(gear_rows(signed_in))["miles"] == 10.0

    assert signed_in.post(f"/api/workouts/{run.id}/restore").status_code == 200
    assert only(gear_rows(signed_in))["miles"] == 14.0


def test_the_miles_are_raw_and_never_the_converted_ones(signed_in, db_session, member):
    """A walk is worth less than a run to the level bar and exactly the same to
    a shoe: this is wear, not a score."""
    pair = only(add(signed_in))["id"]
    walk = log_workout(db_session, member.id, "walk", 3.0)
    wear(signed_in, walk.id, pair)
    assert only(gear_rows(signed_in))["miles"] == 3.0


# --------------------------------------------------------------------------
# Deleting versus retiring
# --------------------------------------------------------------------------


def test_a_pair_nothing_was_recorded_in_can_be_deleted(signed_in):
    pair = only(add(signed_in))["id"]
    assert signed_in.delete(f"/api/gear/{pair}").status_code == 204
    assert gear_rows(signed_in) == []


def test_a_pair_on_an_activity_is_refused_and_told_to_retire(signed_in, db_session, member):
    pair = only(add(signed_in))["id"]
    run = log_workout(db_session, member.id, "run", 4.0)
    wear(signed_in, run.id, pair)

    response = signed_in.delete(f"/api/gear/{pair}")
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == (
        "Those are on activities you have recorded. Retire them instead."
    )
    assert len(gear_rows(signed_in)) == 1


def test_a_deleted_workout_still_holds_its_pair_against_deletion(signed_in, db_session, member):
    """A deleted workout can be restored, and it would come back wearing shoes
    that no longer exist."""
    pair = only(add(signed_in))["id"]
    run = log_workout(db_session, member.id, "run", 4.0)
    wear(signed_in, run.id, pair)
    signed_in.delete(f"/api/workouts/{run.id}")

    assert signed_in.delete(f"/api/gear/{pair}").status_code == 400


# --------------------------------------------------------------------------
# Who sees what
# --------------------------------------------------------------------------


def test_a_friend_reads_the_pair_and_its_size(signed_in, db_session, member):
    """Deliberate, and the reason the card exists at all: a friend can read what
    somebody wears."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    pair = only(add(other_client, nickname="Trainers", starting_mi=20.0, replace_around_mi=400))
    other_client.post(f"/api/gear/{pair['id']}/default")

    body = signed_in.get(f"/api/profile/{other.id}").json()
    theirs = only(body["gear"])
    assert theirs["nickname"] == "Trainers"
    assert (theirs["style"], theirs["size"], theirs["width"]) == ("mens", 10.0, "D")
    assert theirs["miles"] == 20.0
    assert theirs["retired"] is False
    # What is only the owner's business does not cross: what the pair started
    # at, when they mean to replace it, and which pair is their default.
    assert (
        set(theirs) & {"starting_mi", "replace_around_mi", "is_default", "applies_to"}
        == set()
    )


def test_a_member_who_is_not_a_friend_reads_no_gear_at_all(signed_in, db_session):
    other, other_client = sign_in(db_session, "stranger")
    add(other_client, nickname="Trainers")
    body = signed_in.get(f"/api/profile/{other.id}").json()
    assert body["restricted"] is True
    assert "gear" not in body
    assert "Trainers" not in signed_in.get(f"/api/profile/{other.id}").text


def test_a_friends_workout_card_says_nothing_about_gear(signed_in, db_session, member):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    pair = only(add(other_client, nickname="Trainers"))["id"]
    run = log_workout(db_session, other.id, "run", 5.0)
    assert wear(other_client, run.id, pair).status_code == 200

    # Cards carry no gear at all; a friend reads the Shoes card instead.
    row = signed_in.get("/api/feed").json()[0]
    assert "gear" not in row
    # And the id is the owner's alone: it only ever fills the owner's picker.
    assert "gear_id" not in row


# --------------------------------------------------------------------------
# The two-lane law
# --------------------------------------------------------------------------


def test_gear_earns_nothing_anywhere(signed_in, db_session, member):
    """The whole of what this round is allowed to move: nothing.

    Every number the game keeps is read either side of recording a pair, making
    it the default, and putting it on a workout, and none of them moves.
    """
    run = log_workout(db_session, member.id, "run", 6.0, kcal=300)
    before = signed_in.get("/api/profile").json()

    pair = only(add(signed_in, starting_mi=400.0))["id"]
    signed_in.post(f"/api/gear/{pair}/default")
    assert wear(signed_in, run.id, pair).status_code == 200

    after = signed_in.get("/api/profile").json()
    for field in (
        "xp",
        "level",
        "xp_into_level",
        "manna",
        "medals",
        "grove",
        "item_tallies",
        "lifetime",
        "week",
        "streak_weeks",
        "next_chest",
    ):
        assert after[field] == before[field], field
    # And the four hundred miles it started with are in no total anywhere.
    assert "400" not in str(after["lifetime"])


def test_a_workout_outlives_the_pair_it_was_done_in(signed_in, db_session, member):
    """A shoe going away is never a workout going away.

    Postgres says so with ON DELETE SET NULL. The test database does not enforce
    foreign keys at all, so what is asserted here is the app's own reading: the
    workout is still whole and its card simply says nothing about shoes.
    """
    pair = only(add(signed_in))["id"]
    run = log_workout(db_session, member.id, "run", 4.0)
    wear(signed_in, run.id, pair)

    db_session.delete(db_session.get(models.Gear, pair))
    db_session.commit()
    db_session.expire_all()

    # The workout is whole. gear_id is not asserted: Postgres nulls it via
    # ON DELETE SET NULL, and the FK-less test database keeps the dead id.
    row = only(signed_in.get("/api/workouts").json())
    assert row["workout_id"] == run.id
    assert row["distance_mi"] == 4.0
