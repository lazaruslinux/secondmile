"""Chests, the album, the recap, and what an unowned plate may say about itself."""

from conftest import log_workout

from app import models, security, world


def give_chest(db_session, user_id: int, card_id: str) -> models.Chest:
    chest = models.Chest(
        user_id=user_id, card_id=card_id, dropped_at=security.now_utc(), opened_at=None
    )
    db_session.add(chest)
    db_session.commit()
    return chest


def test_the_catalogue_holds_thirty_six_cards_in_four_sets():
    assert len(world.CARDS) == 36
    sizes = {set_id: len(cards) for set_id, cards in world.CARDS_BY_SET.items()}
    assert sizes == {"hedgerow": 12, "still_water": 10, "open_hill": 8, "first_light": 6}
    for set_id, cards in world.CARDS_BY_SET.items():
        assert [card.number for card in cards] == list(range(1, len(cards) + 1))
        assert all(card.rarity in world.RARITIES for card in cards)
        assert all(card.flavor.strip() for card in cards)
        # The id convention the artwork guide documents, and the reason a file
        # dropped in named after a card finds its plate without a list to edit.
        assert all(card.id.startswith(f"{set_id}_") for card in cards)
    assert all(card_set.weight > 0 for card_set in world.CARD_SETS.values())


def test_a_closed_chest_does_not_say_what_is_in_it(signed_in, db_session, member):
    give_chest(db_session, member.id, "still_water_heron")
    listed = signed_in.get("/api/chests").json()
    assert len(listed) == 1
    assert set(listed[0]) == {"id", "dropped_at", "set_id", "set_name"}
    assert listed[0]["set_name"] == "Still Water"


def test_opening_a_chest_reveals_the_card(signed_in, db_session, member):
    chest = give_chest(db_session, member.id, "still_water_kingfisher")
    body = signed_in.post(f"/api/chests/{chest.id}/open").json()
    assert body["card"]["name"] == "Kingfisher"
    assert body["card"]["rarity"] == "rare"
    assert body["card"]["flavor"]
    assert body["duplicate"] is False
    assert body["count"] == 1
    # Opened chests leave the pending list.
    assert signed_in.get("/api/chests").json() == []


def test_opening_the_same_chest_twice_is_a_conflict(signed_in, db_session, member):
    chest = give_chest(db_session, member.id, "open_hill_skylark")
    assert signed_in.post(f"/api/chests/{chest.id}/open").status_code == 200
    assert signed_in.post(f"/api/chests/{chest.id}/open").status_code == 409
    assert db_session.get(models.UserCard, (member.id, "open_hill_skylark")).count == 1


def test_a_second_copy_is_a_duplicate(signed_in, db_session, member):
    first = give_chest(db_session, member.id, "open_hill_curlew")
    second = give_chest(db_session, member.id, "open_hill_curlew")
    assert signed_in.post(f"/api/chests/{first.id}/open").json()["duplicate"] is False
    body = signed_in.post(f"/api/chests/{second.id}/open").json()
    assert body["duplicate"] is True
    assert body["count"] == 2


def test_somebody_elses_chest_answers_like_one_that_never_existed(
    signed_in, db_session, admin, member
):
    theirs = give_chest(db_session, admin.id, "still_water_heron")
    mine = signed_in.post(f"/api/chests/{theirs.id}/open")
    missing = signed_in.post("/api/chests/999999/open")
    assert mine.status_code == missing.status_code == 404
    assert mine.json() == missing.json()
    # And it is still closed for the person it belongs to.
    assert db_session.get(models.Chest, theirs.id).opened_at is None


def test_the_album_hides_the_names_of_cards_not_yet_found(signed_in, db_session, member):
    give_chest(db_session, member.id, "hedgerow_hawthorn")
    chest = signed_in.get("/api/chests").json()[0]
    signed_in.post(f"/api/chests/{chest['id']}/open")

    album = signed_in.get("/api/album").json()
    assert [row["id"] for row in album["sets"]] == [
        "hedgerow",
        "still_water",
        "open_hill",
        "first_light",
    ]
    hedgerow = album["sets"][0]
    assert hedgerow["size"] == 12
    assert hedgerow["owned"] == 1

    found = [plate for plate in hedgerow["cards"] if plate["owned"]]
    assert len(found) == 1
    assert found[0]["name"] == "Hawthorn"
    assert found[0]["count"] == 1
    assert found[0]["flavor"]

    for plate in hedgerow["cards"]:
        if plate["owned"]:
            continue
        # A number and a rarity, and nothing that gives the plate away. The id
        # is left out too, because the slug is the name in another shape.
        assert set(plate) == {"number", "rarity", "owned"}


def test_the_album_starts_empty_and_still_lists_every_plate(signed_in):
    album = signed_in.get("/api/album").json()
    assert sum(row["size"] for row in album["sets"]) == 36
    assert all(row["owned"] == 0 for row in album["sets"])
    assert all(not plate["owned"] for row in album["sets"] for plate in row["cards"])


def test_the_recap_carries_chests_badges_and_miles_then_clears(signed_in):
    log_workout(signed_in, "run", 8.0, pace_min=9)
    recap = signed_in.get("/api/recap").json()
    assert recap["since"] is None
    assert recap["miles"] == 8.0
    assert recap["chests"], "eight Miles should have dropped at least one chest"
    assert set(recap["chests"][0]) == {"id", "dropped_at", "set_id", "set_name"}
    assert [row["id"] for row in recap["achievements"]]

    assert signed_in.post("/api/recap/ack").status_code == 204
    cleared = signed_in.get("/api/recap").json()
    assert cleared["since"] is not None
    assert cleared["miles"] == 0.0
    assert cleared["achievements"] == []
    # Chests are not cleared by acknowledging: they wait to be opened.
    assert cleared["chests"] == recap["chests"]


def test_a_pending_chest_in_the_recap_never_names_the_card(signed_in):
    log_workout(signed_in, "run", 20.0, pace_min=9)
    chests = signed_in.get("/api/recap").json()["chests"]
    assert chests
    for row in chests:
        assert "card_id" not in row
        assert "card" not in row
        assert row["set_name"]


def test_the_card_endpoints_need_a_session(client):
    assert client.get("/api/chests").status_code == 401
    assert client.post("/api/chests/1/open").status_code == 401
    assert client.get("/api/album").status_code == 401
    assert client.get("/api/recap").status_code == 401
    assert client.post("/api/recap/ack").status_code == 401
