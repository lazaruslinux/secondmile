"""The satchel, the plot, and the oil one friend spends on another.

Every account and every workout here is invented. The anointing cases are the
careful ones: what matters about oil is as much what the recipient is never
told as what they eventually get, so the silence is asserted against whole
responses rather than against one field.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import models, progress, security, species
from app.config import WATER_POUR_MI
from app.main import app as fastapi_app
from conftest import log_workout, make_user


def sign_in(db_session, username: str) -> tuple[models.User, TestClient]:
    """A second account with a cookie jar of its own."""
    password = f"{username}-password-1"
    user = make_user(db_session, username, password)
    client = TestClient(fastapi_app)
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 204, response.text
    return user, client


def befriend(db_session, first: models.User, second: models.User) -> None:
    db_session.add(
        models.Friendship(
            requester_id=first.id,
            addressee_id=second.id,
            status="accepted",
            created_at=security.now_utc(),
        )
    )
    db_session.commit()


def give_item(db_session, user_id: int, kind: str, species_id: str | None = None, rarity="common"):
    row = models.SatchelItem(
        user_id=user_id,
        kind=kind,
        species=species_id,
        rarity=rarity,
        chest_id=None,
        acquired_at=security.now_utc(),
        used_at=None,
    )
    db_session.add(row)
    db_session.commit()
    return row


def give_planting(db_session, user_id: int, species_id="strawberry", *, growth=0.0, days_ago=1):
    row = models.Planting(
        user_id=user_id,
        species=species_id,
        rarity=species.BY_ID[species_id].rarity,
        planted_at=security.now_utc() - dt.timedelta(days=days_ago),
        growth_mi=growth,
        matured_at=None,
    )
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def mate(client, db_session) -> tuple[models.User, TestClient]:
    return sign_in(db_session, "mate")


# --------------------------------------------------------------------------
# The satchel and its three verbs
# --------------------------------------------------------------------------


def test_the_satchel_lists_what_is_waiting_and_nothing_spent(signed_in, db_session, member):
    give_item(db_session, member.id, "seed", "olive", rarity="rare")
    spent = give_item(db_session, member.id, "water")
    spent.used_at = security.now_utc()
    db_session.commit()

    rows = signed_in.get("/api/satchel").json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "seed"
    assert rows[0]["species"] == "olive"
    # The satchel says the seed; what it becomes rides along for the plot.
    assert rows[0]["seed_name"] == "Olive seed"
    assert rows[0]["plant_name"] == "Olive tree"
    assert rows[0]["rarity"] == "rare"


def test_water_carries_no_species(signed_in, db_session, member):
    give_item(db_session, member.id, "water", rarity="uncommon")
    row = signed_in.get("/api/satchel").json()[0]
    assert row["species"] is None
    assert row["seed_name"] is None
    assert row["plant_name"] is None


def test_planting_a_seed_puts_it_in_the_ground(signed_in, db_session, member):
    item = give_item(db_session, member.id, "seed", "fig_bush", rarity="uncommon")
    body = signed_in.post(f"/api/satchel/{item.id}/plant")
    assert body.status_code == 201, body.text
    planting = body.json()
    assert planting["species"] == "fig_bush"
    assert planting["growth_mi"] == 0.0
    assert planting["level"] == 0
    assert planting["level_mi"] == 40.0
    assert planting["stage"] == 1
    assert planting["mature"] is False
    assert planting["gilded"] is False
    assert planting["produce"] == "figs"

    # The seed is spent, and the plot has it.
    assert signed_in.get("/api/satchel").json() == []
    assert [row["id"] for row in signed_in.get("/api/grove").json()] == [planting["id"]]


def test_a_seed_cannot_be_planted_twice(signed_in, db_session, member):
    item = give_item(db_session, member.id, "seed", "blueberry")
    assert signed_in.post(f"/api/satchel/{item.id}/plant").status_code == 201
    assert signed_in.post(f"/api/satchel/{item.id}/plant").status_code == 404
    assert len(signed_in.get("/api/grove").json()) == 1


def test_somebody_elses_item_answers_like_one_that_never_existed(
    signed_in, db_session, admin, member
):
    theirs = give_item(db_session, admin.id, "seed", "blueberry")
    mine = signed_in.post(f"/api/satchel/{theirs.id}/plant")
    missing = signed_in.post("/api/satchel/999999/plant")
    assert mine.status_code == missing.status_code == 404
    assert mine.json() == missing.json()
    assert db_session.get(models.SatchelItem, theirs.id).used_at is None


def test_an_item_only_does_its_own_verb(signed_in, db_session, member, mate):
    other, _ = mate
    befriend(db_session, member, other)
    water = give_item(db_session, member.id, "water")
    planting = give_planting(db_session, member.id)
    assert signed_in.post(f"/api/satchel/{water.id}/plant").status_code == 400
    assert (
        signed_in.post(
            f"/api/satchel/{water.id}/anoint", json={"user_id": other.id}
        ).status_code
        == 400
    )
    seed = give_item(db_session, member.id, "seed", "blueberry")
    assert (
        signed_in.post(
            f"/api/satchel/{seed.id}/pour", json={"planting_id": planting.id}
        ).status_code
        == 400
    )


# --------------------------------------------------------------------------
# Water
# --------------------------------------------------------------------------


def test_pouring_water_grows_one_chosen_planting(signed_in, db_session, member):
    chosen = give_planting(db_session, member.id, "strawberry")
    other = give_planting(db_session, member.id, "raspberry")
    item = give_item(db_session, member.id, "water")

    body = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": chosen.id})
    assert body.status_code == 200, body.text
    assert body.json()["growth_mi"] == WATER_POUR_MI
    assert body.json()["stage"] == 2
    db_session.refresh(other)
    assert other.growth_mi == 0.0
    assert signed_in.get("/api/satchel").json() == []


def test_water_cannot_be_poured_on_a_strangers_plot(signed_in, db_session, admin, member):
    theirs = give_planting(db_session, admin.id)
    item = give_item(db_session, member.id, "water")
    stranger = signed_in.post(
        f"/api/satchel/{item.id}/pour", json={"planting_id": theirs.id}
    )
    missing = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": 999999})
    assert stranger.status_code == missing.status_code == 404
    assert stranger.json() == missing.json()
    assert db_session.get(models.SatchelItem, item.id).used_at is None


def test_watering_a_friends_plot_grows_it_and_pays_the_giver(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "grapevine")
    item = give_item(db_session, member.id, "water")

    body = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": theirs.id})
    assert body.status_code == 200, body.text
    # Answered in the shape a friend's plot is allowed to be seen in.
    assert set(body.json()) == {
        "id",
        "species",
        "seed_name",
        "plant_name",
        "rarity",
        "growth",
        "stage",
        "mature",
        "gilded",
    }
    db_session.refresh(theirs)
    assert theirs.growth_mi == WATER_POUR_MI

    # Renown to whoever poured it, and none to whoever it grew for.
    assert db_session.get(models.UserProgress, member.id).renown == 5
    assert db_session.get(models.UserProgress, other.id) is None or (
        db_session.get(models.UserProgress, other.id).renown == 0
    )
    spent = db_session.get(models.SatchelItem, item.id)
    assert (spent.given_to_user_id, spent.earned_renown) == (other.id, True)


def test_a_second_pour_on_the_same_friend_still_grows_but_earns_nothing(
    signed_in, db_session, member, mate
):
    other, _ = mate
    befriend(db_session, member, other)
    first = give_planting(db_session, other.id, "grapevine")
    second = give_planting(db_session, other.id, "olive")
    for item, target in (
        (give_item(db_session, member.id, "water"), first),
        (give_item(db_session, member.id, "water"), second),
    ):
        assert (
            signed_in.post(
                f"/api/satchel/{item.id}/pour", json={"planting_id": target.id}
            ).status_code
            == 200
        )
    db_session.refresh(second)
    # The water still landed; only the renown diminished.
    assert second.growth_mi == WATER_POUR_MI
    assert db_session.get(models.UserProgress, member.id).renown == 5

    # A pour from outside the window earns again.
    stale = (
        db_session.query(models.SatchelItem)
        .filter(models.SatchelItem.earned_renown.is_(True))
        .one()
    )
    stale.used_at = security.now_utc() - dt.timedelta(days=8)
    db_session.commit()
    third = give_item(db_session, member.id, "water")
    signed_in.post(f"/api/satchel/{third.id}/pour", json={"planting_id": second.id})
    assert db_session.get(models.UserProgress, member.id).renown == 10


def test_a_friends_finished_plant_refuses_water_too(signed_in, db_session, member, mate):
    other, _ = mate
    befriend(db_session, member, other)
    done = give_planting(db_session, other.id, "blueberry", growth=15.0 * species.MAX_LEVEL)
    item = give_item(db_session, member.id, "water")
    refused = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": done.id})
    assert refused.status_code == 400
    assert "nothing left to grow" in refused.json()["detail"]
    assert db_session.get(models.SatchelItem, item.id).used_at is None


def test_water_is_refused_on_something_gilded(signed_in, db_session, member):
    done = give_planting(db_session, member.id, "strawberry", growth=15.0 * species.MAX_LEVEL)
    item = give_item(db_session, member.id, "water")
    refused = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": done.id})
    assert refused.status_code == 400
    assert "nothing left to grow" in refused.json()["detail"]
    # And the water is still in the satchel rather than wasted.
    assert len(signed_in.get("/api/satchel").json()) == 1


def test_a_grown_plant_still_takes_water_toward_its_next_level(signed_in, db_session, member):
    grown = give_planting(db_session, member.id, "strawberry", growth=15.0)
    item = give_item(db_session, member.id, "water")
    body = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": grown.id})
    assert body.status_code == 200, body.text
    # Mature is not finished: the water counts toward level two.
    assert body.json()["mature"] is True
    assert body.json()["gilded"] is False
    assert body.json()["growth_mi"] == 15.0 + WATER_POUR_MI
    assert body.json()["level"] == 1


# --------------------------------------------------------------------------
# Growth
# --------------------------------------------------------------------------


def test_every_planting_grows_from_every_workout(signed_in, db_session, member):
    first = give_planting(db_session, member.id, "strawberry")
    second = give_planting(db_session, member.id, "olive")
    log_workout(signed_in, "run", 4.0, offset_min=0)
    log_workout(signed_in, "cycle", 9.0, pace_min=4, offset_min=200)

    rows = {row["id"]: row for row in signed_in.get("/api/grove").json()}
    # Four run miles and nine cycled ones are seven Miles, into both of them.
    assert rows[first.id]["growth_mi"] == 7.0
    assert rows[second.id]["growth_mi"] == 7.0
    assert rows[first.id]["growth"] == pytest.approx(7.0 / 15.0, abs=1e-3)
    assert rows[second.id]["growth"] == pytest.approx(7.0 / 100.0, abs=1e-3)


def test_swimming_brings_extra_water(signed_in, db_session, member):
    planting = give_planting(db_session, member.id, "grapevine")
    # Two swum miles are eight converted Miles, and a swim adds half again.
    log_workout(signed_in, "swim", 2.0, pace_min=30)
    row = signed_in.get("/api/grove").json()[0]
    assert row["growth_mi"] == 12.0
    assert db_session.get(models.UserProgress, member.id).xp == 8.0
    assert planting.id == row["id"]


def test_a_planting_comes_of_age_at_its_own_threshold(signed_in, db_session, member):
    quick = give_planting(db_session, member.id, "blueberry")
    slow = give_planting(db_session, member.id, "olive")
    log_workout(signed_in, "run", 20.0, pace_min=9)

    rows = {row["id"]: row for row in signed_in.get("/api/grove").json()}
    # Fifteen Miles is level one, which is grown, and the five over count
    # toward level two.
    assert rows[quick.id]["level"] == 1
    assert rows[quick.id]["mature"] is True
    assert rows[quick.id]["gilded"] is False
    assert rows[quick.id]["stage"] == 3
    assert rows[quick.id]["matured_at"] is not None
    assert rows[quick.id]["growth"] == pytest.approx(5.0 / 15.0, abs=1e-3)
    # The tree needs a hundred, so the same twenty Miles leave it a seedling.
    assert rows[slow.id]["level"] == 0
    assert rows[slow.id]["mature"] is False
    assert rows[slow.id]["stage"] == 1
    assert rows[slow.id]["growth_mi"] == 20.0


@pytest.mark.parametrize(
    ("species_id", "step"),
    [("strawberry", 15.0), ("grapevine", 40.0), ("olive", 100.0), ("mustard", 100.0)],
)
@pytest.mark.parametrize("level", [0, 1, 2, 7])
def test_a_level_costs_what_its_rarity_costs(signed_in, db_session, member, species_id, step, level):
    give_planting(db_session, member.id, species_id, growth=step * level + step / 2)
    row = signed_in.get("/api/grove").json()[0]
    assert row["level"] == level
    assert row["level_mi"] == step
    # Level one is grown, and nothing here is anywhere near the last level.
    assert row["mature"] is (level >= 1)
    assert row["gilded"] is False
    # The bar reads the way through the level it is in, not a lifetime.
    assert row["growth"] == pytest.approx(0.5, abs=1e-4)


def test_the_level_stops_at_thirty_three_and_the_miles_do_not(signed_in, db_session, member):
    give_planting(db_session, member.id, "strawberry", growth=5000.0)
    row = signed_in.get("/api/grove").json()[0]
    # Five thousand Miles is three hundred levels of a common bush, and the
    # level it shows is the last one there is.
    assert row["level"] == 33
    assert row["gilded"] is True
    assert row["mature"] is True
    assert row["stage"] == 3
    # The bookkeeping keeps the miles, and the bar is simply full.
    assert row["growth_mi"] == 5000.0
    assert row["growth"] == 1.0


@pytest.mark.parametrize(
    ("grown_mi", "gilded"), [(3200.0, False), (3299.9, False), (3300.0, True), (9000.0, True)]
)
def test_a_rare_tree_gilds_at_thirty_three_levels(signed_in, db_session, member, grown_mi, gilded):
    give_planting(db_session, member.id, "pomegranate", growth=grown_mi)
    row = signed_in.get("/api/grove").json()[0]
    assert row["gilded"] is gilded
    assert row["level"] == (33 if gilded else 32)


def test_a_levelled_mustard_tree_still_takes_water(signed_in, db_session, member):
    grown = give_planting(db_session, member.id, "mustard", growth=250.0)
    item = give_item(db_session, member.id, "water")
    body = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": grown.id})
    assert body.status_code == 200, body.text
    assert body.json()["growth_mi"] == 250.0 + WATER_POUR_MI
    assert body.json()["level"] == 2


def test_a_planting_says_the_same_things_whatever_it_is(signed_in, db_session, member):
    give_planting(db_session, member.id, "olive", growth=50.0)
    row = signed_in.get("/api/grove").json()[0]
    assert set(row) == {
        "id",
        "species",
        "seed_name",
        "plant_name",
        "rarity",
        "planted_at",
        "growth_mi",
        "growth",
        "stage",
        "level",
        "level_mi",
        "mature",
        "gilded",
        "matured_at",
        "produce",
    }
    # Every species levels, so none of them answers with a null here.
    assert (row["level"], row["level_mi"]) == (0, 100.0)


def test_the_catalogue_is_four_of_each_and_the_one_that_is_given():
    by_rarity: dict[str, list[str]] = {"common": [], "uncommon": [], "rare": []}
    for row in species.BY_ID.values():
        by_rarity[row.rarity].append(row.id)
    assert sorted(by_rarity["common"]) == [
        "banana",
        "blueberry",
        "raspberry",
        "strawberry",
    ]
    assert sorted(by_rarity["uncommon"]) == ["blackberry", "fig_bush", "grapevine", "mango"]
    assert sorted(by_rarity["rare"]) == [
        "coffee",
        "dates",
        "mustard",
        "olive",
        "pomegranate",
    ]
    # Four to a slot, twelve in all, and the mustard tree outside the count.
    assert [len(species.BY_RARITY[rarity]) for rarity in species.RARITIES] == [4, 4, 4]
    assert len(species.BY_ID) == 13


def test_the_ones_he_named_are_where_he_put_them():
    assert species.BY_ID["coffee"].rarity == "rare"
    assert species.BY_ID["banana"].rarity == "common"
    assert species.BY_ID["mango"].rarity == "uncommon"


def test_every_species_names_its_own_harvest():
    assert all(row.produce.strip() for row in species.BY_ID.values())
    assert species.BY_ID["coffee"].produce == "coffee cherries"
    assert species.BY_ID["dates"].produce == "dates"


def test_the_level_ladder_is_by_rarity():
    assert {row.level_mi for row in species.BY_RARITY["common"]} == {15.0}
    assert {row.level_mi for row in species.BY_RARITY["uncommon"]} == {40.0}
    assert {row.level_mi for row in species.BY_RARITY["rare"]} == {100.0}
    # Nothing in the catalogue disagrees with its own rarity.
    assert all(row.level_mi == species.LEVEL_MI[row.rarity] for row in species.BY_ID.values())


def test_the_mustard_tree_levels_like_a_rare_and_is_never_rolled():
    mustard = species.BY_ID["mustard"]
    assert mustard.level_mi == 100.0
    # A rare like any other to a chest, and never in the bag it rolls from.
    assert mustard.rarity == "rare"
    assert "mustard" not in {row.id for row in species.BY_RARITY["rare"]}


def test_only_the_mustard_seed_explains_anything_about_itself():
    assert species.BY_ID["mustard"].reveal == "You will only ever receive one."
    assert [row.id for row in species.BY_ID.values() if row.reveal] == ["mustard"]


def test_nothing_planted_after_a_workout_grows_from_it(signed_in, db_session, member):
    log_workout(signed_in, "run", 5.0)
    later = give_planting(db_session, member.id, "blueberry", days_ago=0)
    assert signed_in.get("/api/grove").json()[0]["growth_mi"] == 0.0
    assert later.growth_mi == 0.0


def test_a_rebuild_replays_growth_and_touches_nothing_chosen(signed_in, db_session, member):
    planting = give_planting(db_session, member.id, "blackberry")
    log_workout(signed_in, "run", 12.0, pace_min=9)
    water = give_item(db_session, member.id, "water")
    signed_in.post(f"/api/satchel/{water.id}/pour", json={"planting_id": planting.id})
    before = signed_in.get("/api/grove").json()[0]
    assert before["growth_mi"] == 22.0

    progress.recompute(db_session, member.id)
    after = signed_in.get("/api/grove").json()[0]
    # The miles come back; the poured water does not, because it was spent.
    assert after["growth_mi"] == 12.0
    assert after["id"] == before["id"]
    # The item stays spent: what somebody did with it is not derived from
    # anything and is never replayed.
    assert db_session.get(models.SatchelItem, water.id).used_at is not None


# --------------------------------------------------------------------------
# A friend's plot
# --------------------------------------------------------------------------


def test_a_friend_sees_the_plants_and_not_one_number(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "pomegranate", growth=50.0)

    rows = other_client.get(f"/api/grove/{member.id}").json()
    assert len(rows) == 1
    # Enough to pick one and water it, and no miles and no dates behind that.
    assert set(rows[0]) == {
        "id",
        "species",
        "seed_name",
        "plant_name",
        "rarity",
        "growth",
        "stage",
        "mature",
        "gilded",
    }
    assert rows[0]["species"] == "pomegranate"
    assert rows[0]["stage"] == 2
    assert rows[0]["growth"] == 0.5
    assert rows[0]["mature"] is False
    assert rows[0]["gilded"] is False


def test_a_friend_sees_that_a_plant_is_finished(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "olive", growth=100.0 * species.MAX_LEVEL)
    row = other_client.get(f"/api/grove/{member.id}").json()[0]
    # Enough to know there is no point pouring water into it, and no numbers.
    assert (row["gilded"], row["mature"], row["stage"]) == (True, True, 3)
    assert "level" not in row and "growth_mi" not in row


def test_a_stranger_sees_nothing_of_somebody_elses_plot(signed_in, db_session, member, mate):
    other, other_client = mate
    give_planting(db_session, member.id, "olive")
    assert other_client.get(f"/api/grove/{member.id}").status_code == 404


def test_the_profile_counts_what_was_found_and_the_levels_it_grew(
    signed_in, db_session, member
):
    give_planting(db_session, member.id, "blueberry", growth=15.0).matured_at = security.now_utc()
    give_planting(db_session, member.id, "olive", growth=250.0)
    # A seed nobody has planted yet is still one of the twelve, found.
    give_item(db_session, member.id, "seed", "mango", rarity="uncommon")
    db_session.commit()
    # One level of a common and two of a rare, and three species between the
    # ground and the satchel.
    assert signed_in.get("/api/profile").json()["grove"] == {
        "seeds_found": 3,
        "plant_levels": 3,
    }


def test_the_mustard_tree_is_outside_the_twelve_and_inside_the_levels(
    signed_in, db_session, member
):
    """It was given rather than found, so it counts toward nothing that could
    be read as a collection, and toward everything that cannot."""
    give_planting(db_session, member.id, "mustard", growth=250.0)
    assert signed_in.get("/api/profile").json()["grove"] == {
        "seeds_found": 0,
        "plant_levels": 2,
    }

    # An unplanted one is left out of the count for the same reason.
    give_item(db_session, member.id, "seed", "mustard", rarity="rare")
    give_planting(db_session, member.id, "strawberry", growth=45.0)
    assert signed_in.get("/api/profile").json()["grove"] == {
        "seeds_found": 1,
        "plant_levels": 5,
    }


def test_a_whole_plot_counts_twelve_and_never_thirteen(signed_in, db_session, member):
    for row in species.BY_ID.values():
        give_planting(db_session, member.id, row.id)
    body = signed_in.get("/api/profile").json()["grove"]
    # Thirteen things in the ground, twelve of them found.
    assert body["seeds_found"] == 12
    assert body["plant_levels"] == 0


def test_the_level_sum_counts_the_level_a_plant_shows(signed_in, db_session, member):
    """Capped, like the plot itself is: the miles keep counting past the last
    level and the number the profile adds up is the one on the plant."""
    give_planting(db_session, member.id, "strawberry", growth=5000.0)
    assert signed_in.get("/api/profile").json()["grove"]["plant_levels"] == 33


# --------------------------------------------------------------------------
# Oil
# --------------------------------------------------------------------------


def test_anointing_says_nothing_to_anybody_until_the_chest_lands(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")

    assert (
        signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id}).status_code
        == 204
    )
    # The oil is spent, and the giver is told nothing more than that.
    assert signed_in.get("/api/satchel").json() == []

    # Nothing the recipient can read has changed in any way.
    for path in ("/api/profile", "/api/recap", "/api/chests", "/api/satchel", "/api/feed"):
        body = other_client.get(path).text
        assert "anoint" not in body.lower(), path
        assert member.username not in body, path
    assert other_client.get("/api/chests").json() == []


def test_the_bonus_chest_lands_on_the_next_workout_without_costing_miles(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    # The recipient is partway up the ladder already.
    log_workout(other_client, "run", 4.0, offset_min=0)
    before = db_session.get(models.UserProgress, other.id)
    assert (before.cycle_pos, round(before.chest_progress_mi, 2)) == (1, 0.9)

    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})
    log_workout(other_client, "run", 1.0, offset_min=200)

    after = db_session.get(models.UserProgress, other.id)
    # One mile of credit, and the cycle is exactly where the mile put it: the
    # gift did not move it along.
    assert after.cycle_pos == 1
    assert round(after.chest_progress_mi, 2) == 1.9
    # The 5K chest the four miles earned, and the one that was given.
    waiting = other_client.get("/api/chests").json()
    assert [row["tier_id"] for row in waiting] == ["5k", "10k"]
    # At the tier the recipient is working toward, not the giver's, and it
    # looks like any other chest until the letter says otherwise.
    assert set(waiting[1]) == {"id", "dropped_at", "tier", "tier_id"}

    row = db_session.get(models.Anointing, 1)
    assert row.consumed_at is not None
    assert row.consumed_chest_id == waiting[1]["id"]


def test_the_letter_is_where_the_gift_is_finally_attributed(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})
    log_workout(other_client, "run", 4.0)

    letter = other_client.get("/api/recap").json()
    gifts = [row for row in letter["chests"] if row["from_username"]]
    assert len(gifts) == 1
    assert gifts[0]["from_username"] == member.username
    # The chest the miles earned is still nobody's gift.
    assert any(row["from_username"] is None for row in letter["chests"])
    # And the letter still reads in the order it always has.
    assert list(letter) == [
        "since",
        "miles",
        "encouragement",
        "medals",
        "chests",
        "flourish_stage",
        "flourish_rose",
    ]


def test_anointing_pays_the_giver_and_diminishes_like_everything_else(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    first = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{first.id}/anoint", json={"user_id": other.id})
    assert db_session.get(models.UserProgress, member.id).renown == 8
    spent = db_session.get(models.SatchelItem, first.id)
    assert (spent.given_to_user_id, spent.earned_renown) == (other.id, True)

    # The gift lands, and a second one on the same friend inside the window
    # arrives all the same and pays nothing.
    log_workout(other_client, "run", 1.0, offset_min=0)
    second = give_item(db_session, member.id, "oil", rarity="rare")
    assert (
        signed_in.post(f"/api/satchel/{second.id}/anoint", json={"user_id": other.id}).status_code
        == 204
    )
    assert db_session.get(models.UserProgress, member.id).renown == 8


def test_only_one_anointing_can_wait_on_the_same_friend(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    first = give_item(db_session, member.id, "oil", rarity="rare")
    second = give_item(db_session, member.id, "oil", rarity="rare")

    assert (
        signed_in.post(f"/api/satchel/{first.id}/anoint", json={"user_id": other.id}).status_code
        == 204
    )
    again = signed_in.post(f"/api/satchel/{second.id}/anoint", json={"user_id": other.id})
    assert again.status_code == 409
    # The refused oil is still in the satchel.
    assert [row["id"] for row in signed_in.get("/api/satchel").json()] == [second.id]

    # Once the first has landed, the same pair can give again.
    log_workout(other_client, "run", 1.0)
    assert (
        signed_in.post(f"/api/satchel/{second.id}/anoint", json={"user_id": other.id}).status_code
        == 204
    )


def test_oil_is_for_somebody_else_and_only_for_a_friend(signed_in, db_session, member, mate):
    other, _ = mate
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    mine = signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": member.id})
    assert mine.status_code == 400

    # A stranger and an account that does not exist answer identically.
    stranger = signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})
    missing = signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": 999999})
    assert stranger.status_code == missing.status_code == 404
    assert stranger.json() == missing.json()
    assert db_session.get(models.SatchelItem, oil.id).used_at is None


def test_a_rebuild_keeps_a_chest_somebody_gave(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})
    log_workout(other_client, "run", 4.0)
    assert len(other_client.get("/api/chests").json()) == 2

    progress.recompute(db_session, other.id)
    left = other_client.get("/api/chests").json()
    # The earned chest is rebuilt and the gift is simply left alone.
    assert len(left) == 2
    assert db_session.get(models.Anointing, 1).consumed_at is not None


def test_the_grove_endpoints_need_a_session(client):
    assert client.get("/api/satchel").status_code == 401
    assert client.get("/api/grove").status_code == 401
    assert client.post("/api/satchel/1/plant").status_code == 401
    assert client.post("/api/satchel/1/pour", json={"planting_id": 1}).status_code == 401
    assert client.post("/api/satchel/1/anoint", json={"user_id": 1}).status_code == 401


# --------------------------------------------------------------------------
# What each species is called, as a seed and as the thing it becomes
# --------------------------------------------------------------------------

# His catalogue, both names, written out rather than derived: the whole point of
# the pair is that the planted form is not the seed name with a word swapped.
NAMES = {
    "strawberry": ("Strawberry seed", "Strawberry bush"),
    "banana": ("Banana seed", "Banana tree"),
    "raspberry": ("Raspberry seed", "Raspberry bush"),
    "blueberry": ("Blueberry seed", "Blueberry bush"),
    "blackberry": ("Blackberry seed", "Blackberry bush"),
    "mango": ("Mango seed", "Mango tree"),
    "grapevine": ("Grape seed", "Grapevine"),
    "fig_bush": ("Fig seed", "Fig bush"),
    "olive": ("Olive seed", "Olive tree"),
    "dates": ("Date seed", "Date palm"),
    "coffee": ("Coffee seed", "Coffee plant"),
    "pomegranate": ("Pomegranate seed", "Pomegranate tree"),
    "mustard": ("Mustard seed", "Mustard"),
}


def test_every_species_has_both_names():
    assert set(species.BY_ID) == set(NAMES)
    for species_id, (seed_name, plant_name) in NAMES.items():
        row = species.BY_ID[species_id]
        assert (row.seed_name, row.plant_name) == (seed_name, plant_name), species_id


def test_the_satchel_says_the_seed_and_the_plot_says_the_plant(signed_in, db_session, member):
    item = give_item(db_session, member.id, "seed", "dates", rarity="rare")
    listed = signed_in.get("/api/satchel").json()[0]
    assert listed["seed_name"] == "Date seed"

    planted = signed_in.post(f"/api/satchel/{item.id}/plant").json()
    assert planted["plant_name"] == "Date palm"
    assert planted["seed_name"] == "Date seed"


def test_a_friends_plot_says_the_planted_form_too(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "coffee")
    row = other_client.get(f"/api/grove/{member.id}").json()[0]
    assert (row["seed_name"], row["plant_name"]) == ("Coffee seed", "Coffee plant")
