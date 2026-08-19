"""The bug report dropbox: what a session may file, and what the server stamps
on it without being asked."""

import argparse
import datetime as dt
import logging

import pytest
from conftest import FROZEN_NOW

from app import config, models
from app.config import BUG_REPORT_MAX_CHARS

TOO_SOON = "One report an hour. Try again later."


def test_a_report_needs_a_session(client):
    response = client.post("/api/bugreport", json={"text": "it broke", "view": "home"})
    assert response.status_code == 401


def test_an_empty_report_is_refused(signed_in):
    """Nothing typed is nothing to store, and whitespace is nothing typed."""
    empty = signed_in.post("/api/bugreport", json={"text": "", "view": "home"})
    assert empty.status_code == 400
    blank = signed_in.post("/api/bugreport", json={"text": "  \n \t ", "view": "home"})
    assert blank.status_code == 400
    assert blank.json()["detail"] == "A bug report needs some words in it."


def test_a_report_is_stored_with_what_the_server_stamps(signed_in, db_session, member):
    """The body carries the words and the screen. The account, the moment and
    the browser are facts about the request and are taken from it."""
    response = signed_in.post(
        "/api/bugreport",
        json={"text": "  the grove drew nothing  ", "view": "grove"},
        headers={"User-Agent": "Mozilla/5.0 (iPhone) Safari"},
    )
    assert response.status_code == 201
    body = response.json()
    assert list(body) == ["id"]

    row = db_session.get(models.BugReport, body["id"])
    assert row.user_id == member.id
    assert row.created_at == FROZEN_NOW
    # Trimmed, so a box somebody hit return in does not store the return.
    assert row.text == "the grove drew nothing"
    assert row.view == "grove"
    assert row.user_agent == "Mozilla/5.0 (iPhone) Safari"


def test_a_report_that_names_no_screen_still_lands(signed_in, db_session):
    """A client that cannot say which screen it was on is answered rather than
    refused: the words are the point, and the screen is context around them."""
    report_id = signed_in.post("/api/bugreport", json={"text": "no idea where"}).json()["id"]
    assert db_session.get(models.BugReport, report_id).view == "unknown"


def test_a_report_past_the_cap_is_refused(signed_in, db_session):
    """The box stops at the same number, so this is a client being odd rather
    than a person being surprised."""
    response = signed_in.post(
        "/api/bugreport", json={"text": "x" * (BUG_REPORT_MAX_CHARS + 1), "view": "home"}
    )
    assert response.status_code == 400
    assert str(BUG_REPORT_MAX_CHARS) in response.json()["detail"]
    # Exactly the cap is fine: the refusal is for what is past it.
    assert (
        signed_in.post(
            "/api/bugreport", json={"text": "y" * BUG_REPORT_MAX_CHARS, "view": "home"}
        ).status_code
        == 201
    )
    assert db_session.query(models.BugReport).count() == 1


def test_reporting_is_rate_limited(signed_in):
    """Its own allowance, per account, and a tight one: a report is written by
    hand, so a burst of them is the same one sent several times."""
    seen = {
        signed_in.post("/api/bugreport", json={"text": "again", "view": "home"}).status_code
        for _ in range(10)
    }
    assert seen == {201, 429}


def test_a_second_report_inside_the_hour_is_refused(signed_in, db_session):
    """One an hour, per account. The hour is read off the newest stored row
    rather than out of a limiter's memory, so restarting the server cannot hand
    everybody a fresh allowance."""
    first = signed_in.post("/api/bugreport", json={"text": "the grove drew nothing"})
    assert first.status_code == 201

    again = signed_in.post("/api/bugreport", json={"text": "and it still draws nothing"})
    assert again.status_code == 429
    assert again.json()["detail"] == TOO_SOON
    assert db_session.query(models.BugReport).count() == 1


def test_a_report_an_hour_after_the_last_one_is_taken(signed_in, db_session):
    """A window and not a lock: once the newest report is older than an hour,
    the next one is stored like any other."""
    first = signed_in.post("/api/bugreport", json={"text": "this morning"}).json()["id"]
    stored = db_session.get(models.BugReport, first)
    stored.created_at = FROZEN_NOW - dt.timedelta(hours=1, minutes=1)
    db_session.commit()

    later = signed_in.post("/api/bugreport", json={"text": "and again this afternoon"})
    assert later.status_code == 201
    # The acknowledgement is the id and nothing else, whichever report it is.
    assert list(later.json()) == ["id"]
    assert db_session.query(models.BugReport).count() == 2


@pytest.fixture()
def reports_file(tmp_path, monkeypatch):
    """A configured BUG_REPORTS_FILE, in a directory that does not exist yet:
    making it is part of what the first report has to do."""
    target = tmp_path / "reports" / "bug-reports.txt"
    monkeypatch.setattr(config.settings, "bug_reports_file", str(target))
    return target


def test_a_configured_file_gets_a_block_for_every_report(
    signed_in, db_session, member, reports_file
):
    """One header line and the words under it, appended rather than replaced,
    and written where nobody else on the host can read them."""
    first = signed_in.post(
        "/api/bugreport",
        json={"text": "the grove drew nothing", "view": "grove"},
        headers={"User-Agent": "Mozilla/5.0 (iPhone) Safari"},
    )
    assert first.status_code == 201
    assert reports_file.read_text(encoding="utf-8") == (
        f"{FROZEN_NOW.isoformat()}  {member.username}  "
        "on grove  [Mozilla/5.0 (iPhone) Safari]\n"
        "the grove drew nothing\n\n"
    )
    # The report itself, not the file, and the directory around it.
    assert oct(reports_file.stat().st_mode)[-3:] == "600"
    assert oct(reports_file.parent.stat().st_mode)[-3:] == "700"

    stored = db_session.get(models.BugReport, first.json()["id"])
    stored.created_at = FROZEN_NOW - dt.timedelta(hours=2)
    db_session.commit()
    # No browser string and no screen, which is what the file says out loud
    # rather than leaving an empty bracket nobody can read.
    signed_in.post(
        "/api/bugreport", json={"text": "no browser this time"}, headers={"User-Agent": ""}
    )
    written = reports_file.read_text(encoding="utf-8")
    assert written.startswith(f"{FROZEN_NOW.isoformat()}  {member.username}  on grove")
    assert written.endswith(
        f"{FROZEN_NOW.isoformat()}  {member.username}  on unknown  [no user agent]\n"
        "no browser this time\n\n"
    )


def test_a_file_that_cannot_be_written_still_stores_the_report(
    signed_in, db_session, tmp_path, monkeypatch, caplog
):
    """The row is the record and the file is a copy of it, so a path that
    cannot be written is a line in the log rather than a lost report."""
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setattr(config.settings, "bug_reports_file", str(blocked / "reports.txt"))

    with caplog.at_level(logging.WARNING, logger="secondmile.bugreport"):
        response = signed_in.post("/api/bugreport", json={"text": "still stored", "view": "home"})
    assert response.status_code == 201
    assert db_session.query(models.BugReport).count() == 1
    logged = [record for record in caplog.records if record.name == "secondmile.bugreport"]
    assert len(logged) == 1
    assert "Could not append a bug report" in logged[0].getMessage()


def test_no_file_is_written_when_the_setting_is_empty(signed_in, tmp_path, caplog):
    """Empty is the default and a supported configuration: nothing is written,
    and nothing is said about not writing it either."""
    assert config.settings.bug_reports_file == ""
    with caplog.at_level(logging.WARNING, logger="secondmile.bugreport"):
        response = signed_in.post("/api/bugreport", json={"text": "nowhere to put it"})
    assert response.status_code == 201
    assert not (tmp_path / "reports").exists()
    assert [record for record in caplog.records if record.name == "secondmile.bugreport"] == []


def _report(db_session, user_id: int, text: str, view: str, minutes: int, agent=None) -> None:
    db_session.add(
        models.BugReport(
            user_id=user_id,
            created_at=FROZEN_NOW + dt.timedelta(minutes=minutes),
            text=text,
            view=view,
            user_agent=agent,
        )
    )
    db_session.commit()


def test_the_command_prints_the_reports_newest_first(db_session, member, monkeypatch, capsys):
    import manage

    _report(db_session, member.id, "the oldest one", "home", 0, agent="Mozilla/5.0 (iPhone)")
    _report(db_session, member.id, "the newest one", "grove", 5)

    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_bug_reports(argparse.Namespace(limit=20))
    printed = capsys.readouterr().out

    assert printed.index("the newest one") < printed.index("the oldest one")
    assert member.username in printed
    assert "on grove" in printed
    assert "Mozilla/5.0 (iPhone)" in printed
    # A report with no browser string says so rather than printing an empty
    # bracket nobody can read.
    assert "no user agent" in printed


def test_the_command_honours_its_limit_and_says_when_there_is_nothing(
    db_session, member, monkeypatch, capsys
):
    import manage

    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_bug_reports(argparse.Namespace(limit=20))
    assert "No bug reports." in capsys.readouterr().out

    for minute in range(3):
        _report(db_session, member.id, f"report {minute}", "home", minute)
    manage.cmd_bug_reports(argparse.Namespace(limit=2))
    printed = capsys.readouterr().out
    assert "report 2" in printed
    assert "report 1" in printed
    assert "report 0" not in printed


def test_the_command_writes_nothing(db_session, member, monkeypatch):
    """A dropbox is read only. Nothing here marks a report seen, because there
    is no such thing to mark and the app never promised one."""
    import manage

    _report(db_session, member.id, "still here", "home", 0)
    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_bug_reports(argparse.Namespace(limit=20))
    assert db_session.query(models.BugReport).count() == 1


@pytest.mark.parametrize("length,expected_tail", [(20, ""), (200, "...")])
def test_a_long_browser_string_is_cut_short_in_the_listing(
    db_session, member, monkeypatch, capsys, length, expected_tail
):
    import manage

    _report(db_session, member.id, "words", "home", 0, agent="b" * length)
    monkeypatch.setattr(manage, "_session", lambda: db_session)
    manage.cmd_bug_reports(argparse.Namespace(limit=20))
    printed = capsys.readouterr().out
    assert ("..." in printed) == bool(expected_tail)
    assert "b" * min(length, 60) in printed
