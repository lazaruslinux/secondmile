"""Sliding-window rate limiting, per address or per account.

Two kinds of key go through one limiter class. Anything anonymous is counted
per address, because an address is the only thing there is to count; anything
behind a session is counted per account instead, because that is the thing
actually spending the allowance, and one household behind one address should
not share a budget between its phones.
"""

import ipaddress
import logging
import time
from collections import defaultdict, deque

from fastapi import Request

from app import models
from app.config import settings

log = logging.getLogger("secondmile.throttle")

_WINDOW_SECONDS = 60
# Sweep only once the table is larger than any real audience, so a normal
# install never pays for the sweep at all.
_SWEEP_THRESHOLD = 2048
# A hard ceiling in case keys arrive faster than the sweep clears them.
_MAX_TRACKED = 20000

# Every limiter ever built, so nothing has to be listed twice. Appended to by
# the constructor rather than written out below: a hand-kept list is exactly
# how a new limiter ends up outside reset_limiters and produces the test that
# passes alone and fails in the suite.
_ALL_LIMITERS: list["RateLimiter"] = []


class RateLimiter:
    """Attempt counting per key over a sliding window.

    One instance per thing being limited, so a phone syncing workouts cannot eat
    into the allowance that protects password guessing.

    The sweep is not incidental. A bare dictionary of keys grows a permanent
    entry for every key it ever sees: the timestamps inside age out, but the
    entry itself never does. That is a slow leak under ordinary traffic and a
    deliberate one under attack, so entries whose window has fully passed get
    swept.
    """

    def __init__(self, max_attempts: int, name: str):
        self.max_attempts = max_attempts
        self.name = name
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)
        _ALL_LIMITERS.append(self)

    def _sweep(self, now: float) -> None:
        stale = [
            key
            for key, hits in self._hits.items()
            if not hits or now - hits[-1] > _WINDOW_SECONDS
        ]
        for key in stale:
            del self._hits[key]

    def _evict_oldest(self) -> None:
        """Drop whichever key has gone longest without a hit.

        Only ever at the ceiling, and only after the sweep has already cleared
        everything fully idle. Refusing new keys instead was the old answer and
        it is the wrong one: an address-keyed limiter reaching the ceiling means
        somebody is flooding it with spoofed addresses, and the refusal would
        then lock every real person out of the endpoint the flood is aimed at.
        Evicting costs the oldest attacker their count and nobody else anything.
        """
        oldest = min(
            self._hits,
            key=lambda key: self._hits[key][-1] if self._hits[key] else 0.0,
        )
        del self._hits[oldest]

    def hit(self, key: str) -> bool:
        """Record an attempt. True means this one should be refused."""
        now = time.time()
        if len(self._hits) >= _SWEEP_THRESHOLD:
            self._sweep(now)
        if key not in self._hits and len(self._hits) >= _MAX_TRACKED:
            log.warning("%s limiter is at its ceiling; evicting the oldest key", self.name)
            self._evict_oldest()
        history = self._hits[key]
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
# Asking to move an account to another address. As tight as a resend, for both
# of its reasons at once: every accepted call mails an address the caller typed
# in, and every call checks a password, which is the other thing that must never
# be guessable in a burst.
email_change_limiter = RateLimiter(3, "email-change")
# Uploading a profile picture. Tight, because every accepted call hands the
# server several megabytes to decode and re-encode, which is by far the most
# expensive thing a signed-in account can ask it to do.
avatar_limiter = RateLimiter(5, "avatar")
# Titling a workout and writing on it. Roomy, because somebody catching up on a
# week of posts is doing the thing the feature is for, and it is a plain UPDATE
# of two columns on a row they already own.
workout_edit_limiter = RateLimiter(30, "workout-edit")
# Attaching a photo. Tighter, for the avatar's reason: every accepted call hands
# the server up to ten megabytes to decode and re-encode, which is the most
# expensive thing a signed-in account can ask it to do.
photo_limiter = RateLimiter(10, "photo")
# Attaching a video. Tighter again: every accepted call hands the server up to
# a hundred megabytes and re-encodes it while the request waits, which takes
# the photo endpoint's place as the most expensive thing a signed-in account
# can ask for.
video_limiter = RateLimiter(5, "video")
# Spending a verification link. Its own budget because the token is the only
# secret it checks, and without one the endpoint is a place to guess tokens at
# whatever rate the network allows.
verify_limiter = RateLimiter(10, "verify")
# Asking to be somebody's friend. Roomy enough to add a family in one sitting,
# tight enough that nobody walks the username space with it: the endpoint
# answers the same way whoever it is asked about, and this is what stops the
# timing of a thousand attempts saying anything either.
invite_limiter = RateLimiter(10, "invite")
# Cheering and writing notes. The most generous of the lot, because reading a
# morning's feed and answering all of it is the behaviour this app is for.
encourage_limiter = RateLimiter(30, "encourage")
# Reading the instance totals on the welcome page. Unauthenticated, so counted
# per address, and as roomy as the signed-in reads below: the answer is a cached
# pair of integers that guards nothing, so the only thing worth stopping here is
# a loop, and a page that is opened and reloaded a few times must never hit it.
stats_limiter = RateLimiter(60, "stats")
# Opening a welcome page, and fetching the face on it. Unauthenticated, so it
# is counted per address like the rest of the anonymous endpoints. Twenty is a
# person opening a link and reloading it a few times; it is nowhere near enough
# to walk the code space, which is the thing this guards against, and the codes
# are high entropy besides.
welcome_limiter = RateLimiter(20, "welcome")

# --------------------------------------------------------------------------
# Keyed per account
# --------------------------------------------------------------------------
# Everything below is spent by a signed-in account, so it is counted per
# account rather than per address. None of these guards a secret; they are
# there so one session cannot make the server do an unbounded amount of work,
# and so a loop left running by mistake stops being free.

# Saving the edit form. Roomy for somebody filling in every field one save at a
# time, tight enough that nothing is hammering the write path.
profile_edit_limiter = RateLimiter(10, "profile-edit")
# Planting, pouring, wishing, and anointing, all out of one budget: they are
# four verbs on one satchel and an account holding a hundred items is not
# spending them faster than this.
satchel_limiter = RateLimiter(20, "satchel")
# Opening chests. Somebody back from a fortnight away opens a dozen in a
# sitting, and each one is a roll and a write.
chest_open_limiter = RateLimiter(20, "chest-open")
# Gathering, feeding a plant, and giving manna or fruit away, all out of one
# budget: they are four verbs on one harvest, and the satchel's four already
# share theirs for the same reason.
harvest_spend_limiter = RateLimiter(20, "harvest-spend")
# Putting the letter down. Once per sign-in in real use; the allowance is for
# a client that retries rather than for a person.
recap_ack_limiter = RateLimiter(10, "recap-ack")
# Minting a new ingest token. Rare by nature, and every call invalidates the
# phone's current one, so a burst of them is a mistake either way.
token_rotate_limiter = RateLimiter(5, "token-rotate")
# Answering invites: accepting one, declining one, cancelling one, or ending a
# friendship. Enough to tidy a whole list in one sitting.
friend_action_limiter = RateLimiter(20, "friend-action")
# Taking media back down: a profile picture, or a photo or video off a workout.
# The same budget as the uploads it undoes.
delete_media_limiter = RateLimiter(10, "media-delete")
# Deleting a workout and putting one back, out of one budget: they are the two
# halves of the same decision, and each one reworks the account's whole derived
# history. Ten is a tidy-up in one sitting and nothing is looping.
workout_delete_limiter = RateLimiter(10, "workout-delete")
# Looking a member up by name. Twenty a minute is somebody typing a name and
# correcting it a few times, which is what the box is for; it is well short of
# what walking the roster a letter at a time would take, and the endpoint
# refuses a query under two characters anyway.
member_search_limiter = RateLimiter(20, "member-search")
# Minting an invite link. Single digits an hour is his own word for what is
# plenty, and this window is a minute: five is a person making links for a
# family in one sitting and nothing is looping.
invite_link_limiter = RateLimiter(5, "invite-link")
# Recording a pair of shoes and everything done to one afterwards, out of one
# budget: they are a handful of verbs on a list of two or three rows, and
# nobody is adding shoes faster than this.
gear_limiter = RateLimiter(20, "gear")
# Reporting a bug. As tight as anything a signed-in account can do, because a
# report is written by hand and three in one minute is already somebody sending
# the same one three times. The window here is a minute rather than the hour
# the rest of this app's writing is paced in: every limiter shares one window,
# and three a minute is well inside the handful an hour this is meant to be.
bug_report_limiter = RateLimiter(3, "bug-report")
# The three screens the app reads on every visit. Sixty a minute is well past
# anything a person does and well under what a stuck poll would do.
profile_read_limiter = RateLimiter(60, "profile-read")
feed_limiter = RateLimiter(60, "feed")
recap_read_limiter = RateLimiter(60, "recap-read")
# The harvest and the basket beside it, on the same allowance as the three
# screens above: both are read every time somebody opens the grove or the You
# screen, and neither guards anything.
harvest_read_limiter = RateLimiter(60, "harvest-read")


# What a screen asked for too fast is told. Shared rather than written out in
# each router, because these are all the same event to whoever reads it: the app
# is looking at something faster than anybody looks at anything.
TOO_MANY_READS = "Too many refreshes just now. Wait a minute."


def user_key(user: models.User) -> str:
    """The bucket one account spends from.

    Prefixed so an account key can never collide with an address key, in case
    the two ever meet in one limiter: no address is spelled "u7".
    """
    return f"u{user.id}"


def reset_limiters() -> None:
    """Clear every limiter at once.

    The tests share one process, so state carried between cases makes them
    order dependent. Every limiter registers itself when it is built, so this
    cannot miss one: a hand-kept list is how a new limiter ends up outside it
    and produces the test that passes alone and fails in the suite.
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

    One hop is the topology this ships with, and TRUSTED_PROXY_HOPS is how an
    install with more says so: each proxy of your own in front of that one wrote
    an entry of its own, so that many right-most entries are skipped before the
    reading starts. Only entries your own proxies wrote may be skipped. Setting
    it higher than the number you really run hands the choice of bucket back to
    the caller, which is the hole this whole function exists to close.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    entries = [part.strip() for part in reversed(forwarded.split(","))]
    # Clamped, so a header shorter than the configured hop count falls through
    # to the connection address rather than reading past the end of the list.
    hops = min(max(settings.trusted_proxy_hops, 0), len(entries))
    for entry in entries[hops:]:
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
