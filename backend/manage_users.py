"""Manage sign-in accounts in the configured database (DATABASE_URL). Run from backend/:

    python manage_users.py add <username>        # prompts for the password
    python manage_users.py passwd <username>
    python manage_users.py delete <username>
    python manage_users.py list
    python manage_users.py migrate               # bring an existing users table up to the current rules
"""
import argparse
import getpass
import sys

from app.config import get_settings
from models.db import Database
from services.user_migration import MigrationBlocked, migrate_users
from services.users import InvalidUserInputError, UserExistsError, UserStore


def _ask_password() -> str:
    pw = getpass.getpass("Password: ")
    if not pw or pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords are empty or don't match.")
    return pw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["add", "passwd", "delete", "list", "migrate"])
    parser.add_argument("username", nargs="?")
    args = parser.parse_args()
    if args.command not in ("list", "migrate") and not args.username:
        parser.error("username is required")

    db = Database(get_settings().database_url)
    users = UserStore(db)
    try:
        if args.command == "migrate":
            try:
                report = migrate_users(db)
            except MigrationBlocked as e:
                sys.exit(f"Migration stopped, nothing changed: {e}")
            print(f"Hashed plain-text passwords: {report.hashed or 'none'}")
            print(f"Normalized usernames: {report.renamed or 'none'}")
            print(f"Constraints added: {report.constraints_added or 'none (already present)'}")
            for note in report.notes:
                print(note)
        elif args.command == "list":
            print("\n".join(users.list_usernames()) or "(no users)")
        elif args.command == "add":
            try:
                users.signup(args.username, _ask_password(), min_length=get_settings().password_min_length)
            except InvalidUserInputError as e:
                sys.exit(str(e))
            except UserExistsError:
                sys.exit(f"User {args.username!r} already exists.")
            print(f"Created {args.username!r}.")
        elif args.command == "passwd":
            if not users.set_password(args.username, _ask_password()):
                sys.exit(f"No user {args.username!r}.")
            print(f"Password updated for {args.username!r}.")
        elif not users.delete(args.username):
            sys.exit(f"No user {args.username!r}.")
        else:
            print(f"Deleted {args.username!r}.")
    finally:
        db.dispose()


if __name__ == "__main__":
    main()
