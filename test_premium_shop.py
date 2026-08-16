import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import config
import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_premium_shop_test.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        await db.create_country(1, 1, "Тестландия")
        assert await db.grant_premium(1, 4000, "Тестовая выдача", 99)
        assert await db.get_premium_balance(1) == 4000
        assert not await db.purchase_premium(1, "territory_expansion", 5000, "Слишком дорого")
        assert await db.purchase_premium(1, "territory_expansion", 1000, "Покупка территории")
        country = await db.get_country(1)
        assert country["territory"] == 102500
        assert await db.purchase_premium(1, "luck_boost", 250, "Покупка буста")
        items = await db.get_premium_items(1)
        assert items["luck_boost"] == 1
        assert await db.consume_premium_item(1, "luck_boost")
        assert not await db.consume_premium_item(1, "luck_boost")
        assert await db.get_premium_balance(1) == 2750
        assert config.PREMIUM_CURRENCY_NAME == "Гаванские кредиты"
        print("PREMIUM_SHOP_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
