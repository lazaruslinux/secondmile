"""A bug report: what somebody typed, and the three things the server stamps.

A dropbox rather than a tracker. Nothing here is read by the app again: there
is no history, no status, and no reply, because the honest answer to a report
is a release and not a row that says somebody looked. The Settings card says
as much, and says exactly what is stamped, so nothing about a report is
collected quietly.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models, security, throttle
from app.config import (
    BUG_REPORT_MAX_CHARS,
    BUG_REPORT_UA_MAX_CHARS,
    BUG_REPORT_VIEW_MAX_CHARS,
)
from app.db import get_db

router = APIRouter(prefix="/bugreport", tags=["bugreport"])

# What the screen name says when the client sent nothing usable. A report with
# no screen on it is still worth keeping: the words are the point.
UNKNOWN_VIEW = "unknown"


class ReportBody(BaseModel):
    text: str
    # Which screen they were on. Optional, because a client that cannot say is
    # better answered than refused.
    view: str = ""


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
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many reports just now. Wait a minute."
        )
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
    # The id and nothing else. There is no screen that reads a report back, so
    # this is an acknowledgement rather than a resource anybody fetches.
    return {"id": report.id}
