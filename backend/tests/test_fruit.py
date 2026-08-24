"""Fruit: what a grown plant bears, and the four things manna is spent on.

The law this file pins, in one sentence: the MILES decide when a grove bears and
the MANNA decides how much, and neither of them ever crosses into the other's
lane. Nothing here moves experience, a level, a chest, growth or a medal.

Fruit is the only thing that spoils. It is gathered whole and lives seven days
from the gather; manna is a bank and none of this touches it.

The clock never ticks on its own. Everything about those seven days, and about
the window the giving cap is measured over, is said with let_a_moment_pass,
which pushes what is already stored into the past, because the suite's now is
pinned and a case that means "and then a week went by" has to say so.
"""

import datetime as dt

import pytest

from conftest import (
    LETTER_KEYS,
    give_planting,
    let_a_moment_pass,
    log_workout,
    make_user,
)
from test_grove import befriend, sign_in

from app import harvest, models, progress, species
from app.routers.harvest import NOT_ENOUGH_FRUIT
from app.config import (
    FEED_COST,
    FEED_MAX_BANKED,
    FRUIT_SEASON_MI,
    GATHERED_LIFE_DAYS,
    MANNA_TO_ONE_PERSON,
)

DAY = 24 * 60 * 60
# Long enough that anything with a seven day life is well past it, and short of
# the session's own thirty: let_a_moment_pass ages every stamp in the database,
# the signed-in cookie's included, so a case that pushed everything back three
# months would be measuring a logged-out client.
A_LONG_WHILE = 20 * DAY


# --------------------------------------------------------------------------
# Shorthands
# --------------------------------------------------------------------------


def state(client) -> dict:
    response = client.get("/api/harvest")
    assert response.status_code == 200, response.text
    return response.json()


def gather(client) -> dict:
    """Bring in the harvest. Fruit and nothing else: manna is never gathered."""
    response = client.post("/api/harvest/gather")
    assert response.status_code == 200, response.text
    return response.json()


def profile(client) -> dict:
    response = client.get("/api/profile")
    assert response.status_code == 200, response.text
    return response.json()


def basket(client) -> list[dict]:
    response = client.get("/api/basket")
    assert response.status_code == 200, response.text
    return response.json()


def run_miles(db_session, user_id: int, miles: float, *, offset_min: int = 0):
    """One run of exactly this many converted Miles, which is what a season is
    measured in. Running is one for one, so the two numbers are the same."""
    return log_workout(db_session, user_id, "run", miles, offset_min=offset_min)


def stock_manna(db_session, user_id: int, amount: int, *, offset_min: int = 0) -> None:
    """Put this much manna in somebody's bank, and no miles with it.

    A workout with no distance is the whole trick: it burns calories, which is
    the only thing manna comes from, and it moves neither meter. It lands in the
    bank as it is credited, so there is nothing to gather afterwards.
    """
    log_workout(db_session, user_id, "run", 0.0, kcal=amount, offset_min=offset_min)


def batches(db_session, user_id: int) -> list[models.FruitBatch]:
    db_session.expire_all()
    return list(
        db_session.query(models.FruitBatch)
        .filter(models.FruitBatch.user_id == user_id)
        .order_by(models.FruitBatch.id)
        .all()
    )


def renown_of(db_session, user_id: int) -> int:
    db_session.expire_all()
    row = db_session.get(models.UserProgress, user_id)
    return 0 if row is None else row.renown


def meter(db_session, user_id: int) -> tuple[float, int]:
    db_session.expire_all()
    row = db_session.get(models.UserProgress, user_id)
    return round(row.fruit_progress_mi, 4), row.fruit_seasons


def as_a_pre_release_account(db_session, user_id: int) -> None:
    """Rewind the fruit columns to the shape 0032 backfills.

    A history that was run before the release: every mile on record is fuel the
    meter never saw, so the baseline covers all of it, nothing has ever borne,
    and the meter stands at nothing. The migration computes exactly this from
    the same three numbers; said here in the app's own terms, because the
    account the bug was found on is shaped like this and no test can log a
    workout into a release that has already happened.
    """
    db_session.query(models.FruitBatch).filter(models.FruitBatch.user_id == user_id).delete()
    row = db_session.get(models.UserProgress, user_id)
    row.fruit_baseline_mi = row.xp
    row.fruit_progress_mi = 0.0
    row.fruit_seasons = 0
    db_session.commit()


# --------------------------------------------------------------------------
# The season: when a grove bears
# --------------------------------------------------------------------------


def test_a_grove_bears_when_the_meter_fills_and_keeps_the_remainder(
    signed_in, db_session, member
):
    """His rhythm: every 33 converted Miles, grove-wide, no clocks. The meter
    carries what is left over exactly as the chest one does."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 20.0)
    assert meter(db_session, member.id) == (20.0, 0)
    assert batches(db_session, member.id) == []

    run_miles(db_session, member.id, 15.0, offset_min=100)
    assert meter(db_session, member.id) == (2.0, 1)
    assert len(batches(db_session, member.id)) == 1


def test_one_long_day_bears_as_many_times_as_it_pays_for(signed_in, db_session, member):
    """Two seasons and a remainder out of one workout. A crossing is a crossing
    however it arrived, which is what makes a backfilled year land right."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 70.0)
    assert meter(db_session, member.id) == (70.0 - 2 * FRUIT_SEASON_MI, 2)
    assert len(batches(db_session, member.id)) == 2


def test_everything_grown_bears_at_once_and_nothing_younger_does(
    signed_in, db_session, member
):
    """Grove-wide, which is what makes it one gathering rather than a chore per
    plant. A seedling is not part of it: nothing bears before it is grown."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    give_planting(db_session, member.id, "banana", growth=15.0)
    # Two thirds of the way to its first level, so it is still growing.
    give_planting(db_session, member.id, "olive", growth=10.0)
    run_miles(db_session, member.id, 33.0)

    grown = {row.species for row in batches(db_session, member.id)}
    assert grown == {"strawberry", "banana"}


def test_a_plant_that_matured_on_the_same_workout_is_in_that_harvest(
    signed_in, db_session, member
):
    """The growing happens before the bearing, so a plant the season itself
    brought of age is standing grown when its grove comes round."""
    give_planting(db_session, member.id, "strawberry", growth=0.0)
    run_miles(db_session, member.id, 33.0)
    assert [row.species for row in batches(db_session, member.id)] == ["strawberry"]


def test_an_empty_grove_still_spends_its_season(signed_in, db_session, member):
    """Nothing planted is nothing borne, and the crossing still happened: the
    meter is the miles' own record and does not wait for a gardener."""
    run_miles(db_session, member.id, 33.0)
    assert meter(db_session, member.id) == (0.0, 1)
    assert batches(db_session, member.id) == []


def test_steps_never_fill_the_season(signed_in, ingest_token, db_session, member):
    """The retreat law, one meter further on: a pedometer's day is stored and
    shown and moves nothing at all."""
    from test_steps import reading, sync

    give_planting(db_session, member.id, "strawberry", growth=15.0)
    sync(signed_in, ingest_token, metrics=reading(steps=60000, miles=40.0))
    assert meter(db_session, member.id) == (0.0, 0)
    assert batches(db_session, member.id) == []


# --------------------------------------------------------------------------
# The yield: how much a plant bears
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("species_id", "count"),
    [("strawberry", 3), ("mango", 2), ("olive", 1), ("mustard", 1)],
)
def test_yield_is_scaled_by_what_the_plant_is(
    signed_in, db_session, member, species_id, count
):
    """His pick: the commoner the plant the more it bears, and the mustard tree
    answers for itself rather than as the rare it is filed under."""
    step = species.BY_ID[species_id].level_mi
    give_planting(db_session, member.id, species_id, growth=step)
    run_miles(db_session, member.id, 33.0)
    borne = batches(db_session, member.id)
    assert [(row.species, row.count) for row in borne] == [(species_id, count)]


def test_a_fully_grown_plant_bears_a_finer_name_and_never_more(
    signed_in, db_session, member
):
    """His answer outright: gilded is a better fruit, not a bigger pile."""
    give_planting(db_session, member.id, "strawberry", growth=15.0 * species.MAX_LEVEL)
    run_miles(db_session, member.id, 33.0)
    borne = batches(db_session, member.id)[0]
    assert (borne.golden, borne.count) == (True, 3)
    assert harvest.fruit_name(borne.species, borne.golden) == "golden strawberries"


def test_every_species_keeps_its_own_harvest_name(signed_in, db_session, member):
    """The catalogue names what each one bears, and the banana tree collects
    bananas. Nothing anywhere calls a harvest "fruit"."""
    assert harvest.fruit_name("banana") == "bananas"
    assert harvest.fruit_name("coffee") == "coffee cherries"
    assert harvest.fruit_name("mustard") == "mustard seeds"
    assert harvest.fruit_name("olive", True) == "golden olives"


def test_a_count_of_one_is_said_in_the_singular(signed_in, db_session, member):
    """A rare tree bears exactly one, which is the commonest case there is for
    getting this wrong. "1 olives" is not a sentence anybody wrote."""
    assert harvest.fruit_words(1, "olive") == "1 olive"
    assert harvest.fruit_words(3, "olive") == "3 olives"
    assert harvest.fruit_words(1, "coffee") == "1 coffee cherry"
    assert harvest.fruit_words(1, "olive", True) == "1 golden olive"
    assert harvest.fruit_words(1, "mustard") == "1 mustard seed"


def test_a_batch_carries_the_miles_and_the_month_it_grew_in(
    signed_in, db_session, member
):
    """The provenance is written at the bearing, so what a gift says about
    itself cannot change when a constant is retuned."""
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    borne = batches(db_session, member.id)[0]
    assert (borne.season_mi, borne.season_month) == (FRUIT_SEASON_MI, "April")
    assert harvest.provenance(borne) == "3 bananas, grown over 33 miles in April"


# --------------------------------------------------------------------------
# Gathering
# --------------------------------------------------------------------------


def test_one_button_brings_in_the_whole_harvest(signed_in, db_session, member):
    """His pick: one act on the grove, because a grove is one place. Fruit only,
    and whole: manna is banked as it is earned and is no part of this."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)

    before = state(signed_in)
    assert before["ready"] is True
    assert before["manna"] == 650
    assert len(before["borne"]) == 1

    taken = gather(signed_in)
    # What this act brought in. No manna moved, in either direction.
    assert taken["fruit"] == 3
    assert "gathered_manna" not in taken
    after = state(signed_in)
    assert after["ready"] is False
    assert after["manna"] == 650
    assert after["borne"] == []
    assert [row["count"] for row in after["basket"]] == [3]


def test_the_grove_screen_says_one_manna_number(signed_in, db_session, member):
    """The waiting half is gone from this payload too, and the button is ready
    for fruit alone: a bank is never something to gather."""
    log_workout(db_session, member.id, "run", 0.0, kcal=1000)
    read = state(signed_in)
    assert read["manna"] == 1000
    assert "manna_pending" not in read
    assert read["ready"] is False


def test_gathering_nothing_is_not_a_refusal(signed_in, db_session, member):
    """A second press a moment later is the same answer as an empty grove:
    nothing moved, and nothing went wrong."""
    taken = gather(signed_in)
    assert taken["fruit"] == 0


def test_what_is_not_gathered_is_safe_forever(signed_in, db_session, member):
    """Fruit on the plant never ages, and neither does the bank. The seven days
    start at the gather and nowhere earlier, which is what makes time away
    free."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)
    let_a_moment_pass(db_session, seconds=A_LONG_WHILE)

    read = state(signed_in)
    assert len(read["borne"]) == 1
    assert read["manna"] == 650


def test_nothing_anywhere_counts_down(signed_in, db_session, member):
    """No countdown, no expiry, no guilt copy: his rule, pinned by the shape of
    every payload that could have carried one."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)
    gather(signed_in)
    for read in (state(signed_in), profile(signed_in), signed_in.get("/api/recap").json()):
        assert not [key for key in read if "spoil" in key or "expire" in key]
    assert not [key for key in state(signed_in)["basket"][0] if "expire" in key]


# --------------------------------------------------------------------------
# Compost
# --------------------------------------------------------------------------


def test_gathered_fruit_lasts_exactly_seven_days(signed_in, db_session, member):
    """Never a day early. The window is the whole of the promise, so the case
    stands a minute inside it and then crosses it. The bank beside it does not
    move at either moment: manna never spoils."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)
    gather(signed_in)

    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY - 60)
    read = state(signed_in)
    assert len(read["basket"]) == 1
    assert read["manna"] == 650

    let_a_moment_pass(db_session, seconds=60)
    read = state(signed_in)
    assert read["basket"] == []
    assert read["manna"] == 650


def test_compost_leaves_the_plant_and_the_bank_alone(signed_in, db_session, member):
    """Only gathered fruit ages. A second harvest still on the plant and every
    manna anybody holds are untouched by the sweep."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)
    gather(signed_in)
    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY)
    # Borne after the gather, so it is still on the plant, and calories with it.
    log_workout(db_session, member.id, "run", 33.0, kcal=400, offset_min=300)

    read = state(signed_in)
    assert read["basket"] == []
    assert len(read["borne"]) == 1
    assert read["manna"] == 1050


def test_the_letter_says_one_soft_line_when_something_composted(
    signed_in, db_session, member
):
    """One flag, said afterwards and once. Nothing warned anybody first."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)
    gather(signed_in)
    assert signed_in.get("/api/recap").json()["composted"] is False

    assert signed_in.post("/api/recap/ack").status_code == 204
    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY)
    state(signed_in)
    assert signed_in.get("/api/recap").json()["composted"] is True


def test_composted_fruit_is_gone_and_not_merely_hidden(signed_in, db_session, member):
    """What went back to the soil cannot be given away, which is the difference
    between composting and a screen that stopped drawing it."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY)
    state(signed_in)
    refused = signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 1})
    assert refused.status_code == 400
    assert refused.json()["detail"] == NOT_ENOUGH_FRUIT


# --------------------------------------------------------------------------
# Feeding your own grove
# --------------------------------------------------------------------------


def test_feeding_buys_one_more_fruit_on_the_next_bearing(signed_in, db_session, member):
    """Five hundred manna, one more fruit, once. It banks on the plant and is
    spent the moment that plant bears."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, member.id, FEED_COST)

    fed = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert fed.status_code == 200, fed.text
    assert fed.json()["fed"] == 1
    assert state(signed_in)["manna"] == 0

    run_miles(db_session, member.id, 33.0, offset_min=300)
    borne = batches(db_session, member.id)
    assert [row.count for row in borne] == [4]
    # Spent on that harvest: the next one is back to what the plant is worth.
    db_session.refresh(plant)
    assert plant.fed_bonus == 0
    run_miles(db_session, member.id, 33.0, offset_min=600)
    assert [row.count for row in batches(db_session, member.id)] == [4, 3]


def test_a_plant_holds_only_so_much_feeding_before_it_bears(
    signed_in, db_session, member
):
    """Three, and the fourth is refused rather than swallowed: a spend that
    bought nothing would be worse than a plain no."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, member.id, FEED_COST * 5)

    for _ in range(FEED_MAX_BANKED):
        assert signed_in.post("/api/harvest/feed", json={"planting_id": plant.id}).status_code == 200
    refused = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "A plant holds 3 extra fruit at most before it bears."
    # Nothing was taken for the refusal.
    assert state(signed_in)["manna"] == FEED_COST * 2


def test_several_fruit_can_be_bought_in_one_go(signed_in, db_session, member):
    plant = give_planting(db_session, member.id, "olive", growth=100.0)
    stock_manna(db_session, member.id, FEED_COST * 3)
    fed = signed_in.post(
        "/api/harvest/feed", json={"planting_id": plant.id, "bonus": 3}
    )
    assert fed.status_code == 200, fed.text
    assert fed.json()["fed"] == 3
    run_miles(db_session, member.id, 33.0, offset_min=300)
    assert [row.count for row in batches(db_session, member.id)] == [4]


def test_a_feeding_costs_five_hundred_and_a_full_plant_costs_fifteen(
    signed_in, db_session, member
):
    """His numbers: 500 for one more fruit, three at most on a plant, so a plant
    fed as far as it goes has cost 1500 and bears three more."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, member.id, 1500)
    assert state(signed_in)["feed_cost"] == 500

    fed = signed_in.post(
        "/api/harvest/feed", json={"planting_id": plant.id, "bonus": FEED_MAX_BANKED}
    )
    assert fed.status_code == 200, fed.text
    assert state(signed_in)["manna"] == 0
    run_miles(db_session, member.id, 33.0, offset_min=300)
    assert [row.count for row in batches(db_session, member.id)] == [6]


def test_feeding_needs_the_manna_in_the_bank(signed_in, db_session, member):
    """A refusal takes nothing, and the whole bank is still there afterwards."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, member.id, FEED_COST - 5)
    refused = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "You do not have enough manna for that."
    assert state(signed_in)["manna"] == FEED_COST - 5


def test_nothing_ungrown_is_fed(signed_in, db_session, member):
    """A plant that cannot bear cannot be paid to bear more."""
    plant = give_planting(db_session, member.id, "olive", growth=10.0)
    stock_manna(db_session, member.id, FEED_COST)
    refused = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "That one is not grown yet."
    assert state(signed_in)["manna"] == FEED_COST


def test_a_fully_grown_plant_still_takes_feeding(signed_in, db_session, member):
    """Unlike water, which has no level left to buy: a gilded plant still bears,
    so there is still something for manna to do."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0 * species.MAX_LEVEL)
    stock_manna(db_session, member.id, FEED_COST)
    assert signed_in.post("/api/harvest/feed", json={"planting_id": plant.id}).status_code == 200
    run_miles(db_session, member.id, 33.0, offset_min=300)
    borne = batches(db_session, member.id)[0]
    assert (borne.golden, borne.count) == (True, 4)


def test_feeding_your_own_plot_pays_no_renown(signed_in, db_session, member):
    """The quiet option. Giving to yourself is not giving, and the ladder says
    so by paying nothing for it."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, member.id, FEED_COST)
    signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert renown_of(db_session, member.id) == 0


def test_feeding_moves_nothing_in_the_earning_lane(signed_in, db_session, member):
    """TWO-LANE LAW, pinned. Manna buys fruit and never a mile of growth, a
    level, a chest or a medal."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 10.0)
    stock_manna(db_session, member.id, FEED_COST * 3, offset_min=100)
    before = profile(signed_in)
    growth_before = plant.growth_mi
    chests_before = len(signed_in.get("/api/chests").json())

    signed_in.post("/api/harvest/feed", json={"planting_id": plant.id, "bonus": 3})

    after = profile(signed_in)
    db_session.refresh(plant)
    assert (after["xp"], after["level"]) == (before["xp"], before["level"])
    assert after["next_chest"] == before["next_chest"]
    assert plant.growth_mi == growth_before
    assert len(signed_in.get("/api/chests").json()) == chests_before
    assert after["medals"] == before["medals"]


# --------------------------------------------------------------------------
# Feeding a friend's grove
# --------------------------------------------------------------------------


def test_feeding_a_friends_plant_boosts_their_yield_and_pays_the_giver(
    signed_in, db_session, member
):
    """His direction: manna is primarily spent on others, and this is where the
    ladder says so. The fruit is theirs; the renown is the giver's."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, member.id, FEED_COST)

    fed = signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    assert fed.status_code == 200, fed.text
    # Answered in the shape a friend's plot is allowed to be seen in.
    assert "growth_mi" not in fed.json()
    assert fed.json()["fed"] == 1

    db_session.refresh(theirs)
    assert theirs.fed_bonus == 1
    assert renown_of(db_session, member.id) == 5
    assert renown_of(db_session, other.id) == 0

    run_miles(db_session, other.id, 33.0)
    assert [row.count for row in batches(db_session, other.id)] == [3]


def test_a_second_feeding_on_the_same_friend_still_lands_and_earns_nothing(
    signed_in, db_session, member
):
    """The diminishing window, kind by kind, exactly as water and words have
    it: two accounts feeding each other all evening earn one feeding's worth."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, member.id, FEED_COST * 2)

    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    db_session.refresh(theirs)
    assert theirs.fed_bonus == 2
    assert renown_of(db_session, member.id) == 5


def test_the_window_opens_again_once_it_has_run_out(signed_in, db_session, member):
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, member.id, FEED_COST)

    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    # A week and a day later, so the renown window has run out. The bank did not
    # move in the meantime; manna does not spoil.
    let_a_moment_pass(db_session, seconds=8 * DAY)
    stock_manna(db_session, member.id, FEED_COST, offset_min=300)
    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    assert renown_of(db_session, member.id) == 10


def test_a_strangers_plant_answers_like_one_that_never_existed(
    signed_in, db_session, member
):
    """404 and not 403, the water rule: whose plot an id belongs to is not a
    thing to learn by asking."""
    other, _ = sign_in(db_session, "mate")
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, member.id, FEED_COST)

    refused = signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    assert refused.status_code == 404
    assert refused.json()["detail"] == "No such planting."
    missing = signed_in.post("/api/harvest/feed", json={"planting_id": 9999})
    assert missing.status_code == 404
    assert missing.json()["detail"] == "No such planting."
    # Nothing was spent on either refusal.
    assert state(signed_in)["manna"] == FEED_COST


# --------------------------------------------------------------------------
# Giving manna away
# --------------------------------------------------------------------------


def test_gifted_manna_joins_their_bank_and_pays_the_giver(
    signed_in, db_session, member
):
    """A gift lands in their bank and is theirs to spend at once, because a bank
    is what manna is on both sides of a gift."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 500)

    sent = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 300})
    assert sent.status_code == 201, sent.text
    assert state(signed_in)["manna"] == 200
    assert profile(other_client)["manna"] == 300
    assert renown_of(db_session, member.id) == 3
    assert renown_of(db_session, other.id) == 0


def test_a_second_manna_gift_to_the_same_friend_arrives_and_earns_nothing(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 500)

    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 100})
    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 100})
    assert profile(other_client)["manna"] == 200
    assert renown_of(db_session, member.id) == 3


def test_manna_is_only_given_to_a_friend_and_never_to_yourself(
    signed_in, db_session, member
):
    other, _ = sign_in(db_session, "mate")
    stock_manna(db_session, member.id, 500)

    stranger = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 50})
    assert stranger.status_code == 404
    assert stranger.json()["detail"] == "No such friend."
    myself = signed_in.post("/api/harvest/manna", json={"user_id": member.id, "amount": 50})
    assert myself.status_code == 400
    assert myself.json()["detail"] == "You cannot give to yourself."
    assert state(signed_in)["manna"] == 500


@pytest.mark.parametrize("amount", [0, -50])
def test_a_gift_has_to_be_a_real_amount(signed_in, db_session, member, amount):
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 500)
    refused = signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": amount}
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "A gift is at least 1 manna."


def test_nobody_gives_away_more_than_they_have(signed_in, db_session, member):
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 100)

    refused = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 500})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "You do not have enough manna for that."
    assert state(signed_in)["manna"] == 100


def test_gifted_manna_is_spent_like_any_other(signed_in, db_session, member):
    """A gift is manna, not a token of one: it is spendable the moment it
    lands, with nothing to be done to it first."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "strawberry", growth=15.0)
    stock_manna(db_session, member.id, FEED_COST)

    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": FEED_COST})
    fed = other_client.post("/api/harvest/feed", json={"planting_id": theirs.id})
    assert fed.status_code == 200, fed.text


# --------------------------------------------------------------------------
# What one person may be given in a week
# --------------------------------------------------------------------------


def test_two_thousand_to_one_person_lands_and_the_next_manna_does_not(
    signed_in, db_session, member
):
    """His cap, at the boundary: exactly the limit goes through, and one manna
    past it is refused. A big bank drains across people rather than into one."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 5000)

    sent = signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": MANNA_TO_ONE_PERSON}
    )
    assert sent.status_code == 201, sent.text
    refused = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 5})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "That is more manna than you can give one person just now."
    # Nothing was taken for the refusal.
    assert state(signed_in)["manna"] == 3000


def test_feeding_and_gifting_are_counted_against_the_same_cap(
    signed_in, db_session, member
):
    """Both halves are manna put into the same person, so a limit one of them
    could walk around would not be one."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, member.id, 5000)

    # 1500 fed to their plant leaves 500 of the window.
    fed = signed_in.post(
        "/api/harvest/feed", json={"planting_id": theirs.id, "bonus": FEED_MAX_BANKED}
    )
    assert fed.status_code == 200, fed.text
    assert signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": 500}
    ).status_code == 201
    refused = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 5})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "That is more manna than you can give one person just now."


def test_the_cap_is_per_person_and_not_a_budget_for_everybody(
    signed_in, db_session, member
):
    """It is a limit on what one person may be given, so the next friend starts
    from nothing."""
    other, _ = sign_in(db_session, "mate")
    third, _third = sign_in(db_session, "third")
    befriend(db_session, member, other)
    befriend(db_session, member, third)
    stock_manna(db_session, member.id, 5000)

    assert signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": MANNA_TO_ONE_PERSON}
    ).status_code == 201
    assert signed_in.post(
        "/api/harvest/manna", json={"user_id": third.id, "amount": 1000}
    ).status_code == 201


def test_the_giving_window_opens_again_once_it_has_run_out(
    signed_in, db_session, member
):
    """Rolling, and read off the stamps on the rows: a week later the same
    friend may be given the same again."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 5000)

    assert signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": MANNA_TO_ONE_PERSON}
    ).status_code == 201
    assert signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": 5}
    ).status_code == 400

    let_a_moment_pass(db_session, seconds=8 * DAY)
    assert signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": 1000}
    ).status_code == 201


def test_your_own_grove_is_outside_the_cap(signed_in, db_session, member):
    """Feeding your own plot is capped by what a plant holds and by nothing
    else, so a solo member still has somewhere for a big bank to go."""
    stock_manna(db_session, member.id, 20000)
    for species_id in ("strawberry", "banana", "grapevine", "olive"):
        plant = give_planting(db_session, member.id, species_id, growth=100.0)
        fed = signed_in.post(
            "/api/harvest/feed",
            json={"planting_id": plant.id, "bonus": FEED_MAX_BANKED},
        )
        assert fed.status_code == 200, fed.text
    # Four plants fed as far as they go, which is well past what one friend
    # could have been given in the same window.
    assert state(signed_in)["manna"] == 20000 - 4 * FEED_COST * FEED_MAX_BANKED


def test_the_refusal_says_nothing_about_when(signed_in, db_session, member):
    """A limit and not a timer: no countdown, no date, no number of days
    anywhere in the answer."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 5000)
    signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": MANNA_TO_ONE_PERSON}
    )

    refused = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 5})
    said = refused.json()["detail"]
    assert "day" not in said and "week" not in said
    assert not [word for word in said.split() if word.strip(".").isdigit()]


# --------------------------------------------------------------------------
# Giving fruit away
# --------------------------------------------------------------------------


def hand_over_fruit(db_session, signed_in, member, other, count=3):
    """One banana tree's harvest, gathered and handed to a friend."""
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    return signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": count})


def test_fruit_is_given_with_where_it_came_from(signed_in, db_session, member):
    """The top of the ladder, and the only thing in the game that carries its
    own history: the miles that grew it and the month it came in."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)

    given = hand_over_fruit(db_session, signed_in, member, other)
    assert given.status_code == 201, given.text
    assert state(signed_in)["basket"] == []
    assert renown_of(db_session, member.id) == 8

    keepsakes = basket(other_client)
    assert len(keepsakes) == 1
    assert keepsakes[0]["from"] == "runner"
    assert keepsakes[0]["name"] == "bananas"
    assert keepsakes[0]["count"] == 3
    assert keepsakes[0]["provenance"] == "3 bananas, grown over 33 miles in April"


def test_a_gift_of_an_amount_takes_the_oldest_fruit_first(signed_in, db_session, member):
    """One number, and the oldest goes first: the same rule a pet is fed by, so
    giving never costs somebody the batch they were about to lose anyway."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    let_a_moment_pass(db_session, seconds=DAY)
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0, offset_min=300)
    gather(signed_in)

    given = signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 4})
    assert given.status_code == 201, given.text

    # Three batches in gather order: the day-old bananas, and the two the
    # second season brought in. The oldest went whole, the next kept a
    # remainder, and the newest was never touched.
    held = batches(db_session, member.id)
    assert [row.count for row in held] == [0, 2, 3]
    assert [row.borne_count for row in held] == [3, 3, 3]
    assert sum(row["count"] for row in state(signed_in)["basket"]) == 5


def test_a_gift_off_two_batches_says_what_it_really_is(signed_in, db_session, member):
    """A handful of two kinds is fruit, because naming one of them would be the
    sentence saying more than it knows."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 4})
    keepsake = basket(other_client)[0]
    assert keepsake["count"] == 4
    assert keepsake["name"] == "fruit"
    assert keepsake["label"] == "4 fruit"
    assert keepsake["provenance"] == "4 fruit, grown over 33 miles in April"


def test_a_gift_all_of_one_species_still_names_it(signed_in, db_session, member):
    """Species survive where they are read. One kind in the handful and the
    keepsake says which."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 2})
    keepsake = basket(other_client)[0]
    assert keepsake["name"] == "bananas"
    assert keepsake["provenance"] == "2 bananas, grown over 33 miles in April"


def test_giving_everything_empties_the_basket(signed_in, db_session, member):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    assert signed_in.post(
        "/api/harvest/fruit", json={"user_id": other.id, "count": 6}
    ).status_code == 201
    assert state(signed_in)["basket"] == []
    assert basket(other_client)[0]["count"] == 6


def test_more_than_the_basket_holds_gives_nothing_at_all(signed_in, db_session, member):
    """No partial ambiguity, exactly as feeding has none: the basket is checked
    before anything leaves it."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    refused = signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 4})
    assert refused.status_code == 400
    assert state(signed_in)["basket"][0]["count"] == 3
    assert basket(other_client) == []


def test_what_a_gift_left_behind_is_still_fruit(signed_in, db_session, member):
    """A part-given batch keeps its remainder, and the remainder is fruit like
    any other: it feeds a pet and it goes back to the soil in its own time."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 1})
    assert state(signed_in)["basket"][0]["count"] == 2

    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY)
    state(signed_in)
    assert state(signed_in)["basket"] == []
    assert signed_in.get("/api/recap").json()["composted"] is True


def test_a_gift_off_two_seasons_says_since_rather_than_in(signed_in, db_session, member):
    """Two months in one handful is not a handful from one month, so the
    sentence names the earlier month and says the gift reaches back to it."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    # The batch already in the basket keeps its own month; the next one is
    # written with another, which is what a gift spanning two seasons looks like.
    held = batches(db_session, member.id)[0]
    held.season_month = "March"
    db_session.commit()
    run_miles(db_session, member.id, 33.0, offset_min=300)
    gather(signed_in)

    signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 4})
    assert basket(other_client)[0]["provenance"] == "4 bananas, grown over 33 miles since March"


def test_one_gift_pays_renown_once_however_many_batches_it_came_off(
    signed_in, db_session, member
):
    """A gift is a gift. Taking it off three batches is an accident of when the
    grove bore and must never read as three givings."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 6})
    assert renown_of(db_session, member.id) == 8
    assert db_session.query(models.FruitGift).count() == 1


def test_a_keepsake_is_kept_forever_and_does_nothing(signed_in, db_session, member):
    """No mechanics, no loops, no spoilage. It is a record that somebody grew
    something and gave it away."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    hand_over_fruit(db_session, signed_in, member, other)

    before = profile(other_client)
    let_a_moment_pass(db_session, seconds=A_LONG_WHILE)
    # Read again, which is what runs the sweep on that account.
    state(other_client)
    assert len(basket(other_client)) == 1
    after = profile(other_client)
    assert (after["xp"], after["level"], after["manna"]) == (
        before["xp"],
        before["level"],
        before["manna"],
    )
    # It is a keepsake and not a basket of fruit to give on.
    assert state(other_client)["basket"] == []


def test_a_second_fruit_gift_to_the_same_friend_lands_and_earns_nothing(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    hand_over_fruit(db_session, signed_in, member, other)
    # A second season, a second basket, the same friend inside the window.
    run_miles(db_session, member.id, 33.0, offset_min=300)
    gather(signed_in)
    again = signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 3})
    assert again.status_code == 201, again.text
    assert len(basket(other_client)) == 2
    assert renown_of(db_session, member.id) == 8


def test_only_gathered_fruit_can_be_given(signed_in, db_session, member):
    """What is still on the plant is not in anybody's hands yet."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    assert batches(db_session, member.id)[0].gathered_at is None

    refused = signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 1})
    assert refused.status_code == 400
    assert refused.json()["detail"] == NOT_ENOUGH_FRUIT


def test_the_same_fruit_cannot_be_given_twice(signed_in, db_session, member):
    """Given is gone. What left the basket is not in it to hand to somebody
    else, which is the whole difference between a gift and a copy."""
    other, _ = sign_in(db_session, "mate")
    third, _third_client = sign_in(db_session, "third")
    befriend(db_session, member, other)
    befriend(db_session, member, third)

    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    assert signed_in.post(
        "/api/harvest/fruit", json={"user_id": other.id, "count": 3}
    ).status_code == 201
    again = signed_in.post("/api/harvest/fruit", json={"user_id": third.id, "count": 1})
    assert again.status_code == 400
    assert again.json()["detail"] == NOT_ENOUGH_FRUIT


def test_fruit_is_only_given_to_a_friend_and_never_to_yourself(
    signed_in, db_session, member
):
    other, _ = sign_in(db_session, "mate")
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)

    stranger = signed_in.post("/api/harvest/fruit", json={"user_id": other.id, "count": 1})
    assert stranger.status_code == 404
    assert stranger.json()["detail"] == "No such friend."
    myself = signed_in.post("/api/harvest/fruit", json={"user_id": member.id, "count": 1})
    assert myself.status_code == 400
    assert myself.json()["detail"] == "You cannot give to yourself."
    assert len(state(signed_in)["basket"]) == 1


def test_a_keepsake_never_reaches_anybody_elses_screen(signed_in, db_session, member):
    """The basket is the You screen's, like the manna beside it. A friend reads
    a level and a garden, never a cupboard."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    hand_over_fruit(db_session, signed_in, member, other)

    seen = signed_in.get(f"/api/profile/{other.id}").json()
    assert "basket" not in seen
    assert "manna" not in seen


# --------------------------------------------------------------------------
# The letter
# --------------------------------------------------------------------------


def test_the_letter_tells_the_harvest_as_news(signed_in, db_session, member):
    """It is earned by miles, so it is news. Piled by fruit, because four
    bushes bearing is one sentence rather than four."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 66.0)

    letter = signed_in.get("/api/recap").json()
    assert letter["harvest"]["seasons"] == 2
    assert sorted(letter["harvest"]["fruit"], key=lambda row: row["name"]) == [
        {"name": "bananas", "count": 6, "label": "6 bananas"},
        {"name": "strawberries", "count": 6, "label": "6 strawberries"},
    ]


def test_a_batch_records_what_it_bore_as_well_as_what_is_left(
    signed_in, db_session, member
):
    """Two numbers on one row. What the plant bore is written once at the
    bearing and never moves; what is left is what the basket shows, what a gift
    carries and what compost returns."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, FRUIT_SEASON_MI)

    row = batches(db_session, member.id)[0]
    assert (row.borne_count, row.count) == (3, 3)


def test_a_letter_with_no_harvest_in_it_says_none(signed_in, db_session, member):
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 5.0)
    letter = signed_in.get("/api/recap").json()
    assert letter["harvest"] == {"seasons": 0, "fruit": []}


def test_the_harvest_window_is_the_letters_own(signed_in, db_session, member):
    """Read, cleared, and then another season: the letter reports what came in
    since, never the whole year."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    assert signed_in.get("/api/recap").json()["harvest"]["seasons"] == 1
    assert signed_in.post("/api/recap/ack").status_code == 204
    let_a_moment_pass(db_session)

    run_miles(db_session, member.id, 33.0, offset_min=300)
    letter = signed_in.get("/api/recap").json()
    assert letter["harvest"]["seasons"] == 1
    assert letter["harvest"]["fruit"] == [
        {"name": "strawberries", "count": 3, "label": "3 strawberries"}
    ]


def test_the_letter_attributes_both_kinds_of_gift(signed_in, db_session, member):
    """Gifts are attributed where every gift in this app is attributed: in the
    receiver's letter, afterwards."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 500)
    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 200})
    hand_over_fruit(db_session, signed_in, member, other)

    letter = other_client.get("/api/recap").json()
    assert letter["manna_gifts"] == [{"from": "runner", "amount": 200}]
    assert letter["fruit_gifts"] == [
        {
            "from": "runner",
            "name": "bananas",
            "label": "3 bananas",
            "count": 3,
            "provenance": "3 bananas, grown over 33 miles in April",
        }
    ]


def test_the_letter_keeps_its_shape(signed_in, db_session, member):
    letter = signed_in.get("/api/recap").json()
    assert list(letter) == LETTER_KEYS


def test_giving_manna_grows_the_frame_like_any_other_giving(
    signed_in, db_session, member
):
    """The flourish is read from what somebody has given, so the three new ways
    of giving are counted with the old ones or the letter goes quiet."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, member.id, FEED_COST * 2)

    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 100})
    letter = signed_in.get("/api/recap").json()
    # Five and three is over the first flourish threshold, which is ten with the
    # eight a fruit gift is worth still to come.
    assert renown_of(db_session, member.id) == 8
    assert letter["flourish_rose"] is False

    hand_over_fruit(db_session, signed_in, member, other)
    letter = signed_in.get("/api/recap").json()
    assert renown_of(db_session, member.id) == 16
    assert letter["flourish_rose"] is True


# --------------------------------------------------------------------------
# Rebuilding
# --------------------------------------------------------------------------


def test_deleting_a_workout_takes_back_the_meter_and_never_the_fruit(
    signed_in, db_session, member
):
    """Spent stays spent (R31), one meter across: the miles come back off, and
    the harvest they already brought stays exactly where it is."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    doomed = run_miles(db_session, member.id, 10.0, offset_min=200)
    assert meter(db_session, member.id) == (10.0, 1)

    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204
    assert meter(db_session, member.id) == (0.0, 1)
    assert len(batches(db_session, member.id)) == 1


def test_a_rebuild_never_bears_a_season_twice(signed_in, db_session, member):
    """The chest ladder's owed pattern: the surviving miles have to pay for
    every season already borne before a new one comes round."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    doomed = run_miles(db_session, member.id, 33.0, offset_min=200)
    assert (len(batches(db_session, member.id)), meter(db_session, member.id)[1]) == (2, 2)

    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204
    # One season's worth of miles left and two seasons already borne, so the
    # meter parks empty and no fruit is taken back.
    assert meter(db_session, member.id) == (0.0, 2)
    assert len(batches(db_session, member.id)) == 2

    # And putting it back does not bear it a second time.
    assert signed_in.post(f"/api/workouts/{doomed.id}/restore").status_code == 200
    assert meter(db_session, member.id) == (0.0, 2)
    assert len(batches(db_session, member.id)) == 2


def test_a_restore_gives_back_what_the_deletion_took(
    signed_in, db_session, member
):
    """The returning miles repay the season already borne and the meter fills
    back to where it stood; no fruit is taken or borne along the way."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    doomed = run_miles(db_session, member.id, 20.0)
    run_miles(db_session, member.id, 20.0, offset_min=200)
    assert (len(batches(db_session, member.id)), meter(db_session, member.id)) == (
        1,
        (7.0, 1),
    )

    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204
    assert meter(db_session, member.id) == (0.0, 1)
    assert len(batches(db_session, member.id)) == 1

    assert signed_in.post(f"/api/workouts/{doomed.id}/restore").status_code == 200
    assert meter(db_session, member.id) == (7.0, 1)
    assert len(batches(db_session, member.id)) == 1


def test_a_history_older_than_the_meter_never_bears_a_phantom_season(
    signed_in, db_session, member
):
    """The bug 0032 came for. A rebuild replays the surviving fuel and pays back
    only the seasons actually borne, so an account carrying a year of miles the
    meter never walked used to bear a harvest for every one of those crossings
    the first time it deleted anything. The walk starts above the baseline."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 100.0)
    as_a_pre_release_account(db_session, member.id)

    since = run_miles(db_session, member.id, 5.0, offset_min=200)
    assert meter(db_session, member.id) == (5.0, 0)

    assert signed_in.delete(f"/api/workouts/{since.id}").status_code == 204
    # A hundred miles on record, three seasons' worth of them, and not one
    # season: the meter reads what is above the baseline and nothing else.
    assert meter(db_session, member.id) == (0.0, 0)
    assert batches(db_session, member.id) == []

    assert signed_in.post(f"/api/workouts/{since.id}/restore").status_code == 200
    assert meter(db_session, member.id) == (5.0, 0)
    assert batches(db_session, member.id) == []


def test_a_restore_still_bears_what_it_newly_pays_for_above_the_baseline(
    signed_in, db_session, member
):
    """Owed, with a baseline underneath it: the returning miles pay for the
    season already borne again first, and what they cover past it still bears
    the moment they come back."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 100.0)
    as_a_pre_release_account(db_session, member.id)

    doomed = run_miles(db_session, member.id, 20.0, offset_min=200)
    run_miles(db_session, member.id, 20.0, offset_min=400)
    assert (meter(db_session, member.id), len(batches(db_session, member.id))) == ((7.0, 1), 1)

    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204
    assert meter(db_session, member.id) == (0.0, 1)

    # Thirty more while it was away, so the returning twenty pay the season
    # already borne back and carry the grove past the next one.
    run_miles(db_session, member.id, 30.0, offset_min=600)
    assert signed_in.post(f"/api/workouts/{doomed.id}/restore").status_code == 200
    assert meter(db_session, member.id) == (70.0 - 2 * FRUIT_SEASON_MI, 2)
    assert len(batches(db_session, member.id)) == 2


def test_a_rebuild_bears_three_seasons_at_the_most(
    signed_in, db_session, member, monkeypatch
):
    """The flood clamp. Lower FRUIT_SEASON_MI and every account's surviving
    miles newly pay for crossings nobody was there for; the first deletion after
    that would pour a year of harvests into one grove in a single pass. Three
    bear and the rest are forgiven, on the same terms the shortfall the other
    way is forgiven."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 40.0)
    spare = run_miles(db_session, member.id, 5.0, offset_min=200)
    assert (meter(db_session, member.id), len(batches(db_session, member.id))) == ((12.0, 1), 1)

    # The retune: a season is five miles from here, so the forty already run
    # cross eight times, one of which pays the season already borne back.
    monkeypatch.setattr(progress, "FRUIT_SEASON_MI", 5.0)

    assert signed_in.delete(f"/api/workouts/{spare.id}").status_code == 204
    assert meter(db_session, member.id) == (0.0, 4)
    assert len(batches(db_session, member.id)) == 4


def test_a_rebuild_takes_back_the_calories_and_never_the_spend(
    signed_in, db_session, member
):
    """Spent stays spent (R31): a deleted workout lowers what the surviving
    history is worth and never reaches into what has already been fed away."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, member.id, FEED_COST)
    doomed = log_workout(db_session, member.id, "run", 1.0, kcal=300, offset_min=200)
    assert signed_in.post(
        "/api/harvest/feed", json={"planting_id": plant.id}
    ).status_code == 200
    assert state(signed_in)["manna"] == 300

    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204
    assert state(signed_in)["manna"] == 0
    # The fruit it bought is still bought.
    db_session.refresh(plant)
    assert plant.fed_bonus == 1


def test_deleting_past_what_was_spent_empties_the_bank_and_never_goes_below(
    signed_in, db_session, member
):
    """The chest ladder's floor, one column across: an account that spent more
    than its surviving workouts now account for simply waits for the miles."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    doomed = log_workout(db_session, member.id, "run", 1.0, kcal=FEED_COST)
    assert signed_in.post(
        "/api/harvest/feed", json={"planting_id": plant.id}
    ).status_code == 200
    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204

    assert state(signed_in)["manna"] == 0
    # And the next real workout starts filling the bank again from nothing
    # rather than from a debt.
    log_workout(db_session, member.id, "run", 1.0, kcal=100, offset_min=300)
    assert state(signed_in)["manna"] == 100


def test_a_gift_survives_the_receivers_rebuild(signed_in, db_session, member):
    """A gift is nobody's derivation. Taking one of their own runs back must
    never take away what a friend sent."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, member.id, 500)
    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 300})

    doomed = log_workout(db_session, other.id, "run", 2.0, kcal=200)
    assert profile(other_client)["manna"] == 500
    assert other_client.delete(f"/api/workouts/{doomed.id}").status_code == 204
    assert profile(other_client)["manna"] == 300


def test_recompute_lands_where_it_started_and_bears_nothing_again(
    signed_in, db_session, member
):
    """The safety hatch replays the history without harvesting it: the fruit it
    would bear has already been borne, and some of it has been given away."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 40.0, kcal=650)
    gather(signed_in)
    borne = len(batches(db_session, member.id))
    assert (borne, meter(db_session, member.id)) == (1, (7.0, 1))

    progress.recompute(db_session, member.id)
    assert len(batches(db_session, member.id)) == borne
    assert meter(db_session, member.id) == (7.0, 1)
    # The bank is what the replay is worth, because nothing has been spent.
    assert state(signed_in)["manna"] == 650


# --------------------------------------------------------------------------
# Who may read any of it
# --------------------------------------------------------------------------


def test_the_harvest_is_behind_a_session(client, db_session, member):
    for path in ("/api/harvest", "/api/basket"):
        assert client.get(path).status_code == 401
    assert client.post("/api/harvest/gather").status_code == 401
    assert client.post("/api/harvest/feed", json={"planting_id": 1}).status_code == 401
    assert client.post(
        "/api/harvest/manna", json={"user_id": 1, "amount": 5}
    ).status_code == 401
    assert client.post(
        "/api/harvest/fruit", json={"user_id": 1, "count": 1}
    ).status_code == 401


def test_an_account_that_has_done_nothing_reads_an_empty_harvest(db_session, admin):
    person = make_user(db_session, "quiet", "quiet-password-1")
    row = progress.ensure_progress(db_session, person.id)
    assert (row.fruit_progress_mi, row.fruit_seasons) == (0.0, 0)
    assert row.manna == 0
    assert harvest.on_the_plant(db_session, person.id) == []


def test_the_season_is_reported_as_miles_and_never_as_a_clock(
    signed_in, db_session, member
):
    """Your miles are the season. The screen is told how far along the meter is
    and how long a season runs, and nothing anywhere is a date."""
    run_miles(db_session, member.id, 10.0)
    read = state(signed_in)
    assert read["season_mi"] == FRUIT_SEASON_MI
    assert read["season_progress_mi"] == 10.0
    assert not [key for key in read if "days" in key or "until" in key]


def test_the_window_is_seven_days_by_the_clock_and_not_by_a_stored_count(
    signed_in, db_session, member
):
    """The sweep is passive and reads the stamp on the row, so an account that
    is never opened for a fortnight composts on the next read rather than
    holding onto everything until somebody presses something."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    row = db_session.query(models.FruitBatch).one()
    assert row.composted_at is None
    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY + 1)
    harvest.compost(db_session, member.id, dt.datetime.now(dt.timezone.utc))
    db_session.commit()
    db_session.refresh(row)
    assert row.composted_at is not None
