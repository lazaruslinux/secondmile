#!/usr/bin/env python3
"""Command line administration, run inside the backend container.

    python manage.py create-admin <username>
    python manage.py create-invite [--expires-days N]
    python manage.py seed-demo

There is no open registration, so the first account has to be made here.
"""

import argparse
import datetime as dt
import getpass
import secrets
import sys

from sqlalchemy import select

from app import activity as activity_rules
from app import models, security
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
        password = _prompt_password()
        db.add(
            models.User(
                username=username,
                password_hash=security.hash_password(password),
                is_admin=True,
                units="imperial",
                created_at=security.now_utc(),
            )
        )
        db.commit()
        print(f"Created admin account {username}.")
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
        user = models.User(
            username="demo",
            password_hash=security.hash_password(password),
            is_admin=False,
            units="imperial",
            created_at=security.now_utc(),
        )
        db.add(user)
        db.flush()

        today = dt.datetime.now(activity_rules.SERVER_TZ).date()
        first_monday = today - dt.timedelta(days=today.weekday(), weeks=_DEMO_WEEKS - 1)
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
        print("Seeded the demo account.")
        print("  username: demo")
        print(f"  password: {password}")
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

    demo = sub.add_parser("seed-demo", help="fill an empty database with a fictional account")
    demo.set_defaults(func=cmd_seed_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
