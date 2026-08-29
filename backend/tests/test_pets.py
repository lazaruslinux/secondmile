"""Pets: what the harvest draws, what fruit is fed to, and what it is worth.

The law this file pins, in one sentence: a pet is presence and nothing else.
Feeding one moves no experience, no level, no chest, no medal, no manna and no
yield, and the two lanes on either side of it are untouched by everything here.

Nothing counts down anywhere in it. There is no case about a pet starving, going
hungry or leaving, because there is no such thing: an unfed pet is resting.
"""

import datetime as dt
import random

import pytest

from conftest import give_planting, let_a_moment_pass, log_workout, make_user
from test_fruit import renown_of, run_miles, stock_manna
from test_grove import befriend, sign_in

from app import models, pets, security
from app.config import FRUIT_SEASON_MI, PET_STAGE_FRUIT, PET_WEIGHT_CAP

SECOND, THIRD = PET_STAGE_FRUIT


# --------------------------------------------------------------------------
# Shorthands
# --------------------------------------------------------------------------


def gather(client) -> dict:
    response = client.post("/api/harvest/gather")
    assert response.status_code == 200, response.text
    return response.json()


def harvest_state(client) -> dict:
    response = client.get("/api/harvest")
    assert response.status_code == 200, response.text
    return response.json()


def a_grove_that_bears(db_session, user_id: int, *, offset_min: int = 0) -> None:
    """One grown plant and enough miles to bring its season round."""
    give_planting(db_session, user_id, "strawberry", growth=15.0)
    run_miles(db_session, user_id, FRUIT_SEASON_MI, offset_min=offset_min)


def give_basket(
    db_session,
    user_id: int,
    count: int,
    *,
    golden: bool = False,
    minutes_ago: int = 0,
    species_id: str = "banana",
) -> models.FruitBatch:
    """Fruit already in the basket, gathered this long ago.

    Written in rather than grown, because these cases are about what feeding
    takes and in what order, not about how a grove comes round.
    """
    gathered = security.now_utc() - dt.timedelta(minutes=minutes_ago)
    row = models.FruitBatch(
        user_id=user_id,
        planting_id=None,
        species=species_id,
        golden=golden,
        count=count,
        borne_count=count,
        season=1,
        season_mi=FRUIT_SEASON_MI,
        season_month="April",
        borne_at=gathered - dt.timedelta(minutes=1),
        gathered_at=gathered,
    )
    db_session.add(row)
    db_session.commit()
    return row


def give_pet(db_session, user_id: int, species: str, *, fruit_fed: int = 0, grown: bool = False):
    now = security.now_utc()
    row = models.Pet(
        user_id=user_id,
        species=species,
        stage=3 if grown else pets.stage_for(fruit_fed),
        fruit_fed=THIRD if grown else fruit_fed,
        arrived_at=now,
        staged_at=now if grown else None,
        grown_at=now if grown else None,
    )
    db_session.add(row)
    db_session.commit()
    return row


def earn_time_medal(db_session, user_id: int, badge_id: str, times: int) -> None:
    """Time medals on the board, written straight in.

    The rules that award them are the medal file's own business and are pinned
    there; what is being checked here is that the draw reads the count.
    """
    for index in range(times):
        db_session.add(
            models.BadgeEarn(
                user_id=user_id,
                badge_id=badge_id,
                workout_id=1000 + index,
                earned_at=security.now_utc(),
            )
        )
    db_session.commit()


def pet_rows(db_session, user_id: int) -> list[models.Pet]:
    db_session.expire_all()
    return pets.owned(db_session, user_id)


def feed(client, count: int = 1):
    return client.post("/api/pets/feed", json={"count": count})


# --------------------------------------------------------------------------
# Arrival
# --------------------------------------------------------------------------


def test_the_first_harvest_draws_a_stray(signed_in, db_session, member):
    """His shape: a pet is found by the harvest rather than chosen, so the first
    gather anybody makes always draws one."""
    a_grove_that_bears(db_session, member.id)
    assert pet_rows(db_session, member.id) == []

    body = gather(signed_in)
    drawn = pet_rows(db_session, member.id)
    assert len(drawn) == 1
    assert drawn[0].species in pets.SPECIES
    assert (drawn[0].stage, drawn[0].fruit_fed, drawn[0].grown_at) == (1, 0, None)
    assert body["pets"][0]["species"] == drawn[0].species


def test_nothing_new_arrives_while_one_is_still_growing(signed_in, db_session, member):
    """One at a time, which is what makes feeding unambiguous and what stops a
    grove filling up in an afternoon."""
    a_grove_that_bears(db_session, member.id)
    gather(signed_in)
    first = pet_rows(db_session, member.id)[0].species

    a_grove_that_bears(db_session, member.id, offset_min=200)
    gather(signed_in)
    assert [row.species for row in pet_rows(db_session, member.id)] == [first]


def test_a_grown_pet_lets_the_next_stray_in(signed_in, db_session, member):
    """A grown pet is a permanent resident rather than a slot held open, so the
    grove is open to the next arrival the moment it finishes growing."""
    give_pet(db_session, member.id, "wolf", grown=True)
    a_grove_that_bears(db_session, member.id)
    gather(signed_in)

    held = pet_rows(db_session, member.id)
    assert len(held) == 2
    assert {row.species for row in held} > {"wolf"}


def test_the_draw_leans_on_the_time_medals(db_session, member):
    """His split, verbatim: many Night Owl badges lean it toward a bat, a cat or
    a wolf, and many Early Riser badges toward a dog, a sheep or a rooster."""
    earn_time_medal(db_session, member.id, "night_owl", 4)
    earn_time_medal(db_session, member.id, "early_riser", 1)

    assert pets.arrival_weights(db_session, member.id) == {
        "bat": 5,
        "cat": 5,
        "wolf": 5,
        "dog": 2,
        "sheep": 2,
        "rooster": 2,
    }


def test_the_lean_is_capped_and_never_a_gate(db_session, member):
    """A thousand early mornings lean the draw rather than settling it: the cap
    holds, and every species is still worth at least one."""
    earn_time_medal(db_session, member.id, "early_riser", PET_WEIGHT_CAP + 50)
    weights = pets.arrival_weights(db_session, member.id)

    assert weights["dog"] == 1 + PET_WEIGHT_CAP
    assert weights["bat"] == 1
    assert min(weights.values()) >= 1


def test_a_grove_with_no_medals_draws_evenly(db_session, member):
    assert pets.arrival_weights(db_session, member.id) == dict.fromkeys(pets.SPECIES, 1)


def test_a_species_already_in_the_grove_is_not_in_the_bag(db_session, member):
    """The whole of the no-duplicate rule: an owned species is not rolled and
    re-rolled, it is simply not a candidate. A half-grown one counts too."""
    give_pet(db_session, member.id, "wolf", grown=True)
    give_pet(db_session, member.id, "dog", fruit_fed=5)

    weights = pets.arrival_weights(db_session, member.id)
    assert set(weights) == {"bat", "cat", "sheep", "rooster"}


def test_all_six_owned_is_the_end_of_the_arrivals(signed_in, db_session, member):
    for species in pets.SPECIES:
        give_pet(db_session, member.id, species, grown=True)
    assert pets.arrival_weights(db_session, member.id) == {}
    assert pets.roll_arrival(random.Random("anything"), {}) is None

    a_grove_that_bears(db_session, member.id)
    gather(signed_in)
    assert len(pet_rows(db_session, member.id)) == 6


def test_a_leaned_draw_can_still_land_anywhere(db_session, member):
    """Weights are never gates. Over a spread of seeds the heavy half wins more
    often and the light half still wins, which is the difference between a lean
    and a lock."""
    weights = {"bat": 10, "cat": 10, "wolf": 10, "dog": 1, "sheep": 1, "rooster": 1}
    drawn = [pets.roll_arrival(random.Random(f"seed:{index}"), weights) for index in range(400)]

    assert set(drawn) == set(weights)
    night = sum(1 for one in drawn if one in {"bat", "cat", "wolf"})
    assert night > len(drawn) / 2


def test_the_same_grove_and_the_same_harvest_draw_the_same_stray(db_session, member):
    """Seeded on the account and on how full the grove is, the way a chest's
    roll is seeded, so a replay agrees with itself."""
    weights = pets.arrival_weights(db_session, member.id)
    first = pets.roll_arrival(random.Random(f"{member.id}:pet:0"), weights)
    again = pets.roll_arrival(random.Random(f"{member.id}:pet:0"), weights)
    assert first == again


# --------------------------------------------------------------------------
# Feeding
# --------------------------------------------------------------------------


def test_feeding_eats_the_oldest_gathered_fruit_first(signed_in, db_session, member):
    """The kindness rule: whatever is closest to going back to the soil is eaten
    first, so feeding never costs somebody the batch they were about to lose."""
    give_pet(db_session, member.id, "cat")
    old = give_basket(db_session, member.id, 3, minutes_ago=600)
    new = give_basket(db_session, member.id, 3, minutes_ago=5)

    assert feed(signed_in, 4).status_code == 200
    db_session.expire_all()
    assert db_session.get(models.FruitBatch, old.id).count == 0
    assert db_session.get(models.FruitBatch, new.id).count == 2


def test_a_batch_eaten_to_nothing_leaves_the_basket(signed_in, db_session, member):
    give_pet(db_session, member.id, "cat")
    give_basket(db_session, member.id, 2, minutes_ago=600)
    kept = give_basket(db_session, member.id, 2, minutes_ago=5)

    feed(signed_in, 3)
    basket = harvest_state(signed_in)["basket"]
    assert [row["id"] for row in basket] == [kept.id]
    assert basket[0]["count"] == 1
    assert basket[0]["label"] == "1 banana"


def test_any_fruit_is_worth_exactly_one(signed_in, db_session, member):
    give_pet(db_session, member.id, "cat")
    give_basket(db_session, member.id, 2, species_id="olive")
    give_basket(db_session, member.id, 3, species_id="strawberry", minutes_ago=1)

    body = feed(signed_in, 5).json()
    assert body["pet"]["fruit_fed"] == 5


def test_feeding_crosses_the_stages_and_stamps_the_growing(signed_in, db_session, member):
    pet = give_pet(db_session, member.id, "sheep")
    give_basket(db_session, member.id, THIRD)

    first = feed(signed_in, SECOND).json()["pet"]
    assert (first["stage"], first["grown"]) == (2, False)
    db_session.expire_all()
    assert db_session.get(models.Pet, pet.id).staged_at is not None
    assert db_session.get(models.Pet, pet.id).grown_at is None

    second = feed(signed_in, THIRD - SECOND).json()["pet"]
    assert (second["stage"], second["grown"]) == (3, True)
    db_session.expire_all()
    assert db_session.get(models.Pet, pet.id).grown_at is not None


def test_one_short_of_a_stage_is_still_the_stage_below(signed_in, db_session, member):
    give_pet(db_session, member.id, "sheep")
    give_basket(db_session, member.id, SECOND)

    body = feed(signed_in, SECOND - 1).json()["pet"]
    assert body["stage"] == 1


def test_golden_fruit_is_marked_and_worth_the_same(signed_in, db_session, member):
    """A different word on the screen and not one thing more, which is the
    bargain gilding already makes with the harvest."""
    give_pet(db_session, member.id, "rooster")
    give_basket(db_session, member.id, 1, golden=True)
    give_basket(db_session, member.id, 1, minutes_ago=-5)

    golden = feed(signed_in, 1).json()
    assert golden["golden"] is True
    assert golden["pet"]["fruit_fed"] == 1

    plain = feed(signed_in, 1).json()
    assert plain["golden"] is False
    assert plain["pet"]["fruit_fed"] == 2


def test_feeding_with_nothing_growing_is_refused(signed_in, db_session, member):
    give_basket(db_session, member.id, 5)
    assert feed(signed_in, 1).status_code == 400

    give_pet(db_session, member.id, "wolf", grown=True)
    refused = feed(signed_in, 1)
    assert refused.status_code == 400
    assert "growing" in refused.json()["detail"]


def test_feeding_more_than_the_basket_holds_takes_nothing(signed_in, db_session, member):
    """No partial ambiguity: the basket is checked before anything is taken, so
    a refusal costs nothing rather than emptying it part way."""
    pet = give_pet(db_session, member.id, "dog")
    batch = give_basket(db_session, member.id, 2)

    refused = feed(signed_in, 5)
    assert refused.status_code == 400
    db_session.expire_all()
    assert db_session.get(models.FruitBatch, batch.id).count == 2
    assert db_session.get(models.Pet, pet.id).fruit_fed == 0


def test_a_feeding_is_at_least_one_fruit(signed_in, db_session, member):
    give_pet(db_session, member.id, "dog")
    give_basket(db_session, member.id, 2)
    assert feed(signed_in, 0).status_code == 400


def test_fruit_still_on_the_plant_is_not_in_the_basket(signed_in, db_session, member):
    """Feeding takes what has been gathered, the way giving does. What is still
    hanging is safe forever and is not reachable from here."""
    give_pet(db_session, member.id, "dog")
    a_grove_that_bears(db_session, member.id)
    assert feed(signed_in, 1).status_code == 400


def test_fruit_a_pet_ate_cannot_be_given_away(signed_in, db_session, member):
    """One basket, two things to spend it on. What went into the pet is not
    there to hand to a friend afterwards."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_pet(db_session, member.id, "cat")
    give_basket(db_session, member.id, 2)

    feed(signed_in, 2)
    given = signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 1})
    assert given.status_code == 400


def test_feeding_moves_nothing_in_the_earning_lane(signed_in, db_session, member):
    """The two-lane law, one lane over. A pet returns nothing, ever: not manna,
    not experience, not a level, not a chest, not a medal, not renown."""
    give_pet(db_session, member.id, "cat")
    give_basket(db_session, member.id, THIRD)
    run_miles(db_session, member.id, 10.0)
    stock_manna(db_session, member.id, 500, offset_min=100)
    before = signed_in.get("/api/profile").json()
    chests_before = len(signed_in.get("/api/chests").json())
    renown_before = renown_of(db_session, member.id)

    feed(signed_in, THIRD)

    after = signed_in.get("/api/profile").json()
    for field in ("xp", "level", "manna", "medals", "grove", "next_chest", "fruit_ready"):
        assert after[field] == before[field], field
    assert len(signed_in.get("/api/chests").json()) == chests_before
    assert renown_of(db_session, member.id) == renown_before


def test_feeding_past_the_last_crossing_is_refused(signed_in, db_session, member):
    """His rule 2026-08-29: a feeding larger than what is left to grow used to
    swallow the remainder whole. Refused at the door now, and the basket is
    untouched, so nothing is burned for nothing."""
    pet = give_pet(db_session, member.id, "sheep")
    give_basket(db_session, member.id, THIRD + 10)

    refused = feed(signed_in, THIRD + 1)
    assert refused.status_code == 400
    db_session.expire_all()
    assert db_session.get(models.Pet, pet.id).fruit_fed == 0
    assert harvest_state(signed_in)["basket"][0]["count"] == THIRD + 10


def test_exactly_what_is_left_to_grow_is_allowed(signed_in, db_session, member):
    """The line is at the last crossing and not before it: the Max the card
    offers is the most anybody can hand over, and it goes through."""
    give_pet(db_session, member.id, "sheep")
    give_basket(db_session, member.id, THIRD + 10)

    body = feed(signed_in, THIRD).json()["pet"]
    assert (body["fruit_fed"], body["stage"], body["grown"]) == (THIRD, 3, True)
    assert harvest_state(signed_in)["basket"][0]["count"] == 10


def test_the_room_left_counts_what_has_already_been_fed(signed_in, db_session, member):
    """Cumulative, like the crossings themselves. A pet part way along has room
    for the difference and not for the whole ladder again."""
    give_pet(db_session, member.id, "sheep")
    give_basket(db_session, member.id, THIRD * 2)
    feed(signed_in, SECOND)

    assert feed(signed_in, THIRD - SECOND + 1).status_code == 400
    assert feed(signed_in, THIRD - SECOND).status_code == 200


def test_the_card_is_told_where_the_meter_ends(signed_in, db_session, member):
    """The bar fills toward one number for the whole of a pet's growing, so the
    count beside it and the fill can never disagree."""
    give_pet(db_session, member.id, "sheep")
    give_basket(db_session, member.id, SECOND)

    pet = harvest_state(signed_in)["pets"][0]
    assert (pet["grown_fruit"], pet["next_fruit"]) == (THIRD, SECOND)

    grown = feed(signed_in, SECOND).json()["pet"]
    assert (grown["grown_fruit"], grown["next_fruit"]) == (THIRD, THIRD)


# --------------------------------------------------------------------------
# Naming
# --------------------------------------------------------------------------


def name(client, pet_id: int, sent):
    return client.post(f"/api/pets/{pet_id}/name", json={"name": sent})


def test_a_pet_goes_by_its_species_and_drawing_until_it_is_named(
    signed_in, db_session, member
):
    """His pick 2026-08-29: an unnamed one is called by what it is and how far
    along it is, capitalised, and the grown one drops the qualifier."""
    pet = give_pet(db_session, member.id, "rooster")
    assert pets.serialize(pet)["display_name"] == "Baby Rooster"

    pet.stage = 2
    assert pets.serialize(pet)["display_name"] == "Young Rooster"

    pet.stage = 3
    assert pets.serialize(pet)["display_name"] == "Rooster"

    body = name(signed_in, pet.id, "Boaz").json()
    assert (body["name"], body["display_name"]) == ("Boaz", "Boaz")


def test_a_named_pet_keeps_its_name_at_every_drawing(signed_in, db_session, member):
    """The stage word stands in for a name and never sits in front of one."""
    pet = give_pet(db_session, member.id, "wolf")
    name(signed_in, pet.id, "Ari")
    db_session.refresh(pet)
    for stage in (1, 2, 3):
        pet.stage = stage
        assert pets.serialize(pet)["display_name"] == "Ari"


def test_a_name_is_stripped_of_control_bytes_and_capped(signed_in, db_session, member):
    pet = give_pet(db_session, member.id, "bat")
    body = name(signed_in, pet.id, "  Ni\x00gh\x1bt  " + "x" * 200).json()

    assert "\x00" not in body["name"] and "\x1b" not in body["name"]
    assert body["name"].startswith("Night")
    assert len(body["name"]) == pets.MAX_NAME


def test_a_blank_name_takes_it_back_off(signed_in, db_session, member):
    pet = give_pet(db_session, member.id, "bat")
    name(signed_in, pet.id, "Dusk")
    body = name(signed_in, pet.id, "   ").json()
    assert body["name"] is None
    assert body["display_name"] == "Baby Bat"


def test_a_grown_pet_can_still_be_renamed(signed_in, db_session, member):
    pet = give_pet(db_session, member.id, "wolf", grown=True)
    assert name(signed_in, pet.id, "Ari").status_code == 200


def test_somebody_elses_pet_is_the_same_answer_as_none(signed_in, db_session, member):
    other = make_user(db_session, "stranger", "stranger-password-1")
    theirs = give_pet(db_session, other.id, "cat")

    assert name(signed_in, theirs.id, "Mine").status_code == 404
    assert name(signed_in, 9999, "Ghost").status_code == 404


# --------------------------------------------------------------------------
# What a friend sees
# --------------------------------------------------------------------------


def test_a_friend_sees_the_animals_and_never_the_numbers(signed_in, db_session, member):
    """Presence only. How much somebody has fed their own pet is a record of
    their own weeks, and no number of it crosses the fence."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    pet = give_pet(db_session, other.id, "sheep", fruit_fed=SECOND)
    name(other_client, pet.id, "Wooly")

    body = signed_in.get(f"/api/profile/{other.id}").json()
    assert body["pets"] == [{"species": "sheep", "name": "Wooly", "stage": 2, "grown": False}]
    assert "fruit_fed" not in str(body)


def test_your_own_profile_carries_no_pets_row(signed_in, db_session, member):
    """Pets live in one place, the Grove: the own profile payload says nothing
    about them. Friends still read presence off the friend payload."""
    give_pet(db_session, member.id, "wolf", fruit_fed=SECOND)

    body = signed_in.get("/api/profile").json()
    assert "pets" not in body


def test_a_stranger_sees_no_pets_at_all(signed_in, db_session, member):
    other, _ = sign_in(db_session, "stranger")
    give_pet(db_session, other.id, "cat")
    body = signed_in.get(f"/api/profile/{other.id}").json()
    assert "pets" not in body


# --------------------------------------------------------------------------
# The letter
# --------------------------------------------------------------------------


def letter(client) -> dict:
    response = client.get("/api/recap")
    assert response.status_code == 200, response.text
    return response.json()


def put_the_letter_down(client) -> None:
    assert client.post("/api/recap/ack").status_code == 204


def test_the_letter_says_a_stray_arrived(signed_in, db_session, member):
    a_grove_that_bears(db_session, member.id)
    gather(signed_in)

    said = letter(signed_in)["pets"]
    assert len(said) == 1
    assert said[0]["event"] == "arrived"
    assert said[0]["species"] in pets.SPECIES


def test_the_letter_says_a_pet_grew_and_then_that_it_is_grown(signed_in, db_session, member):
    give_pet(db_session, member.id, "dog")
    give_basket(db_session, member.id, THIRD)
    put_the_letter_down(signed_in)
    let_a_moment_pass(db_session)

    feed(signed_in, SECOND)
    assert [one["event"] for one in letter(signed_in)["pets"]] == ["grew"]

    put_the_letter_down(signed_in)
    let_a_moment_pass(db_session)
    feed(signed_in, THIRD - SECOND)
    said = letter(signed_in)["pets"]
    assert [one["event"] for one in said] == ["grown"]
    assert said[0]["stage"] == 3


def test_the_letter_says_nothing_about_a_pet_that_did_nothing(signed_in, db_session, member):
    give_pet(db_session, member.id, "dog")
    put_the_letter_down(signed_in)
    let_a_moment_pass(db_session)
    assert letter(signed_in)["pets"] == []


def test_a_pet_that_finished_in_one_letter_says_so_once(signed_in, db_session, member):
    """Two sentences about one animal read as two animals, so the middle step
    goes unsaid when both crossings land in the same letter."""
    give_pet(db_session, member.id, "dog")
    give_basket(db_session, member.id, THIRD)
    put_the_letter_down(signed_in)
    let_a_moment_pass(db_session)

    feed(signed_in, THIRD)
    assert [one["event"] for one in letter(signed_in)["pets"]] == ["grown"]


def test_the_letter_says_what_the_grove_bore_however_much_was_fed(
    signed_in, db_session, member
):
    """The letter tells what happened, and what a plant bore is what it bore.

    Feeding takes from the basket afterwards, the way giving and composting do,
    and none of the three may reach back and change the news.
    """
    give_pet(db_session, member.id, "cat")
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, FRUIT_SEASON_MI)
    gather(signed_in)
    assert feed(signed_in, 4).status_code == 200

    piles = signed_in.get("/api/recap").json()["harvest"]["fruit"]
    assert sorted(piles, key=lambda row: row["name"]) == [
        {"name": "bananas", "count": 3, "label": "3 bananas"},
        {"name": "strawberries", "count": 3, "label": "3 strawberries"},
    ]


def test_feeding_can_never_letter_a_harvest_of_none(signed_in, db_session, member):
    """A whole bearing eaten by a pet still reads as the bearing it was. "0
    strawberries" is not a sentence anybody wrote, and nothing can produce it."""
    give_pet(db_session, member.id, "cat")
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, FRUIT_SEASON_MI)
    gather(signed_in)
    feed(signed_in, 3)

    piles = signed_in.get("/api/recap").json()["harvest"]["fruit"]
    assert piles == [{"name": "strawberries", "count": 3, "label": "3 strawberries"}]
    assert all(row["count"] > 0 for row in piles)
    # And the basket is empty, which is the other half of the same fact.
    assert harvest_state(signed_in)["basket"] == []


def test_the_letter_carries_the_name_when_there_is_one(signed_in, db_session, member):
    pet = give_pet(db_session, member.id, "cat")
    give_basket(db_session, member.id, SECOND)
    name(signed_in, pet.id, "Ember")
    put_the_letter_down(signed_in)
    let_a_moment_pass(db_session)

    feed(signed_in, SECOND)
    assert letter(signed_in)["pets"][0]["name"] == "Ember"


# --------------------------------------------------------------------------
# The shape of the thing
# --------------------------------------------------------------------------


def test_the_harvest_carries_the_grove_s_pets(signed_in, db_session, member):
    give_pet(db_session, member.id, "wolf", grown=True)
    give_pet(db_session, member.id, "cat", fruit_fed=SECOND)

    held = harvest_state(signed_in)["pets"]
    assert [one["species"] for one in held] == ["wolf", "cat"]
    assert held[0]["grown"] is True and held[0]["next_fruit"] is None
    assert held[1]["next_fruit"] == THIRD


@pytest.mark.parametrize("fed,stage", [(0, 1), (SECOND - 1, 1), (SECOND, 2), (THIRD, 3)])
def test_the_stage_is_read_off_the_fruit(fed, stage):
    assert pets.stage_for(fed) == stage


def test_the_six_are_split_between_the_two_time_medals():
    assert len(pets.SPECIES) == 6
    assert {one for one in pets.SPECIES if pets.LEANS[one] == "night_owl"} == {
        "bat",
        "cat",
        "wolf",
    }
    assert {one for one in pets.SPECIES if pets.LEANS[one] == "early_riser"} == {
        "dog",
        "sheep",
        "rooster",
    }


def test_a_pet_is_never_reachable_without_a_session(client, db_session, member):
    assert client.post("/api/pets/feed", json={"count": 1}).status_code == 401
    assert client.post("/api/pets/1/name", json={"name": "x"}).status_code == 401


def test_workouts_alone_never_draw_a_pet(signed_in, db_session, member):
    """Drawn by the harvest and by nothing else. Miles bring the season round;
    the gather is the act a stray answers."""
    a_grove_that_bears(db_session, member.id)
    log_workout(db_session, member.id, "run", 5.0, offset_min=300)
    assert pet_rows(db_session, member.id) == []
