"""A short video attached to a workout.

The photos' bargain, one size up. The uploaded bytes are size-capped, probed
with ffprobe to prove there really is a video in there and that it is short
enough to keep, then re-encoded by ffmpeg and thrown away. What lands on disk
is an H.264 mp4 this server built, no taller than 720p and carrying no
metadata, beside a poster frame it cut itself, under names derived from two row
ids and nothing an uploader sent.

ffmpeg is shelled out to rather than bound as a library: the two commands below
are the whole of what this needs, and a binary in the image is a smaller thing
to carry than a wrapper around it.
"""

import contextlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator

from app.config import (
    MAX_VIDEO_SECONDS,
    MIN_VIDEO_SECONDS,
    VIDEO_MAX_SHORT_EDGE,
    settings,
)

log = logging.getLogger("secondmile.videos")

# The server decides the stored format; it is never negotiated with the
# uploader. H.264 in an mp4 is the one combination every phone and every
# browser plays, which is the whole reason everything is re-encoded.
SUFFIX = ".mp4"
MEDIA_TYPE = "video/mp4"
# The still under the play mark on a card, cut from the encoded video rather
# than from the upload so its shape can never disagree with what plays.
POSTER_SUFFIX = ".jpg"
POSTER_MEDIA_TYPE = "image/jpeg"

# What a refusal says. Written here because the reasons are this module's, and
# the router only passes them on.
NOT_A_VIDEO = "That file is not a video this server can read."
TOO_LONG = "That video is too long. About a minute is the limit."
TOOK_TOO_LONG = "That video could not be processed. Try a shorter clip."

# A minute of 720p takes a couple of seconds on anything that runs this app.
# The ceiling is here so a file built to be expensive cannot hold a worker
# open, not because a real clip ever comes near it.
WORK_TIMEOUT_S = 120

# 720p for a clip held portrait means the SHORT edge, not the height: a phone
# video is 1080 wide and 1920 tall, and capping the height would leave it 405
# across. Never upscaled either, for the reason a small photo is not: scaling
# up invents detail and pays bytes for it. -2 keeps the aspect ratio and rounds
# to an even number, which H.264 requires.
_SCALE = (
    f"scale=w='if(gte(iw,ih),-2,min({VIDEO_MAX_SHORT_EDGE},iw))'"
    f":h='if(gte(iw,ih),min({VIDEO_MAX_SHORT_EDGE},ih),-2)'"
)


class RejectedVideo(Exception):
    """The upload is not a video this server is willing to store."""


def _directory() -> str:
    # Read through settings so tests can point this at a temporary directory.
    return settings.video_dir


def _ensure_directory() -> str:
    os.makedirs(_directory(), exist_ok=True)
    return _directory()


def path_for(workout_id: int, video_id: int) -> str:
    """Where one video lives. Derived from the two ids, never supplied."""
    return os.path.join(_directory(), f"{workout_id}-{video_id}{SUFFIX}")


def poster_path_for(workout_id: int, video_id: int) -> str:
    """Where its poster frame lives, under the same two ids."""
    return os.path.join(_directory(), f"{workout_id}-{video_id}{POSTER_SUFFIX}")


@contextlib.contextmanager
def workspace() -> Iterator[str]:
    """A throwaway directory for one upload, on the volume videos live on.

    The upload is written here before anything looks at it, and the encoder
    writes its output beside it. A hundred megabytes has no business in the
    container's writable layer, and the disk provisioned for videos is the one
    that should carry the working copy too.
    """
    path = tempfile.mkdtemp(dir=_ensure_directory(), prefix="incoming-")
    try:
        yield path
    finally:
        # A request killed mid-encode is the one case that leaves one of these
        # behind; everything that returns or raises clears its own.
        shutil.rmtree(path, ignore_errors=True)


def _run(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, timeout=WORK_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        log.warning("%s gave up after %s seconds", command[0], WORK_TIMEOUT_S)
        raise RejectedVideo(TOOK_TOO_LONG) from None


def inspect(source: str) -> float:
    """How many seconds of video the uploaded file holds, or RejectedVideo.

    Read before a single frame is encoded, because the duration is the real
    limit here and the byte cap is only the guard in front of it: a minute of
    phone video is fifty megabytes and an hour of it is not.

    A decoder either finds a video in the file or it does not, which is the
    only check worth making; the extension and the content type are claims. A
    still picture is the case the floor is for. A JPEG opens quite happily as a
    video stream four hundredths of a second long, and nobody meant to post one
    as a clip.
    """
    probe = _run(
        [
            "ffprobe",
            "-v",
            "error",
            # v:0 alone, so a file with no video in it comes back with an empty
            # stream list rather than with its audio.
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type:format=duration",
            "-of",
            "json",
            source,
        ]
    )
    if probe.returncode != 0:
        raise RejectedVideo(NOT_A_VIDEO)
    try:
        found = json.loads(probe.stdout)
    except ValueError:
        raise RejectedVideo(NOT_A_VIDEO) from None
    if not found.get("streams"):
        raise RejectedVideo(NOT_A_VIDEO)
    try:
        seconds = float(found.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        # No duration at all is what a single still image looks like once its
        # container has been unwrapped.
        raise RejectedVideo(NOT_A_VIDEO) from None
    if seconds < MIN_VIDEO_SECONDS:
        raise RejectedVideo(NOT_A_VIDEO)
    if seconds > MAX_VIDEO_SECONDS:
        raise RejectedVideo(TOO_LONG)
    return seconds


def encode(source: str, seconds: float) -> tuple[bytes, bytes]:
    """Turn an uploaded file into the mp4 this server serves and its poster.

    Called before the row exists, so a video this server will not store never
    burns an id, exactly as a photo does not.

    Both outputs are written beside the source, which is inside the workspace
    the caller opened, and both come back as bytes so the writing into place
    happens once the row has an id to name them with.
    """
    work = os.path.dirname(source)
    video = os.path.join(work, "encoded.mp4")
    poster = os.path.join(work, "poster.jpg")

    done = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            source,
            # Exactly one video stream and at most one audio stream. Capital V
            # skips attached pictures, so a file carrying cover art cannot have
            # the artwork chosen as its video; -sn -dn drop subtitles and data.
            "-map",
            "0:V:0",
            "-map",
            "0:a:0?",
            "-sn",
            "-dn",
            # The duration was checked above. This is the second answer, in
            # case a container lied about it: the encode is synchronous, so
            # unbounded input is unbounded time spent inside a request.
            "-t",
            str(MAX_VIDEO_SECONDS),
            "-vf",
            _SCALE,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            # Ten-bit and 4:2:2 phone footage exists and Safari will not play
            # it, so the pixel format is decided here rather than inherited.
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ac",
            "2",
            # The index at the front, so a browser can start playing before it
            # has the whole file.
            "-movflags",
            "+faststart",
            # The photos' strip-everything stance: no title, no comment, no
            # creation date, no GPS. bitexact takes the last of it, the encoder
            # name and version ffmpeg writes into every file by default.
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-bitexact",
            video,
        ]
    )
    if done.returncode != 0 or not os.path.isfile(video):
        log.warning("ffmpeg refused an upload: %s", done.stderr.decode("utf-8", "replace")[:500])
        raise RejectedVideo(NOT_A_VIDEO)

    # A second in, or the middle of a shorter clip: the first frame of a phone
    # video is usually the moment the lens was still finding the light.
    at = min(1.0, seconds / 2)
    framed = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            # Before -i, so ffmpeg seeks rather than decoding up to the point.
            "-ss",
            f"{at:.3f}",
            "-i",
            video,
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-map_metadata",
            "-1",
            "-bitexact",
            poster,
        ]
    )
    if framed.returncode != 0 or not os.path.isfile(poster):
        log.warning(
            "ffmpeg could not cut a poster: %s", framed.stderr.decode("utf-8", "replace")[:500]
        )
        raise RejectedVideo(NOT_A_VIDEO)

    with open(video, "rb") as encoded, open(poster, "rb") as still:
        return encoded.read(), still.read()


def _write(target: str, payload: bytes) -> None:
    """Write-then-rename, so a request dying halfway cannot leave a truncated
    file, with a temporary name unique per call so two writes cannot share one.
    """
    handle, temporary = tempfile.mkstemp(
        dir=_directory(), prefix=os.path.basename(target) + "-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(payload)
        os.replace(temporary, target)
    except OSError:
        # A failed write must not leave its scratch file behind for good.
        try:
            os.remove(temporary)
        except OSError:
            pass
        raise


def store(workout_id: int, video_id: int, encoded: bytes, poster: bytes) -> None:
    """Write an already-encoded video and its poster into place.

    Takes the encoded bytes rather than the raw ones because the video id comes
    from the row, and the row must not be written for something that turns out
    not to be a video.
    """
    _ensure_directory()
    _write(path_for(workout_id, video_id), encoded)
    _write(poster_path_for(workout_id, video_id), poster)


def remove(workout_id: int, video_id: int) -> None:
    """Delete one stored video and its poster. Missing is not an error."""
    for target in (path_for(workout_id, video_id), poster_path_for(workout_id, video_id)):
        try:
            os.remove(target)
        except FileNotFoundError:
            pass
        except OSError:
            # The row decides whether a video exists; a stuck file is an admin
            # problem, not a reason to fail the request that deleted the row.
            log.warning("Could not delete %s", target)
