"""Per-address sliding-window rate limiting, and working out which address."""

import ipaddress
import logging
import time
from collections import defaultdict, deque

from fastapi import Request

log = logging.getLogger("secondmile.throttle")

_WINDOW_SECONDS = 60
# Sweep only once the table is larger than any real audience, so a normal
# install never pays for the sweep at all.
_SWEEP_THRESHOLD = 2048
# A hard ceiling in case addresses arrive faster than the sweep clears them.
# Reaching it means new addresses are refused, which is the correct failure for
# a flood: the alternative is allocating until the box falls over.
_MAX_TRACKED = 20000


class RateLimiter:
    """Attempt counting per address over a sliding window.

    One instance per thing being limited, so a phone syncing workouts cannot eat
    into the allowance that protects password guessing.

    The eviction is not incidental. A bare dictionary of addresses grows a
    permanent entry for every address it ever sees: the timestamps inside age
    out, but the entry itself never does. That is a slow leak under ordinary
    traffic and a deliberate one under attack, so entries whose window has fully
    passed get swept.
    """

    def __init__(self, max_attempts: int, name: str):
        self.max_attempts = max_attempts
        self.name = name
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def _sweep(self, now: float) -> None:
        stale = [
            address
            for address, hits in self._hits.items()
            if not hits or now - hits[-1] > _WINDOW_SECONDS
        ]
        for address in stale:
            del self._hits[address]

    def hit(self, address: str) -> bool:
        """Record an attempt. True means this one should be refused."""
        now = time.time()
        if len(self._hits) >= _SWEEP_THRESHOLD:
            self._sweep(now)
        if address not in self._hits and len(self._hits) >= _MAX_TRACKED:
            log.warning("%s limiter is at its address ceiling; refusing new ones", self.name)
            return True
        history = self._hits[address]
        while history and now - history[0] > _WINDOW_SECONDS:
            history.popleft()
        if len(history) >= self.max_attempts:
            return True
        history.append(now)
        return False

    def clear(self) -> None:
        self._hits.clear()

    def tracked(self) -> int:
        return len(self._hits)


# Guessing a password. Tight, because this is the one an attacker actually wants.
login_limiter = RateLimiter(5, "login")
# Burning through invite codes. Same budget as login: a code is guessable in
# principle, and registration is the other way into an account.
register_limiter = RateLimiter(5, "register")
# Syncing workouts. Far higher, because a phone catching up after a week offline
# posts in a burst and none of it is an attempt at anything.
ingest_limiter = RateLimiter(60, "ingest")
# Changing a password. Its own budget so that a stolen session cannot brute
# force the current-password check the change has to clear, and so doing that
# does not consume the login allowance a real user needs.
password_limiter = RateLimiter(5, "password")
# Asking for another verification mail. Tighter than the rest, because every
# accepted call sends a message to an address someone else chose, and a form
# that will mail a stranger on demand is a way to use this server to bother
# them.
resend_limiter = RateLimiter(3, "resend")
# Uploading a profile picture. Tight, because every accepted call hands the
# server several megabytes to decode and re-encode, which is by far the most
# expensive thing a signed-in account can ask it to do.
avatar_limiter = RateLimiter(5, "avatar")

_ALL_LIMITERS = (
    login_limiter,
    register_limiter,
    ingest_limiter,
    password_limiter,
    resend_limiter,
    avatar_limiter,
)


def reset_limiters() -> None:
    """Clear every limiter at once.

    The tests share one process, so state carried between cases makes them
    order dependent. They are cleared as a group rather than one by one because
    adding a fifth limiter and forgetting to reset it produces exactly the test
    that passes alone and fails in the suite.
    """
    for limiter in _ALL_LIMITERS:
        limiter.clear()


def client_address(request: Request) -> str:
    """The caller's address, taken from the right-most X-Forwarded-For entry.

    X-Forwarded-For is a list the caller gets to start writing, and a reverse
    proxy appends what it saw rather than replacing what arrived. A request sent
    with "X-Forwarded-For: 1.2.3.4" therefore arrives as "1.2.3.4, <real
    caller>". Reading the left-most entry reads the value the caller chose,
    which lets anyone pick their own rate-limit bucket and walk straight past
    the limiter. The right-most entry is the one our own proxy wrote, so it is
    the only one nobody upstream could have forged.

    This trusts exactly one hop, which is the topology this ships with. Put a
    second proxy in front and this needs to skip that many more entries.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    for entry in reversed([part.strip() for part in forwarded.split(",")]):
        if not entry:
            continue
        try:
            ipaddress.ip_address(entry)
        except ValueError:
            # A proxy writes a bare address. Anything else did not come from our
            # proxy, so stop rather than reading further left into whatever the
            # caller supplied.
            break
        return entry
    return request.client.host if request.client else "unknown"
