"""A bug report: what somebody typed, and the three things the server stamps.

A dropbox rather than a tracker. Nothing here is read by the app again: there
is no history, no status, and no reply, because the honest answer to a report
is a release and not a row that says somebody looked. The Settings card asks
for detail and says what is taken from the request, so nothing about a report
is collected quietly.
"""

import datetime as dt
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, security, throttle
from app.config import (
    BUG_REPORT_COOLDOWN_HOURS,
    BUG_REPORT_MAX_CHARS,
    BUG_REPORT_UA_MAX_CHARS,
    BUG_REPORT_VIEW_MAX_CHARS,
    settings,
)
from app.db import get_db

log = logging.getLogger("secondmile.bugreport")

router = APIRouter(prefix="/bugreport", tags=["bugreport"])

# What the screen name says when the client sent nothing usable. A report with
# no screen on it is still worth keeping: the words are the point.
UNKNOWN_VIEW = "unknown"

# What stands in for a browser string the request did not carry. The same words
# manage.py bug-reports prints, because the file below and that command are one
# report read two ways.
NO_USER_AGENT = "no user agent"

# What both refusals say. They are the same event to whoever met one, and the
# hour is the only one of them a person meets: the limiter above it fires on a
# client hammering the endpoint several times in a minute.
TOO_SOON = "One report an hour. Try again later."


class ReportBody(BaseModel):
    text: str
    # Which screen they were on. Optional, because a client that cannot say is
    # better answered than refused.
    view: str = ""


def _append_to_file(report: models.BugReport, username: str) -> None:
    """Append one report to BUG_REPORTS_FILE, if the install configured one.

    Empty is a supported configuration and writes nothing at all. When a path is
    set, the row stays the record and this is a second copy for whoever runs the
    instance, which is why a failed write is a warning rather than a refusal:
    losing the report over a copy of it would help nobody.
    """
    path = settings.bug_reports_file
    if not path:
        return
    block = (
        f"{report.created_at.isoformat()}  {username}  "
        f"on {report.view}  [{report.user_agent or NO_USER_AGENT}]\n"
        f"{report.text}\n\n"
    )
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, mode=0o700, exist_ok=True)
        # The mode goes to os.open rather than to a chmod afterwards: a file
        # created first and tightened second is readable by everyone on the host
        # for the moment in between, and what people write in that box is theirs.
        handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(handle, "a", encoding="utf-8") as out:
            out.write(block)
    except OSError as err:
        log.warning("Could not append a bug report to %s: %s", path, err)


@router.post("", status_code=status.HTTP_201_CREATED)
def report_bug(
    body: ReportBody,
    request: Request,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Take one report and store it.

    The account, the moment and the browser are taken from the session, the
    clock and the request header rather than from the body: those three are
    facts about the request, and a client that could set them could file a
    report as somebody else.
    """
    if throttle.bug_report_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_SOON)
    # The hour itself, asked of the table rather than of the limiter above. The
    # limiter is memory and a restart empties it, which would make the rule a
    # suggestion; the newest stored row cannot be restarted away.
    since = security.now_utc() - dt.timedelta(hours=BUG_REPORT_COOLDOWN_HOURS)
    newest = db.execute(
        select(models.BugReport.created_at)
        .where(models.BugReport.user_id == user.id)
        .order_by(models.BugReport.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if newest is not None and newest > since:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_SOON)
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A bug report needs some words in it.")
    if len(text) > BUG_REPORT_MAX_CHARS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A bug report must be at most {BUG_REPORT_MAX_CHARS} characters.",
        )
    # Both of these are trimmed rather than refused: neither is typed by
    # anybody, so an over-long one is a client being odd rather than a person
    # making a mistake, and losing the report over it would help nobody.
    view = body.view.strip()[:BUG_REPORT_VIEW_MAX_CHARS] or UNKNOWN_VIEW
    agent = request.headers.get("user-agent", "").strip()[:BUG_REPORT_UA_MAX_CHARS]
    report = models.BugReport(
        user_id=user.id,
        created_at=security.now_utc(),
        text=text,
        view=view,
        user_agent=agent or None,
    )
    db.add(report)
    db.commit()
    # After the commit, so nothing is ever written to the file that the database
    # did not keep.
    _append_to_file(report, user.username)
    # The id and nothing else. There is no screen that reads a report back, so
    # this is an acknowledgement rather than a resource anybody fetches.
    return {"id": report.id}
