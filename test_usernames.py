import asyncio
import os
import tempfile

import db


async def main():
    old_path = db.DB_PATH
    fd, path = tempfile.mkstemp(prefix="gavan_usernames_", suffix=".sqlite3")
    os.close(fd)
    db.DB_PATH = path
    try:
        await db.init_db()
        assert await db.create_country(1001, 1, "Альфа", "medium", {"iso_code": "AAA"}, "Alpha_Player")
        assert await db.create_country(1002, 2, "Бета", "medium", {"iso_code": "BBB"}, "Beta_Player")
        alpha = await db.get_country_by_username("@alpha_player")
        assert alpha and alpha["user_id"] == 1001 and alpha["username"] == "alpha_player"
        assert await db.update_country_username(1001, "Alpha_New")
        assert await db.get_country_by_username("alpha_player") is None
        assert (await db.get_country_by_username("@ALPHA_NEW"))["user_id"] == 1001
        assert not await db.update_country_username(1002, "alpha_new")
        beta = await db.get_country(1002)
        assert beta["username"] == "beta_player"
        assert await db.transfer_country(1001, 1003)
        transferred = await db.get_country(1003)
        assert transferred and transferred["username"] is None
        assert await db.get_country_by_username("alpha_new") is None
        print("USERNAME_RESOLUTION_OK")
    finally:
        db.DB_PATH = old_path
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
