import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_statements.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        assert await db.create_country_statement(1, "Альфа", "слишком коротко") is None
        first = await db.create_country_statement(1, "Альфа", "Правительство объявляет долгосрочную программу модернизации инфраструктуры и укрепления дипломатических связей.", 2020)
        second = await db.create_country_statement(2, "Бета", "Страна подтверждает готовность к переговорам, торговому сотрудничеству и взаимным гарантиям безопасности.", 2020)
        assert first and second and second > first
        feed = await db.get_recent_country_statements(10)
        assert [row["country_name"] for row in feed[:2]] == ["Бета", "Альфа"]
        assert feed[0]["game_year"] == 2020
        assert "Правительство" in feed[1]["statement"]
        print("STATEMENTS_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
