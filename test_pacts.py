import asyncio
import os
import tempfile
import time

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_pacts.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        await db.create_country(1, 1, "Альфа", "medium", {})
        await db.create_country(2, 2, "Бета", "medium", {})
        await db.create_country(3, 3, "Гамма", "medium", {})
        assert await db.create_diplomatic_pact(1, 1, "trade", "сам с собой", 3) is None
        assert await db.create_diplomatic_pact(1, 2, "unknown", "неверный тип", 3) is None
        now = int(time.time())
        pact_id = await db.create_diplomatic_pact(1, 2, "non_aggression", "Не нападать друг на друга и сохранять торговый коридор.", 3, timestamp=now)
        assert pact_id
        assert await db.create_diplomatic_pact(1, 2, "defense", "второй договор", 3, timestamp=now + 1) is None
        assert await db.resolve_diplomatic_pact(pact_id, 1, True, timestamp=now + 2) is None
        accepted = await db.resolve_diplomatic_pact(pact_id, 2, True, timestamp=now + 2)
        assert accepted and accepted["status"] == "active"
        listed = await db.list_diplomatic_pacts(1)
        assert listed[0]["status"] == "active"
        expired_id = await db.create_diplomatic_pact(1, 3, "trade", "Сотрудничество на короткий срок.", 1, timestamp=now + 10)
        assert expired_id is not None
        expired = await db.list_diplomatic_pacts(1)
        assert any(item["id"] == expired_id and item["status"] == "pending" for item in expired)
        assert await db.resolve_diplomatic_pact(expired_id, 3, True, timestamp=now + 10 + 86401) is None
        print("DIPLOMATIC_PACTS_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
