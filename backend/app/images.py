"""Turning uploaded bytes into pixels, and refusing the ones that are not.

Shared by profile pictures and workout photos. Decoding IS the validation here,
so it lives in one place: two copies of this is how one of them gets a fix and
the other keeps the hole.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import MAX_AVATAR_PIXELS, MAX_PHOTO_PIXELS

# Past this Pillow only warns by default; the callers below refuse outright.
# The larger of the two caps, because this is one global for both of them.
Image.MAX_IMAGE_PIXELS = max(MAX_AVATAR_PIXELS, MAX_PHOTO_PIXELS)


class RejectedImage(Exception):
    """The upload is not an image this server is willing to store."""


def decode(raw: bytes, max_pixels: int) -> Image.Image:
    """Uploaded bytes as a loaded RGB image, or RejectedImage.

    Extensions and Content-Type are claims. A decoder either produces pixels or
    it does not, which is the only check worth making.
    """
    try:
        # verify() leaves the object unusable, hence opening twice.
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        image = Image.open(io.BytesIO(raw))
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
    ) as exc:
        raise RejectedImage("That file is not an image this server can read.") from exc

    # Declared size comes from the header, so a small file claiming an enormous
    # canvas is refused before load() decodes a single pixel.
    width, height = image.size
    if width < 1 or height < 1:
        raise RejectedImage("That image has no size.")
    if width * height > max_pixels:
        raise RejectedImage("That image is too large to process.")

    try:
        image.load()
    except (OSError, ValueError, SyntaxError) as exc:
        raise RejectedImage("That file is not an image this server can read.") from exc

    # Transpose before any crop or re-encode: callers strip metadata, so an
    # untransposed image keeps the sideways pixels permanently.
    return ImageOps.exif_transpose(image).convert("RGB")
