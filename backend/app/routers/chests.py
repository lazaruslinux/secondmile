"""Chests, what comes out of them, and the recap of everything that happened while away."""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import fellowship, grove, harvest, medals, models, progress, security, throttle
from app.activity import converted_miles
from app.config import SERVER_TZ
from app.db import get_db
from app.routers.workouts import photos_for, videos_for

router = APIRouter(tags=["chests"])

ALREADY_OPEN = "That chest is already open."

# Cap on notes in one letter. Past this, the rest stay on the workouts they
# were written on.
MAX_RECAP = 200

# How many of the new workouts the letter lists. A season of history imported in
# one go would otherwise draw a dialog nobody can reach the end of, and the rows
# are an invitation to annotate rather than a record: the log has all of them.
MAX_RECAP_WORKOUTS = 10


def _chest(row: models.Chest) -> dict:
    """A closed chest, saying which step of the ladder dropped it and nothing
    more. What is inside is rolled when it is opened.

    tier is the name to print; tier_id is the stable one, which is what the
    odds are keyed on and what the column holds.
    """
    tier_id, tier_name = progress.tier_of(row)
    return {
        "id": row.id,
        "dropped_at": row.dropped_at.isoformat(),
        "tier": tier_name,
        "tier_id": tier_id,
    }


def _pending(db: Session, user_id: int) -> list[models.Chest]:
    """Every chest still closed, oldest first. Never capped: the letter names
    them now, and a list that stopped at some number would be a lie."""
    return list(
        db.execute(
            select(models.Chest)
            .where(models.Chest.user_id == user_id, models.Chest.opened_at.is_(None))
            .order_by(models.Chest.id)
        ).scalars()
    )


@router.get("/chests")
def list_chests(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> list[dict]:
    """Every chest still closed, oldest first.

    A chest somebody's oil lifted looks exactly like any other here. Every chest
    in this list was earned by the miles, and what a gift did to one of them is
    a rarity nobody can see until the lid comes off.
    """
    progress.process_user(db, user.id)
    return [_chest(row) for row in _pending(db, user.id)]


@router.post("/chests/{chest_id}/open")
def open_chest(
    chest_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> dict:
    """Open a chest and put what was in it into the satchel.

    The answer is the item itself, in the shape the satchel lists it in, with
    the chest's tier alongside so the moment can be named. One shape for a
    thing that is one thing.
    """
    if throttle.chest_open_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many chests just now. Wait a minute.")
    chest = db.get(models.Chest, chest_id)
    if chest is None or chest.user_id != user.id:
        # One answer for a chest that never existed and one that belongs to
        # somebody else. Telling the two apart would let anyone count another
        # account's chests by walking the ids.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such chest.")
    if chest.opened_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_OPEN)

    tier_id, tier_name = progress.tier_of(chest)
    item = progress.open_chest(db, user.id, chest)
    if item is None:
        # Two requests carrying the same chest id, and the other one had the
        # lid off first. Told exactly what the check above tells a chest opened
        # yesterday, because by now that is what this one is.
        raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_OPEN)
    db.commit()
    return {**grove.serialize_item(item), "tier": tier_name, "tier_id": tier_id}


@router.get("/recap")
def read_recap(
    db: Session = Depends(get_db), user: models.User = Depends(security.current_user)
) -> dict:
    """Everything waiting since the last time this was cleared.

    Harvest and mail, which is the only thing opening the app is for. The
    chests were already dropped and the badges were already earned; nothing
    here happens because somebody looked.

    Nothing is opened here either, any more. The letter announces what landed
    and the inventory is where the lid comes off, which is what makes a chest
    something kept rather than something cleared on the way past.
    """
    if throttle.recap_read_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    row = progress.process_user(db, user.id)
    since = row.last_ack_at
    miles, xp = _miles(db, user.id, since)

    # Ordered as the letter reads: what window it covers, what the body did in
    # it, what landed, what people said, what grew, and the workouts themselves,
    # which the letter invites a word on rather than merely reporting.
    return {
        "since": since.isoformat() if since is not None else None,
        "last_sync_at": _last_sync(db, user.id),
        "miles": miles,
        # Added up from the four numbers as sent rather than from the sums
        # behind them, so the total under the four rows is always the total of
        # the rows the reader can see.
        "miles_total": round(sum(miles.values()), 2),
        # Steps counted, and only counted. Its own line rather than a fifth row
        # above, and in neither the total nor the XP: the rows are activities
        # somebody went out and did, and a pedometer's tally is not one of them
        # and earns nothing.
        "steps": _step_count(db, user.id, since),
        # Beside the body's own figures and above the weighted one, because
        # this is what the calories in those workouts came to rather than
        # anything the ladder runs on. Never news on its own: manna only
        # arrives with workouts, and workouts are already news.
        "manna": _manna(db, user.id, since),
        "xp": round(xp, 2),
        "chests": _delivered(db, user.id, since),
        "medals": _fresh_medals(db, user.id, since),
        "encouragement": _received(db, user.id, since),
        "plant_growth": _plant_growth(db, user.id),
        # What the grove bore while they were away, which is news for the
        # plainest reason there is: the miles earned it. The letter tells it and
        # points at the grove; the gathering itself happens there, because the
        # letter is what arrived and the grove is where things are done.
        "harvest": _harvest(db, user.id, since),
        # Gifts, attributed the way every gift in this app is attributed: in the
        # letter, afterwards, by the person who received it.
        "manna_gifts": _manna_gifts(db, user.id, since),
        "fruit_gifts": _fruit_gifts(db, user.id, since),
        # One quiet flag, and the client says one soft line about it. Nothing
        # counts down to this anywhere and nothing is said before it happens.
        "composted": harvest.composted_since(db, user.id, since),
        **_arrived(db, user.id, since),
        **_flourish(db, user.id, row, since),
    }


def _miles(
    db: Session, user_id: int, since: dt.datetime | None
) -> tuple[dict[str, float], float]:
    """What was covered since the last acknowledgement, both ways: the raw
    distance per activity, and what the game made of the lot of it.

    Two numbers because they are two different things. Miles are what a body
    covered and are the only thing ever printed as miles; XP is that distance
    weighted by how hard the activity is, and is what levels, the chest ladder
    and the grove run on. A mile swum is one mile and four XP, and one of those
    numbers wearing the other's name is the whole reason this returns a pair.

    Counted by when the row arrived rather than when the workout started: a week
    of history synced this morning is news this morning, whatever date is on it.

    All four activities, always, zeros included, because the letter prints four
    rows and the client should never have to invent the ones nobody did.

    A deleted workout is not in the window at all. The letter reports what the
    account did, and taking a workout back is saying it did not.
    """
    stmt = select(
        models.Workout.activity, func.coalesce(func.sum(models.Workout.distance_mi), 0.0)
    ).where(models.Workout.user_id == user_id, models.Workout.deleted_at.is_(None))
    if since is not None:
        stmt = stmt.where(models.Workout.created_at > since)
    miles = dict.fromkeys(models.ACTIVITIES, 0.0)
    xp = 0.0
    for activity, total in db.execute(stmt.group_by(models.Workout.activity)).all():
        miles[activity] = round(float(total), 2)
        xp += converted_miles(activity, float(total))
    return miles, xp


def _manna(db: Session, user_id: int, since: dt.datetime | None) -> int:
    """What the calories in this letter's workouts came to.

    The same window the miles above are summed over, down to the arrival rule
    and the deleted ones left out, so the line and the rows it sits under can
    never describe two different sets of workouts.

    Summed one workout at a time rather than off a total of the calories,
    because the rounding is per workout: two sessions of 651 are 1320 manna and
    never 1305. That is also why this walks the rows instead of asking the
    database for a sum, which would have to round the same way in two dialects.
    """
    stmt = select(models.Workout.active_kcal).where(
        models.Workout.user_id == user_id, models.Workout.deleted_at.is_(None)
    )
    if since is not None:
        stmt = stmt.where(models.Workout.created_at > since)
    return sum(progress.manna_for(kcal) for kcal in db.execute(stmt).scalars())


def _harvest(db: Session, user_id: int, since: dt.datetime | None) -> dict:
    """What the grove bore since the last letter was put down.

    Piled by fruit rather than listed by plant, because a harvest is one event
    and four bushes bearing is one sentence. The seasons are counted from the
    moments themselves: a bearing writes every batch at once, so the number of
    distinct moments is the number of times the grove came round.

    Windowed by when the fruit was borne, like every other figure in the letter,
    and counted whatever became of it afterwards. Gathering it, giving it away
    and leaving it to compost all happened after the news.
    """
    stmt = select(func.count(func.distinct(models.FruitBatch.season))).where(
        models.FruitBatch.user_id == user_id
    )
    if since is not None:
        stmt = stmt.where(models.FruitBatch.borne_at > since)
    return {
        "seasons": int(db.execute(stmt).scalar_one()),
        "fruit": harvest.harvest_since(db, user_id, since),
    }


def _manna_gifts(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """Raw manna friends sent, oldest first, with who sent it.

    It is already in the pending pile by the time this is read: a gift is safe
    the moment it arrives and waits there until it is gathered, so this line is
    the news rather than the delivery.
    """
    stmt = (
        select(models.MannaGift.amount, models.User.username)
        .join(models.User, models.User.id == models.MannaGift.from_user_id)
        .where(models.MannaGift.to_user_id == user_id)
    )
    if since is not None:
        stmt = stmt.where(models.MannaGift.created_at > since)
    return [
        {"from": username, "amount": int(amount)}
        for amount, username in db.execute(
            stmt.order_by(models.MannaGift.created_at, models.MannaGift.id)
        ).all()
    ]


def _fruit_gifts(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """Fruit friends gave, with the sentence it came with.

    Read off the keepsake rather than off the giver's grove, because the
    keepsake is the permanent record and the grove it came from has moved on.
    """
    stmt = select(models.FruitKeepsake).where(models.FruitKeepsake.user_id == user_id)
    if since is not None:
        stmt = stmt.where(models.FruitKeepsake.received_at > since)
    return [
        {
            "from": row.from_username,
            "name": harvest.fruit_name(row.species, row.golden),
            "label": harvest.fruit_words(row.count, row.species, row.golden),
            "count": row.count,
            "provenance": row.provenance,
        }
        for row in db.execute(
            stmt.order_by(models.FruitKeepsake.received_at, models.FruitKeepsake.id)
        ).scalars()
    ]


def _step_count(db: Session, user_id: int, since: dt.datetime | None) -> int:
    """Steps counted over the whole local days this letter covers.

    Whole days, which is the whole of the boundary. A step row is a running
    total of a local day and is upserted all through it, so it carries no
    record of when within the day a step was taken: a window measured to the
    minute cannot be asked of it. The window is therefore the local days
    strictly after the day of the last acknowledgement, up to but never
    including the day being lived now.

    Both ends are chosen so the number can only be honest. Today is left out
    because it is half over, and a letter that counted it would say a smaller
    number than the same letter read an hour later. The ack's own day is left
    out whole because part of it was already in the letter that was put down,
    and counting it again would say those steps twice. What that costs is the
    morning-of steps of the day somebody last read their letter, which is the
    cheaper of the two errors: the letter says less than the truth rather than
    more.
    """
    today = security.now_utc().astimezone(SERVER_TZ).date()
    stmt = select(func.coalesce(func.sum(models.DailySteps.steps), 0)).where(
        models.DailySteps.user_id == user_id, models.DailySteps.day < today
    )
    if since is not None:
        stmt = stmt.where(models.DailySteps.day > since.astimezone(SERVER_TZ).date())
    return int(db.execute(stmt).scalar_one())


def _delivered(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """The chests the miles in this letter dropped, in the order they landed,
    each named by the step of the ladder that dropped it and saying who lifted
    it.

    Named rather than counted, because "10K chest" is the thing that happened
    and "2" is only the size of it. Still nothing about what is inside: the
    inventory is where the lid comes off, and a letter that also opened them
    would be two places doing one job.

    Windowed on when the chest dropped, like every other number in the letter,
    rather than being every chest still closed. Two reasons, and the second is
    the serious one. A section headed "Chests found" inside a report about one
    stretch of time has to mean the chests found in it, or it disagrees with the
    miles printed beside it. And an unopened chest is a permanent fact about an
    account: reporting those would make the letter have news forever, so it
    would interrupt every single sign-in, for somebody who is simply saving
    their chests. Nothing is lost by leaving them out, because a chest never
    expires and the inventory counts them on their own squares.

    The giver is what the chest cannot say on its own. Every chest here was
    earned by the miles; a named one is a chest a friend's oil made better, and
    saying so is the thanks the giver never asked for.
    """
    where = [models.Chest.user_id == user_id, models.Chest.opened_at.is_(None)]
    if since is not None:
        where.append(models.Chest.dropped_at > since)
    rows = list(
        db.execute(select(models.Chest).where(*where).order_by(models.Chest.id)).scalars()
    )
    # One query for every giver on the letter. A lookup per chest would be a
    # query per chest, and the count is not bounded.
    gifts = {
        anointing_id: username
        for anointing_id, username in db.execute(
            select(models.Anointing.id, models.User.username)
            .join(models.User, models.User.id == models.Anointing.from_user_id)
            .where(
                models.Anointing.id.in_(
                    [row.from_anointing_id for row in rows if row.from_anointing_id]
                )
            )
        ).all()
    }
    out = []
    for row in rows:
        tier_id, tier_name = progress.tier_of(row)
        out.append(
            {
                "tier_id": tier_id,
                "tier": tier_name,
                # Null on the ordinary chest, where nobody's oil was on it.
                "gifted_by": gifts.get(row.from_anointing_id),
            }
        )
    return out


def _arrived(db: Session, user_id: int, since: dt.datetime | None) -> dict:
    """The workouts that landed since the last letter, newest first, and how
    many there really were.

    Filtered by the same arrival rule the miles are summed by, so the list and
    the numbers above it can never describe two different sets of workouts.

    Nothing is held back from the feed by being here. These were credited and
    published when they arrived; the letter is a second chance to say something
    about them, which is what the rows carry a title, a post and photos for.

    The true count travels beside a capped list, because a cut nobody is told
    about is the same as a lie. A deleted workout is in neither, which is also
    why a restored one is not re-reported: its arrival is behind the last
    acknowledgement, exactly where it was before.
    """
    where = [models.Workout.user_id == user_id, models.Workout.deleted_at.is_(None)]
    if since is not None:
        where.append(models.Workout.created_at > since)
    rows = list(
        db.execute(
            select(models.Workout)
            .where(*where)
            # By when the workout happened, not by when the row arrived. Which
            # is which only matters once a sync brings several at once, and
            # then it matters a lot: arrival order reads as shuffled, because
            # it puts this morning's run above yesterday evening's ride for a
            # reason nobody can see. By id within a timestamp, so a batch that
            # arrived together reads the same way twice.
            .order_by(models.Workout.start_ts.desc(), models.Workout.id.desc())
            .limit(MAX_RECAP_WORKOUTS)
        ).scalars()
    )
    total = db.execute(
        select(func.count()).select_from(models.Workout).where(*where)
    ).scalar_one()
    pictures = photos_for(db, rows)
    clips = videos_for(db, rows)
    return {
        "workouts": [
            {
                # workout_id rather than id, because the edit panel and the feed
                # already read that key and one of them was not going to change.
                "workout_id": row.id,
                "activity": row.activity,
                # The letter's rows wear the sport mark too, so they carry what
                # decides which one it is.
                "indoor": row.indoor,
                "start_ts": row.start_ts.isoformat(),
                "duration_s": row.duration_s,
                "distance_mi": round(row.distance_mi, 3),
                "title": row.title,
                "post": row.post,
                "photos": pictures.get(row.id, []),
                "videos": clips.get(row.id, []),
            }
            for row in rows
        ],
        "workouts_total": total,
    }


def _last_sync(db: Session, user_id: int) -> str | None:
    """When the phone last posted an export, or null for an account that has
    never sent one.

    Null is an ordinary answer rather than a fault: a player whose history was
    loaded straight into the database has no sync to report, and neither has
    anybody on their first day.

    UTC and ISO, like every other stamp in the letter. The instance timezone
    rides on /api/status and the client renders in it, because a browser pinned
    to UTC would read a quarter to two in the afternoon as nine in the evening.
    """
    stamp = db.execute(
        select(models.IngestLog.received_at)
        .where(models.IngestLog.user_id == user_id)
        .order_by(models.IngestLog.received_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return stamp.isoformat() if stamp is not None else None


def _plant_growth(db: Session, user_id: int) -> list[dict]:
    """The plants that put on a whole level or changed shape since the letter
    was last cleared, in the shape the plot is read in.

    Both ends of the climb travel, because "7 -> 8" needs the number it started
    from and a plant that came up from nothing is a different sentence from one
    that gained a level. Which sentence to write is the client's call: the level
    and the stage it started at are the facts, and what they mean is words.

    Read against the level and the growth written down when the letter was put
    down, rather than worked out by taking this letter's growth back off again.
    Subtraction could only ever see the workouts: nothing records which planting
    a water item was poured into, so a level that water alone paid for went
    unsaid. A number written at the time does not care where the growth came
    from, and survives whatever the next release grows a plant with.

    The stage needs the growth rather than the level because the first two of
    the three drawings are both level zero: a seed in the ground and a plant a
    third of the way up look different and count the same.

    A plant with nothing written down predates the column and says nothing.
    That is the quiet side of being wrong: reading a missing number as zero
    would congratulate somebody on every plant they have had for weeks. The two
    numbers are missing separately, so a plant can be silent about its level and
    still say it came up. The next acknowledgement writes both.

    Upward only on both, so a rebuild part way through emptying and replaying a
    plot reads as no news rather than as growth running backwards.
    """
    out = []
    for row in db.execute(
        select(models.Planting)
        .where(models.Planting.user_id == user_id)
        .order_by(models.Planting.id)
    ).scalars():
        level = grove.level_of(row)
        levelled = row.level_at_ack is not None and level > row.level_at_ack
        stage_before = (
            grove.stage_for(row.species, row.growth_at_ack)
            if row.growth_at_ack is not None
            else None
        )
        crossed = stage_before is not None and grove.stage(row) > stage_before
        if not levelled and not crossed:
            continue
        entry = grove.serialize_planting(row)
        # An unrecorded level reads as the one it stands at now, which is the
        # same silence saying nothing at all would be: no climb to announce.
        entry["level_before"] = row.level_at_ack if row.level_at_ack is not None else level
        entry["levels_gained"] = level - entry["level_before"]
        if stage_before is not None:
            entry["stage_before"] = stage_before
        out.append(entry)
    return out


def _received(db: Session, user_id: int, since: dt.datetime | None) -> dict:
    """What friends said since the last recap was cleared.

    Notes arrive whole, with the name of whoever wrote them, because a note is
    the point of the whole feature and a summary of one is worth nothing.
    Cheers are wordless, so they are counted per workout instead.
    """
    stmt = select(models.Encouragement).where(models.Encouragement.to_user_id == user_id)
    if since is not None:
        stmt = stmt.where(models.Encouragement.created_at > since)
    # Capped at MAX_RECAP, the same bargain the workout list makes: a handful of
    # chests costs nothing to be honest about, and a wall of notes does.
    rows = list(
        db.execute(stmt.order_by(models.Encouragement.created_at).limit(MAX_RECAP)).scalars()
    )
    senders = {
        sender_id: username
        for sender_id, username in db.execute(
            select(models.User.id, models.User.username).where(
                models.User.id.in_({row.from_user_id for row in rows})
            )
        ).all()
    }

    cheers: dict[int, int] = {}
    notes = []
    for row in rows:
        if row.kind == "cheer":
            cheers[row.workout_id] = cheers.get(row.workout_id, 0) + 1
            continue
        notes.append(
            {
                "workout_id": row.workout_id,
                "from_user_id": row.from_user_id,
                "username": senders.get(row.from_user_id, ""),
                "body": row.body or "",
                "created_at": row.created_at.isoformat(),
            }
        )
    return {
        "cheers": [
            {"workout_id": workout_id, "count": count}
            for workout_id, count in sorted(cheers.items())
        ],
        "cheer_count": sum(cheers.values()),
        "notes": notes,
    }


def _flourish(
    db: Session, user_id: int, row: models.UserProgress, since: dt.datetime | None
) -> dict:
    """The flourish stage, and whether it grew since the last recap.

    Worked out by taking back the renown earned since that moment rather than
    by storing the old stage, so nothing has to be written down to answer it.
    The renown itself never leaves this function.
    """
    stage = fellowship.flourish_stage(row.renown)
    before = fellowship.flourish_stage(row.renown - fellowship.renown_since(db, user_id, since))
    return {"flourish_stage": stage, "flourish_rose": stage > before}


def _fresh_medals(db: Session, user_id: int, since: dt.datetime | None) -> list[dict]:
    """Medals to tell the player about, newest last, every family.

    Selected by when the workout arrived rather than by when it happened, the
    same rule the miles above follow. A medal's own earned_at is the date of
    the run, which is what the profile should show and exactly the wrong thing
    to filter a recap by: a fortnight of history synced this morning would then
    hand over nothing. A weekly medal is filtered by the arrival of the workout
    that crossed the line, which is the same rule read one table across.
    """
    found: list[tuple[dt.datetime, int, dict]] = []
    order = {medal.id: index for index, medal in enumerate(medals.CATALOG)}

    def keep(row) -> None:
        if row.badge_id not in medals.BY_ID:
            return
        found.append(
            (
                row.earned_at,
                order[row.badge_id],
                {
                    "id": row.badge_id,
                    "name": medals.BY_ID[row.badge_id].name,
                    "earned_at": row.earned_at.isoformat(),
                },
            )
        )

    for table in (models.BadgeEarn, models.WeeklyBadgeEarn):
        stmt = (
            select(table)
            .join(models.Workout, models.Workout.id == table.workout_id)
            # A medal a deleted workout earned is already gone from the table,
            # taken out by the rebuild the deletion ran. Said here as well
            # because this is a join to the workouts, and the letter is the one
            # place a stale row would be announced as news.
            .where(table.user_id == user_id, models.Workout.deleted_at.is_(None))
        )
        if since is not None:
            stmt = stmt.where(models.Workout.created_at > since)
        for row in db.execute(stmt).scalars():
            keep(row)

    # A weekly row with no workout on it is from the round that let step credit
    # cross a line. Nothing writes another, and this reads the ones already
    # written rather than dropping them on the floor: the join above needs a
    # workout to date a row by, and these carry their own stamp.
    weekly = select(models.WeeklyBadgeEarn).where(
        models.WeeklyBadgeEarn.user_id == user_id,
        models.WeeklyBadgeEarn.workout_id.is_(None),
    )
    if since is not None:
        weekly = weekly.where(models.WeeklyBadgeEarn.earned_at > since)
    for row in db.execute(weekly).scalars():
        keep(row)

    # Oldest first, and the catalogue settles two earned on the same run, so the
    # letter reads the same way twice.
    return [entry for _stamp, _rank, entry in sorted(found, key=lambda item: item[:2])]


@router.post("/recap/ack", status_code=status.HTTP_204_NO_CONTENT)
def ack_recap(
    response: Response,
    db: Session = Depends(get_db),
    user: models.User = Depends(security.current_user),
) -> Response:
    """Mark the recap read. Chests are not touched: they wait to be opened.

    Where every plant stood is written down here too, because this is the one
    moment the answer is known for certain: whatever the letter just said, from
    now on it has been said. The next letter compares against these numbers
    instead of trying to work out where the growth came from.

    Both numbers are written in the same breath, so the level and the stage the
    next letter compares against belong to the same moment.
    """
    if throttle.recap_ack_limiter.hit(throttle.user_key(user)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, throttle.TOO_MANY_READS)
    row = progress.ensure_progress(db, user.id)
    row.last_ack_at = security.now_utc()
    for planting in db.execute(
        select(models.Planting).where(models.Planting.user_id == user.id)
    ).scalars():
        planting.level_at_ack = grove.level_of(planting)
        planting.growth_at_ack = planting.growth_mi
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
