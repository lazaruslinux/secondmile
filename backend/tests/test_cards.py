"""Chests, the album, and what an unowned plate is allowed to say about itself."""

from conftest import log_workout

from app import models, security, world


def give_chest(db_session, user_id: int, card_id: str) -> models.Chest:
    chest = models.Chest(
        user_id=user_id, card_id=card_id, dropped_at=security.now_utc(), opened_at=None
    )
    db_session.add(chest)
    db_session.commit()
    return chest


def test_the_world_holds_thirty_six_cards_in_four_sets():
    assert len(world.CARDS) == 36
    sizes = {set_id: len(cards) for set_id, cards in world.CARDS_BY_SET.items()}
    assert sizes == {"east_road": 12, "millbrook": 10, "north_road": 8, "high_fells": 6}
    for cards in world.CARDS_BY_SET.values():
        assert [card.number for card in cards] == list(range(1, len(cards) + 1))
        assert all(card.rarity in world.RARITIES for card in cards)
        assert all(card.flavor.strip() for card in cards)


def test_a_closed_chest_does_not_say_what_is_in_it(traveller, db_session, member):
    give_chest(db_session, member.id, "east_road_heron")
    listed = traveller.get("/api/chests").json()
    assert len(listed) == 1
    assert set(listed[0]) == {"id", "dropped_at", "set_id", "set_name"}
    assert listed[0]["set_name"] == "East Road"


def test_opening_a_chest_reveals_the_card(traveller, db_session, member):
    chest = give_chest(db_session, member.id, "millbrook_willow")
    body = traveller.post(f"/api/chests/{chest.id}/open").json()
    assert body["card"]["name"] == "The Millbrook Willow"
    assert body["card"]["rarity"] == "rare"
    assert body["card"]["flavor"]
    assert body["duplicate"] is False
    assert body["count"] == 1
    # Opened chests leave the pending list.
    assert traveller.get("/api/chests").json() == []


def test_opening_the_same_chest_twice_is_a_conflict(traveller, db_session, member):
    chest = give_chest(db_session, member.id, "east_road_skylark")
    assert traveller.post(f"/api/chests/{chest.id}/open").status_code == 200
    assert traveller.post(f"/api/chests/{chest.id}/open").status_code == 409
    assert db_session.get(models.UserCard, (member.id, "east_road_skylark")).count == 1


def test_a_second_copy_is_a_duplicate(traveller, db_session, member):
    first = give_chest(db_session, member.id, "north_road_curlew")
    second = give_chest(db_session, member.id, "north_road_curlew")
    assert traveller.post(f"/api/chests/{first.id}/open").json()["duplicate"] is False
    body = traveller.post(f"/api/chests/{second.id}/open").json()
    assert body["duplicate"] is True
    assert body["count"] == 2


def test_somebody_elses_chest_answers_like_one_that_never_existed(
    traveller, db_session, admin, member
):
    theirs = give_chest(db_session, admin.id, "east_road_heron")
    mine = traveller.post(f"/api/chests/{theirs.id}/open")
    missing = traveller.post("/api/chests/999999/open")
    assert mine.status_code == missing.status_code == 404
    assert mine.json() == missing.json()
    # And it is still closed for the person it belongs to.
    assert db_session.get(models.Chest, theirs.id).opened_at is None


def test_the_album_hides_the_names_of_cards_not_yet_found(traveller, db_session, member):
    give_chest(db_session, member.id, "east_road_hawthorn")
    chest = traveller.get("/api/chests").json()[0]
    traveller.post(f"/api/chests/{chest['id']}/open")

    album = traveller.get("/api/album").json()
    assert [row["id"] for row in album["sets"]] == [
        "east_road",
        "millbrook",
        "north_road",
        "high_fells",
    ]
    east = album["sets"][0]
    assert east["size"] == 12
    assert east["owned"] == 1

    found = [plate for plate in east["cards"] if plate["owned"]]
    assert len(found) == 1
    assert found[0]["name"] == "Hedgerow Hawthorn"
    assert found[0]["count"] == 1
    assert found[0]["flavor"]

    for plate in east["cards"]:
        if plate["owned"]:
            continue
        # A number and a rarity, and nothing that gives the plate away. The id
        # is left out too, because the slug is the name in another shape.
        assert set(plate) == {"number", "rarity", "owned"}


def test_the_album_starts_empty_and_still_lists_every_plate(traveller):
    album = traveller.get("/api/album").json()
    assert sum(row["size"] for row in album["sets"]) == 36
    assert all(row["owned"] == 0 for row in album["sets"])
    assert all(not plate["owned"] for row in album["sets"] for plate in row["cards"])


def test_accolades_are_empty_until_a_mark_is_passed(traveller):
    assert traveller.get("/api/accolades").json() == []
    log_workout(traveller, "run", 4.0)
    earned = traveller.get("/api/accolades").json()
    assert [row["id"] for row in earned] == ["east_road_footbridge"]
    assert earned[0]["name"] == "The Footbridge"
    assert earned[0]["earned_at"]


def test_the_card_endpoints_need_a_session(client):
    assert client.get("/api/chests").status_code == 401
    assert client.post("/api/chests/1/open").status_code == 401
    assert client.get("/api/album").status_code == 401
    assert client.get("/api/accolades").status_code == 401
