import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_labor_priority.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        assert await db.create_country(1, 1, "Альфа", "medium", {})
        country = await db.get_country(1)
        assert country["labor_focus"] == "balanced"
        assert await db.set_labor_focus(1, "civilian")
        assert (await db.get_country(1))["labor_focus"] == "civilian"
        assert await db.set_labor_focus(1, "military")
        assert (await db.get_country(1))["labor_focus"] == "military"
        try:
            await db.set_labor_focus(1, "invalid")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid labor focus accepted")
        print("LABOR_PRIORITY_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
