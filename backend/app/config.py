"""Settings, tunable thresholds, and the guard that refuses a placeholder install."""

import datetime as dt
import logging
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("secondmile.config")

# Reported at GET /api/status and kept in step with the frontend's package.json
# and the README whenever a release round bumps it.
APP_VERSION = "0.1.1"
APP_NAME = "secondmile"


class Settings(BaseSettings):
    # Field names map to upper-case environment variables, so session_hours
    # reads SESSION_HOURS. Every one of these is documented in .env.example;
    # keep the two in step.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = ""

    # Whether the session cookie carries the Secure attribute. True by default
    # because the wrong default here leaks sessions over plain HTTP, and a
    # self-hoster who has not thought about it should get the safe behaviour.
    cookie_secure: bool = True
    session_hours: int = 720

    # Whether anyone who can reach the site may create an account. False keeps
    # the instance invite-only. It is the default because an open form on a
    # public URL is found by bots within days, and turning it on is a decision
    # the person running the server should have to make on purpose.
    registration_open: bool = False

    # Where the verification link points. Getting this wrong produces links
    # that work from the machine you tested on and nowhere else, so it is the
    # first thing to check when a verification mail arrives and the link does
    # not open the app.
    site_url: str = "http://127.0.0.1:8110"

    # Outbound mail. An empty smtp_host is a supported configuration, not a
    # broken one: the verification link is written to the backend log instead,
    # which is enough for an instance whose accounts are all made by people the
    # admin can hand a link to.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""

    # Timezone used to group workouts into days and weeks. Everything is stored
    # in UTC; this only decides where the day boundaries fall for the Almanac
    # and for the daily distance caps.
    tz: str = "UTC"

    # Where re-encoded profile pictures are written. The default is the path
    # the compose file mounts a named volume at, so avatars survive a rebuild
    # without anybody having to configure anything. Files here are named from
    # the account id and never from anything the uploader sent.
    avatar_dir: str = "/data/avatars"

    # Where re-encoded workout photos are written, on the same terms as the
    # avatars above: the default is the path the compose file mounts a second
    # named volume at, and file names come from the workout and photo ids
    # rather than from anything the uploader sent.
    photo_dir: str = "/data/photos"

    # Where re-encoded workout videos and their poster frames are written, on
    # the photos' terms again: a third named volume, and names built from the
    # workout and video ids rather than from anything the uploader sent.
    video_dir: str = "/data/videos"

    daily_cap_walk_mi: float = 40.0
    daily_cap_run_mi: float = 40.0
    daily_cap_cycle_mi: float = 200.0
    daily_cap_swim_mi: float = 10.0

    # How many proxies of your own sit in front of this app. Zero means the one
    # the compose file ships. See client_address in app/throttle.py for what the
    # number does and why getting it wrong is a rate-limiting hole.
    trusted_proxy_hops: int = 0


settings = Settings()


def _load_timezone(name: str) -> dt.tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        # A missing zone must not take the server down: UTC still groups days
        # correctly, just possibly on the wrong boundary. Warn loudly instead,
        # because silently shifted week totals are hard to notice and harder to
        # explain. Slim base images sometimes ship without the zone database.
        log.warning("Unknown timezone %r; falling back to UTC for day grouping", name)
        return dt.timezone.utc


SERVER_TZ = _load_timezone(settings.tz)


# Soft-flag thresholds. These are not rejections: anything past them is still
# imported, just marked, so a confused watch or a garbled export never
# silently becomes progress. Generous on purpose, because a false flag on a
# real effort is worse than a missed flag on a fake one.
MIN_PACE_MIN_PER_MI = 4.0  # applies to walking and running
MAX_CYCLE_SPEED_MPH = 30.0
MAX_SWIM_SPEED_MPH = 5.0


# Hard bounds, which the soft flags above are not. Anything past one of these is
# not a workout somebody had a strange day doing, it is a broken export or a
# deliberate one, and it never becomes a row: the progress pipeline reads every
# row an account owns on every request, so one impossible number stored today is
# an account that cannot load tomorrow. Generous enough that no real effort is
# refused; a 48 hour ultra and a thousand mile day are both already past what a
# body does.
MAX_WORKOUT_DISTANCE_MI = 1000.0
MAX_WORKOUT_DURATION_S = 172800
MAX_WORKOUT_KCAL = 50000.0
MIN_WORKOUT_HR = 20.0
MAX_WORKOUT_HR = 300.0


# How far one raw mile of each activity carries the marker, in Miles. Effort
# equivalence rather than distance: an hour of swimming is not an hour of
# cycling, and the world is priced in effort. These live in code and not in the
# environment on purpose. They are game balance, not deployment configuration,
# and an instance that quietly tripled its own rates would not be playing the
# same game as anybody else.
MILES_PER_RAW = {"walk": 1.0, "run": 1.0, "cycle": 1.0 / 3.0, "swim": 4.0}

# The chest ladder: what each step of the cycle costs in converted Miles, and
# what the chest at the top of it is called. Fixed costs, not rolled, so the
# next chest is always countable. Wraps to the 5K step. Fuel is converted Miles
# from every activity, the same distance experience is measured in.
CHEST_LADDER: tuple[tuple[str, str, float], ...] = (
    ("5k", "5K", 3.1),
    ("10k", "10K", 6.2),
    ("half", "Half", 13.1),
    ("marathon", "Marathon", 26.2),
    ("ultra", "Ultra", 31.1),
)

# The rarity slot each step of the ladder is worth at worst. A chest is never
# poorer than its step, which is what makes the long steps worth walking: an
# Ultra is a legendary chest and cannot come up as anything else.
CHEST_TIER_FLOOR: dict[str, str] = {
    "5k": "common",
    "10k": "uncommon",
    "half": "rare",
    "marathon": "epic",
    "ultra": "legendary",
}

# How often a chest comes up one rarity above its floor, and never further. The
# top of the ladder has nothing above it, so an Ultra keeps its own.
CHEST_UPGRADE_CHANCE = 0.20

# How many gifts one account may have waiting at once, counted across every
# friend who has spent oil on them. Oil promises the upgrade above rather than
# risking it, so this is a cap on how much of somebody's coming ladder can be
# lifted before they have run any of it.
MAX_PENDING_ANOINTINGS = 3

# The step a chest that predates the ladder is worth. Those chests were dropped
# without a tier and roll as the first step in every respect.
LEGACY_CHEST_TIER = "5k"

# What comes out of a rarity slot once it has been rolled, as (kind, chance)
# summing to one. Every item is a tool with exactly one verb: a seed is
# planted, water is poured, oil anoints somebody else, and a wish is spent on
# whichever seed you are missing. The two top slots are the tools alone: an
# epic is the wish and oil in even halves, and a legendary is oil.
#
# Epic is wish+oil in halves, not wish alone: a full plot degrades every wish
# to water, so an all-twelve plot would turn every epic into water.
CHEST_SLOT_ITEMS: dict[str, tuple[tuple[str, float], ...]] = {
    "common": (("seed", 0.85), ("water", 0.15)),
    "uncommon": (("seed", 0.70), ("water", 0.30)),
    "rare": (("seed", 0.80), ("water", 0.20)),
    "epic": (("wish", 0.5), ("oil", 0.5)),
    "legendary": (("oil", 1.0),),
}

# Growth. Every planting grows from every credited workout, all at once and
# with no tending: the miles are the water. Swimming adds this much again of
# its converted Miles on top, which is the extra water a swim is.
SWIM_GROWTH_BONUS = 0.5

# What one water item pours into a single planting, in converted Miles of
# growth. Roughly a swim and a run, given to whichever plant you choose.
WATER_POUR_MI = 10.0


# Manna: what burned calories become. The giving lane's currency and nothing
# else, so no number below this line ever touches experience, a level, a chest,
# growth or a medal.

# One workout's active calories convert one for one and round UP to the next
# multiple of this, which is the generous read of "nearest 5": 650 is 650 and
# 656 is 660. Rounding up rather than to the nearest is deliberate, because a
# workout should never be worth less than the calories it cost.
MANNA_STEP_KCAL = 5

# Days gathered FRUIT keeps before composting. Clock starts at the gather, not
# before: fruit left on the plant never expires, and manna never spoils at all.
GATHERED_LIFE_DAYS = 7

# What feeding a mature plant costs, in manna, for one more fruit on its next
# bearing, and how many of those may be banked before it bears. Three at 500 is
# a full feeding at 1500. Yield only: no line that reads either of these may
# touch growth, a level, a chest or a medal (see the TWO-LANE LAW).
FEED_COST = 500
FEED_MAX_BANKED = 3

# The most manna one account may put into one other person inside this many
# days, counting a friend's plant fed and raw manna sent to them together. A
# bank built out of a year of calories drains across people rather than into one
# of them. Your own grove is exempt: a plant holds FEED_MAX_BANKED and no more,
# which caps it by shape rather than by arithmetic. A limit and not a timer, so
# nothing anywhere counts down to it.
MANNA_TO_ONE_PERSON = 2000
MANNA_TO_ONE_PERSON_DAYS = 7


# Fruit: what a grown plant bears, which is the only thing manna is ever spent
# toward. Everything under this line is the giving lane as well: bearing is paid
# for in converted Miles, and what it produces buys nothing in the earning lane.

# How many converted Miles the meter beside the chest ladder takes to fill. At
# the top of it every mature plant in the grove bears at once and the meter
# keeps whatever is left over, so one long day can bear several times. Miles are
# the season and there is no clock anywhere in it.
FRUIT_SEASON_MI = 33.0

# How much one plant bears, by what it is. Rarer plants bear less and are worth
# more for it, which is the whole of the scale. The mustard tree is named on its
# own rather than read off its rarity: it is a rare for rolling purposes only,
# and what it bears is a decision about the mustard tree.
FRUIT_YIELD: dict[str, int] = {
    "common": 3,
    "uncommon": 2,
    "rare": 1,
    "mustard": 1,
}

# What a fully grown plant's harvest is called: the same count, a finer name.
# Never more fruit, which was his answer outright.
GOLDEN_FRUIT_PREFIX = "golden "


# Experience is converted Miles, one for one. Nothing but synced movement ever
# produces any of it, and the number on the profile is the distance itself
# rather than a score derived from it.

# The level curve, in converted Miles. The first four levels are the race
# ladder every runner already knows, so reaching level one is running a 5K.
# From level five on, each level costs one more marathon than the last.
LEVEL_COSTS_MI = (3.1, 6.2, 13.1, 26.2)
LEVEL_STEP_MI = 26.2

# Where the loop that walks the curve stops. Reaching it takes a few million
# miles, so it is not a ceiling anybody meets; it is there so a corrupted total
# can never hold a request open.
MAX_LEVEL = 500

# The level each border tier arrives at, in order. Six files, six tiers, and a
# player is on the highest tier whose level they have passed. A fresh account
# stands at level 0, so the first tier starts there.
BORDER_LEVELS = (0, 6, 10, 15, 25, 35)

# How many badges a player may wear around their avatar. Fixed slots, and the
# picture is never covered, so this is a layout constant as much as a rule.
# Three by intent rather than by fit: the trinity is the reason, and the ring
# around an avatar would hold a fourth quite happily.
MAX_DISPLAYED_BADGES = 3

# How many sports the profile shows as diamonds. Fixed slots again, and the
# same number whether the player picked them or the server did.
MAX_DIAMOND_SPORTS = 3


# Renown: what encouraging somebody else is worth to the person who did it.
# Never to the person it was said to, because a number that grew from being
# admired would reward posting rather than caring.
RENOWN_CHEER = 1
RENOWN_NOTE = 3
# Giving away something a chest gave you is worth more than words, and oil is
# worth more than water because it is scarcer and because it becomes a chest.
RENOWN_WATER = 5
RENOWN_OIL = 8
# Manna spent on somebody else. Feeding a friend's plant sits where water sits,
# because it is the same act pointed at the same thing; raw manna sits where a
# note sits, because it is given without being aimed at anything; and fruit sits
# at the top beside the potion, because it is the end of the whole chain: miles
# grew it, calories fed it, and it was gathered before it could be given.
#
# Feeding your own plant is worth none of this and never asks. Others first by
# what it pays, not by what it forbids.
RENOWN_FEED = 5
RENOWN_MANNA_GIFT = 3
RENOWN_FRUIT_GIFT = 8

# The diminishing window. Inside this many days, one pair earns renown for the
# first cheer and the first note only; everything after still arrives, and is
# still worth as much to the person who receives it, but pays its sender
# nothing. Two accounts cheering each other all evening earn one cheer's worth.
RENOWN_WINDOW_DAYS = 7

# Renown at which each flourish stage arrives, in order. A player is at the
# highest stage they have passed, so stage 0 is where everybody starts.
FLOURISH_RENOWN = (10, 40, 120)

# How long a note may be. Long enough for a real remark, short enough that
# notes stay short.
NOTE_MAX_CHARS = 500

# What one bug report may carry. The text is as long as a workout post, because
# a useful report is a paragraph or two of what happened. The other two are
# stamped by the server rather than typed: the screen name is one of a handful
# of short words, and the browser string is trimmed to a length no real one
# exceeds, so a client sending a kilobyte of either stores neither.
BUG_REPORT_MAX_CHARS = 2000
BUG_REPORT_VIEW_MAX_CHARS = 32
BUG_REPORT_UA_MAX_CHARS = 300

# Avatar upload limits. The byte cap is checked against Content-Length and then
# again while reading, because a client is free to lie in the header. The pixel
# cap is the decompression-bomb guard: a small file can declare an enormous
# canvas, and Pillow will happily try to allocate it.
MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 25_000_000
AVATAR_SIZE = 512

# What an owner may write on their own workout. A title is a headline and a
# post is the story behind it, so one is a line and the other is a few
# paragraphs. Neither is ever suggested by the app.
WORKOUT_TITLE_MAX_CHARS = 100
WORKOUT_POST_MAX_CHARS = 2000

# Workout photo limits, read the same way as the avatar ones above: the byte
# cap is checked against Content-Length and again while reading, and the pixel
# cap is the decompression-bomb guard. Roomier than an avatar because this is a
# photograph off a phone rather than a face in a circle.
MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_PHOTO_PIXELS = 25_000_000
# The longest edge a stored photo may have. Anything smaller is left alone:
# scaling a small picture up would invent detail and cost bytes doing it.
PHOTO_MAX_EDGE = 1600
# How many pictures and videos one workout may carry between them. A handful
# from a morning out, not an album, and a bound on what one workout can ask the
# disk for. A video takes one of these slots exactly as a photo does.
MAX_MEDIA_PER_WORKOUT = 6

# Workout video limits. The duration is the real one and the byte cap is the
# guard in front of it: a minute off a phone is fifty megabytes or so, and a
# hundred leaves room for a phone that records richer than that without leaving
# room for an hour of anything. Checked against Content-Length and again while
# reading, like every other upload here.
MAX_VIDEO_BYTES = 100 * 1024 * 1024
# Sixty seconds is the rule and this is the tolerance around it: a clip trimmed
# to a minute by hand is often a second or two over, and refusing that would be
# a rule about arithmetic rather than about length.
MAX_VIDEO_SECONDS = 65
# Below this, whatever was uploaded is a still picture in a container that
# calls itself a video. A JPEG opens as a video stream four hundredths of a
# second long.
MIN_VIDEO_SECONDS = 0.5
# The shorter edge a stored video may have, which is what 720p means for a clip
# held portrait. Anything smaller is left alone, for the reason a small photo
# is: scaling up invents detail and pays bytes for it.
VIDEO_MAX_SHORT_EDGE = 720
# How many videos one workout may carry. A minute of video is a moment, and two
# moments is an album; the slot cap above is shared with the photos regardless.
MAX_VIDEOS_PER_WORKOUT = 1

# Request body ceilings, enforced by the app itself so an install that fronts
# uvicorn with something other than the bundled proxy, or with nothing, still
# has one. The default sits just above the avatar cap so that endpoint keeps
# refusing in its own words; sync gets far more room because a phone's export
# carries sample arrays and a first catch-up can cover years.
MAX_BODY_BYTES = 6 * 1024 * 1024
MAX_INGEST_BODY_BYTES = 15 * 1024 * 1024
# Sits just above the photo cap for the same reason the default sits just above
# the avatar one: the upload endpoint keeps refusing an oversized picture in its
# own words rather than having the middleware answer first.
MAX_PHOTO_BODY_BYTES = 11 * 1024 * 1024
# And the same again for a video, five megabytes above its hundred.
MAX_VIDEO_BODY_BYTES = 105 * 1024 * 1024

# How many workout entries one export may carry. The byte cap above bounds the
# body, not the entry count, and an export of tiny entries is a request that
# asks the server for one savepoint and one insert each. Years of catching up
# for four activities does not come close to this.
MAX_INGEST_WORKOUTS = 2000

# And the same ceiling on the samples the export's metrics carry between them,
# set far higher because a metric is not sent as a day. The real automation
# sends a bucket every few minutes: a hundred and seventy samples by mid
# afternoon, a few hundred to a couple of thousand per metric per day, and both
# metrics at once. This is weeks of catching up at that rate, and the body cap
# above bites first for anything past it; what this bounds is the arithmetic on
# a body that got in under the cap by being nothing but tiny samples.
MAX_INGEST_METRIC_POINTS = 100_000

# What one day's pedometer reading is allowed to claim, before anything is
# subtracted from it or credited. Neither is a rule about what earns, which is
# the daily cap's business: they are the bound that keeps a phone with a broken
# sensor from writing a number the integer column cannot hold. A hundred
# thousand steps is a very long day out; this is well past one.
MAX_DAILY_STEPS = 250_000
MAX_DAILY_STEP_MI = MAX_WORKOUT_DISTANCE_MI

# How far back of a phone's history one account may import, counted from the day
# that account was created. Anchored to the signup and never to now, so an
# offline fortnight after joining still syncs whole: what this refuses is a new
# account importing years of somebody's old exports at once. Stored rows are
# never reconsidered by it.
BACKFILL_WINDOW_DAYS = 14

# How long a stored sync payload is kept. The log is a replay net for a parsing
# bug, and a bug older than a season has either been found or has been lived
# with, so holding every export forever only grows a table nothing else reads.
# Each account's old rows go on that account's own next sync.
INGEST_LOG_RETENTION_DAYS = 90

# How long a deleted workout can still be got back. Long enough to undo a
# mistake noticed a fortnight later, short enough that the promise "then it is
# gone" means something. Past it, the pictures, the video, the route line and
# the words are purged on that account's own next sync; the workout row itself
# stays forever as a tombstone, because the sync dedupe key is on that row and
# losing it would let the phone import the same session all over again.
DELETED_WORKOUT_RETENTION_DAYS = 30


def daily_cap_mi(activity: str) -> float:
    """The configured daily distance ceiling for one activity, in miles."""
    return {
        "walk": settings.daily_cap_walk_mi,
        "run": settings.daily_cap_run_mi,
        "cycle": settings.daily_cap_cycle_mi,
        "swim": settings.daily_cap_swim_mi,
    }[activity]


# The placeholder values shipped in .env.example. An install still using one is
# readable by anyone who can read the public source, so startup refuses it.
_PLACEHOLDER = "change-me"


def check_deploy_config() -> None:
    """Refuse to start while .env still holds the placeholder secrets.

    Called once when the app is imported, and again at the top of the migration
    environment, so a misconfigured install gets a plain-language fix rather
    than a database driver traceback several layers down.
    """
    problems = []
    if not settings.database_url:
        problems.append("DATABASE_URL is empty. Copy .env.example to .env and fill it in.")
    elif _PLACEHOLDER in settings.database_url:
        problems.append(
            "DATABASE_URL still contains the placeholder database password.\n"
            "Generate one with: openssl rand -hex 24\n"
            "then put the same value in POSTGRES_PASSWORD and in DATABASE_URL."
        )
    # Not a Settings field: only the database container needs this one, and the
    # backend merely receives it through compose's env_file. Checking it here
    # anyway catches the fix-one-forget-the-other mistake, which matters because
    # Postgres freezes the password it was first initialised with into the
    # volume and changing it afterwards is a chore.
    if os.environ.get("POSTGRES_PASSWORD", "") == _PLACEHOLDER:
        problems.append(
            "POSTGRES_PASSWORD in .env is still the placeholder. Pick a real one\n"
            "and use the same value in DATABASE_URL."
        )
    if problems:
        raise SystemExit(
            f"{APP_NAME} refused to start: insecure or incomplete configuration.\n\n"
            + "\n\n".join(problems)
        )
