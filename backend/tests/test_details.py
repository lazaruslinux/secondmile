"""The details screen behind a card: who may open it, and what it tells them.

Every case here is about one endpoint, GET /api/workouts/{id}/details, and
about the two rules it inherits rather than invents. Who may read it is the
feed's reach, said in the same neutral 404 a route line and a photograph
answer a stranger with. What a reader is told is the owner's own list from
HIDEABLE, applied the way feed_row applies it: a field kept back is absent
rather than null, because a null would say the workout never carried one.

The zone ladder is the one reading that is worked out rather than stored, so
the three rungs it can be read from each have a case of their own.

Nothing here earns anything, which is why no case asserts a mile, a medal or a
chest: no field this endpoint serves is read by any of them.
"""

import datetime as dt

from conftest import FROZEN_NOW
from test_fellowship import befriend, hide, sign_in
from test_ingest import export, post
from test_samples import START, entry

from app import models

# The birthdate every zone case uses, and the age it gives on the frozen day.
# The clock is pinned to 2026-04-15, so a birthday on that date has already
# happened and the arithmetic has no edge in it.
BORN = dt.date(FROZEN_NOW.year - 36, 4, 15)
AGE = 36


def details(client, workout_id: int):
    return client.get(f"/api/workouts/{workout_id}/details")


def the_workout_id(db_session) -> int:
    db_session.expire_all()
    return db_session.query(models.Workout).one().id


def give_birthdate(client, born: dt.date) -> None:
    """Whoever holds that session sets their birthdate, through the endpoint the
    edit form uses rather than by writing the column."""
    response = client.patch("/api/profile", json={"birthdate": born.isoformat()})
    assert response.status_code == 200, response.text
    assert response.json()["age"] == AGE


# --------------------------------------------------------------------------
# Who may open one
# --------------------------------------------------------------------------


def test_a_member_who_is_not_a_friend_gets_the_refusal_a_missing_workout_gets(
    signed_in, ingest_token, db_session
):
    """The same sentence and the same status a workout that does not exist
    answers with, so asking for an id says nothing about whose history it is
    on. Read as text as well as status, because a refusal that named the owner
    or the reason would be the leak this is here to stop."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)
    _, stranger = sign_in(db_session, "stranger")

    refused = details(stranger, workout_id)
    assert refused.status_code == 404
    assert refused.json()["detail"] == "No such workout."
    assert details(stranger, workout_id + 5000).json() == refused.json()


def test_an_accepted_friend_receives_the_minutes_and_the_summaries_beside_them(
    signed_in, ingest_token, db_session, member
):
    """A friend sees what you did, in full, which is the feed's own promise
    carried down onto the screen behind the card."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)

    body = details(other_client, workout_id).json()
    assert [row["minute"] for row in body["minutes"]] == [0, 1, 2]
    assert body["minutes"][0] == {
        "minute": 0,
        "distance_mi": 0.05,
        "steps": 110,
        "hr_min": 100,
        "hr_avg": 120,
        "hr_max": 140,
    }
    assert body["max_hr"] == 168
    assert body["temperature_f"] == 78.5
    assert body["humidity_pct"] == 44.0
    assert body["elevation_gain_ft"] == 142.0


def test_the_owner_receives_every_field_the_workout_carries(
    signed_in, ingest_token, db_session
):
    """The whole shape in one assertion, so a field added to the payload without
    being thought about here fails a case rather than passing quietly."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)
    give_birthdate(signed_in, BORN)

    body = details(signed_in, workout_id).json()
    assert set(body) == {
        "workout_id",
        "minutes",
        "max_hr",
        "temperature_f",
        "humidity_pct",
        "elevation_gain_ft",
        "zone_max",
        "zone_basis",
    }
    assert body["workout_id"] == workout_id
    assert len(body["minutes"]) == 3
    assert (body["zone_max"], body["zone_basis"]) == (220 - AGE, "age")


# --------------------------------------------------------------------------
# What the two toggles take with them
# --------------------------------------------------------------------------


def test_hiding_the_heart_rate_takes_every_beat_and_both_zone_fields_with_it(
    signed_in, ingest_token, db_session, member
):
    """The frozen rule: a ladder drawn from somebody's age with their own
    minutes hung on it is the heart rate said another way, so it goes when the
    beats go. Asserted against the text of the response as well as its keys,
    because a beat carried under another name would pass a key check."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)
    give_birthdate(signed_in, BORN)
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    hide(signed_in, "avg_hr")

    kept_back = details(other_client, workout_id)
    body = kept_back.json()
    assert "max_hr" not in body
    assert "zone_max" not in body
    assert "zone_basis" not in body
    assert all("hr_min" not in row for row in body["minutes"])
    assert all("hr_avg" not in row for row in body["minutes"])
    assert all("hr_max" not in row for row in body["minutes"])
    for beat in ("168", "120", "140", str(220 - AGE)):
        assert beat not in kept_back.text

    # What is not a beat is still there: how far each minute went and how many
    # steps it took are the same class of reading as the distance on the card.
    assert [row["distance_mi"] for row in body["minutes"]] == [0.05, 0.05, 0.05]
    assert [row["steps"] for row in body["minutes"]] == [110, 111, 112]


def test_your_own_copy_carries_the_beats_and_the_zones_whatever_you_have_hidden(
    signed_in, ingest_token, db_session
):
    """Hiding something from your friends is not hiding it from yourself, which
    is the rule a card already follows."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)
    give_birthdate(signed_in, BORN)
    hide(signed_in, "avg_hr", "route")

    body = details(signed_in, workout_id).json()
    assert body["max_hr"] == 168
    assert body["zone_max"] == 220 - AGE
    assert body["minutes"][0]["hr_avg"] == 120
    assert body["elevation_gain_ft"] == 142.0


def test_hiding_the_route_takes_the_climb_and_leaves_the_weather_alone(
    signed_in, ingest_token, db_session, member
):
    """His call, frozen: how much a session climbed is read off the ground it
    crossed and travels with the line, and what the air was like is a fact about
    the afternoon rather than about a body, so it rides on every copy."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)
    other, other_client = sign_in(db_session, "mate")
    befriend(db_session, member, other)
    hide(signed_in, "route")

    kept_back = details(other_client, workout_id)
    body = kept_back.json()
    assert "elevation_gain_ft" not in body
    assert "142.0" not in kept_back.text
    assert body["temperature_f"] == 78.5
    assert body["humidity_pct"] == 44.0
    # The beats are untouched: the two toggles govern two different things.
    assert body["max_hr"] == 168


# --------------------------------------------------------------------------
# The three rungs of the zone ladder
# --------------------------------------------------------------------------


def test_the_ceiling_is_read_from_the_birthdate_when_there_is_one(
    signed_in, ingest_token, db_session
):
    """220 minus the age, and the basis says so. The birthdate itself is
    nowhere in the answer: what a friend is shown is a ceiling, and the day
    somebody was born stays between them and the server."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)
    give_birthdate(signed_in, BORN)

    answer = details(signed_in, workout_id)
    assert (answer.json()["zone_max"], answer.json()["zone_basis"]) == (220 - AGE, "age")
    assert BORN.isoformat() not in answer.text


def test_without_a_birthdate_the_ceiling_falls_back_to_the_highest_beat_on_record(
    signed_in, ingest_token, db_session
):
    """The highest of the two places a beat is kept, across the whole history
    rather than this one session: the per-minute rows and the summary on the
    workout beside them. The summary is the higher of the two here, so the
    answer being 168 rather than 142 is the case."""
    assert post(signed_in, ingest_token, export(entry())).json()["imported"] == 1
    workout_id = the_workout_id(db_session)

    body = details(signed_in, workout_id).json()
    assert (body["zone_max"], body["zone_basis"]) == (168, "observed")


def test_an_account_with_neither_a_birthdate_nor_a_beat_gets_no_ladder_at_all(
    signed_in, ingest_token, db_session
):
    """Null rather than a guess. A ladder with no top is not a reading with a
    caveat on it, so the screen draws no zones rather than drawing five bands
    off a number nobody gave it."""
    plain = {"name": "Indoor Walk", "start": START, "duration": 1800}
    assert post(signed_in, ingest_token, export(plain)).json()["imported"] == 1
    workout_id = the_workout_id(db_session)

    body = details(signed_in, workout_id).json()
    assert body["zone_max"] is None
    assert body["zone_basis"] is None


# --------------------------------------------------------------------------
# A workout that never carried any of it
# --------------------------------------------------------------------------


def test_a_workout_with_no_minutes_answers_with_its_summaries_and_an_empty_list(
    signed_in, ingest_token, db_session
):
    """Every workout synced before the samples table existed looks like this,
    and so does one from a phone that sent no arrays. An empty list rather than
    a refusal: the screen still has figures to draw and says the rest in one
    line."""
    plain = {
        "name": "Outdoor Walk",
        "start": START,
        "duration": 1800,
        "distance": {"qty": 1.2, "units": "mi"},
        "temperature": {"qty": 61.0, "units": "degF"},
        "humidity": {"qty": 55.0, "units": "%"},
    }
    assert post(signed_in, ingest_token, export(plain)).json()["imported"] == 1
    workout_id = the_workout_id(db_session)

    body = details(signed_in, workout_id).json()
    assert body["minutes"] == []
    assert body["temperature_f"] == 61.0
    assert body["humidity_pct"] == 55.0
    assert body["max_hr"] is None
    assert body["elevation_gain_ft"] is None
