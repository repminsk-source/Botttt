import asyncio
import os
import tempfile
import time

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot
import db


async def main():
    assert not bot.is_realistic_war_scenario("Десант из восьми космонавтов и трёх единорогов")
    assert bot.is_realistic_war_scenario("Артиллерийский удар по позициям противника и оборона рубежа")
    path = os.path.join(tempfile.gettempdir(), "gavan_pending_war_test.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        war_id = await db.create_pending_war(1, "Альфа", 2, "Бета", "Артиллерийский удар по рубежу и наступление", int(time.time()), int(time.time()) + 3600)
        assert war_id
        assert not await db.claim_pending_war(war_id, 1, "чужой ответ", int(time.time()))
        assert await db.claim_pending_war(war_id, 2, "Оборона рубежа войсками и резервами", int(time.time()))
        assert not await db.claim_pending_war(war_id, 2, "Повторная оборона позиций войсками", int(time.time()))
        await db.reset_pending_war(war_id)
        assert (await db.get_pending_war(war_id))["status"] == "pending"
        print("WAR_PENDING_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
