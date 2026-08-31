"""The satchel, the plot, and the oil one friend spends on another.

Every account and every workout here is invented. The anointing cases are the
careful ones: oil lifts a chest the recipient's own miles bring, so what matters
is as much where it does not land as where it does, and the cases walk whole
responses rather than one field.
"""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app import grove, models, progress, security, species
from app.config import MAX_PENDING_ANOINTINGS, WATER_POUR_MI
from app.main import app as fastapi_app
from app.routers import grove as grove_router
from conftest import LETTER_KEYS, give_item, give_planting, log_workout, make_user


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

    # The seed is spent, and the plot has it.
    assert signed_in.get("/api/satchel").json() == []
    assert [row["id"] for row in signed_in.get("/api/grove").json()] == [planting["id"]]


def test_a_seed_cannot_be_planted_twice(signed_in, db_session, member):
    item = give_item(db_session, member.id, "seed", "blueberry")
    assert signed_in.post(f"/api/satchel/{item.id}/plant").status_code == 201
    assert signed_in.post(f"/api/satchel/{item.id}/plant").status_code == 404
    assert len(signed_in.get("/api/grove").json()) == 1


@pytest.fixture()
def blind_read(monkeypatch):
    """The satchel's read check taken out of the way.

    Two requests carrying the same item id can both read it as unspent, which
    is what a race is, and one thread cannot arrange that on its own. Taking the
    read out leaves exactly the situation the loser of a race is in when it
    reaches the write, so what refuses it below is the conditional update and
    nothing else.
    """

    def blind(db, _user, item_id, _kind):
        return db.get(models.SatchelItem, item_id)

    monkeypatch.setattr(grove_router, "_item", blind)


def test_a_lost_race_cannot_plant_a_seed_somebody_else_already_spent(
    signed_in, db_session, member, blind_read
):
    item = give_item(db_session, member.id, "seed", "blueberry")
    assert signed_in.post(f"/api/satchel/{item.id}/plant").status_code == 201

    second = signed_in.post(f"/api/satchel/{item.id}/plant")
    assert second.status_code == 404
    assert second.json() == {"detail": "No such item."}
    # One seed, one plant. The whole point of the claim is that this is not two.
    assert db_session.query(models.Planting).count() == 1


def test_a_lost_race_cannot_pour_water_that_is_already_gone(
    signed_in, db_session, member, blind_read
):
    item = give_item(db_session, member.id, "water")
    planting = give_planting(db_session, member.id)
    body = {"planting_id": planting.id}
    assert signed_in.post(f"/api/satchel/{item.id}/pour", json=body).status_code == 200
    db_session.refresh(planting)
    grown = planting.growth_mi

    assert signed_in.post(f"/api/satchel/{item.id}/pour", json=body).status_code == 404
    db_session.refresh(planting)
    # One water, one pour's worth of growth.
    assert planting.growth_mi == grown


def test_a_lost_race_cannot_spend_a_wish_twice(signed_in, db_session, member, blind_read):
    item = give_item(db_session, member.id, "wish", rarity="epic")
    assert (
        signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "olive"}).status_code
        == 201
    )
    # A different species the second time, so the wish's own checks all pass and
    # what refuses this is the claim rather than a plot that already holds one.
    second = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "mango"})
    assert second.status_code == 404
    # The wish and the one seed it became, and no second seed.
    assert db_session.query(models.SatchelItem).count() == 2


def test_a_lost_race_cannot_spend_the_same_oil_on_two_friends(
    signed_in, db_session, member, mate, blind_read
):
    other, _ = mate
    third, _third_client = sign_in(db_session, "third")
    befriend(db_session, member, other)
    befriend(db_session, member, third)
    item = give_item(db_session, member.id, "oil", rarity="legendary")

    assert (
        signed_in.post(
            f"/api/satchel/{item.id}/anoint", json={"user_id": other.id}
        ).status_code
        == 204
    )
    refused = signed_in.post(f"/api/satchel/{item.id}/anoint", json={"user_id": third.id})
    assert refused.status_code == 404
    # One gift out of one oil, and the second friend got nothing.
    assert db_session.query(models.Anointing).count() == 1


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
        "level",
        "stage",
        "mature",
        "gilded",
        # How much manna has been fed into it, which is a count of giving and
        # not a fact about how its owner spent their weeks.
        "fed",
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
    assert refused.json()["detail"] == "That one is fully grown."
    assert db_session.get(models.SatchelItem, item.id).used_at is None


def test_water_is_refused_on_something_gilded(signed_in, db_session, member):
    done = give_planting(db_session, member.id, "strawberry", growth=15.0 * species.MAX_LEVEL)
    item = give_item(db_session, member.id, "water")
    refused = signed_in.post(f"/api/satchel/{item.id}/pour", json={"planting_id": done.id})
    assert refused.status_code == 400
    assert refused.json()["detail"] == "That one is fully grown."
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
# Watering the whole plot at once
# --------------------------------------------------------------------------


def water_all(client):
    return client.post("/api/satchel/water-all")


def test_water_all_pours_one_item_onto_each_planting(signed_in, db_session, member):
    """One water per plant down the row, each worth the same ten Miles the
    single pour is, and every item it used is out of the satchel."""
    plants = [
        give_planting(db_session, member.id, "strawberry"),
        give_planting(db_session, member.id, "raspberry"),
    ]
    for _ in range(2):
        give_item(db_session, member.id, "water")

    body = water_all(signed_in)
    assert body.status_code == 200, body.text
    assert body.json()["poured"] == 2
    for row in plants:
        db_session.refresh(row)
        assert row.growth_mi == WATER_POUR_MI
    assert signed_in.get("/api/satchel").json() == []


def test_water_all_takes_the_oldest_plants_when_there_is_not_enough(
    signed_in, db_session, member
):
    """Fewer waters than plants is an ordinary answer rather than a refusal.
    The plot's own order decides, which is the order the screen draws it in."""
    first = give_planting(db_session, member.id, "strawberry")
    second = give_planting(db_session, member.id, "raspberry")
    give_item(db_session, member.id, "water")

    assert water_all(signed_in).json()["poured"] == 1
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.growth_mi, second.growth_mi) == (WATER_POUR_MI, 0.0)


def test_water_all_leaves_a_finished_plant_alone(signed_in, db_session, member):
    """Water helps until there are no levels left. A gilded plant is passed
    over, and the item it would have been thrown away on stays in the satchel."""
    gilded = give_planting(db_session, member.id, "strawberry", growth=100000.0)
    assert grove.is_gilded(gilded)
    give_item(db_session, member.id, "water")

    refused = water_all(signed_in)
    assert refused.status_code == 400
    assert len(signed_in.get("/api/satchel").json()) == 1


def test_water_all_with_an_empty_satchel_is_refused(signed_in, db_session, member):
    """No water and no plot are the same answer to the same press, and neither
    of them changes anything."""
    plant = give_planting(db_session, member.id, "strawberry")

    refused = water_all(signed_in)
    assert refused.status_code == 400
    db_session.refresh(plant)
    assert plant.growth_mi == 0.0


def test_water_all_never_reaches_a_friends_plot(signed_in, db_session, member, mate):
    """Your own plot only. Watering a friend is the half that pays renown, and
    it is aimed at one plant belonging to one person on purpose."""
    friend, _ = mate
    theirs = give_planting(db_session, friend.id, "strawberry")
    mine = give_planting(db_session, member.id, "raspberry")
    for _ in range(2):
        give_item(db_session, member.id, "water")

    assert water_all(signed_in).json()["poured"] == 1
    db_session.refresh(theirs)
    db_session.refresh(mine)
    assert (theirs.growth_mi, mine.growth_mi) == (0.0, WATER_POUR_MI)
    assert len(signed_in.get("/api/satchel").json()) == 1


def test_water_all_writes_a_pour_a_rebuild_can_read(signed_in, db_session, member):
    """The event rows are the point: a pour has nothing behind it, so a rebuild
    that could not read these would take the water back out of the ground."""
    give_planting(db_session, member.id, "strawberry")
    give_planting(db_session, member.id, "raspberry")
    for _ in range(2):
        give_item(db_session, member.id, "water")
    water_all(signed_in)

    rows = db_session.query(models.PourEvent).all()
    assert len(rows) == 2
    assert {row.miles for row in rows} == {WATER_POUR_MI}
    assert {row.user_id for row in rows} == {member.id}


@pytest.fixture()
def rival_press(monkeypatch):
    """Another press spending a water between the read and the write.

    The whole plot is read out of the satchel and then claimed one item at a
    time, and two presses can both read the same items before either claims one.
    Put an item id in what this answers with and the rival takes that one in the
    gap, so the claim under test is the loser of a real race rather than a
    request that was handed an id nobody holds. Not synchronised into this
    session, because a second connection's write is not either.
    """
    taken: set[int] = set()
    real = grove_router._claim

    def after_a_rival(db, item, moment):
        if item.id in taken:
            db.execute(
                update(models.SatchelItem)
                .where(models.SatchelItem.id == item.id)
                .values(used_at=moment)
                .execution_options(synchronize_session=False)
            )
        return real(db, item, moment)

    monkeypatch.setattr(grove_router, "_claim", after_a_rival)
    return taken


def test_water_all_takes_the_next_water_when_one_goes_underneath_it(
    signed_in, db_session, member, rival_press
):
    """A water another press spent first is one fewer to go round, which this
    door already has an ordinary answer for. The plant is poured on out of the
    next item in the satchel rather than the press failing."""
    plant = give_planting(db_session, member.id, "strawberry")
    lost = give_item(db_session, member.id, "water")
    give_item(db_session, member.id, "water")
    rival_press.add(lost.id)

    body = water_all(signed_in)
    assert body.status_code == 200, body.text
    assert body.json()["poured"] == 1
    db_session.refresh(plant)
    assert plant.growth_mi == WATER_POUR_MI
    # Both are out of the satchel: one poured here, one taken by the rival.
    assert signed_in.get("/api/satchel").json() == []


def test_water_all_that_loses_every_claim_answers_in_its_own_words(
    signed_in, db_session, member, rival_press
):
    """Nobody picked an item at this door, so the single pour's answer would be
    about something the press never did. A satchel emptied a moment ago and one
    that was empty all along are the same answer to the same press."""
    give_planting(db_session, member.id, "strawberry")
    items = [give_item(db_session, member.id, "water") for _ in range(2)]
    rival_press.update(row.id for row in items)

    refused = water_all(signed_in)
    assert refused.status_code == 400
    assert refused.json() == {"detail": "Nothing to water just now."}
    assert db_session.query(models.PourEvent).count() == 0


# --------------------------------------------------------------------------
# The wish
# --------------------------------------------------------------------------


def give_wish(db_session, user_id: int):
    """One wish, which is half of what an epic slot is and the only item that
    asks."""
    return give_item(db_session, user_id, "wish", rarity="epic")


def hold_everything(db_session, user_id: int, *, keep: str | None = None) -> None:
    """Put the whole twelve in the ground, less one if a species is named."""
    for species_id in species.ROLLABLE:
        if species_id != keep:
            give_planting(db_session, user_id, species_id)


def test_the_satchel_names_a_wish_for_what_it_promises(signed_in, db_session, member):
    give_wish(db_session, member.id)
    row = signed_in.get("/api/satchel").json()[0]
    assert row["kind"] == "wish"
    assert row["species"] is None
    assert row["rarity"] == "epic"
    assert row["seed_name"] == "Unmarked seed"
    # It is not a species, so there is nothing yet for it to become.
    assert row["plant_name"] is None
    assert row["reveal"] is None


def test_choosing_a_seed_spends_the_wish_and_hands_over_the_seed(
    signed_in, db_session, member
):
    item = give_wish(db_session, member.id)
    body = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "pomegranate"})
    assert body.status_code == 201, body.text
    made = body.json()
    assert made["kind"] == "seed"
    assert made["species"] == "pomegranate"
    assert made["seed_name"] == "Pomegranate seed"
    # Its own rarity, not the wish's: a wish is how it arrived, not what it is.
    assert made["rarity"] == "rare"

    # The wish is gone and the seed is what is waiting, ready to be planted.
    listed = signed_in.get("/api/satchel").json()
    assert [row["id"] for row in listed] == [made["id"]]
    assert db_session.get(models.SatchelItem, item.id).used_at is not None
    assert signed_in.post(f"/api/satchel/{made['id']}/plant").status_code == 201


def test_a_wish_cannot_name_the_one_that_is_only_ever_given(signed_in, db_session, member):
    item = give_wish(db_session, member.id)
    body = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "mustard"})
    assert body.status_code == 400
    # And it is the same answer as a name that is not a species at all, so
    # nothing about the mustard tree reads as a special case.
    unknown = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "sycamore"})
    assert unknown.status_code == 400
    assert unknown.json() == body.json()
    assert db_session.get(models.SatchelItem, item.id).used_at is None


def test_a_wish_needs_a_name_while_there_is_still_something_to_name(
    signed_in, db_session, member
):
    item = give_wish(db_session, member.id)
    assert signed_in.post(f"/api/satchel/{item.id}/choose", json={}).status_code == 400
    assert signed_in.post(f"/api/satchel/{item.id}/choose").status_code == 400
    assert db_session.get(models.SatchelItem, item.id).used_at is None


def test_a_wish_refuses_something_already_growing_or_waiting(signed_in, db_session, member):
    give_planting(db_session, member.id, "coffee")
    give_item(db_session, member.id, "seed", "mango", rarity="uncommon")
    item = give_wish(db_session, member.id)
    for species_id in ("coffee", "mango"):
        body = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": species_id})
        assert body.status_code == 400, species_id
    assert db_session.get(models.SatchelItem, item.id).used_at is None


def test_somebody_elses_wish_answers_like_one_that_never_existed(
    signed_in, db_session, admin, member
):
    theirs = give_wish(db_session, admin.id)
    mine = signed_in.post(f"/api/satchel/{theirs.id}/choose", json={"species": "olive"})
    missing = signed_in.post("/api/satchel/999999/choose", json={"species": "olive"})
    assert mine.status_code == missing.status_code == 404
    assert mine.json() == missing.json()
    assert db_session.get(models.SatchelItem, theirs.id).used_at is None


def test_a_wish_is_spent_exactly_once(signed_in, db_session, member):
    item = give_wish(db_session, member.id)
    assert signed_in.post(
        f"/api/satchel/{item.id}/choose", json={"species": "olive"}
    ).status_code == 201
    again = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "dates"})
    assert again.status_code == 404
    # And it gave out exactly one seed.
    assert [row["species"] for row in signed_in.get("/api/satchel").json()] == ["olive"]


def test_only_a_wish_is_chosen_from(signed_in, db_session, member):
    water = give_item(db_session, member.id, "water")
    body = signed_in.post(f"/api/satchel/{water.id}/choose", json={"species": "olive"})
    assert body.status_code == 400
    assert body.json()["detail"] == "That item cannot be used here."


def test_a_wish_becomes_water_once_the_whole_plot_is_held(signed_in, db_session, member):
    """The grove filled up after the wish dropped, which is the one way to hold
    a wish with nothing left to want. It pours rather than going to waste."""
    hold_everything(db_session, member.id)
    item = give_wish(db_session, member.id)
    body = signed_in.post(f"/api/satchel/{item.id}/choose")
    assert body.status_code == 201, body.text
    made = body.json()
    assert made["kind"] == "water"
    assert made["species"] is None
    assert made["seed_name"] is None
    # What the slot was worth is what the water out of it is worth.
    assert made["rarity"] == "epic"
    assert db_session.get(models.SatchelItem, item.id).used_at is not None


def test_a_full_plot_pours_whatever_the_wish_was_pointed_at(signed_in, db_session, member):
    """Naming something already held is normally refused; with nothing left
    anywhere to name it is moot, and the wish pours all the same."""
    hold_everything(db_session, member.id)
    item = give_wish(db_session, member.id)
    body = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "olive"})
    assert body.status_code == 201, body.text
    assert body.json()["kind"] == "water"


def test_the_last_seed_in_the_plot_is_still_a_wish(signed_in, db_session, member):
    """One short of the twelve is still something to wish for, and the wish is
    the way to name exactly it."""
    hold_everything(db_session, member.id, keep="dates")
    item = give_wish(db_session, member.id)
    body = signed_in.post(f"/api/satchel/{item.id}/choose", json={"species": "dates"})
    assert body.status_code == 201, body.text
    assert (body.json()["kind"], body.json()["species"]) == ("seed", "dates")


# --------------------------------------------------------------------------
# Growth
# --------------------------------------------------------------------------


def test_every_planting_grows_from_every_workout(signed_in, db_session, member):
    first = give_planting(db_session, member.id, "strawberry")
    second = give_planting(db_session, member.id, "olive")
    log_workout(db_session, member.id, "run", 4.0, offset_min=0)
    log_workout(db_session, member.id, "cycle", 9.0, pace_min=4, offset_min=200)

    rows = {row["id"]: row for row in signed_in.get("/api/grove").json()}
    # Four run miles and nine cycled ones are seven Miles, into both of them.
    assert rows[first.id]["growth_mi"] == 7.0
    assert rows[second.id]["growth_mi"] == 7.0
    assert rows[first.id]["growth"] == pytest.approx(7.0 / 15.0, abs=1e-3)
    assert rows[second.id]["growth"] == pytest.approx(7.0 / 100.0, abs=1e-3)


def test_swimming_brings_extra_water(signed_in, db_session, member):
    planting = give_planting(db_session, member.id, "grapevine")
    # Two swum miles are eight converted Miles, and a swim adds half again.
    log_workout(db_session, member.id, "swim", 2.0, pace_min=30)
    row = signed_in.get("/api/grove").json()[0]
    assert row["growth_mi"] == 12.0
    assert db_session.get(models.UserProgress, member.id).xp == 8.0
    assert planting.id == row["id"]


def test_a_planting_comes_of_age_at_its_own_threshold(signed_in, db_session, member):
    quick = give_planting(db_session, member.id, "blueberry")
    slow = give_planting(db_session, member.id, "olive")
    log_workout(db_session, member.id, "run", 20.0, pace_min=9)

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
        "fed",
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
    assert (
        species.BY_ID["mustard"].reveal
        == "Everyone's first chest holds a mustard seed. There are 12 more seeds to find."
    )
    assert [row.id for row in species.BY_ID.values() if row.reveal] == ["mustard"]


def test_nothing_planted_after_a_workout_grows_from_it(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 5.0)
    later = give_planting(db_session, member.id, "blueberry", days_ago=0)
    assert signed_in.get("/api/grove").json()[0]["growth_mi"] == 0.0
    assert later.growth_mi == 0.0


def test_a_rebuild_replays_growth_and_touches_nothing_chosen(signed_in, db_session, member):
    planting = give_planting(db_session, member.id, "blackberry")
    log_workout(db_session, member.id, "run", 12.0, pace_min=9)
    water = give_item(db_session, member.id, "water")
    signed_in.post(f"/api/satchel/{water.id}/pour", json={"planting_id": planting.id})
    before = signed_in.get("/api/grove").json()[0]
    assert before["growth_mi"] == 22.0

    progress.recompute(db_session, member.id)
    after = signed_in.get("/api/grove").json()[0]
    # The miles come back and so does the water: a pour is an event of its own
    # from 0031 on, and a rebuild puts it back where it went.
    assert after["growth_mi"] == 22.0
    assert after["id"] == before["id"]
    # The item stays spent: what somebody did with it is not derived from
    # anything and is never replayed.
    assert db_session.get(models.SatchelItem, water.id).used_at is not None


def test_a_pour_writes_down_where_the_water_went(signed_in, db_session, member, mate):
    """The event beside the growth, for a pour into your own plot and into a
    friend's: the plant it landed on, who poured it, and what it was worth."""
    other, other_client = mate
    befriend(db_session, member, other)
    mine = give_planting(db_session, member.id, "strawberry")
    theirs = give_planting(db_session, other.id, "grapevine")
    for client, item_owner, target in (
        (signed_in, member, mine),
        (signed_in, member, theirs),
    ):
        item = give_item(db_session, item_owner.id, "water")
        assert (
            client.post(
                f"/api/satchel/{item.id}/pour", json={"planting_id": target.id}
            ).status_code
            == 200
        )
    events = (
        db_session.query(models.PourEvent).order_by(models.PourEvent.id).all()
    )
    assert [(row.planting_id, row.user_id, row.miles) for row in events] == [
        (mine.id, member.id, WATER_POUR_MI),
        # The pourer rather than the plot's owner: the friend who brought it.
        (theirs.id, member.id, WATER_POUR_MI),
    ]
    assert all(row.created_at is not None for row in events)
    # Nothing is written for a pour that never happened.
    refused = give_item(db_session, member.id, "water")
    signed_in.post(f"/api/satchel/{refused.id}/pour", json={"planting_id": 999999})
    assert db_session.query(models.PourEvent).count() == 2


def test_a_rebuild_lands_a_watered_plot_exactly_where_it_was(
    signed_in, db_session, member
):
    """Workouts and water together: the same growth, the same date of maturity,
    and the same level on the other side of the hatch."""
    planting = give_planting(db_session, member.id, "strawberry")
    log_workout(db_session, member.id, "run", 8.0, pace_min=9, offset_min=0)
    for _ in range(2):
        water = give_item(db_session, member.id, "water")
        assert (
            signed_in.post(
                f"/api/satchel/{water.id}/pour", json={"planting_id": planting.id}
            ).status_code
            == 200
        )
    log_workout(db_session, member.id, "swim", 1.0, pace_min=30, offset_min=200)
    before = signed_in.get("/api/grove").json()[0]
    matured_at = db_session.get(models.Planting, planting.id).matured_at
    assert before["growth_mi"] > 0 and before["level"] >= 1 and matured_at is not None

    progress.recompute(db_session, member.id)
    after = signed_in.get("/api/grove").json()[0]
    assert after == before
    assert db_session.get(models.Planting, planting.id).matured_at == matured_at


def test_a_rebuild_never_lowers_a_plant_that_predates_the_pour_record(
    signed_in, db_session, member
):
    """A plot from before 0031, where the pours left no trace: the floor that
    migration wrote is what a rebuild is held to, and it holds the date of
    maturity with it."""
    planting = give_planting(db_session, member.id, "strawberry", growth=42.0)
    # What 0031 does to every plant already in the ground, and the maturity it
    # had reached before any of this existed.
    planting.legacy_growth_mi = 42.0
    matured_at = security.now_utc() - dt.timedelta(days=30)
    planting.matured_at = matured_at
    db_session.commit()
    was = grove.serialize_planting(planting)
    log_workout(db_session, member.id, "run", 3.0)

    progress.recompute(db_session, member.id)
    db_session.refresh(planting)
    assert planting.growth_mi >= was["growth_mi"]
    assert grove.level_of(planting) >= was["level"]
    # The date it came of age is remembered rather than worked out again.
    assert planting.matured_at == matured_at
    # And a pour recorded since lands on top of the floor rather than inside it.
    water = give_item(db_session, member.id, "water")
    assert (
        signed_in.post(
            f"/api/satchel/{water.id}/pour", json={"planting_id": planting.id}
        ).status_code
        == 200
    )
    poured = db_session.get(models.Planting, planting.id).growth_mi
    progress.recompute(db_session, member.id)
    assert db_session.get(models.Planting, planting.id).growth_mi == poured


def test_a_gilded_plant_is_still_gilded_after_a_rebuild(signed_in, db_session, member):
    """The finished plant is the one a stripped rebuild embarrassed most: its
    fruit had already been borne, and it came back unfinished."""
    grown = 15.0 * species.MAX_LEVEL
    planting = give_planting(db_session, member.id, "strawberry", growth=grown)
    planting.legacy_growth_mi = grown
    planting.matured_at = security.now_utc() - dt.timedelta(days=60)
    db_session.commit()
    assert signed_in.get("/api/grove").json()[0]["gilded"] is True

    progress.recompute(db_session, member.id)
    after = signed_in.get("/api/grove").json()[0]
    assert after["gilded"] is True
    assert after["growth_mi"] == grown
    assert after["matured_at"] is not None


# --------------------------------------------------------------------------
# A friend's plot
# --------------------------------------------------------------------------


def test_a_friend_sees_the_plants_and_their_levels_and_no_miles(signed_in, db_session, member, mate):
    other, other_client = mate
    befriend(db_session, member, other)
    give_planting(db_session, member.id, "pomegranate", growth=50.0)

    rows = other_client.get(f"/api/grove/{member.id}").json()
    assert len(rows) == 1
    # Enough to pick one, water it, and see how it is doing. The level is the
    # one number that crossed the fence; the miles behind it and the dates did
    # not, because those describe the owner rather than the garden.
    assert set(rows[0]) == {
        "id",
        "species",
        "seed_name",
        "plant_name",
        "rarity",
        "growth",
        "level",
        "stage",
        "mature",
        "gilded",
        # How much manna has been fed into it, which is a count of giving and
        # not a fact about how its owner spent their weeks.
        "fed",
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
    # Enough to know there is no point pouring water into it.
    assert (row["gilded"], row["mature"], row["stage"]) == (True, True, 3)
    # The level crossed the fence on his word, so a friend can see how a plant
    # is doing. The miles behind it and the dates did not: those describe how
    # somebody spent their weeks rather than how their garden looks.
    assert row["level"] == species.MAX_LEVEL
    assert "growth_mi" not in row and "planted_at" not in row


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


def stand_at(db_session, user_id: int, cycle_pos: int) -> None:
    """Put an account at a step of the chest ladder with nothing banked yet."""
    row = progress.ensure_progress(db_session, user_id)
    row.cycle_pos = cycle_pos
    row.chest_progress_mi = 0.0
    db_session.commit()


def test_a_gift_shows_on_the_chest_ahead_and_nowhere_else(
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

    # The recipient reads it in one place: the chest it is waiting on.
    body = other_client.get("/api/profile").json()
    assert body["next_chest"]["gifted_by"] == member.username
    assert body["pending_gifts"] == [{"from": member.username}]

    # Nothing was pushed at them, and nothing has landed to open.
    for path in ("/api/recap", "/api/chests", "/api/satchel", "/api/feed"):
        text = other_client.get(path).text
        assert "anoint" not in text.lower(), path
        assert member.username not in text, path
    assert other_client.get("/api/chests").json() == []


def test_the_gift_lifts_a_chest_the_miles_earned_and_drops_none_of_its_own(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})

    log_workout(db_session, other.id, "run", 4.0)

    row = db_session.get(models.UserProgress, other.id)
    # Four miles is the 5K chest and nine tenths of a mile toward the 10K. The
    # gift moved none of that: it is not a distance.
    assert (row.cycle_pos, round(row.chest_progress_mi, 2)) == (1, 0.9)
    # One chest, not two. Nothing drops a bonus chest any more.
    waiting = other_client.get("/api/chests").json()
    assert [chest["tier_id"] for chest in waiting] == ["5k"]
    # And it is the shape of every other chest: what the oil did to it is not
    # visible until the lid comes off.
    assert set(waiting[0]) == {"id", "dropped_at", "tier", "tier_id"}

    anointing = db_session.get(models.Anointing, 1)
    assert anointing.consumed_at is not None
    assert anointing.consumed_chest_id == waiting[0]["id"]
    assert db_session.get(models.Chest, waiting[0]["id"]).from_anointing_id == anointing.id
    assert other_client.get("/api/profile").json()["pending_gifts"] == []


def test_an_ultra_is_skipped_and_the_gift_waits_for_a_chest_with_room(
    signed_in, db_session, member, mate
):
    """An Ultra floors at legendary and legendary is the top rung, so there is
    no step for a gift to buy. It holds rather than being spent on nothing."""
    other, other_client = mate
    befriend(db_session, member, other)
    stand_at(db_session, other.id, 4)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})

    # The chest ahead is the Ultra, and the gift is not on it: waiting, and
    # named nowhere yet.
    body = other_client.get("/api/profile").json()
    assert body["next_chest"]["tier_id"] == "ultra"
    assert body["next_chest"]["gifted_by"] is None
    assert body["pending_gifts"] == [{"from": member.username}]

    log_workout(db_session, other.id, "run", 31.1, offset_min=0)
    landed = other_client.get("/api/chests").json()
    assert [chest["tier_id"] for chest in landed] == ["ultra"]
    assert db_session.get(models.Chest, landed[0]["id"]).from_anointing_id is None
    assert db_session.get(models.Anointing, 1).consumed_at is None
    # The wheel has turned, and now the gift has somewhere to go.
    body = other_client.get("/api/profile").json()
    assert body["next_chest"]["tier_id"] == "5k"
    assert body["next_chest"]["gifted_by"] == member.username

    log_workout(db_session, other.id, "run", 3.1, offset_min=200)
    landed = other_client.get("/api/chests").json()
    assert [chest["tier_id"] for chest in landed] == ["ultra", "5k"]
    assert db_session.get(models.Chest, landed[1]["id"]).from_anointing_id == 1
    assert other_client.get("/api/profile").json()["pending_gifts"] == []


def test_two_gifts_lift_two_chests_and_never_the_same_one(
    signed_in, db_session, member, mate
):
    """One gift lifts one chest. Two friends lift the next two with room, one
    each, rather than stacking into a chest two rarities up."""
    other, other_client = mate
    third, third_client = sign_in(db_session, "third")
    befriend(db_session, member, other)
    befriend(db_session, third, other)
    first = give_item(db_session, member.id, "oil", rarity="rare")
    second = give_item(db_session, third.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{first.id}/anoint", json={"user_id": other.id})
    third_client.post(f"/api/satchel/{second.id}/anoint", json={"user_id": other.id})

    body = other_client.get("/api/profile").json()
    # In the order they arrived, and the first in the queue is on the chest ahead.
    assert body["pending_gifts"] == [{"from": member.username}, {"from": third.username}]
    assert body["next_chest"]["gifted_by"] == member.username

    # Ten miles is the 5K and the 10K, and one gift lands on each.
    log_workout(db_session, other.id, "run", 10.0)
    landed = other_client.get("/api/chests").json()
    assert [chest["tier_id"] for chest in landed] == ["5k", "10k"]
    assert [
        db_session.get(models.Chest, chest["id"]).from_anointing_id for chest in landed
    ] == [1, 2]
    assert other_client.get("/api/profile").json()["pending_gifts"] == []


def test_a_backfill_spends_one_gift_across_all_of_it(signed_in, db_session, member, mate):
    """A week of history swept in one pass drops several chests, and the one
    gift waiting lifts the first of them and no other."""
    other, _other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})

    for day in range(3):
        db_session.add(
            models.Workout(
                user_id=other.id,
                activity="run",
                start_ts=security.now_utc() - dt.timedelta(hours=3 + day * 24),
                duration_s=3600,
                distance_mi=5.0,
                active_kcal=500.0,
                avg_hr=None,
                source="sync",
                flags={},
                created_at=security.now_utc(),
            )
        )
    db_session.commit()
    progress.process_user(db_session, other.id)

    lifted = [
        row.id
        for row in db_session.query(models.Chest)
        .filter(models.Chest.user_id == other.id)
        .order_by(models.Chest.id)
        if row.from_anointing_id is not None
    ]
    assert len(lifted) == 1
    assert db_session.get(models.Anointing, 1).consumed_chest_id == lifted[0]


def test_a_walker_holds_only_so_many_gifts_at_once(signed_in, db_session, member, mate):
    """Counted on the receiver across every giver, so nobody's whole coming
    ladder can be lifted before they have run any of it."""
    other, other_client = mate
    for index in range(MAX_PENDING_ANOINTINGS):
        giver, giver_client = sign_in(db_session, f"giver{index}")
        befriend(db_session, giver, other)
        oil = give_item(db_session, giver.id, "oil", rarity="rare")
        assert (
            giver_client.post(
                f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id}
            ).status_code
            == 204
        )

    befriend(db_session, member, other)
    late = give_item(db_session, member.id, "oil", rarity="rare")
    refused = signed_in.post(f"/api/satchel/{late.id}/anoint", json={"user_id": other.id})
    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "They already have all the gifts they can hold. Try again once they have run."
    )
    # The oil is still in the satchel. A refusal never destroys the item, which
    # is the whole reason it is a refusal.
    assert [row["id"] for row in signed_in.get("/api/satchel").json()] == [late.id]
    assert db_session.get(models.SatchelItem, late.id).used_at is None
    assert (
        len(other_client.get("/api/profile").json()["pending_gifts"])
        == MAX_PENDING_ANOINTINGS
    )

    # A chest lands, one gift is spent on it, and there is room to give again.
    log_workout(db_session, other.id, "run", 4.0)
    assert (
        signed_in.post(f"/api/satchel/{late.id}/anoint", json={"user_id": other.id}).status_code
        == 204
    )


def test_the_letter_is_where_the_gift_is_finally_attributed(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})
    log_workout(db_session, other.id, "run", 4.0)

    letter = other_client.get("/api/recap").json()
    # One chest landed, and it carries the name: the miles earned it and a
    # friend's oil made it better.
    assert letter["chests"] == [{"tier_id": "5k", "tier": "5K", "gifted_by": member.username}]
    # And the letter still reads in the order it reads in.
    assert list(letter) == LETTER_KEYS


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

    # The gift is spent on a chest, and a second one on the same friend inside
    # the window arrives all the same and pays nothing.
    log_workout(db_session, other.id, "run", 4.0, offset_min=0)
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

    # Once the first has been spent on a chest, the same pair can give again.
    log_workout(db_session, other.id, "run", 4.0)
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


def test_a_rebuild_walks_the_ladder_again_and_a_spent_gift_stays_spent(
    signed_in, db_session, member, mate
):
    other, other_client = mate
    befriend(db_session, member, other)
    oil = give_item(db_session, member.id, "oil", rarity="rare")
    signed_in.post(f"/api/satchel/{oil.id}/anoint", json={"user_id": other.id})
    log_workout(db_session, other.id, "run", 4.0)
    assert len(other_client.get("/api/chests").json()) == 1

    progress.recompute(db_session, other.id)
    left = other_client.get("/api/chests").json()
    # The same miles, so the same one chest. Every chest is a distance now, so
    # none is held back from the rebuild and none is dropped twice by it.
    assert [chest["tier_id"] for chest in left] == ["5k"]
    # The gift was given once and is not handed back to be given again.
    assert db_session.get(models.Anointing, 1).consumed_at is not None
    assert other_client.get("/api/profile").json()["pending_gifts"] == []


def test_the_grove_endpoints_need_a_session(client):
    assert client.get("/api/satchel").status_code == 401
    assert client.get("/api/grove").status_code == 401
    assert client.get("/api/species").status_code == 401
    assert client.post("/api/satchel/1/plant").status_code == 401
    assert client.post("/api/satchel/1/pour", json={"planting_id": 1}).status_code == 401
    assert client.post("/api/satchel/1/anoint", json={"user_id": 1}).status_code == 401
    assert client.post("/api/satchel/1/choose", json={"species": "olive"}).status_code == 401


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


# --------------------------------------------------------------------------
# The catalogue, served rather than written down twice
# --------------------------------------------------------------------------


def test_the_catalogue_is_the_twelve_in_catalogue_order(signed_in):
    body = signed_in.get("/api/species").json()
    assert [row["id"] for row in body["species"]] == list(species.ROLLABLE)
    # Four of each, low to high, which is the order the catalogue itself keeps.
    assert [row["rarity"] for row in body["species"]] == (
        ["common"] * 4 + ["uncommon"] * 4 + ["rare"] * 4
    )


def test_the_catalogue_says_both_names_and_nothing_else(signed_in):
    body = signed_in.get("/api/species").json()
    assert set(body) == {"species", "wish_name"}
    for row in body["species"]:
        assert set(row) == {"id", "seed_name", "plant_name", "rarity"}
        kind = species.BY_ID[row["id"]]
        assert (row["seed_name"], row["plant_name"]) == (kind.seed_name, kind.plant_name)
    # The wish is not a species and has no row; it is named once, alongside.
    assert body["wish_name"] == species.WISH_NAME == "Unmarked seed"


def test_the_catalogue_leaves_out_the_one_that_is_given(signed_in):
    """A wish is spent from this list, and the mustard tree is in no bag a wish
    reaches into."""
    body = signed_in.get("/api/species").json()
    assert len(body["species"]) == 12
    assert species.FIRST_CHEST_SPECIES not in {row["id"] for row in body["species"]}
