"""User management from the command line: `python -m seed_api.users <command>`.

Passwords are read from a prompt (or stdin when piped), never from arguments,
so they stay out of shell history and process listings.
"""

import argparse
import asyncio
import getpass
import sys

from .auth import ROLES, AuthStore, UserError
from .config import get_settings
from .flow.db import make_pool, migrate


def _read_password() -> str:
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise UserError("The passwords do not match.")
    return first


async def _run(args: argparse.Namespace) -> str:
    settings = get_settings()
    if settings.database_url is None:
        raise UserError("SEED_DATABASE_URL is not set.")
    pool = make_pool(settings.database_url.get_secret_value(), max_size=2)
    await pool.open(wait=True, timeout=30)
    try:
        await migrate(pool)
        store = AuthStore(pool)
        if args.command == "add":
            user = await store.create_user(args.username, _read_password(), args.role)
            await store.audit("user_added", actor="cli", target=user.username)
            return f"Added {user.username} ({user.role})."
        if args.command == "set-password":
            await store.set_password(args.username, _read_password())
            await store.audit("password_changed", actor="cli", target=args.username)
            return f"Changed the password for {args.username}; their sessions were signed out."
        if args.command in ("disable", "enable"):
            await store.set_disabled(args.username, args.command == "disable")
            await store.audit(f"user_{args.command}d", actor="cli", target=args.username)
            return f"{args.command.capitalize()}d {args.username}."
        if args.command == "revoke-sessions":
            n = await store.revoke_user_sessions(args.username)
            await store.audit("sessions_revoked", actor="cli", target=args.username)
            return f"Signed {args.username} out of {n} session(s)."
        rows = await store.list_users()
        return (
            "\n".join(
                f"{u.username}\t{u.role}\t{'disabled' if u.disabled else 'active'}" for u in rows
            )
            or "No users."
        )
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m seed_api.users")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="add a user (password from prompt or stdin)")
    add.add_argument("username")
    add.add_argument("--role", choices=ROLES, default="admin")
    for name, text in (
        ("set-password", "change a password and sign the user out everywhere"),
        ("disable", "block sign-in; existing sessions stop working at once"),
        ("enable", "allow sign-in again"),
        ("revoke-sessions", "sign the user out everywhere"),
    ):
        sub.add_parser(name, help=text).add_argument("username")
    sub.add_parser("list", help="list users")
    args = parser.parse_args(argv)
    try:
        print(asyncio.run(_run(args)))
    except UserError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
