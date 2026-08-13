"""The seeds migration, run over a database shaped like the one it will meet.

Everything in here is invented, and it is run against a throwaway SQLite file
rather than the in-memory database the rest of the suite uses: a migration is
only worth testing if it is the real revision script doing the real work.
"""

import json
import pathlib

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app import config

BACKEND = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def migrated(tmp_path, monkeypatch):
    """A database at revision 0008, and a way to carry it the rest of the way.

    The alembic environment reads the application's own settings, so pointing
    those at a temporary file is all it takes to run the real scripts.
    """
    url = f"sqlite:///{tmp_path}/history.db"
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0008")
    engine = sa.create_engine(url)
    try:
        yield engine, (lambda: command.upgrade(cfg, "head"))
    finally:
        engine.dispose()


@pytest.fixture()
def at_0012(tmp_path, monkeypatch):
    """A database at revision 0012, which is the shape the plot cleanup meets.

    Its own fixture rather than the 0008 one: plantings and satchel_items do
    not exist until 0009, so a case about them has to start further along.
    """
    url = f"sqlite:///{tmp_path}/plot.db"
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0012")
    engine = sa.create_engine(url)
    try:
        yield engine, (lambda: command.upgrade(cfg, "head"))
    finally:
        engine.dispose()


@pytest.fixture()
def at_0024(tmp_path, monkeypatch):
    """A database at revision 0024, which is the shape the manna backfill meets.

    Its own fixture rather than either of the earlier ones: the backfill reads a
    workout's deleted_at and the processed marker beside it, and the column
    arrives in 0020, well after the revision those two start at.
    """
    url = f"sqlite:///{tmp_path}/manna.db"
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0024")
    engine = sa.create_engine(url)
    try:
        yield engine, (lambda: command.upgrade(cfg, "head"))
    finally:
        engine.dispose()


def _account(connection, user_id: int, username: str, slots: str = "[]") -> None:
    connection.execute(
        sa.text(
            "INSERT INTO users (id, username, password_hash, email_verified, is_admin,"
            " units, displayed_badges, created_at)"
            " VALUES (:user_id, :username, 'x', 1, 0, 'imperial', :slots,"
            " '2026-01-01 00:00:00')"
        ),
        {"user_id": user_id, "username": username, "slots": slots},
    )


def _planting(connection, planting_id, user_id, species, planted_at, growth, matured=None) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO plantings (id, user_id, species, rarity, planted_at, growth_mi,"
            " matured_at) VALUES (:id, :user_id, :species, 'common', :planted_at, :growth,"
            " :matured)"
        ),
        {
            "id": planting_id,
            "user_id": user_id,
            "species": species,
            "planted_at": planted_at,
            "growth": growth,
            "matured": matured,
        },
    )


def _seed(connection, item_id, user_id, species, acquired_at, *, used_at=None, kind="seed") -> None:
    connection.execute(
        sa.text(
            "INSERT INTO satchel_items (id, user_id, kind, species, rarity, chest_id,"
            " acquired_at, used_at, earned_renown)"
            " VALUES (:id, :user_id, :kind, :species, 'uncommon', NULL, :acquired_at,"
            " :used_at, 0)"
        ),
        {
            "id": item_id,
            "user_id": user_id,
            "kind": kind,
            "species": species,
            "acquired_at": acquired_at,
            "used_at": used_at,
        },
    )


def test_the_plot_cleanup_folds_every_duplicate_into_the_oldest_one(at_0012):
    """0013: one plant per species, and the miles of the duplicates go into it
    rather than anywhere near a bin."""
    engine, upgrade = at_0012
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _account(connection, 2, "mate")
        # Three strawberries out of order, and the middle row is the oldest.
        _planting(connection, 1, 1, "strawberry", "2026-03-01 00:00:00", 10.0)
        _planting(connection, 2, 1, "strawberry", "2026-02-01 00:00:00", 5.0, "2026-04-01 00:00:00")
        _planting(connection, 3, 1, "strawberry", "2026-05-01 00:00:00", 2.5)
        # One of a kind, and untouched by any of it.
        _planting(connection, 4, 1, "olive", "2026-01-01 00:00:00", 40.0)
        # A keeper with no date of its own takes the earliest one folded in.
        _planting(connection, 5, 2, "olive", "2026-01-05 00:00:00", 1.0)
        _planting(connection, 6, 2, "olive", "2026-02-05 00:00:00", 2.0, "2026-06-01 00:00:00")
        _planting(connection, 7, 2, "olive", "2026-03-05 00:00:00", 3.0, "2026-05-15 00:00:00")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT id, user_id, species, growth_mi, matured_at FROM plantings ORDER BY id"
            )
        ).all()
        assert [(row.id, row.user_id, row.species) for row in rows] == [
            (2, 1, "strawberry"),
            (4, 1, "olive"),
            (5, 2, "olive"),
        ]
        by_id = {row.id: row for row in rows}
        # Ten and two and a half added into the five the keeper had.
        assert by_id[2].growth_mi == 17.5
        # Its own date stands, even though a row folded in had none.
        assert by_id[2].matured_at == "2026-04-01 00:00:00"
        assert by_id[4].growth_mi == 40.0
        assert by_id[5].growth_mi == 6.0
        # The keeper had no date, so the earliest among the folded rows carries.
        assert by_id[5].matured_at == "2026-05-15 00:00:00"


def test_the_plot_cleanup_turns_the_spare_seeds_into_water(at_0012):
    """A seed of something already growing, and every seed past the first of
    something that is not, becomes water and keeps what its slot was worth."""
    engine, upgrade = at_0012
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _planting(connection, 1, 1, "strawberry", "2026-01-01 00:00:00", 4.0)
        # Two of something already in the ground: both are water now.
        _seed(connection, 1, 1, "strawberry", "2026-02-01 00:00:00")
        _seed(connection, 2, 1, "strawberry", "2026-03-01 00:00:00")
        # Three of something with nothing in the ground: the oldest survives.
        _seed(connection, 3, 1, "mango", "2026-04-01 00:00:00")
        _seed(connection, 4, 1, "mango", "2026-02-15 00:00:00")
        _seed(connection, 5, 1, "mango", "2026-05-01 00:00:00")
        # A seed already spent is the planting above and is never touched.
        _seed(connection, 6, 1, "strawberry", "2026-01-01 00:00:00", used_at="2026-01-01 00:00:00")
        # Water that was always water stays exactly as it is.
        _seed(connection, 7, 1, None, "2026-01-02 00:00:00", kind="water")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        rows = {
            row.id: row
            for row in connection.execute(
                sa.text("SELECT id, kind, species, rarity, used_at FROM satchel_items")
            ).all()
        }
        for item_id in (1, 2, 3, 5):
            assert (rows[item_id].kind, rows[item_id].species) == ("water", None), item_id
            # The slot it came out of is what it is worth, converted or not.
            assert rows[item_id].rarity == "uncommon", item_id
        # The earliest mango is the one kept, and it is still a seed.
        assert (rows[4].kind, rows[4].species) == ("seed", "mango")
        # Neither the spent seed nor the water that was always water moved.
        assert (rows[6].kind, rows[6].species, rows[6].used_at) == (
            "seed",
            "strawberry",
            "2026-01-01 00:00:00",
        )
        assert (rows[7].kind, rows[7].species) == ("water", None)

        # Nothing was invented and nothing was deleted.
        assert len(rows) == 7


def test_the_recorded_level_arrives_empty_on_the_plants_already_growing(at_0012):
    """0014 is purely additive, and deliberately backfills nothing: a plant
    that predates it has no recorded level, which is what keeps the first
    letter after the release quiet about plants somebody has had for weeks."""
    engine, upgrade = at_0012
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _planting(connection, 1, 1, "strawberry", "2026-01-01 00:00:00", 40.0)
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(sa.text("PRAGMA table_info(plantings)"))}
        assert "level_at_ack" in columns
        assert connection.execute(
            sa.text("SELECT growth_mi, level_at_ack FROM plantings")
        ).all() == [(40.0, None)]


def test_the_recorded_growth_is_backfilled_where_every_plant_stands(at_0012):
    """0021 does backfill, which 0014 could not: copying growth across needs no
    catalogue. A plant recorded where it stands has crossed nothing, so the
    first letter after the release says nothing about weeks it already had."""
    engine, upgrade = at_0012
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _planting(connection, 1, 1, "strawberry", "2026-01-01 00:00:00", 40.0)
        _planting(connection, 2, 1, "mango", "2026-01-01 00:00:00", 0.0)
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(sa.text("PRAGMA table_info(plantings)"))}
        assert "growth_at_ack" in columns
        assert connection.execute(
            sa.text("SELECT id, growth_mi, growth_at_ack FROM plantings ORDER BY id")
        ).all() == [(1, 40.0, 40.0), (2, 0.0, 0.0)]


def _run(connection, workout_id: int, user_id: int, start: str) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO workouts (id, user_id, activity, start_ts, duration_s,"
            " distance_mi, active_kcal, source, flags, created_at)"
            " VALUES (:id, :user_id, 'run', :start, 5400, 9.0, 900.0, 'sync', '{}',"
            " :start)"
        ),
        {"id": workout_id, "user_id": user_id, "start": start},
    )


def _week_earn(connection, user_id: int, family: str, badge_id: str, workout_id: int) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO weekly_badge_earns (user_id, week_start, family, badge_id,"
            " workout_id, earned_at)"
            " VALUES (:user_id, '2026-06-01', :family, :badge, :workout,"
            " '2026-06-03 09:00:00')"
        ),
        {"user_id": user_id, "family": family, "badge": badge_id, "workout": workout_id},
    )


def test_retiring_the_second_mile_takes_its_earns_and_its_slots(at_0012):
    """0015: the weekly rows it earned go, the id comes out of every badge slot,
    and what was chosen around it stays exactly as it was chosen."""
    engine, upgrade = at_0012
    with engine.connect() as connection:
        _account(
            connection,
            1,
            "runner",
            '["early_riser", "weekly_25", "race_10k", "second_mile"]',
        )
        _account(connection, 2, "mate", '["second_mile"]')
        _account(connection, 3, "other", '["race_5k", "night_owl"]')
        _run(connection, 1, 1, "2026-06-03 09:00:00")
        _run(connection, 2, 2, "2026-06-03 09:00:00")
        _week_earn(connection, 1, "second_mile", "second_mile", 1)
        _week_earn(connection, 1, "weekly", "weekly_25", 1)
        _week_earn(connection, 2, "second_mile", "second_mile", 2)
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        # The family was a family of one, so nothing of it is left; the weekly
        # row beside it is untouched.
        assert connection.execute(
            sa.text(
                "SELECT user_id, family, badge_id FROM weekly_badge_earns ORDER BY user_id"
            )
        ).all() == [(1, "weekly", "weekly_25")]

        slots = {
            row.id: json.loads(row.displayed_badges)
            for row in connection.execute(
                sa.text("SELECT id, displayed_badges FROM users")
            ).all()
        }
        # The three that are left, in the order they were worn.
        assert slots[1] == ["early_riser", "weekly_25", "race_10k"]
        assert slots[2] == []
        # Nobody else's slots were rewritten at all.
        assert slots[3] == ["race_5k", "night_owl"]


def _friendship(connection, row_id, requester, addressee, status) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO friendships (id, requester_id, addressee_id, status, created_at)"
            " VALUES (:id, :requester, :addressee, :status, '2026-07-01 12:00:00')"
        ),
        {"id": row_id, "requester": requester, "addressee": addressee, "status": status},
    )


def test_the_outbound_invites_arrive_carrying_what_is_already_waiting(at_0012):
    """0016: the sent list moves off the friendship rows and onto the names.

    The backfill is what keeps the deploy quiet. Every invite already waiting is
    a name its sender typed, so without it every one of them would vanish from
    the sender's screen while still sitting on the recipient's.
    """
    engine, upgrade = at_0012
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _account(connection, 2, "mate")
        _account(connection, 3, "other")
        _friendship(connection, 1, 1, 2, "pending")
        # Accepted, so it is a friendship now and has nothing left to wait for.
        _friendship(connection, 2, 1, 3, "accepted")
        # Somebody else's invite, which belongs on their list and not on this one.
        _friendship(connection, 3, 2, 3, "pending")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT user_id, username, created_at FROM outbound_invites"
                " ORDER BY user_id, username"
            )
        ).all() == [
            (1, "mate", "2026-07-01 12:00:00"),
            (2, "other", "2026-07-01 12:00:00"),
        ]
        # Nothing was taken off the friendships: they are still what an invite
        # is answered from.
        assert connection.execute(sa.text("SELECT COUNT(*) FROM friendships")).scalar_one() == 3

        # One attempt per name per account, so a second invite is the no-op it
        # always looked like.
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO outbound_invites (user_id, username, created_at)"
                    " VALUES (1, 'mate', '2026-07-02 12:00:00')"
                )
            )
        connection.rollback()


def test_the_plot_cleanup_leaves_a_tidy_plot_alone(at_0012):
    engine, upgrade = at_0012
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _planting(connection, 1, 1, "strawberry", "2026-01-01 00:00:00", 4.0)
        _planting(connection, 2, 1, "olive", "2026-01-02 00:00:00", 9.0)
        _seed(connection, 1, 1, "mango", "2026-02-01 00:00:00")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT id, growth_mi FROM plantings ORDER BY id")
        ).all() == [(1, 4.0), (2, 9.0)]
        assert connection.execute(
            sa.text("SELECT kind, species FROM satchel_items")
        ).all() == [("seed", "mango")]


def _fill(connection) -> None:
    """A little of everything the old shape held: an account partway up the
    old chest accumulator, two unopened chests, a filled album, both kinds of
    achievement, and badge slots holding one id of each era."""
    connection.execute(
        sa.text(
            "INSERT INTO users (id, username, password_hash, email_verified, is_admin,"
            " units, displayed_badges, created_at)"
            " VALUES (1, 'runner', 'x', 1, 0, 'imperial',"
            " '[\"week_10\", \"race_half\"]', '2026-01-01 00:00:00')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO user_progress (user_id, xp, level, chest_progress_mi,"
            " next_chest_gap_mi, renown, updated_at)"
            " VALUES (1, 29.02, 3, 1.75, 3.4, 12, '2026-08-01 00:00:00')"
        )
    )
    for chest_id, card_id in ((1, "hedgerow_wren"), (2, "still_water_otter")):
        connection.execute(
            sa.text(
                "INSERT INTO chests (id, user_id, card_id, dropped_at, opened_at)"
                f" VALUES ({chest_id}, 1, '{card_id}', '2026-08-01 00:00:00', NULL)"
            )
        )
    connection.execute(
        sa.text(
            "INSERT INTO user_cards (user_id, card_id, count, first_found_at)"
            " VALUES (1, 'hedgerow_hawthorn', 2, '2026-07-01 00:00:00')"
        )
    )
    for achievement_id in ("week_10", "week_25", "collection_first_card", "collection_complete"):
        connection.execute(
            sa.text(
                "INSERT INTO user_achievements (user_id, achievement_id, earned_at, gilded)"
                f" VALUES (1, '{achievement_id}', '2026-07-01 00:00:00', 0)"
            )
        )
    connection.commit()


def test_the_seeds_migration_keeps_what_was_earned_and_drops_the_cards(migrated):
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)

    upgrade()

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert {"satchel_items", "plantings", "anointings"} <= tables
        assert "user_cards" not in tables

        columns = {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(chests)"))
        }
        assert "card_id" not in columns
        assert {"tier", "from_anointing_id"} <= columns

        # The chests themselves stay, waiting, and belong to the first step.
        chests = connection.execute(
            sa.text("SELECT id, tier, from_anointing_id, opened_at FROM chests ORDER BY id")
        ).all()
        assert chests == [(1, None, None, None), (2, None, None, None)]

        # The accumulator starts again from the 5K step; nothing else moves.
        row = connection.execute(
            sa.text("SELECT xp, level, chest_progress_mi, cycle_pos, renown FROM user_progress")
        ).one()
        assert row == (29.02, 3, 0.0, 0, 12)
        progress_columns = {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(user_progress)"))
        }
        assert "next_chest_gap_mi" not in progress_columns

        # The achievements went entirely in 0012, table and all.
        assert "user_achievements" not in tables


def test_the_medals_migration_reshapes_the_earns_and_prunes_the_slots(migrated):
    """0012: one workout may hold two medals, a week gets a table of its own,
    and any id the twelve do not name is pruned out of the badge slots."""
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)
        connection.execute(
            sa.text(
                "INSERT INTO workouts (id, user_id, activity, start_ts, duration_s,"
                " distance_mi, active_kcal, source, flags, created_at)"
                " VALUES (1, 1, 'run', '2026-07-01 05:30:00', 2700, 4.0, 400.0,"
                " 'sync', '{}', '2026-07-01 07:00:00')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO badge_earns (id, user_id, badge_id, workout_id, earned_at)"
                " VALUES (1, 1, 'race_5k', 1, '2026-07-01 05:30:00')"
            )
        )
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert "weekly_badge_earns" in tables
        assert "user_achievements" not in tables

        # What was earned survives the table being rebuilt.
        assert connection.execute(
            sa.text("SELECT badge_id, workout_id FROM badge_earns")
        ).all() == [("race_5k", 1)]

        # The same workout may now hold a second medal from another family.
        connection.execute(
            sa.text(
                "INSERT INTO badge_earns (id, user_id, badge_id, workout_id, earned_at)"
                " VALUES (2, 1, 'early_riser', 1, '2026-07-01 05:30:00')"
            )
        )
        connection.commit()
        # The same pair twice is still refused, which is what makes a replay safe.
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO badge_earns (id, user_id, badge_id, workout_id, earned_at)"
                    " VALUES (3, 1, 'early_riser', 1, '2026-07-01 05:30:00')"
                )
            )
        connection.rollback()

        # The achievement id in the badge slots is pruned; the race id stays.
        slots = connection.execute(sa.text("SELECT displayed_badges FROM users")).scalar_one()
        assert json.loads(slots) == ["race_half"]


def test_the_migration_steps_back_down_again(migrated):
    """Not something a release ever does, but a broken downgrade is how a test
    database gets stuck."""
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)
    upgrade()

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "0008")

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert "user_cards" in tables
        assert "satchel_items" not in tables


def test_the_account_columns_arrive_empty_and_disturb_nothing(migrated):
    """0010 is purely additive, which is what lets it run on a live database:
    an account that existed before it keeps working with all five empty."""
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)

    upgrade()

    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(sa.text("PRAGMA table_info(users)"))}
        assert {
            "first_name",
            "last_name",
            "birthdate",
            "gender",
            "pending_email",
        } <= columns

        row = connection.execute(
            sa.text(
                "SELECT username, first_name, last_name, birthdate, gender, pending_email"
                " FROM users"
            )
        ).one()
        assert row == ("runner", None, None, None, None, None)


def test_the_video_table_arrives_empty_beside_the_photo_one(migrated):
    """0019 is purely additive as well: a workout that existed before it keeps
    working with nothing attached, and the photo table beside it is untouched.
    """
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)
        _run(connection, 1, 1, "2026-07-01 06:00:00")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert {"workout_photos", "workout_videos"} <= tables
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM workout_videos")
        ).scalar_one() == 0
        columns = {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(workout_videos)"))
        }
        assert columns == {"id", "workout_id", "created_at"}
        # The workout it hangs off is still exactly what it was.
        assert connection.execute(
            sa.text("SELECT distance_mi FROM workouts")
        ).scalar_one() == 9.0


def test_the_workout_words_and_photos_arrive_empty(migrated):
    """0011 is purely additive too: a workout that existed before it keeps
    working with both columns empty and no pictures on it."""
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)
        connection.execute(
            sa.text(
                "INSERT INTO workouts (id, user_id, activity, start_ts, duration_s,"
                " distance_mi, active_kcal, source, flags, created_at)"
                " VALUES (1, 1, 'run', '2026-07-01 06:00:00', 1800, 3.0, 300.0,"
                " 'manual', '{}', '2026-07-01 07:00:00')"
            )
        )
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert "workout_photos" in tables
        row = connection.execute(
            sa.text("SELECT distance_mi, title, post FROM workouts")
        ).one()
        assert row == (3.0, None, None)


def test_the_step_tables_arrive_empty_and_the_crossing_learns_to_be_null(migrated):
    """0023: three new tables, nothing in them, and a weekly earn that may now
    record no workout at all.

    The nullable column is the half worth checking with a statement rather than
    with PRAGMA: what the release needs is for a row carrying no workout at all
    to be storable beside one that carries its own. The table itself arrives in
    0012, well after the revision this database starts at, so both rows are
    written on the far side of the upgrade.
    """
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)
        _run(connection, 1, 1, "2026-07-01 06:00:00")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert {"daily_steps", "step_credits", "processed_step_credits"} <= tables
        for table in ("daily_steps", "step_credits", "processed_step_credits"):
            assert connection.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
        _week_earn(connection, 1, "weekly", "weekly_10", 1)
        connection.execute(
            sa.text(
                "INSERT INTO weekly_badge_earns (user_id, week_start, family, badge_id,"
                " workout_id, earned_at)"
                " VALUES (1, '2026-06-08', 'weekly', 'weekly_15', NULL,"
                " '2026-06-10 09:00:00')"
            )
        )
        connection.commit()
        rows = connection.execute(
            sa.text("SELECT badge_id, workout_id FROM weekly_badge_earns ORDER BY week_start")
        ).all()
        # One week names the run that crossed the line and the other names
        # nothing, which is what a week the steps carried looks like.
        assert rows == [("weekly_10", 1), ("weekly_15", None)]


def test_the_bug_report_table_arrives_empty_and_touches_nothing(migrated):
    """0024 is purely additive: one table, nothing in it, and every row that was
    already there exactly as it was.

    The stamped columns are checked by writing a row rather than by PRAGMA,
    because what the release needs is for a report with no browser string to be
    storable beside one that has one.
    """
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)
        _run(connection, 1, 1, "2026-07-01 06:00:00")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert "bug_reports" in tables
        assert connection.execute(sa.text("SELECT COUNT(*) FROM bug_reports")).scalar_one() == 0
        # The account and its workout are untouched by an additive revision.
        assert connection.execute(sa.text("SELECT username FROM users")).scalar_one() == "runner"
        assert connection.execute(sa.text("SELECT distance_mi FROM workouts")).scalar_one() == 9.0

        connection.execute(
            sa.text(
                "INSERT INTO bug_reports (user_id, created_at, text, view, user_agent)"
                " VALUES (1, '2026-08-12 09:00:00', 'the grove drew nothing', 'grove',"
                " 'Mozilla/5.0'), (1, '2026-08-12 09:05:00', 'and again', 'home', NULL)"
            )
        )
        connection.commit()
        assert connection.execute(
            sa.text("SELECT view, user_agent FROM bug_reports ORDER BY id")
        ).all() == [("grove", "Mozilla/5.0"), ("home", None)]


def _credited(connection, workout_id: int) -> None:
    """The marker the pipeline writes when it has paid for a workout. What the
    manna backfill counts is what already carries one."""
    connection.execute(
        sa.text("INSERT INTO processed_workouts (workout_id) VALUES (:id)"),
        {"id": workout_id},
    )


def _progress(connection, user_id: int, xp: float = 0.0) -> None:
    """One progress row in the shape 0024 leaves it, which is the row the manna
    column lands on."""
    connection.execute(
        sa.text(
            "INSERT INTO user_progress (user_id, xp, level, chest_progress_mi,"
            " cycle_pos, renown, updated_at)"
            " VALUES (:user_id, :xp, 0, 0, 0, 0, '2026-08-01 00:00:00')"
        ),
        {"user_id": user_id, "xp": xp},
    )


def _burn(connection, workout_id: int, user_id: int, kcal, *, deleted=None) -> None:
    """One workout that burned something, dated so nothing collides."""
    start = f"2026-07-{workout_id:02d} 06:00:00"
    connection.execute(
        sa.text(
            "INSERT INTO workouts (id, user_id, activity, start_ts, duration_s,"
            " distance_mi, active_kcal, source, flags, created_at, deleted_at)"
            " VALUES (:id, :user_id, 'run', :start, 3600, 5.0, :kcal, 'sync', '{}',"
            " :start, :deleted)"
        ),
        {
            "id": workout_id,
            "user_id": user_id,
            "start": start,
            "kcal": kcal,
            "deleted": deleted,
        },
    )


def test_the_manna_backfill_converts_every_credited_workout(at_0024):
    """0025: the column arrives at zero for everybody and is then filled from
    the calories already recorded.

    Per workout and rounded up, which is his rule and the app's: 650 stays 650
    and 656 climbs to 660. A deleted workout never earned anything, and one
    still waiting for its first sweep is paid for by that sweep, so neither is
    counted here.
    """
    engine, upgrade = at_0024
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _progress(connection, 1, xp=29.02)
        _account(connection, 2, "mate")
        _progress(connection, 2)
        # His two examples, on one account.
        _burn(connection, 1, 1, 650.0)
        _burn(connection, 2, 1, 656.0)
        # Nothing burned is worth nothing rather than a free step. The column
        # itself refuses a null, which is why a workout with nothing recorded is
        # a zero here; the null a reader might still meet is answered one layer
        # up, in app.progress.manna_for.
        _burn(connection, 3, 1, 0.0)
        _burn(connection, 4, 1, 0.0)
        # Taken back, so the calories went with the miles.
        _burn(connection, 5, 1, 900.0, deleted="2026-08-01 00:00:00")
        # Somebody else's, by the same rule and no special case.
        _burn(connection, 6, 2, 121.0)
        for workout_id in (1, 2, 3, 4, 5, 6):
            _credited(connection, workout_id)
        # Arrived and not yet credited: the sweep after the upgrade pays for it,
        # and counting it here as well would pay twice.
        _burn(connection, 7, 1, 500.0)
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT user_id, manna_pending FROM user_progress ORDER BY user_id")
        ).all() == [(1, 1310), (2, 125)]
        # Purely additive beside it: the experience the account already had is
        # exactly where it was.
        assert connection.execute(
            sa.text("SELECT xp FROM user_progress WHERE user_id = 1")
        ).scalar_one() == 29.02


def test_the_manna_column_steps_back_down_again(at_0024):
    """Stepping back takes the column away and leaves the workouts every number
    in it was worked out from untouched, so the same upgrade lands on the same
    pile a second time."""
    engine, upgrade = at_0024
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _progress(connection, 1)
        _burn(connection, 1, 1, 656.0)
        _credited(connection, 1)
        connection.commit()
    upgrade()

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "0024")

    with engine.connect() as connection:
        columns = {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(user_progress)"))
        }
        assert "manna_pending" not in columns
        assert connection.execute(
            sa.text("SELECT active_kcal FROM workouts")
        ).scalar_one() == 656.0

    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT manna_pending FROM user_progress")
        ).scalar_one() == 660


def test_the_bug_report_table_steps_back_down_again(migrated):
    """The whole revision is one table, so stepping back takes it away and
    leaves the release before it intact."""
    engine, upgrade = migrated
    with engine.connect() as connection:
        _fill(connection)
    upgrade()

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "0023")

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert "bug_reports" not in tables
        # The revision before it is still whole.
        assert {"daily_steps", "step_credits"} <= tables


@pytest.fixture()
def at_0025(tmp_path, monkeypatch):
    """A database at revision 0025, which is the shape the fruit release meets.

    Its own fixture again: the columns land on user_progress and plantings, and
    the pending manna the whole round is built around only exists from 0025 on.
    """
    url = f"sqlite:///{tmp_path}/fruit.db"
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0025")
    engine = sa.create_engine(url)
    try:
        yield engine, (lambda: command.upgrade(cfg, "head"))
    finally:
        engine.dispose()


@pytest.fixture()
def at_0026(tmp_path, monkeypatch):
    """A database at revision 0026, which is the shape the indoor column meets.

    Its own fixture because the backfill reads ingest_log payloads against
    workout rows, and it is the last revision before the column exists.
    """
    url = f"sqlite:///{tmp_path}/indoor.db"
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0026")
    engine = sa.create_engine(url)
    try:
        yield engine, (lambda: command.upgrade(cfg, "head"))
    finally:
        engine.dispose()


def _session_row(connection, workout_id: int, user_id: int, start: str, duration: int) -> None:
    """One stored workout, keyed the way the sync keys them: the account, the
    start in UTC, and the duration in whole seconds."""
    connection.execute(
        sa.text(
            "INSERT INTO workouts (id, user_id, activity, start_ts, duration_s,"
            " distance_mi, active_kcal, source, flags, created_at)"
            " VALUES (:id, :user_id, 'run', :start, :duration, 3.0, 300.0, 'sync', '{}',"
            " :start)"
        ),
        {"id": workout_id, "user_id": user_id, "start": start, "duration": duration},
    )


def _sync(connection, log_id: int, user_id: int, *entries) -> None:
    """One surviving ingest log row, carrying the export as it arrived."""
    connection.execute(
        sa.text(
            "INSERT INTO ingest_log (id, user_id, received_at, payload, result)"
            " VALUES (:id, :user_id, '2026-07-20 20:00:00', :payload, '{}')"
        ),
        {
            "id": log_id,
            "user_id": user_id,
            "payload": json.dumps({"data": {"workouts": list(entries)}}),
        },
    )


def _entry(name: str, start: str, duration) -> dict:
    return {"name": name, "start": start, "duration": duration}


def test_the_indoor_column_is_backfilled_from_the_surviving_ingest_log(at_0026):
    """0027: the column arrives false for everybody and is then filled in for
    exactly the workouts a surviving payload can still name.

    Matched on the dedupe key and nothing looser: the same account, the same
    start once the offset is read, and the same whole-second duration.
    """
    engine, upgrade = at_0026
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _account(connection, 2, "mate")
        # Named indoors, and the export wrote the start with an offset on it.
        _session_row(connection, 1, 1, "2026-07-20 13:12:00", 1800)
        # Named outdoors, same account, same sync.
        _session_row(connection, 2, 1, "2026-07-20 15:00:00", 2400)
        # Named indoors in the log, but the stored duration is a different
        # session: no match, so it stays false rather than being guessed at.
        _session_row(connection, 3, 1, "2026-07-20 17:00:00", 3600)
        # Somebody else's workout at the same moment as the indoor one. The
        # account is part of the key, so this is untouched.
        _session_row(connection, 4, 2, "2026-07-20 13:12:00", 1800)
        # Older than the log's window, which is the honest limit: nothing left
        # anywhere says what this one was called.
        _session_row(connection, 5, 1, "2026-01-04 14:00:00", 1800)
        _sync(
            connection,
            1,
            1,
            _entry("Indoor Run", "2026-07-20T06:12:00-07:00", 1800.4),
            _entry("Outdoor Walk", "2026-07-20T08:00:00-07:00", 2400),
            _entry("Indoor Walk", "2026-07-20T10:00:00-07:00", 900),
        )
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT id, indoor FROM workouts ORDER BY id")
        ).all() == [(1, 1), (2, 0), (3, 0), (4, 0), (5, 0)]


def test_the_indoor_column_lands_false_on_a_history_with_no_log_left(at_0026):
    """The common case on a long-lived install: the log has been pruned, so the
    column is simply false everywhere and nothing else moves."""
    engine, upgrade = at_0026
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _session_row(connection, 1, 1, "2026-02-01 14:00:00", 1800)
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT indoor, distance_mi FROM workouts")
        ).one() == (0, 3.0)


def test_the_indoor_column_steps_back_down_again(at_0026):
    """Stepping back takes the column away and leaves every workout it was
    written from untouched, so the same upgrade run again lands on the same
    answer out of the same log rows."""
    engine, upgrade = at_0026
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _session_row(connection, 1, 1, "2026-07-20 13:12:00", 1800)
        _sync(connection, 1, 1, _entry("Indoor Run", "2026-07-20T06:12:00-07:00", 1800))
        connection.commit()
    upgrade()

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "0026")

    with engine.connect() as connection:
        columns = {row[1] for row in connection.execute(sa.text("PRAGMA table_info(workouts)"))}
        assert "indoor" not in columns
        assert connection.execute(
            sa.text("SELECT duration_s FROM workouts")
        ).scalar_one() == 1800

    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT indoor FROM workouts")).scalar_one() == 1


def _progress_with_manna(connection, user_id: int, pending: int, xp: float = 0.0) -> None:
    """One progress row in the shape 0025 leaves it, which is the row the fruit
    meter lands on."""
    connection.execute(
        sa.text(
            "INSERT INTO user_progress (user_id, xp, level, chest_progress_mi,"
            " cycle_pos, renown, manna_pending, updated_at)"
            " VALUES (:user_id, :xp, 0, 0, 0, 0, :pending, '2026-08-01 00:00:00')"
        ),
        {"user_id": user_id, "xp": xp, "pending": pending},
    )


def test_the_fruit_release_lands_on_a_grove_that_has_never_borne(at_0025):
    """0026: five tables and three columns, every one of them additive.

    Nothing already stored is read or rewritten. A grove that has been growing
    for a year arrives with an empty meter and no seasons behind it, which is
    the truth about it: fruit begins with this release, and backdating a harvest
    would be inventing one. The pending manna 0025 seeded is untouched.
    """
    engine, upgrade = at_0025
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _progress_with_manna(connection, 1, 71940, xp=1240.5)
        _planting(connection, 1, 1, "banana", "2026-05-01 00:00:00", 320.0)
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        assert connection.execute(
            sa.text(
                "SELECT xp, manna_pending, fruit_progress_mi, fruit_seasons"
                " FROM user_progress WHERE user_id = 1"
            )
        ).one() == (1240.5, 71940, 0.0, 0)
        # The plant is where it was, and unfed.
        assert connection.execute(
            sa.text("SELECT growth_mi, fed_bonus FROM plantings WHERE id = 1")
        ).one() == (320.0, 0)
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert {
            "fruit_batches",
            "fruit_keepsakes",
            "manna_batches",
            "manna_gifts",
            "plant_feedings",
        } <= tables
        # Nothing is backfilled anywhere: there is no harvest to invent.
        for table in ("fruit_batches", "manna_batches", "manna_gifts", "plant_feedings"):
            assert connection.execute(
                sa.text(f"SELECT count(*) FROM {table}")  # noqa: S608 - a fixed list
            ).scalar_one() == 0


def test_the_fruit_release_steps_back_down_again(at_0025):
    """Stepping back takes the whole round away and leaves the release before it
    exactly as it was, so the same upgrade run again lands on a grove that has
    simply not borne yet."""
    engine, upgrade = at_0025
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _progress_with_manna(connection, 1, 650)
        _planting(connection, 1, 1, "banana", "2026-05-01 00:00:00", 320.0)
        connection.commit()
    upgrade()

    with engine.connect() as connection:
        # Something in every new table, so the drop has real rows to take.
        connection.execute(
            sa.text(
                "INSERT INTO fruit_batches (user_id, planting_id, species, golden, count,"
                " season, season_mi, season_month, borne_at)"
                " VALUES (1, 1, 'banana', 0, 3, 1, 33.0, 'August', '2026-08-12 00:00:00')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO manna_batches (user_id, amount, remaining, gathered_at)"
                " VALUES (1, 450, 450, '2026-08-12 00:00:00')"
            )
        )
        connection.commit()

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "0025")

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert not tables & {
            "fruit_batches",
            "fruit_keepsakes",
            "manna_batches",
            "manna_gifts",
            "plant_feedings",
        }
        columns = {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(user_progress)"))
        }
        assert not columns & {"fruit_progress_mi", "fruit_seasons"}
        assert "fed_bonus" not in {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(plantings)"))
        }
        # Everything the round was built on is still there.
        assert connection.execute(
            sa.text("SELECT manna_pending FROM user_progress WHERE user_id = 1")
        ).scalar_one() == 650
        assert connection.execute(
            sa.text("SELECT growth_mi FROM plantings WHERE id = 1")
        ).scalar_one() == 320.0

    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT fruit_seasons, manna_pending FROM user_progress")
        ).one() == (0, 650)


@pytest.fixture()
def at_0027(tmp_path, monkeypatch):
    """A database at revision 0027, which is the shape the gear release meets.

    Its own fixture because the column lands on workouts and the table it points
    at is new, so nothing before this revision has anywhere to put either.
    """
    url = f"sqlite:///{tmp_path}/gear.db"
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0027")
    engine = sa.create_engine(url)
    try:
        yield engine, (lambda: command.upgrade(cfg, "head"))
    finally:
        engine.dispose()


def test_the_gear_release_lands_on_a_history_wearing_nothing(at_0027):
    """0028: one table and one column, both additive and neither backfilled.

    A workout recorded before there was anywhere to say what it was done in
    arrives wearing nothing, which is the truth about it. Assigning shoes to old
    activities is somebody's own act afterwards, and a migration that guessed at
    it would be inventing a record.
    """
    engine, upgrade = at_0027
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _run(connection, 1, 1, "2026-07-20 13:12:00")
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert "gear" in tables
        assert connection.execute(sa.text("SELECT COUNT(*) FROM gear")).scalar_one() == 0
        # The workout is exactly what it was, wearing nothing.
        assert connection.execute(
            sa.text("SELECT distance_mi, gear_id FROM workouts")
        ).one() == (9.0, None)

        # The stamped columns are checked by writing a pair rather than by
        # PRAGMA: what the release needs is for a pair with no nickname, no
        # replacement mileage and no retirement to be storable.
        connection.execute(
            sa.text(
                "INSERT INTO gear (user_id, kind, style, brand, model, nickname, size,"
                " width, starting_mi, replace_around_mi, is_default, retired_at,"
                " created_at)"
                " VALUES (1, 'shoes', 'mens', 'Testbrand', 'Trail 3', NULL, 10.0, 'D',"
                " 0, NULL, 0, NULL, '2026-08-13 09:00:00')"
            )
        )
        connection.execute(sa.text("UPDATE workouts SET gear_id = 1"))
        connection.commit()
        assert connection.execute(
            sa.text("SELECT brand, width, starting_mi, is_default FROM gear")
        ).one() == ("Testbrand", "D", 0.0, 0)


def test_the_gear_release_steps_back_down_again(at_0027):
    """Stepping back takes the table and the column away and leaves every
    workout untouched, so the same upgrade run again lands on a history wearing
    nothing, which is where it started."""
    engine, upgrade = at_0027
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _run(connection, 1, 1, "2026-07-20 13:12:00")
        connection.commit()
    upgrade()

    with engine.connect() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO gear (user_id, kind, style, brand, model, size, width,"
                " starting_mi, is_default, created_at)"
                " VALUES (1, 'shoes', 'mens', 'Testbrand', 'Trail 3', 10.0, 'D', 25.0,"
                " 1, '2026-08-13 09:00:00')"
            )
        )
        connection.execute(sa.text("UPDATE workouts SET gear_id = 1"))
        connection.commit()

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "0027")

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                sa.text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
        assert "gear" not in tables
        assert "gear_id" not in {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(workouts)"))
        }
        # The miles the shoe was counting are the workout's own and are still
        # exactly where they were.
        assert connection.execute(
            sa.text("SELECT distance_mi FROM workouts")
        ).scalar_one() == 9.0

    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM gear")).scalar_one() == 0
        assert connection.execute(
            sa.text("SELECT gear_id FROM workouts")
        ).scalar_one() is None


@pytest.fixture()
def at_0028(tmp_path, monkeypatch):
    """A database at revision 0028, which is the shape the gear scope meets.

    Its own fixture because the column lands on the gear table, and 0028 is the
    revision that brings the table into being.
    """
    url = f"sqlite:///{tmp_path}/scope.db"
    monkeypatch.setattr(config.settings, "database_url", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "0028")
    engine = sa.create_engine(url)
    try:
        yield engine, (lambda: command.upgrade(cfg, "head"))
    finally:
        engine.dispose()


def _pair(connection, gear_id: int, user_id: int, model: str = "Trail 3") -> None:
    """One recorded pair in the shape 0028 leaves it, which is the row the scope
    column lands on."""
    connection.execute(
        sa.text(
            "INSERT INTO gear (id, user_id, kind, style, brand, model, size, width,"
            " starting_mi, is_default, created_at)"
            " VALUES (:id, :user_id, 'shoes', 'mens', 'Testbrand', :model, 10.0, 'D',"
            " 0, 1, '2026-08-13 09:00:00')"
        ),
        {"id": gear_id, "user_id": user_id, "model": model},
    )


def test_the_gear_scope_lands_on_every_pair_as_both(at_0028):
    """0029: one additive column, and every pair already recorded arrives saying
    what it has been doing all along.

    Both rather than nothing, because a pair nobody has said anything about is
    put on new walks and new runs alike, which is exactly how it behaved before
    the column existed.
    """
    engine, upgrade = at_0028
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _run(connection, 1, 1, "2026-07-20 13:12:00")
        _pair(connection, 1, 1)
        connection.execute(sa.text("UPDATE workouts SET gear_id = 1"))
        connection.commit()

    upgrade()

    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT model, applies_to FROM gear")
        ).one() == ("Trail 3", "both")
        # The three the form offers are storable, and the assignment already
        # made is untouched by any of it: the column gates new activities only.
        connection.execute(sa.text("UPDATE gear SET applies_to = 'run' WHERE id = 1"))
        connection.commit()
        assert connection.execute(
            sa.text("SELECT applies_to, gear_id FROM gear JOIN workouts ON gear.id = gear_id")
        ).one() == ("run", 1)


def test_the_gear_scope_steps_back_down_again(at_0028):
    """Stepping back takes the column away and leaves the pair and its miles
    exactly as they were, so the same upgrade run again lands on both."""
    engine, upgrade = at_0028
    with engine.connect() as connection:
        _account(connection, 1, "runner")
        _run(connection, 1, 1, "2026-07-20 13:12:00")
        _pair(connection, 1, 1)
        connection.commit()
    upgrade()

    with engine.connect() as connection:
        connection.execute(sa.text("UPDATE gear SET applies_to = 'walk'"))
        connection.commit()

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.downgrade(cfg, "0028")

    with engine.connect() as connection:
        assert "applies_to" not in {
            row[1] for row in connection.execute(sa.text("PRAGMA table_info(gear)"))
        }
        assert connection.execute(sa.text("SELECT model FROM gear")).scalar_one() == "Trail 3"
        assert connection.execute(
            sa.text("SELECT distance_mi FROM workouts")
        ).scalar_one() == 9.0

    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT applies_to FROM gear")).scalar_one() == "both"
