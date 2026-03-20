"""
Reset the admin account password.

Usage:
    uv run reset-admin                  # resets to 'changeme'
    uv run reset-admin --password mypw  # resets to a custom password
    uv run reset-admin --username jane  # reset a different member
"""
import argparse
import asyncio
import sys

import bcrypt


async def _reset(username: str, password: str) -> None:
    import aiosqlite

    from app import create_app

    app = create_app()
    db_path = app.config["DATABASE_PATH"]

    new_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id FROM family_member WHERE username = ?", (username,)
        )
        row = await cur.fetchone()
        if row is None:
            print(f"Error: no member with username '{username}' found.", file=sys.stderr)
            sys.exit(1)

        await db.execute(
            "UPDATE family_member SET password_hash = ? WHERE username = ?",
            (new_hash, username),
        )
        await db.commit()

    print(f"Password for '{username}' reset successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a Tasklings member password.")
    parser.add_argument(
        "--username", default="admin", help="Username to reset (default: admin)"
    )
    parser.add_argument(
        "--password", default="changeme", help="New password (default: changeme)"
    )
    args = parser.parse_args()
    asyncio.run(_reset(args.username, args.password))


if __name__ == "__main__":
    main()
