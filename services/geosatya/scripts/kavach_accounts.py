"""Create and manage KAVACH staff accounts (supervisors and platform admins).

There is no public supervisor or admin sign-up: an authorized administrator
runs this on the server. Passwords are typed at a hidden prompt (never on the
command line, never printed) and stored only as scrypt hashes.

Run from services/geosatya with the server's Python:
  python scripts/kavach_accounts.py list
  python scripts/kavach_accounts.py create-supervisor --name "Priya Sharma" --login priya@city.example
  python scripts/kavach_accounts.py create-admin      --name "Platform Admin" --login admin@kavach.example
  python scripts/kavach_accounts.py set-login --user SUP-DEMO-03 --login priya@city.example   (give an existing user a sign-in)
  python scripts/kavach_accounts.py deactivate --user SUP-1A2B3C4D

A database backup is written to data/backups/ before any change (SQLite).
Supervisors also need SUPERVISOR_ACCESS_CODE on the server, platform admins ADMIN_ACCESS_CODE.
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from geosatya.config import Settings  # noqa: E402
from geosatya.db import init_schema, make_engine, make_session_factory  # noqa: E402
from geosatya.models import UserRow  # noqa: E402
from geosatya.security import hash_password, normalise_login, password_problem  # noqa: E402
from geosatya.services.common import new_id  # noqa: E402
from geosatya.timeutil import utcnow  # noqa: E402


def backup(settings: Settings) -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    db = Path(settings.database_url.split("///", 1)[-1])
    if not db.is_file():
        return
    target = db.parent / "backups" / f"{db.stem}-before-accounts-{datetime.now():%Y%m%d-%H%M%S}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    print(f"Backup: {target}")


def ask_password() -> str:
    for _ in range(3):
        first = getpass.getpass("New password (hidden): ")
        problem = password_problem(first)
        if problem:
            print(problem)
            continue
        if getpass.getpass("Repeat the password: ") != first:
            print("The two passwords are different.")
            continue
        return first
    sys.exit("No password set.")


def login_or_exit(session, raw: str, user_id: str | None = None) -> str:
    login = normalise_login(raw)
    if login is None:
        sys.exit("Use an email address or a 10 to 15 digit mobile number.")
    other = session.scalar(select(UserRow).where(UserRow.login_id == login))
    if other is not None and other.user_id != user_id:
        sys.exit(f"{login} is already used by {other.user_id}.")
    return login


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list staff accounts that can sign in")
    for name in ("create-supervisor", "create-admin"):
        p = sub.add_parser(name)
        p.add_argument("--name", required=True)
        p.add_argument("--login", required=True, help="email or mobile number")
        if name == "create-supervisor":
            p.add_argument("--workspace", default=None, help="workspace id (empty = the open civic workspace)")
    p = sub.add_parser("set-login", help="give an existing user (for example a seeded demo supervisor) a login and password")
    p.add_argument("--user", required=True)
    p.add_argument("--login", required=True)
    p = sub.add_parser("deactivate")
    p.add_argument("--user", required=True)
    args = parser.parse_args()

    settings = Settings()
    engine = make_engine(settings.database_url)
    if args.cmd != "list":
        backup(settings)
    init_schema(engine)  # additive only: adds the sign-in columns to an older database
    with make_session_factory(engine)() as session:
        if args.cmd == "list":
            rows = session.scalars(select(UserRow).where(UserRow.role == "SUPERVISOR").order_by(UserRow.user_id)).all()
            for u in rows:
                state = "can sign in" if u.password_hash and u.is_active is not False else (
                    "deactivated" if u.is_active is False else "no password")
                print(f"{u.user_id:<16} {u.platform_role or 'SUPERVISOR':<16} {u.workspace_id or '(civic)':<14} "
                      f"{u.login_id or '-':<32} {state}")
            return
        if args.cmd in ("create-supervisor", "create-admin"):
            login = login_or_exit(session, args.login)
            admin = args.cmd == "create-admin"
            user = UserRow(user_id=new_id("PA" if admin else "SUP", 4), display_name=args.name.strip()[:80], role="SUPERVISOR",
                           is_demo=False, platform_role="PLATFORM_ADMIN" if admin else None,
                           workspace_id=None if admin else args.workspace, login_id=login, password_hash=hash_password(ask_password()),
                           auth_epoch=0, registered_at=utcnow())
            session.add(user)
        elif args.cmd == "set-login":
            user = session.get(UserRow, args.user)
            if user is None:
                sys.exit(f"No user {args.user}.")
            user.login_id = login_or_exit(session, args.login, user.user_id)
            user.password_hash = hash_password(ask_password())
            user.auth_epoch = (user.auth_epoch or 0) + 1  # older tokens stop working
        else:
            user = session.get(UserRow, args.user)
            if user is None:
                sys.exit(f"No user {args.user}.")
            user.is_active = False
            user.auth_epoch = (user.auth_epoch or 0) + 1
        session.commit()
        print(f"Done: {user.user_id} ({user.display_name}, {user.platform_role or user.role}).")


if __name__ == "__main__":
    main()
