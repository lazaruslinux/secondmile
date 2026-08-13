"""Manna: what calories become, where it is kept, and what it never touches.

The law this file pins, in one sentence: manna is the giving lane, so it comes
from burned calories alone and nothing in it moves experience, a level, a chest,
growth or a medal.

Two rules decide every number here. A workout's active calories convert one for
one, rounded up to the next multiple of five, per workout and never over a
total; and steps carry no calories anybody burned on purpose, so they are worth
none of it.

Manna is a bank. It is credited straight into one balance, it is never gathered,
it never spoils and nothing counts down anywhere near it. What it buys, and the
seven days GATHERED FRUIT lives, are test_fruit.py's.
"""

from conftest import let_a_moment_pass, log_workout, make_user
from test_fellowship import befriend, sign_in
from test_steps import reading, sync

from app import models, progress


def bank(db_session, user_id: int) -> int:
    db_session.expire_all()
    row = db_session.get(models.UserProgress, user_id)
    return 0 if row is None else row.manna


def profile(client) -> dict:
    response = client.get("/api/profile")
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# The conversion itself
# --------------------------------------------------------------------------


def test_calories_round_up_to_the_next_five():
    """His two examples, which are the whole rule: a burn already standing on a
    five is worth exactly itself, and anything past one climbs to the next."""
    assert progress.manna_for(650) == 650
    assert progress.manna_for(656) == 660
    # One calorie over is a whole step, which is the generous read on purpose.
    assert progress.manna_for(651) == 655
    assert progress.manna_for(1) == 5


def test_a_workout_with_no_calories_is_worth_no_manna():
    """Nothing recorded, nothing burned, and a confused sensor reading below
    zero are all the same answer. None of them is a free step."""
    assert progress.manna_for(None) == 0
    assert progress.manna_for(0) == 0
    assert progress.manna_for(0.0) == 0
    assert progress.manna_for(-90) == 0


def test_the_conversion_is_per_workout_and_never_over_a_total():
    """Two sessions of 651 are two climbs to 655. Summing the calories first
    would round once and answer 1305, and the backfill, the credit path and the
    rebuild all have to agree, so the rounding happens in one place only."""
    assert progress.manna_for(651) + progress.manna_for(651) == 1310
    assert progress.manna_for(1302) == 1305


# --------------------------------------------------------------------------
# Earning it
# --------------------------------------------------------------------------


def test_a_credited_workout_banks_its_calories(signed_in, db_session, member):
    """Straight into the balance, spendable at once: there is nothing to gather
    and nothing waiting anywhere."""
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    assert profile(signed_in)["manna"] == 650
    log_workout(db_session, member.id, "run", 5.0, kcal=656, offset_min=200)
    # Each workout converts on its own, so the bank is 650 and 660.
    assert profile(signed_in)["manna"] == 1310


def test_accruing_writes_no_batch_of_any_kind(signed_in, db_session, member):
    """The gathered pile is dormant history. Calories reach the balance and
    nothing else, so nothing in the credit path writes a manna batch."""
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    assert db_session.query(models.MannaBatch).count() == 0


def test_the_profile_says_one_manna_number(signed_in, db_session, member):
    """One state, so one field. The waiting half of the old model is gone from
    every payload it was ever on."""
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    read = profile(signed_in)
    assert read["manna"] == 650
    assert "manna_pending" not in read


def test_a_workout_is_only_ever_worth_its_calories_once(signed_in, db_session, member):
    """The same idempotency the experience has: sweeping again credits nothing,
    because the workout already carries its processed marker."""
    log_workout(db_session, member.id, "run", 5.0, kcal=500)
    assert profile(signed_in)["manna"] == 500
    progress.process_user(db_session, member.id)
    assert profile(signed_in)["manna"] == 500


def test_the_miles_play_no_part_in_what_a_workout_is_worth(signed_in, db_session, member):
    """A swim is four XP a mile and a walk is one, and neither of them is a
    calorie: the same burn is the same manna whatever carried it."""
    log_workout(db_session, member.id, "swim", 1.0, kcal=300)
    log_workout(db_session, member.id, "walk", 1.0, kcal=300, offset_min=200)
    assert profile(signed_in)["manna"] == 600


def test_a_long_workout_with_nothing_recorded_earns_experience_and_no_manna(
    signed_in, db_session, member
):
    """The two lanes told apart in one case: the miles are worth what they have
    always been worth, and the empty calorie column is worth nothing."""
    log_workout(db_session, member.id, "run", 10.0)
    read = profile(signed_in)
    assert read["xp"] == 10.0
    assert read["manna"] == 0


# --------------------------------------------------------------------------
# Steps grant nothing
# --------------------------------------------------------------------------


def test_steps_grant_no_manna(signed_in, ingest_token, db_session, member):
    """The retreat law, one lane further on. A pedometer's day is stored and
    shown and is worth no manna, whatever it claims to have covered."""
    sync(signed_in, ingest_token, metrics=reading(steps=22000, miles=9.0))
    read = profile(signed_in)
    assert read["week_steps"] == 22000
    assert read["manna"] == 0
    assert bank(db_session, member.id) == 0


def test_a_day_of_steps_beside_a_workout_adds_nothing_to_it(
    signed_in, ingest_token, db_session, member
):
    """The run's calories and nothing else, with a full day of walking around
    recorded beside them."""
    log_workout(db_session, member.id, "run", 4.0, kcal=400)
    sync(signed_in, ingest_token, metrics=reading(steps=18000, miles=7.0))
    assert profile(signed_in)["manna"] == 400


# --------------------------------------------------------------------------
# Rebuilding it
# --------------------------------------------------------------------------


def test_a_rebuild_recomputes_the_bank_from_what_survives(signed_in, db_session, member):
    """Deleting takes back the calories the same way it takes back the miles:
    both are derivations of the workouts that are still there."""
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    doomed = log_workout(db_session, member.id, "run", 3.0, kcal=300, offset_min=200)
    assert bank(db_session, member.id) == 950

    response = signed_in.delete(f"/api/workouts/{doomed.id}")
    assert response.status_code == 204, response.text
    assert bank(db_session, member.id) == 650

    # And a restore puts back exactly what the deletion took, which is what
    # makes the bank a derivation rather than a running tally.
    response = signed_in.post(f"/api/workouts/{doomed.id}/restore")
    assert response.status_code == 200, response.text
    assert bank(db_session, member.id) == 950


def test_recompute_lands_on_the_same_bank_it_started_with(signed_in, db_session, member):
    """The safety hatch for a changed constant replays the history, and the
    history converts to the same manna every time."""
    log_workout(db_session, member.id, "run", 5.0, kcal=656)
    log_workout(db_session, member.id, "cycle", 12.0, kcal=444, offset_min=200)
    assert bank(db_session, member.id) == 1105

    progress.recompute(db_session, member.id)
    assert bank(db_session, member.id) == 1105


def test_a_rebuild_reads_no_steps_at_all(signed_in, ingest_token, db_session, member):
    """The dormant step ledger is no fuel here either: a rebuild lands on what
    the recorded activities burned and on nothing a pedometer saw."""
    log_workout(db_session, member.id, "run", 4.0, kcal=400)
    sync(signed_in, ingest_token, metrics=reading(steps=20000, miles=8.0))
    progress.recompute(db_session, member.id)
    assert bank(db_session, member.id) == 400


# --------------------------------------------------------------------------
# Who may read it
# --------------------------------------------------------------------------


def test_a_friend_reads_no_manna(signed_in, db_session, member):
    """The friend payload is an allowlist, and manna is not on it. What
    somebody has to give away is theirs to know, exactly as their steps are."""
    friend, mate = sign_in(db_session, "mate")
    befriend(db_session, member, friend)
    log_workout(db_session, member.id, "run", 5.0, kcal=650)

    seen = mate.get(f"/api/profile/{member.id}").json()
    assert "manna" not in seen
    # The lifetime calories are still there under their own name: calories keep
    # reading as calories wherever they always did.
    assert seen["lifetime"]["run"]["active_kcal"] == 650.0


def test_a_member_card_carries_no_manna(signed_in, db_session, member):
    """The stranger's card is shorter still, and this is one more thing not on
    it."""
    other, someone = sign_in(db_session, "other")
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    seen = someone.get(f"/api/profile/{member.id}").json()
    assert seen["restricted"] is True
    assert "manna" not in seen


def test_a_feed_card_carries_no_manna(signed_in, db_session, member):
    """Never beside the XP on a card. Manna meets the feed through giving and
    through nothing else."""
    friend, mate = sign_in(db_session, "mate")
    befriend(db_session, member, friend)
    log_workout(db_session, member.id, "run", 5.0, kcal=650)

    rows = mate.get("/api/feed").json()
    assert rows
    for row in rows:
        assert "manna" not in row


# --------------------------------------------------------------------------
# The letter
# --------------------------------------------------------------------------


def test_the_letter_says_what_the_window_of_calories_became(
    signed_in, db_session, member
):
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    log_workout(db_session, member.id, "run", 3.0, kcal=656, offset_min=200)
    letter = signed_in.get("/api/recap").json()
    # Per workout here as everywhere: 650 and 660.
    assert letter["manna"] == 1310


def test_a_letter_with_no_calories_in_it_says_none(signed_in, db_session, member):
    log_workout(db_session, member.id, "run", 5.0)
    assert signed_in.get("/api/recap").json()["manna"] == 0


def test_the_letter_covers_the_same_window_the_miles_do(signed_in, db_session, member):
    """Read, cleared, and then one more workout: the letter reports what arrived
    since, and never the bank the account is sitting on."""
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    assert signed_in.get("/api/recap").json()["manna"] == 650
    assert signed_in.post("/api/recap/ack").status_code == 204
    let_a_moment_pass(db_session)

    log_workout(db_session, member.id, "run", 2.0, kcal=200, offset_min=300)
    letter = signed_in.get("/api/recap").json()
    assert letter["manna"] == 200
    # The bank itself is the profile's business and has both in it.
    assert profile(signed_in)["manna"] == 850


def test_a_deleted_workout_is_out_of_the_letter_and_out_of_the_bank(
    signed_in, db_session, member
):
    doomed = log_workout(db_session, member.id, "run", 3.0, kcal=300)
    assert signed_in.delete(f"/api/workouts/{doomed.id}").status_code == 204
    letter = signed_in.get("/api/recap").json()
    assert letter["manna"] == 0
    assert profile(signed_in)["manna"] == 0


def test_manna_never_spoils_and_nothing_counts_down(signed_in, db_session, member):
    """A bank read a fortnight later is the same bank, and no response carries a
    countdown of any kind."""
    log_workout(db_session, member.id, "run", 5.0, kcal=650)
    let_a_moment_pass(db_session, seconds=20 * 24 * 60 * 60)
    read = profile(signed_in)
    assert read["manna"] == 650
    assert not [key for key in read if "spoil" in key or "expire" in key]
    letter = signed_in.get("/api/recap").json()
    assert not [key for key in letter if "spoil" in key or "expire" in key]


def test_an_account_that_has_done_nothing_has_none(db_session, admin):
    """A fresh row starts empty rather than null, so nothing downstream has to
    know what a missing bank would mean."""
    person = make_user(db_session, "quiet", "quiet-password-1")
    row = progress.ensure_progress(db_session, person.id)
    assert row.manna == 0
