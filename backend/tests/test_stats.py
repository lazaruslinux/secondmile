"""The public counter: the two numbers the welcome page reads before anybody
signs in.

The negatives are most of the point. It says nothing but the pair, a workout
somebody took back is gone from both totals, and the answer is a count taken up
to ten minutes ago rather than a live one, which is what stops the endpoint
being a way to watch a member's run land.
"""

from conftest import log_workout

from app import security
from app.routers import stats


def test_stats_answers_the_pair_and_nothing_else(client, db_session, member):
    # 3.7 miles reads as 3: the number on the page is ground certainly covered.
    log_workout(db_session, member.id, "run", 3.7)
    response = client.get("/api/stats")
    assert response.status_code == 200
    assert response.json() == {"miles": 3, "activities": 1, "steps": 0}


def test_an_instance_with_nothing_on_it_counts_zero(client):
    assert client.get("/api/stats").json() == {"miles": 0, "activities": 0, "steps": 0}


def test_a_deleted_workout_leaves_both_totals(client, db_session, member):
    kept = log_workout(db_session, member.id, "run", 4.0)
    taken_back = log_workout(db_session, member.id, "run", 6.0, offset_min=120)
    taken_back.deleted_at = security.now_utc()
    db_session.commit()
    stats.reset_cache()
    assert client.get("/api/stats").json() == {"miles": 4, "activities": 1, "steps": 0}
    assert kept.deleted_at is None


def test_the_count_is_held_rather_than_taken_again(client, db_session, member):
    log_workout(db_session, member.id, "run", 2.0)
    first = client.get("/api/stats").json()
    assert first == {"miles": 2, "activities": 1, "steps": 0}

    # A workout lands inside the cache's window. Nobody watching the endpoint
    # learns that it did.
    log_workout(db_session, member.id, "walk", 5.0, offset_min=180)
    assert client.get("/api/stats").json() == first

    stats.reset_cache()
    assert client.get("/api/stats").json() == {"miles": 7, "activities": 2, "steps": 0}


def test_the_count_is_taken_again_once_it_is_old(client, db_session, member, monkeypatch):
    log_workout(db_session, member.id, "run", 2.0)
    assert client.get("/api/stats").json() == {"miles": 2, "activities": 1, "steps": 0}
    # Nothing is cached for no time at all, so the next request is past the age
    # whatever the real clock did between the two.
    monkeypatch.setattr(stats, "CACHE_SECONDS", -1)
    log_workout(db_session, member.id, "walk", 5.0, offset_min=180)
    assert client.get("/api/stats").json() == {"miles": 7, "activities": 2, "steps": 0}


def test_hammering_the_counter_is_refused(client):
    codes = [client.get("/api/stats").status_code for _ in range(61)]
    assert codes.count(200) == 60
    assert codes[-1] == 429
