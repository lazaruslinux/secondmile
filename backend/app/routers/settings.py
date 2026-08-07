"""Account settings: the ingest token, the unit preference, and the address."""

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail, models, security, throttle
from app.db import get_db
from app.routers.auth import validate_email

router = APIRouter(prefix="/settings", tags=["settings"])

UNITS = ("imperial", "metric")


class UnitsBody(BaseModel):
    units: str


class EmailBody(BaseModel):
    # The current password, confirming that whoever is holding this session is
    # the account's owner. A session alone is not enough to move an account to
    # another inbox: that is how a borrowed laptop becomes somebody else's
    # account.
    password: str
    email: str


@router.get("/ingest-token")
def token_status(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    row = db.get(models.IngestToken, user.id)
    return {
        "exists": row is not None,
        "rotated_at": row.rotated_at.isoformat() if row is not None else None,
    }


@router.post("/ingest-token/rotate")
def rotate_token(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """Issue a new ingest token and return it in plaintext, once.

    Only the hash is kept, so this response is the single moment the value
    exists anywhere it can be read. Rotating replaces the row rather than adding
    one, which is what makes rotation actually revoke the old token.
    """
    token = security.generate_token()
    row = db.get(models.IngestToken, user.id)
    if row is None:
        row = models.IngestToken(user_id=user.id, token_hash="", rotated_at=security.now_utc())
        db.add(row)
    row.token_hash = security.hash_token(token)
    row.rotated_at = security.now_utc()
    db.commit()
    return {"token": token}


@router.post("/email", status_code=status.HTTP_204_NO_CONTENT)
def change_email(
    body: EmailBody,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Add an address to an account, or move it to another one.

    Nothing changes here. The address is written to pending_email and a link
    goes to it; the account keeps the address it has until somebody opens that
    link, because the only thing worth proving is that whoever asked can read
    the new inbox.

    An address that already belongs to another account is answered exactly like
    one that does not: 204, and no mail. Any other answer would make this form a
    way to ask whether a given person has an account here, which is the same
    thing registration is careful not to say.
    """
    if throttle.email_change_limiter.hit(throttle.client_address(request)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Wait a minute and try again."
        )
    if not security.verify_password(body.password, user.password_hash):
        # Said plainly, and it leaks nothing: the caller is already signed in as
        # this account and is being told about their own password.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is not correct.")
    wanted = validate_email(body.email)

    taken = db.execute(
        select(models.User.id).where(models.User.email == wanted, models.User.id != user.id)
    ).scalar_one_or_none()
    if taken:
        # Silence, deliberately. Nothing is stored and nothing is sent: the
        # person who really owns that address is not mailed about a request they
        # did not make, and the caller learns nothing either way.
        response.status_code = status.HTTP_204_NO_CONTENT
        return response

    user.pending_email = wanted
    # Replaces any earlier token for this account, so only the newest link
    # works: one address may be waiting at a time.
    token = security.create_email_token(db, user.id, "change-email")
    db.commit()
    background.add_task(mail.send_email_change, wanted, token)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.patch("")
def update_settings(
    body: UnitsBody,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    if body.units not in UNITS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Units must be one of: {', '.join(UNITS)}."
        )
    # Display only. Everything is stored in miles regardless, so switching this
    # never rewrites history or changes what a total means.
    user.units = body.units
    db.commit()
    return {"units": user.units}
