import asyncio
import os
import tempfile
import time

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot
import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_second_pass_regression.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        assert await db.check_integrity()
        pending_id = await db.create_pending_war(101, "Альфа", 202, "Бета", "Артиллерийский удар по приграничному рубежу", int(time.time()), int(time.time()) + 3600)
        assert pending_id
        assert await db.get_pending_war(pending_id)
        await db.delete_country(101)
        assert await db.get_pending_war(pending_id) is None
        assert not bot.is_realistic_war_scenario("Велосипед без тормозов и единорог на МКС")
        assert bot.is_realistic_war_scenario("Механизированные войска занимают рубеж при артиллерийской поддержке")
        assert bot._compact_rank_value(-10) == "0"
        print("SECOND_PASS_REGRESSIONS_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
