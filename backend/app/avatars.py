"""Profile pictures. Uploaded bytes are size-capped, decode-verified with
Pillow, then discarded: what lands on disk is a freshly built square webp with
no metadata. File paths derive from the account id and nothing else."""

import io
import logging
import os
import tempfile

from PIL import Image

from app.config import AVATAR_SIZE, MAX_AVATAR_PIXELS, settings
from app.images import decode

log = logging.getLogger("secondmile.avatars")

# The server decides the stored format; it is never negotiated with the uploader.
SUFFIX = ".webp"
MEDIA_TYPE = "image/webp"


def _directory() -> str:
    # Read through settings so tests can point this at a temporary directory.
    return settings.avatar_dir


def path_for(user_id: int) -> str:
    """Where this account's avatar lives. Derived, never supplied."""
    return os.path.join(_directory(), f"{user_id}{SUFFIX}")


def stored_name(user_id: int) -> str:
    """What goes in users.avatar_path: a name, not a path, so moving
    AVATAR_DIR is a config change rather than an UPDATE over every row."""
    return f"{user_id}{SUFFIX}"


def version(user_id: int) -> int | None:
    """The stored file's mtime, used as the ?v= cache buster."""
    try:
        return int(os.stat(path_for(user_id)).st_mtime)
    except OSError:
        return None


def _square(image: Image.Image) -> Image.Image:
    """Largest centred square, scaled to AVATAR_SIZE. Centred because a
    top-anchored portrait crop loses whoever is in it."""
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = image.crop((left, top, left + side, top + side))
    return cropped.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)


def encode(raw: bytes) -> bytes:
    """Turn uploaded bytes into the webp this server serves.

    Decoding IS the validation, and app/images.py is where that happens; what is
    left here is the shape an avatar has to be.
    """
    square = _square(decode(raw, MAX_AVATAR_PIXELS))
    # Pasted onto a blank canvas: a converted image still carries its source's
    # info dict, and Pillow writes parts of it back out. A fresh canvas has
    # nothing to carry, so EXIF, colour profile, and GPS stop here.
    clean = Image.new("RGB", (AVATAR_SIZE, AVATAR_SIZE))
    clean.paste(square)

    out = io.BytesIO()
    clean.save(out, format="WEBP", quality=88, method=4)
    return out.getvalue()


def store(user_id: int, raw: bytes) -> str:
    """Re-encode and write the avatar. Returns what belongs in users.avatar_path."""
    encoded = encode(raw)
    os.makedirs(_directory(), exist_ok=True)
    target = path_for(user_id)
    # Write-then-rename so a request dying halfway cannot leave a truncated file.
    # The temporary name is unique per call rather than derived from the target:
    # two uploads for the same account at once would otherwise be writing into
    # the same file, and the one that renamed second would publish a mixture of
    # both. The rename itself is atomic, so whichever wins is a whole picture.
    handle, temporary = tempfile.mkstemp(dir=_directory(), prefix=f"{user_id}-", suffix=".tmp")
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
    return stored_name(user_id)


def remove(user_id: int) -> None:
    """Delete the stored avatar if there is one. Missing is not an error."""
    try:
        os.remove(path_for(user_id))
    except FileNotFoundError:
        pass
    except OSError:
        # The row decides whether an avatar exists; a stuck file is an admin
        # problem, not a reason to fail the request that cleared the column.
        log.warning("Could not delete the avatar file for account %s", user_id)
