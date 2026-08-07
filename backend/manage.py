#!/usr/bin/env python3
"""Command line administration, run inside the backend container.

    python manage.py create-admin <username>
    python manage.py create-invite [--expires-days N]
    python manage.py verify-email <username>
    python manage.py recompute-progress <username>
    python manage.py backfill-badges <username>
    python manage.py backfill-routes <username>
    python manage.py seed-demo

The first account has to be made here: registration needs either an invite or
an open instance, and both of those need an admin to exist first.
"""

import argparse
import datetime as dt
import getpass
import secrets
import sys

from sqlalchemy import select

from app import activity as activity_rules
from app import grove, medals, models, progress, routemaps, security
from app.config import check_deploy_config
from app.db import SessionLocal
from app.routers.auth import create_invite


def _session():
    check_deploy_config()
    if SessionLocal is None:
        sys.exit("DATABASE_URL is not set.")
    return SessionLocal()


def _prompt_password() -> str:
    """Read a password twice without echoing it, and check the two match."""
    first = getpass.getpass("Password: ")
    if len(first) < security.MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {security.MIN_PASSWORD_LENGTH} characters.")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("The two passwords did not match.")
    return first


def _prompt_email() -> str | None:
    """Read an optional address, and refuse an obviously wrong one.

    Optional because this account is being made by whoever has a shell on the
    server, which is a stronger claim than any mail round trip, and because an
    instance with no mail server configured has nothing to send to it anyway.
    """
    raw = input("Email (optional, press enter to skip): ").strip().lower()
    if not raw:
        return None
    if len(raw) > security.MAX_EMAIL_LENGTH or not security.EMAIL_PATTERN.match(raw):
        sys.exit("That does not look like an email address.")
    return raw


def cmd_create_admin(args: argparse.Namespace) -> None:
    username = args.username.strip().lower()
    if not security.USERNAME_PATTERN.match(username):
        sys.exit(
            "Username must be 3 to 32 characters, using lower-case letters, "
            "digits, dot, dash, or underscore."
        )
    db = _session()
    try:
        if db.execute(
            select(models.User.id).where(models.User.username == username)
        ).scalar_one_or_none():
            sys.exit(f"There is already an account called {username}.")
        email = _prompt_email()
        if email is not None and db.execute(
            select(models.User.id).where(models.User.email == email)
        ).scalar_one_or_none():
            sys.exit("Another account already uses that address.")
        password = _prompt_password()
        user = models.User(
            username=username,
            password_hash=security.hash_password(password),
            email=email,
            # Verified on the spot. There is no link to click yet, and an
            # admin who cannot sign in cannot mint the first invite either.
            email_verified=True,
            is_admin=True,
            units="imperial",
            created_at=security.now_utc(),
        )
        db.add(user)
        db.commit()
        print(f"Created admin account {username}.")
    finally:
        db.close()


def cmd_verify_email(args: argparse.Namespace) -> None:
    """Mark an account verified by hand.

    The way through for an install with no mail server: the admin reads the
    link out of the backend log, or skips it and does this instead.
    """
    username = args.username.strip().lower()
    db = _session()
    try:
        user = db.execute(
            select(models.User).where(models.User.username == username)
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"There is no account called {username}.")
        user.email_verified = True
        db.commit()
        print(f"{username} can now sign in.")
    finally:
        db.close()


def cmd_recompute_progress(args: argparse.Namespace) -> None:
    """Rebuild one account's experience, level, chests, and growth from its workouts.

    The safety hatch for the day a constant changes, and the way to replay a
    history the migration credited in one lump without dropping its chests.
    Everything derived goes and is rebuilt: the experience, the level, the
    chest ladder and the chests on it, the growth in the plot, and every medal,
    which come back with the dates of the workouts and weeks that earned them.

    Nothing anybody chose is rebuilt either: the satchel, what is planted, and
    every anointing are actions rather than consequences, and chests that came
    from somebody else's oil stay where they are.

    The workouts themselves are never touched, so nothing anybody actually did
    is at risk here. Chests already opened do come back closed, though, and
    opening them again yields items all over again: take a dump first, and do
    not run this casually on an account with a full satchel.
    """
    username = args.username.strip().lower()
    db = _session()
    try:
        user = db.execute(
            select(models.User).where(models.User.username == username)
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"There is no account called {username}.")

        row = progress.recompute(db, user.id)
        chests = (
            db.query(models.Chest).filter(models.Chest.user_id == user.id).count()
        )
        print(f"Rebuilt {username} from their workout history.")
        print(f"  level: {row.level} ({row.xp:.1f} XP)")
        print(f"  chests: {chests}")
        _print_medal_counts(db, user.id)
    finally:
        db.close()


def _print_medal_counts(db, user_id: int) -> None:
    """What an account holds, per table, in the two lines every command ends on."""
    print(
        "  medals on workouts: "
        + str(db.query(models.BadgeEarn).filter(models.BadgeEarn.user_id == user_id).count())
    )
    print(
        "  medals on weeks: "
        + str(
            db.query(models.WeeklyBadgeEarn)
            .filter(models.WeeklyBadgeEarn.user_id == user_id)
            .count()
        )
    )


def cmd_backfill_badges(args: argparse.Namespace) -> None:
    """Award the medals one account's credited history has already earned.

    The gentle sibling of recompute-progress: it replays only the medal
    awards, so chests, the plot, and experience are untouched. This is the
    right tool after a migration adds a medal family to a database with real
    history in it. Safe to run twice: awarding is idempotent per workout, and a
    week is walked from its workouts rather than added to, so a second run
    writes the same rows again.

    It may correct a weekly row that a partial history left holding a lower
    medal than the week actually reached; that is the same answer a full replay
    would produce. Nothing is ever deleted here.
    """
    username = args.username.strip().lower()
    db = _session()
    try:
        user = db.execute(
            select(models.User).where(models.User.username == username)
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"There is no account called {username}.")

        credited = db.execute(
            select(models.Workout)
            .join(
                models.ProcessedWorkout,
                models.ProcessedWorkout.workout_id == models.Workout.id,
            )
            .where(models.Workout.user_id == user.id)
            .order_by(models.Workout.start_ts, models.Workout.id)
        ).scalars().all()
        awarded = 0
        weeks = set()
        for workout in credited:
            awarded += len(medals.award_workout_medals(db, user.id, workout))
            weeks.add(activity_rules.week_start(workout.start_ts))
        for monday in sorted(weeks):
            medals.update_week(db, user.id, monday)
        db.commit()
        print(f"Replayed {len(credited)} credited workouts for {username}.")
        print(f"  medals newly awarded on workouts: {awarded}")
        print(f"  weeks brought up to date: {len(weeks)}")
        _print_medal_counts(db, user.id)
    finally:
        db.close()


def cmd_backfill_routes(args: argparse.Namespace) -> None:
    """Draw the route lines one account's stored syncs already carry.

    Every payload the phone ever posted is kept, traces included, so the maps
    for a history that predates this feature are sitting in the ingest log
    waiting to be read. This replays them: a stored payload is parsed the way
    the sync endpoint parses it, each entry is matched to its workout by the
    dedupe key, and a line is written for the workouts that have none.

    Only routes are written. Workouts, progress, medals, and the plot are all
    untouched, and a workout that already has a line keeps it, so running this
    twice is the same as running it once.
    """
    username = args.username.strip().lower()
    db = _session()
    try:
        user = db.execute(
            select(models.User).where(models.User.username == username)
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"There is no account called {username}.")

        # The workouts still missing a line, keyed the way the payload names
        # them. Aware timestamps compare and hash by instant, so a payload
        # written in local time still finds its row.
        missing = {
            (workout.start_ts, workout.duration_s): workout.id
            for workout in db.execute(
                select(models.Workout)
                .outerjoin(
                    models.WorkoutRoute,
                    models.WorkoutRoute.workout_id == models.Workout.id,
                )
                .where(
                    models.Workout.user_id == user.id,
                    models.WorkoutRoute.workout_id.is_(None),
                )
            ).scalars()
        }

        payloads = db.execute(
            select(models.IngestLog.payload)
            .where(models.IngestLog.user_id == user.id)
            .order_by(models.IngestLog.id)
        ).scalars().all()

        written = 0
        for payload in payloads:
            parsed, _ = activity_rules.parse_payload(payload)
            for item in parsed:
                if item.route is None:
                    continue
                workout_id = missing.get((item.start_ts, item.duration_s))
                if workout_id is None:
                    continue
                if routemaps.store_route(db, workout_id, item.route):
                    # Dropped from the map so a later payload carrying the same
                    # workout does not try to write a second line for it.
                    del missing[(item.start_ts, item.duration_s)]
                    written += 1
        db.commit()

        total = (
            db.query(models.WorkoutRoute)
            .join(models.Workout, models.Workout.id == models.WorkoutRoute.workout_id)
            .filter(models.Workout.user_id == user.id)
            .count()
        )
        print(f"Replayed {len(payloads)} stored syncs for {username}.")
        print(f"  routes newly written: {written}")
        print(f"  workouts still without one: {len(missing)}")
        print(f"  routes held now: {total}")
    finally:
        db.close()


def cmd_create_invite(args: argparse.Namespace) -> None:
    db = _session()
    try:
        # Invites record who issued them, so one has to exist first. Pointing at
        # create-admin is more useful than a foreign key error.
        admin = db.execute(
            select(models.User).where(models.User.is_admin.is_(True)).order_by(models.User.id)
        ).scalars().first()
        if admin is None:
            sys.exit("No admin account yet. Run: python manage.py create-admin <username>")
        invite = create_invite(db, admin.id, args.expires_days)
        db.commit()
        print(f"Invite code: {invite.code}")
        print(f"Valid until: {invite.expires_at.isoformat()} (one use)")
    finally:
        db.close()


# A week of the demo account's movement, keyed by weekday. Sunday is missing on
# purpose: rest is part of the rhythm this game is built around, and demo data
# that shows seven active days would teach the wrong thing about it.
# (activity, miles, duration in seconds, active kcal, average heart rate)
_DEMO_WEEK = {
    0: ("walk", 2.8, 34 * 60, 205.0, 108.0),
    1: ("run", 4.0, 36 * 60, 430.0, 152.0),
    2: ("cycle", 12.4, 48 * 60, 485.0, 131.0),
    3: ("walk", 3.4, 41 * 60, 250.0, 110.0),
    4: ("swim", 0.75, 32 * 60, 300.0, 128.0),
    5: ("run", 6.2, 55 * 60, 655.0, 158.0),
}

# A little week-to-week variation so the Almanac's weekly totals are not six
# identical rows. Real training is not flat, and neither is a good screenshot.
_WEEK_SCALE = (0.82, 0.95, 1.0, 1.12, 0.9, 1.05)

_DEMO_WEEKS = len(_WEEK_SCALE)

# How many of the seeded chests are left closed. Enough that the recap has
# something in it and the profile shows a waiting count, few enough that the
# first screen is not a wall of them.
_DEMO_PENDING_CHESTS = 5


def _add_workout(db, user_id, activity, start_ts, duration_s, distance_mi, kcal, hr, source):
    """Insert one seeded workout, flagged by the same rules the API uses.

    Calling the real helpers rather than hard-coding a flag keeps the demo
    honest: if the thresholds change, the seeded data changes with them.
    """
    flags = {}
    if activity_rules.impossible_pace(activity, duration_s, distance_mi):
        flags["impossible_pace"] = True
    workout = models.Workout(
        user_id=user_id,
        activity=activity,
        start_ts=start_ts,
        duration_s=duration_s,
        distance_mi=round(distance_mi, 2),
        active_kcal=round(kcal, 1),
        avg_hr=hr,
        source=source,
        flags=flags,
        created_at=security.now_utc(),
    )
    db.add(workout)
    db.flush()
    if activity_rules.over_daily_cap(db, user_id, activity, start_ts):
        workout.flags = {**flags, "daily_cap": True}
    return workout


def cmd_seed_demo(args: argparse.Namespace) -> None:
    db = _session()
    try:
        # Refusing outright rather than skipping the seed. On a database with
        # real accounts, adding a fictional user and six weeks of invented
        # workouts is not a helpful default, and there is no undo.
        if db.execute(select(models.User.id).limit(1)).scalar_one_or_none():
            sys.exit(
                "This database already has accounts. seed-demo only runs on an empty one, "
                "so it can never mix invented workouts into real history."
            )

        password = secrets.token_urlsafe(12)
        today = dt.datetime.now(activity_rules.SERVER_TZ).date()
        first_monday = today - dt.timedelta(days=today.weekday(), weeks=_DEMO_WEEKS - 1)

        user = models.User(
            username="demo",
            password_hash=security.hash_password(password),
            # No address, and verified anyway: the point of the demo account is
            # that the password printed below signs you straight in.
            email_verified=True,
            is_admin=False,
            units="imperial",
            # Dated to before the seeded history, so the account is as old
            # as the workouts under it.
            created_at=dt.datetime.combine(
                first_monday - dt.timedelta(days=1), dt.time(9, 0), tzinfo=activity_rules.SERVER_TZ
            ),
        )
        db.add(user)
        db.flush()

        for week in range(_DEMO_WEEKS):
            scale = _WEEK_SCALE[week]
            for weekday, (activity, miles, duration, kcal, hr) in _DEMO_WEEK.items():
                day = first_monday + dt.timedelta(weeks=week, days=weekday)
                if day > today:
                    continue
                start = dt.datetime.combine(
                    day, dt.time(6, 12), tzinfo=activity_rules.SERVER_TZ
                ) + dt.timedelta(minutes=weekday * 7)
                _add_workout(
                    db,
                    user.id,
                    activity,
                    start,
                    round(duration * scale),
                    miles * scale,
                    kcal * scale,
                    hr,
                    "sync",
                )

        # One entry that came in by hand rather than from a watch, so the
        # Almanac's manual marker has something to show.
        manual_day = today - dt.timedelta(days=2)
        _add_workout(
            db,
            user.id,
            "walk",
            dt.datetime.combine(manual_day, dt.time(19, 40), tzinfo=activity_rules.SERVER_TZ),
            52 * 60,
            2.6,
            190.0,
            None,
            "manual",
        )

        # One workout with numbers a body did not produce, so the flag has
        # something to show too. Four miles in eleven minutes is a mile every
        # two and three quarter minutes.
        flagged_day = today - dt.timedelta(days=4)
        _add_workout(
            db,
            user.id,
            "run",
            dt.datetime.combine(flagged_day, dt.time(12, 5), tzinfo=activity_rules.SERVER_TZ),
            11 * 60,
            4.0,
            410.0,
            149.0,
            "sync",
        )

        db.commit()
        # The whole seeded history goes through the real pipeline, so the demo
        # account's level, badges, and chests are all things the invented
        # workouts actually earned rather than numbers typed in here.
        row = progress.process_user(db, user.id)

        # Six weeks of movement is a lot of chests, and a profile behind a wall
        # of several dozen unopened ones shows nothing of the satchel or the
        # plot. Most are opened here, and the last few are left waiting so the
        # recap has something to hand over on the first sign in.
        pending = (
            db.query(models.Chest)
            .filter(models.Chest.user_id == user.id, models.Chest.opened_at.is_(None))
            .order_by(models.Chest.id)
            .all()
        )
        for chest in pending[:-_DEMO_PENDING_CHESTS]:
            progress.open_chest(db, user.id, chest)

        # Every seed found goes straight into the ground, dated to the start of
        # the invented history, and that history is then replayed over the plot.
        # A demo account with an empty plot would show none of this.
        credited = (
            db.query(models.Workout)
            .filter(models.Workout.user_id == user.id)
            .order_by(models.Workout.start_ts)
            .all()
        )
        planted_at = credited[0].start_ts
        seeds = (
            db.query(models.SatchelItem)
            .filter(
                models.SatchelItem.user_id == user.id,
                models.SatchelItem.kind == "seed",
                models.SatchelItem.used_at.is_(None),
            )
            .all()
        )
        for item in seeds:
            grove.plant(db, user.id, item, planted_at)
        for workout in credited:
            grove.grow(
                db,
                user.id,
                activity_rules.converted_miles(workout.activity, workout.distance_mi),
                workout.activity,
                workout.created_at or workout.start_ts,
            )
        db.commit()

        print("Seeded the demo account.")
        print("  username: demo")
        print(f"  password: {password}")
        print(f"  level: {row.level} ({row.xp:.1f} XP)")
        _print_medal_counts(db, user.id)
        print(f"  chests waiting: {min(len(pending), _DEMO_PENDING_CHESTS)}")
        print(f"  planted: {len(seeds)}")
        print("This password is shown once. It is a fictional account; delete it before")
        print("the instance is used for anything real.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    admin = sub.add_parser("create-admin", help="create the first account, with admin rights")
    admin.add_argument("username")
    admin.set_defaults(func=cmd_create_admin)

    invite = sub.add_parser("create-invite", help="mint a one-time registration code")
    invite.add_argument("--expires-days", type=int, default=14)
    invite.set_defaults(func=cmd_create_invite)

    verify = sub.add_parser("verify-email", help="mark an account verified without a link")
    verify.add_argument("username")
    verify.set_defaults(func=cmd_verify_email)

    recompute = sub.add_parser(
        "recompute-progress", help="rebuild one account's progress from its workouts"
    )
    recompute.add_argument("username")
    recompute.set_defaults(func=cmd_recompute_progress)

    backfill = sub.add_parser(
        "backfill-badges", help="award the medals an account's history already earned"
    )
    backfill.add_argument("username")
    backfill.set_defaults(func=cmd_backfill_badges)

    routes = sub.add_parser(
        "backfill-routes", help="draw the route lines an account's stored syncs already carry"
    )
    routes.add_argument("username")
    routes.set_defaults(func=cmd_backfill_routes)

    demo = sub.add_parser("seed-demo", help="fill an empty database with a fictional account")
    demo.set_defaults(func=cmd_seed_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
