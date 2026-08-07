"""The chest ladder, what comes out of a chest, and the recap letter."""

import datetime as dt
import random

from conftest import log_workout

from app import models, progress, security, species
from app.config import CHEST_LADDER, CHEST_TIER_ODDS


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
    assert body["next_chest"] == {"tier": "5K", "tier_id": "5k", "miles_away": 1.1}


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


def test_the_tier_odds_are_the_documented_ones():
    rng = random.Random("odds")
    for tier, (common, uncommon, rare) in CHEST_TIER_ODDS.items():
        rolls = [progress.roll_slot(rng, tier) for _ in range(4000)]
        assert abs(rolls.count("common") / 4000 - common) < 0.04, tier
        assert abs(rolls.count("uncommon") / 4000 - uncommon) < 0.04, tier
        assert abs(rolls.count("rare") / 4000 - rare) < 0.04, tier
    # The Ultra chest never holds a common, which is the whole point of it.
    assert "common" not in {progress.roll_slot(rng, "ultra") for _ in range(2000)}


def test_a_chest_from_before_the_ladder_rolls_the_first_step(signed_in, db_session, member):
    rng = random.Random("legacy")
    rolls = [progress.roll_slot(rng, None) for _ in range(4000)]
    assert abs(rolls.count("common") / 4000 - 0.70) < 0.04

    # And it opens like any other, named for the step it is worth.
    open_one(signed_in, db_session, member.id)
    legacy = give_chest(db_session, member.id, tier=None)
    body = signed_in.post(f"/api/chests/{legacy.id}/open").json()
    assert body["tier"] == "5K"
    assert body["tier_id"] == "5k"
    assert body["kind"] in ("seed", "water", "oil")


def test_each_slot_holds_its_own_tools():
    """The second roll: which tool the slot hands over once it is decided."""
    rng = random.Random("slots")
    seen: dict[str, list[str]] = {"common": [], "uncommon": [], "rare": []}
    for _ in range(20000):
        kind, _species_id, rarity = progress.roll_loot(rng, "half", False)
        seen[rarity].append(kind)
    for rarity, wanted in (("common", 0.15), ("uncommon", 0.30), ("rare", 0.30)):
        tool = "oil" if rarity == "rare" else "water"
        share = seen[rarity].count(tool) / len(seen[rarity])
        assert abs(share - wanted) < 0.03, rarity
    # Oil is a rare-slot thing only, and no tree ever comes with a watering can.
    assert "oil" not in seen["common"] and "oil" not in seen["uncommon"]
    assert "water" not in seen["rare"]


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


def test_the_first_chest_an_account_opens_holds_the_mustard_seed(
    signed_in, db_session, member
):
    first = give_chest(db_session, member.id, "ultra")
    body = signed_in.post(f"/api/chests/{first.id}/open").json()
    assert body["species"] == "mustard"
    assert body["kind"] == "seed"
    # Nothing anywhere says it is unusual: it is a rare seed like any other.
    assert body["rarity"] == "rare"

    # And never again, however many chests follow.
    later = [open_one(signed_in, db_session, member.id) for _ in range(6)]
    assert all(row["species"] != "mustard" for row in later)


def test_opening_a_chest_puts_the_item_in_the_satchel(signed_in, db_session, member):
    chest = give_chest(db_session, member.id, "marathon")
    body = signed_in.post(f"/api/chests/{chest.id}/open").json()
    # The item itself, in the shape the satchel lists it in, and the tier.
    assert set(body) == {
        "id", "kind", "species", "name", "rarity", "acquired_at", "tier", "tier_id"
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


def test_the_achievement_catalogue_no_longer_collects_anything(signed_in):
    rows = signed_in.get("/api/achievements").json()
    assert {row["kind"] for row in rows} == {"week-distance"}
    assert all(not row["id"].startswith("collection") for row in rows)


# --------------------------------------------------------------------------
# The letter
# --------------------------------------------------------------------------


def test_the_recap_carries_chests_badges_and_miles_then_clears(signed_in):
    log_workout(signed_in, "run", 11.0, pace_min=9)
    recap = signed_in.get("/api/recap").json()
    assert recap["since"] is None
    assert recap["miles"] == 11.0
    assert recap["chests"], "eleven Miles should have dropped at least one chest"
    assert set(recap["chests"][0]) == {
        "id",
        "dropped_at",
        "tier",
        "tier_id",
        "from_username",
    }
    assert [row["tier"] for row in recap["chests"]] == ["5K", "10K"]
    # Nothing was given, so nothing is attributed to anybody.
    assert all(row["from_username"] is None for row in recap["chests"])
    assert [row["id"] for row in recap["achievements"]] == ["week_10"]
    assert [row["id"] for row in recap["race_badges"]] == ["race_10k"]

    assert signed_in.post("/api/recap/ack").status_code == 204
    cleared = signed_in.get("/api/recap").json()
    assert cleared["since"] is not None
    assert cleared["miles"] == 0.0
    assert cleared["achievements"] == []
    assert cleared["race_badges"] == []
    # Chests are not cleared by acknowledging: they wait to be opened.
    assert cleared["chests"] == recap["chests"]


def test_a_badge_from_a_backdated_run_still_reaches_the_recap(signed_in, db_session, member):
    """The run happened last month; the sync happened this morning. What makes
    it news is when it arrived, which is the same rule the miles follow."""
    signed_in.post("/api/recap/ack")
    db_session.add(
        models.Workout(
            user_id=member.id,
            activity="run",
            start_ts=security.now_utc() - dt.timedelta(days=40),
            duration_s=50 * 60,
            distance_mi=6.4,
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
    assert [row["id"] for row in recap["race_badges"]] == ["race_10k"]
    assert recap["race_badges"][0]["earned_at"] < recap["since"]


def test_the_chest_endpoints_need_a_session(client):
    assert client.get("/api/chests").status_code == 401
    assert client.post("/api/chests/1/open").status_code == 401
    assert client.get("/api/recap").status_code == 401
    assert client.post("/api/recap/ack").status_code == 401
