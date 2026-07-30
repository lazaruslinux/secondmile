"""Registration, sign in, sign out, and password changes."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, security, throttle
from app.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

# One wording for every way a sign in can fail. Saying "no such user" would let
# anyone map out who has an account here, which is the first step of a targeted
# guessing run.
BAD_CREDENTIALS = "Invalid username or password"
TOO_MANY = "Too many attempts. Wait a minute and try again."


class RegisterBody(BaseModel):
    invite_code: str
    username: str
    password: str


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


def _validate_credentials(username: str, password: str) -> str:
    """Return the cleaned username, or raise a 400 explaining the rule broken."""
    cleaned = username.strip().lower()
    if not security.USERNAME_PATTERN.match(cleaned):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Username must be 3 to 32 characters, using lower-case letters, "
            "digits, dot, dash, or underscore.",
        )
    if len(password) < security.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at least {security.MIN_PASSWORD_LENGTH} characters.",
        )
    return cleaned


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterBody, request: Request, response: Response, db: Session = Depends(get_db)
) -> dict:
    if throttle.register_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)

    username = _validate_credentials(body.username, body.password)
    code = body.invite_code.strip()
    now = security.now_utc()

    invite = db.execute(select(models.Invite).where(models.Invite.code == code)).scalar_one_or_none()
    # One message for a code that is unknown, spent, or stale. Telling the
    # difference would turn the endpoint into a way to test codes.
    invalid_invite = HTTPException(status.HTTP_400_BAD_REQUEST, "Invite code is not valid.")
    if invite is None or invite.used_by is not None or invite.expires_at <= now:
        raise invalid_invite

    if db.execute(
        select(models.User.id).where(models.User.username == username)
    ).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken.")

    user = models.User(
        username=username,
        password_hash=security.hash_password(body.password),
        is_admin=False,
        units="imperial",
        created_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Two registrations for the same name arriving together: the database
        # settles it, and the loser gets the same message as the slow path.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken.") from None

    # Claim the invite conditionally rather than by writing to the row we read.
    # Between the read above and here, another registration may have taken it;
    # the WHERE clause means only one of them can win, and the loser sees zero
    # rows updated.
    claimed = db.execute(
        update(models.Invite)
        .where(
            models.Invite.id == invite.id,
            models.Invite.used_by.is_(None),
            models.Invite.expires_at > now,
        )
        .values(used_by=user.id)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise invalid_invite

    token = security.create_session(db, user.id)
    db.commit()
    security.set_session_cookie(response, token)
    return {"id": user.id, "username": user.username, "units": user.units, "is_admin": False}


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
def login(
    body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)
) -> Response:
    if throttle.login_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)

    username = body.username.strip().lower()
    user = db.execute(
        select(models.User).where(models.User.username == username)
    ).scalar_one_or_none()
    if user is None:
        # Verify against a throwaway hash anyway. Returning early here would
        # make an unknown username measurably faster than a known one, and that
        # difference is enough to enumerate accounts from the outside.
        security.dummy_verify()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)
    if not security.verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, BAD_CREDENTIALS)

    token = security.create_session(db, user.id)
    db.commit()
    security.set_session_cookie(response, token)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    # No sign-in requirement: signing out has to work even when the session is
    # already gone, otherwise a stale cookie leaves the browser stuck.
    token_hash = security.session_token_hash(request)
    if token_hash:
        row = db.get(models.UserSession, token_hash)
        if row is not None:
            db.delete(row)
            db.commit()
    security.clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me")
def me(user: models.User = Depends(security.current_user)) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "units": user.units,
        "is_admin": user.is_admin,
    }


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    if throttle.password_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)
    if not security.verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is not correct.")
    if len(body.new_password) < security.MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Password must be at least {security.MIN_PASSWORD_LENGTH} characters.",
        )

    user.password_hash = security.hash_password(body.new_password)
    # A password change is how someone reacts to a session they think was
    # stolen, so every other session dies with it. The one making the request
    # survives, because being signed out of the browser you just used to fix
    # the problem reads as the change having failed.
    security.delete_sessions(db, user.id, keep=security.session_token_hash(request))
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


def create_invite(db: Session, created_by: int, expires_days: int = 14) -> models.Invite:
    """Mint an invite code. Used by the command line tool, which is the only way
    an account gets created here: there is no open registration to protect."""
    invite = models.Invite(
        code=security.generate_token(),
        created_by=created_by,
        created_at=security.now_utc(),
        expires_at=security.now_utc() + dt.timedelta(days=expires_days),
    )
    db.add(invite)
    return invite
