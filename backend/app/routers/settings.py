"""Account settings: the ingest token and the unit preference."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import models, security
from app.db import get_db

router = APIRouter(prefix="/settings", tags=["settings"])

UNITS = ("imperial", "metric")


class UnitsBody(BaseModel):
    units: str


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
