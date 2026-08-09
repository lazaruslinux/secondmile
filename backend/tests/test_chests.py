"""The chest ladder, what comes out of a chest, and the recap letter."""

import datetime as dt
import random

from conftest import give_item, give_planting, log_workout, neutral_start

from app import models, progress, security, species
from app.config import CHEST_LADDER, CHEST_TIER_FLOOR


def give_chest(db_session, user_id: int, tier: str | None = "5k") -> models.Chest:
    chest = models.Chest(
        user_id=user_id,
        tier=tier,
        from_anointing_id=None,
        dropped_at=security.now_utc(),
        opened_at=None,
    )
    db_session.add(chest)
    db_session.commit()
    return chest


def give_lifted_chest(db_session, user_id: int, giver_id: int, tier: str | None = "5k"):
    """A chest somebody's oil was spent on, wired the way the pipeline wires
    one: a spent anointing, and the chest pointing back at it."""
    anointing = models.Anointing(
        from_user_id=giver_id,
        to_user_id=user_id,
        created_at=security.now_utc(),
        consumed_at=security.now_utc(),
    )
    db_session.add(anointing)
    db_session.flush()
    chest = models.Chest(
        user_id=user_id,
        tier=tier,
        from_anointing_id=anointing.id,
        dropped_at=security.now_utc(),
        opened_at=None,
    )
    db_session.add(chest)
    db_session.flush()
    anointing.consumed_chest_id = chest.id
    db_session.commit()
    return chest


def open_one(client, db_session, user_id) -> dict:
    """Open a throwaway chest, which is how a test gets past the mustard seed
    the first chest of an account always holds."""
    chest = give_chest(db_session, user_id)
    body = client.post(f"/api/chests/{chest.id}/open")
    assert body.status_code == 200, body.text
    return body.json()


def chests(db_session, user_id) -> list[models.Chest]:
    return (
        db_session.query(models.Chest)
        .filter(models.Chest.user_id == user_id)
        .order_by(models.Chest.id)
        .all()
    )


# --------------------------------------------------------------------------
# The ladder
# --------------------------------------------------------------------------


def test_the_ladder_is_the_race_distances_and_it_repeats():
    assert [cost for _id, _name, cost in CHEST_LADDER] == [3.1, 6.2, 13.1, 26.2, 31.1]
    assert [name for _id, name, _cost in CHEST_LADDER] == [
        "5K",
        "10K",
        "Half",
        "Marathon",
        "Ultra",
    ]
    # Position five is position zero again: the wheel turns rather than ending.
    assert progress.ladder_step(5) == progress.ladder_step(0)
    assert progress.ladder_step(9) == progress.ladder_step(4)


def test_chests_drop_in_ladder_order(signed_in, db_session, member):
    """The cycle costs 79.7 Miles; eighty three of them starts the next one."""
    log_workout(signed_in, "run", 30.0, pace_min=9, offset_min=0)
    log_workout(signed_in, "cycle", 160.0, pace_min=3, offset_min=400)
    dropped = [row.tier for row in chests(db_session, member.id)]
    assert dropped[:5] == ["5k", "10k", "half", "marathon", "ultra"]
    assert dropped[5:6] == ["5k"]


def test_the_accumulator_carries_between_workouts(signed_in, db_session, member):
    log_workout(signed_in, "run", 2.0, offset_min=0)
    row = db_session.get(models.UserProgress, member.id)
    assert chests(db_session, member.id) == []
    assert row.chest_progress_mi == 2.0
    assert row.cycle_pos == 0

    # A mile and a bit later the 5K chest lands, and the overshoot carries.
    log_workout(signed_in, "run", 1.2, offset_min=60)
    row = db_session.get(models.UserProgress, member.id)
    assert [chest.tier for chest in chests(db_session, member.id)] == ["5k"]
    assert row.cycle_pos == 1
    assert abs(row.chest_progress_mi - 0.1) < 1e-6


def test_the_profile_says_which_chest_is_coming(signed_in):
    log_workout(signed_in, "run", 2.0)
    body = signed_in.get("/api/profile").json()
    # Nobody has spent oil on this account, so nothing is lifting it.
    assert body["next_chest"] == {
        "tier": "5K",
        "tier_id": "5k",
        "miles_away": 1.1,
        "gifted_by": None,
    }
    assert body["pending_gifts"] == []


def test_every_activity_fuels_the_ladder(signed_in, db_session, member):
    """Nine cycled miles are three Miles, the same as three run ones."""
    log_workout(signed_in, "cycle", 9.3, pace_min=3)
    assert [chest.tier for chest in chests(db_session, member.id)] == ["5k"]


def test_a_rebuild_walks_the_same_ladder(signed_in, db_session, member):
    log_workout(signed_in, "walk", 6.0, offset_min=0)
    log_workout(signed_in, "run", 7.0, offset_min=200)
    before = [row.tier for row in chests(db_session, member.id)]
    assert before
    rebuilt = progress.recompute(db_session, member.id)
    assert [row.tier for row in chests(db_session, member.id)] == before
    assert rebuilt.cycle_pos == db_session.get(models.UserProgress, member.id).cycle_pos


# --------------------------------------------------------------------------
# What is in them
# --------------------------------------------------------------------------


def test_the_ladder_is_the_floor_and_the_only_way_is_up():
    """Every step names the rarity its chest is worth at worst."""
    assert [CHEST_TIER_FLOOR[tier_id] for tier_id, _name, _cost in CHEST_LADDER] == [
        "common",
        "uncommon",
        "rare",
        "epic",
        "legendary",
    ]
    # The two above the seeds are item rarities and nothing in the catalogue
    # claims them.
    assert species.RARITY_LADDER == ("common", "uncommon", "rare", "epic", "legendary")
    assert not [row for row in species.BY_ID.values() if row.rarity in ("epic", "legendary")]


def test_a_chest_is_its_own_step_four_times_in_five():
    """The other time it is exactly one rarity above it, and never further."""
    rng = random.Random("floor")
    for tier_id, _name, _cost in CHEST_LADDER:
        floor = CHEST_TIER_FLOOR[tier_id]
        step = species.RARITY_LADDER.index(floor)
        above = species.RARITY_LADDER[min(step + 1, len(species.RARITY_LADDER) - 1)]
        rolls = [progress.roll_slot(rng, tier_id) for _ in range(4000)]
        assert set(rolls) <= {floor, above}, tier_id
        assert abs(rolls.count(floor) / 4000 - (0.80 if above != floor else 1.0)) < 0.04, tier_id


def test_an_ultra_chest_is_always_a_legendary():
    """The top of the ladder has nothing above it to climb to."""
    rng = random.Random("ultra")
    assert {progress.roll_slot(rng, "ultra") for _ in range(4000)} == {"legendary"}


def test_a_lifted_chest_takes_the_step_up_every_time():
    """Oil is that same upgrade promised rather than risked, so a chest a
    friend paid for is never merely its own step."""
    rng = random.Random("lifted")
    for tier_id, _name, _cost in CHEST_LADDER:
        step = species.RARITY_LADDER.index(CHEST_TIER_FLOOR[tier_id])
        above = species.RARITY_LADDER[min(step + 1, len(species.RARITY_LADDER) - 1)]
        assert {progress.roll_slot(rng, tier_id, True) for _ in range(500)} == {above}, tier_id
    # Which is why an Ultra is worth nothing to give: the step it takes is the
    # rung it already stood on.
    assert progress.can_lift("ultra") is False
    assert all(progress.can_lift(tier_id) for tier_id, _name, _cost in CHEST_LADDER[:4])
    # A chest from before the ladder rolls as the first step here too.
    assert progress.can_lift(None) is True


def test_a_lifted_chest_draws_the_same_rolls_as_a_plain_one():
    """The upgrade roll still happens on a lifted chest, so the generator is
    left in the same place either way and nothing after it shifts."""
    plain = random.Random("stream")
    lifted = random.Random("stream")
    for _ in range(200):
        progress.roll_slot(plain, "5k")
        progress.roll_slot(lifted, "5k", True)
    assert plain.random() == lifted.random()


def test_opening_a_lifted_chest_hands_over_the_better_slot(
    signed_in, db_session, member, admin
):
    """The promise is kept at the lid, which is where every other roll happens."""
    open_one(signed_in, db_session, member.id)
    chest = give_lifted_chest(db_session, member.id, admin.id, tier="half")
    body = signed_in.post(f"/api/chests/{chest.id}/open").json()
    # A Half floors at rare; lifted, it is an epic, and the epic slot is the
    # two tools.
    assert body["rarity"] == "epic"
    assert body["kind"] in ("wish", "oil")


def test_a_chest_from_before_the_ladder_rolls_the_first_step(signed_in, db_session, member):
    rng = random.Random("legacy")
    rolls = [progress.roll_slot(rng, None) for _ in range(4000)]
    assert set(rolls) == {"common", "uncommon"}
    assert abs(rolls.count("common") / 4000 - 0.80) < 0.04

    # And it opens like any other, named for the step it is worth.
    open_one(signed_in, db_session, member.id)
    legacy = give_chest(db_session, member.id, tier=None)
    body = signed_in.post(f"/api/chests/{legacy.id}/open").json()
    assert body["tier"] == "5K"
    assert body["tier_id"] == "5k"
    assert body["kind"] in ("seed", "water")


def test_each_slot_holds_its_own_tools():
    """The second roll: which tool the slot hands over once it is decided."""
    rng = random.Random("slots")
    seen: dict[str, list[str]] = {rarity: [] for rarity in species.RARITY_LADDER}
    for tier_id, _name, _cost in CHEST_LADDER:
        for _ in range(8000):
            kind, _species_id, rarity = progress.roll_loot(rng, tier_id, False)
            seen[rarity].append(kind)
    for rarity, wanted in (("common", 0.15), ("uncommon", 0.30), ("rare", 0.20)):
        share = seen[rarity].count("water") / len(seen[rarity])
        assert abs(share - wanted) < 0.03, rarity
        assert set(seen[rarity]) == {"seed", "water"}, rarity
    # The two slots above the seeds hold no seed at all: the epic is the two
    # tools in even halves and the legendary is oil, every time.
    assert set(seen["epic"]) == {"wish", "oil"}
    assert abs(seen["epic"].count("oil") / len(seen["epic"]) - 0.5) < 0.03
    assert set(seen["legendary"]) == {"oil"}


def test_an_epic_slot_is_half_a_wish_and_half_oil():
    """Why it is not the wish alone: a wish falls to water once the plot holds
    all twelve, so a slot made only of wishes is water forever to anybody who
    finished. The oil half keeps an epic chest worth opening at the end."""
    rng = random.Random("epic-split")
    kinds = [
        kind
        for kind, _species_id, rarity in (
            progress.roll_loot(rng, "marathon", False) for _ in range(4000)
        )
        if rarity == "epic"
    ]
    assert set(kinds) == {"wish", "oil"}
    assert abs(kinds.count("oil") / len(kinds) - 0.5) < 0.04

    # And the half that is oil owes the plot nothing, so a finished grove still
    # gets it: what used to be water end to end is now half a gift to give away.
    full = {row.id for row in species.BY_ID.values()}
    finished = [
        kind
        for kind, _species_id, rarity in (
            progress.roll_loot(rng, "marathon", False, full) for _ in range(4000)
        )
        if rarity == "epic"
    ]
    assert set(finished) == {"water", "oil"}


def test_a_seed_comes_out_of_the_slot_it_was_rolled_in():
    rng = random.Random("seeds")
    for _ in range(500):
        kind, species_id, rarity = progress.roll_loot(rng, "half", False)
        if kind != "seed":
            assert species_id is None
            continue
        assert species.BY_ID[species_id].rarity == rarity
        # Never the one that is only ever given.
        assert species_id != species.FIRST_CHEST_SPECIES


# --------------------------------------------------------------------------
# One of each: what a chest does about something already held
# --------------------------------------------------------------------------


def hold(db_session, user_id: int, species_ids, *, planted: bool) -> None:
    """Put species into an account, either in the ground or in the satchel.

    Both count as held, which is the whole of the rule: a seed nobody has
    planted yet is still a plant that account is going to have.
    """
    for species_id in species_ids:
        rarity = species.BY_ID[species_id].rarity
        if planted:
            db_session.add(
                models.Planting(
                    user_id=user_id,
                    species=species_id,
                    rarity=rarity,
                    planted_at=security.now_utc(),
                    growth_mi=0.0,
                    matured_at=None,
                )
            )
        else:
            db_session.add(
                models.SatchelItem(
                    user_id=user_id,
                    kind="seed",
                    species=species_id,
                    rarity=rarity,
                    chest_id=None,
                    acquired_at=security.now_utc(),
                    used_at=None,
                )
            )
    db_session.commit()


def test_a_seed_already_held_is_rolled_again_inside_its_own_rarity():
    held = {"strawberry", "banana", "raspberry"}
    rng = random.Random("reroll")
    seen = set()
    for _ in range(3000):
        kind, species_id, rarity = progress.roll_loot(rng, "5k", False, held)
        if kind != "seed":
            continue
        seen.add(species_id)
        # Never a duplicate, and never a rarity other than the one rolled.
        assert species_id not in held
        assert species.BY_ID[species_id].rarity == rarity
    # The one common left is still handed out, which is the point of re-rolling
    # rather than simply refusing.
    assert "blueberry" in seen


def test_a_rarity_with_nothing_left_to_want_pours_water():
    held = {row.id for row in species.BY_RARITY["common"]}
    rng = random.Random("full")
    kinds = set()
    for _ in range(2000):
        kind, species_id, rarity = progress.roll_loot(rng, "5k", False, held)
        if rarity != "common":
            continue
        kinds.add(kind)
        assert species_id is None
    assert kinds == {"water"}


def test_a_full_rare_slot_pours_water_for_the_whole_of_it():
    """The rule reaches every seed slot the same way: with nothing left to want
    among the rares, a rare slot is water from end to end."""
    held = {row.id for row in species.BY_RARITY["rare"]}
    rng = random.Random("rare-full")
    rolls = [progress.roll_loot(rng, "half", False, held) for _ in range(4000)]
    rare = [row for row in rolls if row[2] == "rare"]
    assert rare, "a Half chest floors at the rare slot"
    assert {kind for kind, _species_id, _rarity in rare} == {"water"}
    # The tree that is only ever given is in no bag this reaches into.
    assert all(species_id is None for _kind, species_id, _rarity in rare)


def test_a_legendary_slot_pays_oil_whatever_the_plot_holds():
    """Oil is not a seed and owes the plot nothing: a full grove changes it in
    no way at all."""
    held = {row.id for row in species.BY_ID.values()}
    rng = random.Random("oil")
    rolls = [progress.roll_loot(rng, "ultra", False, held) for _ in range(2000)]
    assert {row for row in rolls} == {("oil", None, "legendary")}


def test_water_and_oil_come_up_exactly_as_they_always_did():
    """Same seed, same chest: a roll that was neither a seed nor a wish lands
    identically whatever the account is already holding. Those two are the only
    ones that read the plot."""
    held = {row.id for row in species.BY_ID.values()}
    for seed in range(400):
        for tier_id, _name, _cost in CHEST_LADDER:
            empty = progress.roll_loot(random.Random(seed), tier_id, False)
            full = progress.roll_loot(random.Random(seed), tier_id, False, held)
            # The rarity slot is rolled before anything knows about the plot.
            assert full[2] == empty[2]
            if empty[0] not in ("seed", "wish"):
                assert full == empty


def test_a_wish_falls_to_water_once_there_is_nothing_left_to_wish_for():
    """The last rule of the satchel, said again at the top of the ladder: there
    is no such thing as an item worth nothing."""
    rng = random.Random("wishes")
    full = {row.id for row in species.BY_ID.values()}
    # One short of the whole twelve is still something to wish for.
    nearly = full - {"pomegranate"}
    for held, wanted in ((frozenset(), "wish"), (nearly, "wish"), (full, "water")):
        rolls = [progress.roll_loot(rng, "marathon", False, held) for _ in range(500)]
        epic = [row for row in rolls if row[2] == "epic"]
        assert epic, "a Marathon chest floors at the epic slot"
        # Oil is the other half of the slot and reads nothing about the plot,
        # so it is there whatever is held; the wish half is what this is about.
        assert {row[0] for row in epic} == {wanted, "oil"}
        assert all(row[1] is None for row in epic)


def test_a_chest_from_before_the_ladder_obeys_the_rule_too():
    held = {"strawberry", "banana"}
    rng = random.Random("legacy-reroll")
    for _ in range(2000):
        kind, species_id, _rarity = progress.roll_loot(rng, None, False, held)
        if kind == "seed":
            assert species_id not in held


def test_the_mustard_seed_is_given_whatever_the_plot_already_holds(
    signed_in, db_session, member
):
    """The first chest overrides every roll, and the rule is one of the rolls."""
    hold(db_session, member.id, [row.id for row in species.BY_RARITY["rare"]], planted=True)
    first = give_chest(db_session, member.id, "ultra")
    body = signed_in.post(f"/api/chests/{first.id}/open").json()
    assert (body["kind"], body["species"], body["rarity"]) == ("seed", "mustard", "rare")


def test_a_chest_lands_on_the_same_thing_however_often_it_is_replayed(
    signed_in, db_session, member
):
    """Wind the account back to exactly where it was and open the same chest
    again: the roll is seeded on the pair, so it comes up with the same item."""
    open_one(signed_in, db_session, member.id)
    chest = give_chest(db_session, member.id, "marathon")
    first = signed_in.post(f"/api/chests/{chest.id}/open").json()

    db_session.delete(db_session.get(models.SatchelItem, first["id"]))
    db_session.get(models.Chest, chest.id).opened_at = None
    db_session.commit()

    again = signed_in.post(f"/api/chests/{chest.id}/open").json()
    assert [again[field] for field in ("kind", "species", "rarity")] == [
        first[field] for field in ("kind", "species", "rarity")
    ]


def test_no_chest_ever_hands_over_a_second_of_the_same_plant(
    signed_in, db_session, member
):
    """Twelve chests over the whole ladder, against an account that already has
    both a full plot of commons and a satchel of unplanted uncommons."""
    open_one(signed_in, db_session, member.id)
    hold(db_session, member.id, [row.id for row in species.BY_RARITY["common"]], planted=True)
    hold(
        db_session, member.id, [row.id for row in species.BY_RARITY["uncommon"]], planted=False
    )

    held = {row.id for row in species.BY_RARITY["common"]}
    held |= {row.id for row in species.BY_RARITY["uncommon"]}
    for step, (tier_id, _name, _cost) in enumerate(CHEST_LADDER * 3):
        chest = give_chest(db_session, member.id, tier_id)
        body = signed_in.post(f"/api/chests/{chest.id}/open").json()
        if body["kind"] != "seed":
            continue
        assert body["species"] not in held, step
        held.add(body["species"])

    # And nothing anywhere in the account is doubled up.
    planted = [row.species for row in db_session.query(models.Planting).all()]
    waiting = [
        row.species
        for row in db_session.query(models.SatchelItem).all()
        if row.kind == "seed" and row.used_at is None
    ]
    assert len(planted + waiting) == len(set(planted + waiting))


def test_the_first_chest_an_account_opens_holds_the_mustard_seed(
    signed_in, db_session, member
):
    first = give_chest(db_session, member.id, "ultra")
    body = signed_in.post(f"/api/chests/{first.id}/open").json()
    assert body["species"] == "mustard"
    assert body["kind"] == "seed"
    # It rolls in the rare slot like any other seed there.
    assert body["rarity"] == "rare"
    # The one rule the game explains, said here and nowhere else.
    assert body["reveal"] == "You will only ever receive one."

    # And never again, however many chests follow.
    later = [open_one(signed_in, db_session, member.id) for _ in range(6)]
    assert all(row["species"] != "mustard" for row in later)
    # Nothing else has a word to say about itself.
    assert all(row["reveal"] is None for row in later)


def test_opening_a_chest_puts_the_item_in_the_satchel(signed_in, db_session, member):
    chest = give_chest(db_session, member.id, "marathon")
    body = signed_in.post(f"/api/chests/{chest.id}/open").json()
    # The item itself, in the shape the satchel lists it in, and the tier.
    assert set(body) == {
        "id",
        "kind",
        "species",
        "seed_name",
        "plant_name",
        "rarity",
        "reveal",
        "acquired_at",
        "tier",
        "tier_id",
    }
    assert (body["tier"], body["tier_id"]) == ("Marathon", "marathon")

    satchel = signed_in.get("/api/satchel").json()
    assert [row["id"] for row in satchel] == [body["id"]]
    # Opened chests leave the pending list.
    assert signed_in.get("/api/chests").json() == []


def test_opening_the_same_chest_twice_is_a_conflict(signed_in, db_session, member):
    chest = give_chest(db_session, member.id)
    assert signed_in.post(f"/api/chests/{chest.id}/open").status_code == 200
    assert signed_in.post(f"/api/chests/{chest.id}/open").status_code == 409
    # And it gave out exactly one item.
    assert len(signed_in.get("/api/satchel").json()) == 1


def test_somebody_elses_chest_answers_like_one_that_never_existed(
    signed_in, db_session, admin, member
):
    theirs = give_chest(db_session, admin.id)
    mine = signed_in.post(f"/api/chests/{theirs.id}/open")
    missing = signed_in.post("/api/chests/999999/open")
    assert mine.status_code == missing.status_code == 404
    assert mine.json() == missing.json()
    assert db_session.get(models.Chest, theirs.id).opened_at is None


def test_a_closed_chest_says_only_which_step_dropped_it(signed_in, db_session, member):
    give_chest(db_session, member.id, "half")
    listed = signed_in.get("/api/chests").json()
    assert len(listed) == 1
    assert set(listed[0]) == {"id", "dropped_at", "tier", "tier_id"}
    assert (listed[0]["tier"], listed[0]["tier_id"]) == ("Half", "half")


# --------------------------------------------------------------------------
# The cards are gone
# --------------------------------------------------------------------------


def test_nothing_is_left_of_the_cards(signed_in):
    assert signed_in.get("/api/album").status_code == 404
    assert signed_in.get("/api/cards").status_code == 404
    for path in ("/api/profile", "/api/recap", "/api/chests"):
        body = signed_in.get(path).text
        assert "card" not in body.lower(), path


def test_the_achievements_endpoint_is_gone(signed_in):
    """Achievements retired as a system: the medals took their place, and there
    is no catalogue left to ask for."""
    assert signed_in.get("/api/achievements").status_code == 404


# --------------------------------------------------------------------------
# The letter
# --------------------------------------------------------------------------


def test_the_recap_carries_chests_medals_and_miles_then_clears(signed_in):
    log_workout(signed_in, "run", 11.0, pace_min=9)
    recap = signed_in.get("/api/recap").json()
    assert list(recap) == [
        "since",
        "last_sync_at",
        "miles",
        "encouragement",
        "medals",
        "plant_growth",
        "chests_delivered",
        "chest_givers",
        "flourish_stage",
        "flourish_rose",
    ]
    assert recap["since"] is None
    assert recap["miles"] == 11.0
    # Eleven Miles is the 5K chest and the 10K one, announced as a number
    # rather than listed: the letter no longer opens anything.
    assert recap["chests_delivered"] == 2
    # Nothing was given, so nothing is attributed to anybody.
    assert recap["chest_givers"] == []
    # Eleven miles in one run is a 10K and a ten-mile week, and both families
    # are in the letter. Each entry is the id, the label, and the date.
    assert [row["id"] for row in recap["medals"]] == ["race_10k", "weekly_10"]
    assert set(recap["medals"][0]) == {"id", "name", "earned_at"}
    assert recap["medals"][1]["name"] == "10-mile week"

    assert signed_in.post("/api/recap/ack").status_code == 204
    cleared = signed_in.get("/api/recap").json()
    assert cleared["since"] is not None
    assert cleared["miles"] == 0.0
    assert cleared["medals"] == []
    # Chests are not cleared by acknowledging: they wait in the inventory.
    assert cleared["chests_delivered"] == 2


def test_the_count_falls_as_chests_are_opened_elsewhere(signed_in, db_session, member):
    """The letter counts what is closed, so opening one in the inventory is
    what makes the announcement smaller. Nothing in the letter did it."""
    log_workout(signed_in, "run", 11.0, pace_min=9)
    assert signed_in.get("/api/recap").json()["chests_delivered"] == 2

    waiting = signed_in.get("/api/chests").json()
    assert signed_in.post(f"/api/chests/{waiting[0]['id']}/open").status_code == 200
    assert signed_in.get("/api/recap").json()["chests_delivered"] == 1


def test_the_letter_names_who_lifted_a_chest(signed_in, db_session, member, admin):
    """One name per lifted chest, so the letter can say which of them a friend
    paid for. The chests nobody's oil touched are not named, which is what makes
    the count and the names two different numbers."""
    give_lifted_chest(db_session, member.id, admin.id)
    give_chest(db_session, member.id)
    give_lifted_chest(db_session, member.id, admin.id, tier="half")

    recap = signed_in.get("/api/recap").json()
    assert recap["chests_delivered"] == 3
    assert recap["chest_givers"] == [admin.username, admin.username]


def test_an_account_that_never_synced_has_no_sync_to_report(signed_in):
    """Null rather than an error, and a workout typed in by hand is not a sync:
    the line is about the phone, and this player has not got one talking yet."""
    assert signed_in.get("/api/recap").json()["last_sync_at"] is None
    log_workout(signed_in, "run", 3.0)
    assert signed_in.get("/api/recap").json()["last_sync_at"] is None


def test_the_letter_says_when_the_phone_last_synced(signed_in, ingest_token, db_session):
    """The newest export's arrival, in UTC, for the client to render in the
    instance timezone the way it renders every other stamp."""
    for _ in range(2):
        response = signed_in.post(
            "/api/ingest",
            json={"data": {"workouts": []}},
            headers={"Authorization": f"Bearer {ingest_token}"},
        )
        assert response.status_code == 200, response.text

    newest = (
        db_session.query(models.IngestLog).order_by(models.IngestLog.received_at.desc()).first()
    )
    assert signed_in.get("/api/recap").json()["last_sync_at"] == newest.received_at.isoformat()


def test_a_plant_that_finished_a_level_is_in_the_letter(signed_in, db_session, member):
    """A strawberry costs fifteen Miles a level, so sixteen of them is one
    level and the letter can say which plant reached what."""
    give_planting(db_session, member.id, "strawberry")
    log_workout(signed_in, "run", 16.0, pace_min=9)

    grown = signed_in.get("/api/recap").json()["plant_growth"]
    assert [(row["species"], row["level"], row["levels_gained"]) for row in grown] == [
        ("strawberry", 1, 1)
    ]
    # The plot's own shape, so nothing on the client composes the name.
    assert grown[0]["plant_name"] == "Strawberry bush"


def test_a_plant_that_only_grew_a_little_says_nothing(signed_in, db_session, member):
    """Silence, not a sentence about how far off the next level is. Five Miles
    into a fifteen Mile level is not news."""
    give_planting(db_session, member.id, "strawberry")
    log_workout(signed_in, "run", 5.0)
    assert signed_in.get("/api/recap").json()["plant_growth"] == []


def test_a_level_water_alone_paid_for_is_in_the_letter(signed_in, db_session, member):
    """Nothing records which planting a water item went into, so this is the
    case the old subtraction could not see: five Miles short of a level, and the
    ten a watering can is worth carries it over."""
    planting = give_planting(db_session, member.id, "strawberry", growth=10.0)
    item = give_item(db_session, member.id, "water")
    poured = signed_in.post(
        f"/api/satchel/{item.id}/pour", json={"planting_id": planting.id}
    )
    assert poured.status_code == 200, poured.text

    grown = signed_in.get("/api/recap").json()["plant_growth"]
    assert [(row["species"], row["level"], row["levels_gained"]) for row in grown] == [
        ("strawberry", 1, 1)
    ]


def test_a_plant_with_no_recorded_level_says_nothing(signed_in, db_session, member):
    """A plant that predates the column. Silence rather than announcing a level
    it reached weeks ago, and it joins in once an acknowledgement writes the
    number down."""
    planting = give_planting(db_session, member.id, "strawberry", growth=40.0)
    planting.level_at_ack = None
    db_session.commit()
    log_workout(signed_in, "run", 16.0, pace_min=9)
    assert signed_in.get("/api/recap").json()["plant_growth"] == []

    assert signed_in.post("/api/recap/ack").status_code == 204
    db_session.refresh(planting)
    assert planting.level_at_ack == 3
    log_workout(signed_in, "run", 16.0, pace_min=9, offset_min=300)
    grown = signed_in.get("/api/recap").json()["plant_growth"]
    assert [(row["level"], row["levels_gained"]) for row in grown] == [(4, 1)]


def test_a_level_already_announced_is_not_announced_again(signed_in, db_session, member):
    """Acknowledging the letter writes down where every plant stood, so the
    next one really does start from there."""
    give_planting(db_session, member.id, "strawberry")
    log_workout(signed_in, "run", 16.0, pace_min=9, offset_min=0)
    assert len(signed_in.get("/api/recap").json()["plant_growth"]) == 1

    assert signed_in.post("/api/recap/ack").status_code == 204
    log_workout(signed_in, "run", 2.0, offset_min=300)
    assert signed_in.get("/api/recap").json()["plant_growth"] == []

    # And the next level is news again when it actually lands.
    log_workout(signed_in, "run", 13.0, pace_min=9, offset_min=600)
    grown = signed_in.get("/api/recap").json()["plant_growth"]
    assert [(row["level"], row["levels_gained"]) for row in grown] == [(2, 1)]


def test_a_medal_from_a_backdated_run_still_reaches_the_recap(signed_in, db_session, member):
    """The run happened last month; the sync happened this morning. What makes
    it news is when it arrived, which is the same rule the miles follow."""
    signed_in.post("/api/recap/ack")
    db_session.add(
        models.Workout(
            user_id=member.id,
            activity="run",
            start_ts=neutral_start() - dt.timedelta(days=40),
            duration_s=90 * 60,
            distance_mi=10.5,
            active_kcal=600.0,
            avg_hr=None,
            source="sync",
            flags={},
            created_at=security.now_utc(),
        )
    )
    db_session.commit()
    progress.process_user(db_session, member.id)
    recap = signed_in.get("/api/recap").json()
    # The weekly medal follows the same rule, filtered by the arrival of the
    # workout that crossed the line rather than by the date on it.
    assert [row["id"] for row in recap["medals"]] == ["race_10k", "weekly_10"]
    assert all(row["earned_at"] < recap["since"] for row in recap["medals"])


def test_the_chest_endpoints_need_a_session(client):
    assert client.get("/api/chests").status_code == 401
    assert client.post("/api/chests/1/open").status_code == 401
    assert client.get("/api/recap").status_code == 401
    assert client.post("/api/recap/ack").status_code == 401
