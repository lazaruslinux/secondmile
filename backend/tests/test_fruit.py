"""Fruit: what a grown plant bears, and the four things manna is spent on.

The law this file pins, in one sentence: the MILES decide when a grove bears and
the MANNA decides how much, and neither of them ever crosses into the other's
lane. Nothing here moves experience, a level, a chest, growth or a medal.

The clock never ticks on its own. Everything about the seven days a gathered
pile lives is said with let_a_moment_pass, which pushes what is already stored
into the past, because the suite's now is pinned and a case that means "and then
a week went by" has to say so.
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
from app.config import (
    FEED_COST,
    FEED_MAX_BANKED,
    FRUIT_SEASON_MI,
    GATHERED_LIFE_DAYS,
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


def gather(client, manna: int | None = None) -> dict:
    """Gather, bringing in the whole pending pile unless a case says otherwise.

    The endpoint's own default is none of the manna, because the amount is the
    member's to choose. Most cases here want the lot and are shorter for saying
    so once; the cases about choosing say their own number.
    """
    if manna is None:
        manna = client.get("/api/harvest").json()["manna_pending"]
    response = client.post("/api/harvest/gather", json={"manna": manna})
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


def stock_manna(db_session, client, user_id: int, amount: int, *, offset_min: int = 0) -> None:
    """Put this much GATHERED manna in somebody's pile, and no miles with it.

    A workout with no distance is the whole trick: it burns calories, which is
    the only thing manna comes from, and it moves neither meter.
    """
    log_workout(db_session, user_id, "run", 0.0, kcal=amount, offset_min=offset_min)
    gather(client)


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


def test_one_button_brings_in_the_fruit_and_the_manna_together(
    signed_in, db_session, member
):
    """His pick: one act on the grove, because a grove is one place."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)

    before = state(signed_in)
    assert before["ready"] is True
    assert before["manna_pending"] == 650
    assert before["manna"] == 0
    assert len(before["borne"]) == 1

    taken = gather(signed_in)
    # What this act brought in, said apart from what is now in the pile.
    assert (taken["fruit"], taken["gathered_manna"]) == (3, 650)
    after = state(signed_in)
    assert after["ready"] is False
    assert (after["manna"], after["manna_pending"]) == (650, 0)
    assert after["borne"] == []
    assert [row["count"] for row in after["basket"]] == [3]


def test_manna_comes_in_by_the_amount_the_member_chooses(signed_in, db_session, member):
    """His call, and the reason for it: a pile built out of a year of calories
    is worth far more than a week of giving spends, so gathering all of it would
    be composting most of it seven days later. What is left behind is safe."""
    log_workout(db_session, member.id, "run", 0.0, kcal=1000)
    taken = gather(signed_in, 400)
    assert taken["gathered_manna"] == 400
    read = state(signed_in)
    assert (read["manna"], read["manna_pending"]) == (400, 600)


def test_the_harvest_comes_in_whole_even_when_no_manna_is_asked_for(
    signed_in, db_session, member
):
    """The two halves are not the same shape on purpose: a harvest is a harvest
    and there is nothing to be gained by leaving half of it hanging."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)

    response = signed_in.post("/api/harvest/gather")
    assert response.status_code == 200, response.text
    assert (response.json()["fruit"], response.json()["gathered_manna"]) == (3, 0)
    read = state(signed_in)
    assert len(read["basket"]) == 1
    assert read["manna_pending"] == 650
    assert read["manna"] == 0


def test_what_was_left_pending_outlives_what_was_gathered(signed_in, db_session, member):
    """The seven days only ever run on what somebody deliberately brought in."""
    log_workout(db_session, member.id, "run", 0.0, kcal=1000)
    gather(signed_in, 300)
    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY)

    read = state(signed_in)
    assert (read["manna"], read["manna_pending"]) == (0, 700)


def test_nobody_gathers_more_than_is_waiting(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 0.0, kcal=100)
    refused = signed_in.post("/api/harvest/gather", json={"manna": 500})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "That is more manna than you have waiting."
    assert state(signed_in)["manna_pending"] == 100

    negative = signed_in.post("/api/harvest/gather", json={"manna": -5})
    assert negative.status_code == 400
    assert negative.json()["detail"] == "That is not an amount of manna."


def test_gathering_nothing_is_not_a_refusal(signed_in, db_session, member):
    """A second press a moment later is the same answer as an empty grove:
    nothing moved, and nothing went wrong."""
    taken = gather(signed_in)
    assert (taken["fruit"], taken["gathered_manna"]) == (0, 0)


def test_what_is_not_gathered_is_safe_forever(signed_in, db_session, member):
    """Fruit on the plant and manna in the pile never age. The seven days start
    at the gather and nowhere earlier, which is what makes time away free."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)
    let_a_moment_pass(db_session, seconds=A_LONG_WHILE)

    read = state(signed_in)
    assert len(read["borne"]) == 1
    assert read["manna_pending"] == 650


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


def test_gathered_goods_last_exactly_seven_days(signed_in, db_session, member):
    """Never a day early. The window is the whole of the promise, so the case
    stands a minute inside it and then crosses it."""
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
    assert read["manna"] == 0


def test_compost_leaves_the_plant_and_the_pending_pile_alone(
    signed_in, db_session, member
):
    """Only what was gathered ages. A second harvest still on the plant and a
    pile nobody gathered are both untouched by the sweep."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 33.0, kcal=650)
    gather(signed_in)
    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY)
    # Borne after the gather, so it is still on the plant, and calories with it.
    log_workout(db_session, member.id, "run", 33.0, kcal=400, offset_min=300)

    read = state(signed_in)
    assert read["basket"] == []
    assert len(read["borne"]) == 1
    assert read["manna_pending"] == 400


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


def test_a_composted_pile_is_gone_and_not_merely_hidden(signed_in, db_session, member):
    """What went back to the soil cannot be spent, which is the difference
    between composting and a screen that stopped drawing it."""
    give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST)
    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY)
    run_miles(db_session, member.id, 33.0, offset_min=300)

    plant = db_session.query(models.Planting).first()
    refused = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "You have not gathered enough manna for that."


# --------------------------------------------------------------------------
# Feeding your own grove
# --------------------------------------------------------------------------


def test_feeding_buys_one_more_fruit_on_the_next_bearing(signed_in, db_session, member):
    """A hundred and fifty gathered manna, one more fruit, once. It banks on the
    plant and is spent the moment that plant bears."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST)

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
    stock_manna(db_session, signed_in, member.id, FEED_COST * 5)

    for _ in range(FEED_MAX_BANKED):
        assert signed_in.post("/api/harvest/feed", json={"planting_id": plant.id}).status_code == 200
    refused = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "A plant holds 3 extra fruit at most before it bears."
    # Nothing was taken for the refusal.
    assert state(signed_in)["manna"] == FEED_COST * 2


def test_several_fruit_can_be_bought_in_one_go(signed_in, db_session, member):
    plant = give_planting(db_session, member.id, "olive", growth=100.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST * 3)
    fed = signed_in.post(
        "/api/harvest/feed", json={"planting_id": plant.id, "bonus": 3}
    )
    assert fed.status_code == 200, fed.text
    assert fed.json()["fed"] == 3
    run_miles(db_session, member.id, 33.0, offset_min=300)
    assert [row.count for row in batches(db_session, member.id)] == [4]


def test_feeding_needs_the_manna_gathered_first(signed_in, db_session, member):
    """Pending manna buys nothing. Only what has been brought in is spendable,
    which is the whole reason the gather exists."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    log_workout(db_session, member.id, "run", 0.0, kcal=FEED_COST * 2)
    refused = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "You have not gathered enough manna for that."
    assert state(signed_in)["manna_pending"] == FEED_COST * 2


def test_nothing_ungrown_is_fed(signed_in, db_session, member):
    """A plant that cannot bear cannot be paid to bear more."""
    plant = give_planting(db_session, member.id, "olive", growth=10.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST)
    refused = signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "That one is not grown yet."
    assert state(signed_in)["manna"] == FEED_COST


def test_a_fully_grown_plant_still_takes_feeding(signed_in, db_session, member):
    """Unlike water, which has no level left to buy: a gilded plant still bears,
    so there is still something for manna to do."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0 * species.MAX_LEVEL)
    stock_manna(db_session, signed_in, member.id, FEED_COST)
    assert signed_in.post("/api/harvest/feed", json={"planting_id": plant.id}).status_code == 200
    run_miles(db_session, member.id, 33.0, offset_min=300)
    borne = batches(db_session, member.id)[0]
    assert (borne.golden, borne.count) == (True, 4)


def test_feeding_your_own_plot_pays_no_renown(signed_in, db_session, member):
    """The quiet option. Giving to yourself is not giving, and the ladder says
    so by paying nothing for it."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST)
    signed_in.post("/api/harvest/feed", json={"planting_id": plant.id})
    assert renown_of(db_session, member.id) == 0


def test_feeding_moves_nothing_in_the_earning_lane(signed_in, db_session, member):
    """TWO-LANE LAW, pinned. Manna buys fruit and never a mile of growth, a
    level, a chest or a medal."""
    plant = give_planting(db_session, member.id, "strawberry", growth=15.0)
    run_miles(db_session, member.id, 10.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST * 3, offset_min=100)
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
    stock_manna(db_session, signed_in, member.id, FEED_COST)

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
    stock_manna(db_session, signed_in, member.id, FEED_COST * 2)

    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    db_session.refresh(theirs)
    assert theirs.fed_bonus == 2
    assert renown_of(db_session, member.id) == 5


def test_the_window_opens_again_once_it_has_run_out(signed_in, db_session, member):
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST)

    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    # A week and a day later. Whatever was left in the gathered pile went back
    # to the soil in the meantime, which is why this stocks it again.
    let_a_moment_pass(db_session, seconds=8 * DAY)
    stock_manna(db_session, signed_in, member.id, FEED_COST, offset_min=300)
    signed_in.post("/api/harvest/feed", json={"planting_id": theirs.id})
    assert renown_of(db_session, member.id) == 10


def test_a_strangers_plant_answers_like_one_that_never_existed(
    signed_in, db_session, member
):
    """404 and not 403, the water rule: whose plot an id belongs to is not a
    thing to learn by asking."""
    other, _ = sign_in(db_session, "mate")
    theirs = give_planting(db_session, other.id, "grapevine", growth=40.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST)

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


def test_gifted_manna_joins_their_pending_pile_and_pays_the_giver(
    signed_in, db_session, member
):
    """A gift arrives safe rather than already ageing: it waits in their pending
    pile until they gather it themselves."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, signed_in, member.id, 500)

    sent = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 300})
    assert sent.status_code == 201, sent.text
    assert state(signed_in)["manna"] == 200
    assert profile(other_client)["manna_pending"] == 300
    assert profile(other_client)["manna"] == 0
    assert renown_of(db_session, member.id) == 3
    assert renown_of(db_session, other.id) == 0


def test_a_second_manna_gift_to_the_same_friend_arrives_and_earns_nothing(
    signed_in, db_session, member
):
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, signed_in, member.id, 500)

    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 100})
    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 100})
    assert profile(other_client)["manna_pending"] == 200
    assert renown_of(db_session, member.id) == 3


def test_manna_is_only_given_to_a_friend_and_never_to_yourself(
    signed_in, db_session, member
):
    other, _ = sign_in(db_session, "mate")
    stock_manna(db_session, signed_in, member.id, 500)

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
    stock_manna(db_session, signed_in, member.id, 500)
    refused = signed_in.post(
        "/api/harvest/manna", json={"user_id": other.id, "amount": amount}
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "A gift is at least 1 manna."


def test_nobody_gives_away_more_than_they_gathered(signed_in, db_session, member):
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, signed_in, member.id, 100)
    log_workout(db_session, member.id, "run", 0.0, kcal=900, offset_min=200)

    refused = signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 500})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "You have not gathered enough manna for that."
    assert state(signed_in)["manna"] == 100


def test_gifted_manna_is_gathered_and_spent_like_any_other(
    signed_in, db_session, member
):
    """Once they gather it, it is theirs to spend: a gift is manna, not a token
    of one."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    theirs = give_planting(db_session, other.id, "strawberry", growth=15.0)
    stock_manna(db_session, signed_in, member.id, FEED_COST)

    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": FEED_COST})
    gather(other_client)
    fed = other_client.post("/api/harvest/feed", json={"planting_id": theirs.id})
    assert fed.status_code == 200, fed.text


# --------------------------------------------------------------------------
# Giving fruit away
# --------------------------------------------------------------------------


def hand_over_fruit(db_session, signed_in, member, other):
    """One gathered batch of bananas, given to a friend."""
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    fruit_id = state(signed_in)["basket"][0]["id"]
    return signed_in.post(
        "/api/harvest/fruit", json={"user_id": other.id, "fruit_id": fruit_id}
    )


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
    again = signed_in.post(
        "/api/harvest/fruit",
        json={"user_id": other.id, "fruit_id": state(signed_in)["basket"][0]["id"]},
    )
    assert again.status_code == 201, again.text
    assert len(basket(other_client)) == 2
    assert renown_of(db_session, member.id) == 8


def test_only_gathered_fruit_can_be_given(signed_in, db_session, member):
    """What is still on the plant is not in anybody's hands yet."""
    other, _ = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    borne = batches(db_session, member.id)[0]

    refused = signed_in.post(
        "/api/harvest/fruit", json={"user_id": other.id, "fruit_id": borne.id}
    )
    assert refused.status_code == 404
    assert refused.json()["detail"] == "No such fruit."


def test_the_same_fruit_cannot_be_given_twice(signed_in, db_session, member):
    other, _ = sign_in(db_session, "mate")
    third, _third_client = sign_in(db_session, "third")
    befriend(db_session, member, other)
    befriend(db_session, member, third)

    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    fruit_id = state(signed_in)["basket"][0]["id"]

    assert signed_in.post(
        "/api/harvest/fruit", json={"user_id": other.id, "fruit_id": fruit_id}
    ).status_code == 201
    again = signed_in.post(
        "/api/harvest/fruit", json={"user_id": third.id, "fruit_id": fruit_id}
    )
    assert again.status_code == 404
    assert again.json()["detail"] == "No such fruit."


def test_fruit_is_only_given_to_a_friend_and_never_to_yourself(
    signed_in, db_session, member
):
    other, _ = sign_in(db_session, "mate")
    give_planting(db_session, member.id, "banana", growth=15.0)
    run_miles(db_session, member.id, 33.0)
    gather(signed_in)
    fruit_id = state(signed_in)["basket"][0]["id"]

    stranger = signed_in.post(
        "/api/harvest/fruit", json={"user_id": other.id, "fruit_id": fruit_id}
    )
    assert stranger.status_code == 404
    assert stranger.json()["detail"] == "No such friend."
    myself = signed_in.post(
        "/api/harvest/fruit", json={"user_id": member.id, "fruit_id": fruit_id}
    )
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
    stock_manna(db_session, signed_in, member.id, 500)
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
    stock_manna(db_session, signed_in, member.id, FEED_COST * 2)

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


def test_a_restore_bears_what_the_returning_miles_newly_pay_for(
    signed_in, db_session, member
):
    """The other side of owed: miles beyond the seasons already borne do bear,
    so a restore gives back exactly what the deletion took."""
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


def test_a_rebuild_leaves_gathered_manna_alone_and_recomputes_the_pending_pile(
    signed_in, db_session, member
):
    """Gathering is a spend from the pending pile's side, and spent stays spent:
    a deleted workout reaches into what is still waiting and never into what has
    already been brought in."""
    log_workout(db_session, member.id, "run", 1.0, kcal=500)
    gather(signed_in)
    doomed = log_workout(db_session, member.id, "run", 1.0, kcal=300, offset_min=200)
    read = state(signed_in)
    assert (read["manna"], read["manna_pending"]) == (500, 300)

    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204
    read = state(signed_in)
    assert (read["manna"], read["manna_pending"]) == (500, 0)


def test_deleting_past_what_was_gathered_empties_the_pile_and_never_goes_below(
    signed_in, db_session, member
):
    """The chest ladder's floor, one table across: an account that gathered more
    than its surviving workouts now account for simply waits for the miles."""
    doomed = log_workout(db_session, member.id, "run", 1.0, kcal=500)
    gather(signed_in)
    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204

    read = state(signed_in)
    assert (read["manna"], read["manna_pending"]) == (500, 0)
    # And the next real workout starts filling the pending pile again from
    # nothing rather than from a debt.
    log_workout(db_session, member.id, "run", 1.0, kcal=100, offset_min=300)
    assert state(signed_in)["manna_pending"] == 100


def test_a_gift_survives_the_receivers_rebuild(signed_in, db_session, member):
    """A gift is nobody's derivation. Taking one of their own runs back must
    never take away what a friend sent."""
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    stock_manna(db_session, signed_in, member.id, 500)
    signed_in.post("/api/harvest/manna", json={"user_id": other.id, "amount": 300})

    doomed = log_workout(db_session, other.id, "run", 2.0, kcal=200)
    assert profile(other_client)["manna_pending"] == 500
    assert other_client.delete(f"/api/workouts/{doomed.id}").status_code == 204
    assert profile(other_client)["manna_pending"] == 300


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
    # Gathered stays gathered, and the pending pile is what the replay is worth
    # less what has already left it.
    read = state(signed_in)
    assert (read["manna"], read["manna_pending"]) == (650, 0)


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
        "/api/harvest/fruit", json={"user_id": 1, "fruit_id": 1}
    ).status_code == 401


def test_an_account_that_has_done_nothing_reads_an_empty_harvest(db_session, admin):
    person = make_user(db_session, "quiet", "quiet-password-1")
    row = progress.ensure_progress(db_session, person.id)
    assert (row.fruit_progress_mi, row.fruit_seasons) == (0.0, 0)
    assert harvest.gathered_manna(db_session, person.id) == 0
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
    log_workout(db_session, member.id, "run", 1.0, kcal=500)
    gather(signed_in)
    row = db_session.query(models.MannaBatch).one()
    assert row.composted_at is None
    let_a_moment_pass(db_session, seconds=GATHERED_LIFE_DAYS * DAY + 1)
    harvest.compost(db_session, member.id, dt.datetime.now(dt.timezone.utc))
    db_session.commit()
    db_session.refresh(row)
    assert row.composted_at is not None
