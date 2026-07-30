"""Registration, email verification, sign in, sign out, and password changes."""

import datetime as dt

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
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import mail, models, security, throttle
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

# One wording for every way a sign in can fail. Saying "no such user" would let
# anyone map out who has an account here, which is the first step of a targeted
# guessing run.
BAD_CREDENTIALS = "Invalid username or password"
TOO_MANY = "Too many attempts. Wait a minute and try again."
# The only answer registration gives, whether an account was made or the name or
# address was already taken. The wording has to be true in both cases, so it
# describes what the person should do next rather than what the server did.
CHECK_EMAIL = "Check your email to verify your account."
UNVERIFIED = "Email not verified."


class RegisterBody(BaseModel):
    username: str
    password: str
    email: str
    # Optional in the schema and required by the code only while registration is
    # closed, so an open instance takes a form that never had this field.
    invite_code: str = ""


class LoginBody(BaseModel):
    username: str
    password: str


class VerifyBody(BaseModel):
    token: str


class ResendBody(BaseModel):
    email: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


def _validate_email(raw: str) -> str:
    cleaned = raw.strip().lower()
    if len(cleaned) > security.MAX_EMAIL_LENGTH or not security.EMAIL_PATTERN.match(cleaned):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That does not look like an email address.")
    return cleaned


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
    body: RegisterBody,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict:
    """Create an unverified account and mail it a link.

    No session cookie comes back. An account that has not answered its
    verification mail cannot sign in, so handing one a session here would make
    the whole check decorative.
    """
    if throttle.register_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)

    username = _validate_credentials(body.username, body.password)
    email = _validate_email(body.email)
    now = security.now_utc()

    # One message for a code that is unknown, spent, or stale. Telling the
    # difference would turn the endpoint into a way to test codes.
    invalid_invite = HTTPException(status.HTTP_400_BAD_REQUEST, "Invite code is not valid.")
    invite = None
    if not settings.registration_open:
        code = body.invite_code.strip()
        invite = db.execute(
            select(models.Invite).where(models.Invite.code == code)
        ).scalar_one_or_none()
        if invite is None or invite.used_by is not None or invite.expires_at <= now:
            raise invalid_invite

    # Hashing before the duplicate check, not after, and the wasted work on the
    # duplicate path is the point. Argon2 is by far the slowest part of this
    # request, so returning early for a name or address that already exists
    # would make that answer arrive in a fraction of the time a real signup
    # takes, and the timing would say plainly what the identical response
    # bodies below are there to withhold.
    password_hash = security.hash_password(body.password)

    if db.execute(
        select(models.User.id).where(
            or_(models.User.username == username, models.User.email == email)
        )
    ).scalar_one_or_none():
        # Same status and same body as a successful signup. Whoever sent this
        # learns nothing, and the person who really owns the address is not
        # mailed about an attempt they did not make. The invite, if any, is
        # left unclaimed.
        return {"detail": CHECK_EMAIL}

    user = models.User(
        username=username,
        password_hash=password_hash,
        email=email,
        email_verified=False,
        is_admin=False,
        units="imperial",
        created_at=now,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Two registrations for the same name or address arriving together: the
        # database settles it, and the loser gets the same answer as everyone
        # else rather than a message that confirms the collision.
        db.rollback()
        return {"detail": CHECK_EMAIL}

    if invite is not None:
        # Claim the invite conditionally rather than by writing to the row we
        # read. Between the read above and here, another registration may have
        # taken it; the WHERE clause means only one of them can win, and the
        # loser sees zero rows updated.
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

    token = security.create_email_token(db, user.id)
    db.commit()
    # After the response, so a mail server having a slow morning is not
    # something the person registering has to sit through.
    background.add_task(mail.send_verification, email, token)
    return {"detail": CHECK_EMAIL}


@router.post("/verify", status_code=status.HTTP_204_NO_CONTENT)
def verify_email(body: VerifyBody, response: Response, db: Session = Depends(get_db)) -> Response:
    row = db.execute(
        select(models.EmailToken).where(
            models.EmailToken.token_hash == security.hash_token(body.token.strip()),
            models.EmailToken.purpose == "verify",
        )
    ).scalar_one_or_none()
    if row is None or row.expires_at <= security.now_utc():
        if row is not None:
            # An expired link is spent on sight rather than left to sit in the
            # table until someone thinks to clean it out.
            db.delete(row)
            db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That verification link is not valid any more. Ask for a new one.",
        )

    user = db.get(models.User, row.user_id)
    # The token goes whether or not the account is still there, which is what
    # makes the link single use.
    db.delete(row)
    if user is not None:
        user.email_verified = True
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
def resend_verification(
    body: ResendBody,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Response:
    """Send another verification link, and say nothing about whether it went.

    Answering differently for an address with no account, an address that is
    already verified, and an address waiting on a link would turn this into a
    way to test whether someone has an account here, which is exactly what
    registration was careful not to reveal.
    """
    if throttle.resend_limiter.hit(throttle.client_address(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, TOO_MANY)

    email = body.email.strip().lower()
    user = db.execute(
        select(models.User).where(models.User.email == email)
    ).scalar_one_or_none()
    if user is not None and not user.email_verified:
        token = security.create_email_token(db, user.id)
        db.commit()
        background.add_task(mail.send_verification, email, token)

    response.status_code = status.HTTP_204_NO_CONTENT
    return response


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
    if not user.email_verified:
        # Checked after the password and never before it. The other order would
        # answer differently for a right and a wrong password on an unverified
        # account, which is a password oracle for anyone who registers an
        # account and then goes looking for other people's.
        raise HTTPException(status.HTTP_403_FORBIDDEN, UNVERIFIED)

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
        "email": user.email,
        "email_verified": user.email_verified,
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
    """Mint an invite code. Used by the command line tool, and the only way into
    an account while REGISTRATION_OPEN is false."""
    invite = models.Invite(
        code=security.generate_token(),
        created_by=created_by,
        created_at=security.now_utc(),
        expires_at=security.now_utc() + dt.timedelta(days=expires_days),
    )
    db.add(invite)
    return invite
