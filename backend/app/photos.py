"""Pictures attached to a workout.

Same bargain as the avatars: the uploaded bytes are size-capped, decode-verified
with Pillow, then thrown away. What lands on disk is a webp this server built,
scaled to fit and carrying no metadata, under a name derived from two row ids
and nothing an uploader sent.
"""

import io
import logging
import os
import tempfile

from PIL import Image

from app.config import MAX_PHOTO_PIXELS, PHOTO_MAX_EDGE, settings
from app.images import decode

log = logging.getLogger("secondmile.photos")

# The server decides the stored format; it is never negotiated with the uploader.
SUFFIX = ".webp"
MEDIA_TYPE = "image/webp"


def _directory() -> str:
    # Read through settings so tests can point this at a temporary directory.
    return settings.photo_dir


def path_for(workout_id: int, photo_id: int) -> str:
    """Where one photo lives. Derived from the two ids, never supplied."""
    return os.path.join(_directory(), f"{workout_id}-{photo_id}{SUFFIX}")


def _fit(image: Image.Image) -> Image.Image:
    """Scaled so the longest edge is at most PHOTO_MAX_EDGE, aspect kept.

    Never upscaled: a small picture is left exactly as big as it arrived, because
    stretching it would invent detail and pay bytes for it.
    """
    width, height = image.size
    longest = max(width, height)
    if longest <= PHOTO_MAX_EDGE:
        return image
    scale = PHOTO_MAX_EDGE / longest
    return image.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS
    )


def encode(raw: bytes) -> bytes:
    """Turn uploaded bytes into the webp this server serves.

    Called before the row exists, so a picture this server will not store never
    leaves an id behind.
    """
    fitted = _fit(decode(raw, MAX_PHOTO_PIXELS))
    # Pasted onto a blank canvas: a converted image still carries its source's
    # info dict, and Pillow writes parts of it back out. A fresh canvas has
    # nothing to carry, so EXIF, colour profile, and GPS stop here.
    clean = Image.new("RGB", fitted.size)
    clean.paste(fitted)

    out = io.BytesIO()
    clean.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue()


def store(workout_id: int, photo_id: int, encoded: bytes) -> None:
    """Write an already-encoded photo into place.

    Takes the encoded bytes rather than the raw ones because the photo id comes
    from the row, and the row must not be written for something that turns out
    not to be an image.
    """
    os.makedirs(_directory(), exist_ok=True)
    target = path_for(workout_id, photo_id)
    # Write-then-rename so a request dying halfway cannot leave a truncated file,
    # with a temporary name unique per call so two writes cannot share one.
    handle, temporary = tempfile.mkstemp(
        dir=_directory(), prefix=f"{workout_id}-{photo_id}-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(encoded)
        os.replace(temporary, target)
    except OSError:
        # A failed write must not leave its scratch file behind for good.
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def remove(workout_id: int, photo_id: int) -> None:
    """Delete one stored photo. Missing is not an error."""
    try:
        os.remove(path_for(workout_id, photo_id))
    except FileNotFoundError:
        pass
    except OSError:
        # The row decides whether a photo exists; a stuck file is an admin
        # problem, not a reason to fail the request that deleted the row.
        log.warning("Could not delete photo %s of workout %s", photo_id, workout_id)
