from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

async def change_role(email: str, role: str) -> None:
    from app.account_database import (
        get_user_by_email,
        set_user_role,
        write_admin_audit,
    )
    from app.services.accounts import normalize_email

    user = await get_user_by_email(normalize_email(email))
    if not user:
        raise RuntimeError("account not found")
    user_id = str(user["_id"])
    if not await set_user_role(user_id, role):
        raise RuntimeError("account role was not changed")
    await write_admin_audit(
        "management-cli",
        f"role_{role}",
        "user",
        user_id,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grant or revoke VietLex administrator access."
    )
    parser.add_argument("action", choices=("grant", "revoke"))
    parser.add_argument("email")
    args = parser.parse_args()
    asyncio.run(change_role(args.email, "admin" if args.action == "grant" else "user"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
