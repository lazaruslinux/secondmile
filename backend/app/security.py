"""Password hashing, opaque session tokens, and the signed-in-user dependency."""

import datetime as dt
import hashlib
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import get_db

# One reusable hasher at library defaults, which are Argon2id with parameters
# the argon2-cffi maintainers keep current. Argon2id is memory hard, so a stolen
# database costs an attacker real hardware per guess rather than GPU throughput.
_hasher = PasswordHasher()

COOKIE_NAME = "session"
MIN_PASSWORD_LENGTH = 10
USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,32}$")

# A real hash of a value nobody can log in with, verified against when the
# username does not exist. Without it, a missing user returns in microseconds
# and a real one takes the full Argon2 cost, which is a timing oracle that
# enumerates accounts. Computed once at import so the cost is paid at startup.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, raw)
    except (VerifyMismatchError, VerificationError):
        return False


def dummy_verify() -> None:
    """Burn the same Argon2 work a real verification would, and discard it.

    Called on the unknown-username branch of login so that branch costs what the
    known-username branch costs.
    """
    verify_password("not-the-password", _DUMMY_HASH)


def generate_token() -> str:
    """A bearer value with 256 bits of entropy behind it."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """The form a token is stored in.

    Plain SHA-256 rather than Argon2 on purpose: these are long random values,
    not human-chosen passwords, so there is no dictionary to slow down, and the
    ingest path verifies one on every sync from a phone.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def create_session(db: Session, user_id: int) -> str:
    """Issue a session row and return the plaintext token, which is never stored."""
    token = generate_token()
    db.add(
        models.UserSession(
            token_hash=hash_token(token),
            user_id=user_id,
            created_at=now_utc(),
            expires_at=now_utc() + dt.timedelta(hours=settings.session_hours),
        )
    )
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,  # unreadable from JavaScript, so an XSS bug cannot lift it
        samesite="lax",  # not attached to cross-site POSTs, which is the CSRF defence
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    # The attributes have to match the ones the cookie was set with or the
    # browser keeps the original alongside the deletion.
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def delete_sessions(db: Session, user_id: int, *, keep: str | None = None) -> None:
    """Revoke a user's sessions, optionally sparing the one making the request."""
    stmt = delete(models.UserSession).where(models.UserSession.user_id == user_id)
    if keep is not None:
        stmt = stmt.where(models.UserSession.token_hash != keep)
    db.execute(stmt)


def session_token_hash(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    return hash_token(token) if token else None


def current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """The signed-in user, or a 401.

    The user row is loaded fresh on every request rather than trusted from the
    cookie, so deleting an account or dropping its admin flag takes effect at
    once instead of whenever the session happens to expire.
    """
    token_hash = session_token_hash(request)
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    if not token_hash:
        raise unauthorized
    row = db.get(models.UserSession, token_hash)
    if row is None:
        raise unauthorized
    if row.expires_at <= now_utc():
        # Reaping on sight keeps the table from growing forever without needing
        # a scheduled job for it.
        db.delete(row)
        db.commit()
        raise unauthorized
    user = db.get(models.User, row.user_id)
    if user is None:
        db.delete(row)
        db.commit()
        raise unauthorized
    return user
