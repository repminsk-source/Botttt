import asyncio
import os
import tempfile

import db


async def main():
    old_path = db.DB_PATH
    fd, path = tempfile.mkstemp(prefix="gavan_alliance_invites_", suffix=".sqlite3")
    os.close(fd)
    db.DB_PATH = path
    try:
        await db.init_db()
        assert await db.create_country(2001, 1, "Альфа", "medium", {"iso_code": "AAA", "real_population": 1_000_000})
        assert await db.create_country(2002, 2, "Бета", "medium", {"iso_code": "BBB", "real_population": 1_000_000})
        assert await db.create_country(2003, 3, "Гамма", "medium", {"iso_code": "CCC", "real_population": 1_000_000})
        assert await db.create_alliance("TEST", "Тестовый альянс")
        alliance = await db.get_alliance_by_tag("TEST")
        await db.join_alliance(2001, alliance["id"])
        assert await db.create_alliance_invite(9999, 2002, alliance["id"]) is None
        invite_id = await db.create_alliance_invite(2001, 2002, alliance["id"])
        assert invite_id
        assert await db.create_alliance_invite(2001, 2002, alliance["id"]) is None
        invites = await db.list_alliance_invites(2002)
        assert len(invites) == 1 and invites[0]["id"] == invite_id
        accepted = await db.resolve_alliance_invite(invite_id, 2002, True, 100)
        assert accepted and accepted["accepted"] is True
        assert (await db.get_user_alliance(2002))["id"] == alliance["id"]
        assert await db.create_alliance_invite(2001, 2002, alliance["id"]) is None

        rejected_id = await db.create_alliance_invite(2001, 2003, alliance["id"])
        assert rejected_id
        rejected = await db.resolve_alliance_invite(rejected_id, 2003, False, 101)
        assert rejected and rejected["accepted"] is False
        assert not await db.list_alliance_invites(2003)
        print("ALLIANCE_INVITES_OK")
    finally:
        db.DB_PATH = old_path
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
