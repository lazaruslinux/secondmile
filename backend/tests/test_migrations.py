"""The seeds migration, run over a database shaped like the one it will meet.

Everything in here is invented, and it is run against a throwaway SQLite file
rather than the in-memory database the rest of the suite uses: a migration is
only worth testing if it is the real revision script doing the real work.
"""

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


def _fill(connection) -> None:
    """A little of everything the old shape held: an account partway up the
    old chest accumulator, two unopened chests, a filled album, and both kinds
    of achievement."""
    connection.execute(
        sa.text(
            "INSERT INTO users (id, username, password_hash, email_verified, is_admin,"
            " units, displayed_badges, created_at)"
            " VALUES (1, 'runner', 'x', 1, 0, 'imperial', '[]', '2026-01-01 00:00:00')"
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

        # The weekly badges are untouched and the collection ones are gone,
        # ids and all: nothing may be left that the source cannot name.
        held = set(
            connection.execute(sa.text("SELECT achievement_id FROM user_achievements")).scalars()
        )
        assert held == {"week_10", "week_25"}


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
