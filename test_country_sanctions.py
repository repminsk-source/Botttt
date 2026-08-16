import asyncio
import os
import tempfile

import db


async def main():
    old_path = db.DB_PATH
    fd, path = tempfile.mkstemp(prefix="gavan_sanctions_", suffix=".sqlite3")
    os.close(fd)
    db.DB_PATH = path
    try:
        await db.init_db()
        assert await db.create_country(1, 1, "Альфа", "medium", {})
        assert await db.create_country(2, 2, "Бета", "medium", {})
        now = 1000
        assert await db.create_country_sanction(1, 1, "economic", 3, "самонаказание", now) is None
        assert await db.create_country_sanction(1, 2, "invalid", 3, "ошибка", now) is None
        sanction_id = await db.create_country_sanction(1, 2, "economic", 3, "Ограничение торговли из-за нарушения соглашения.", now)
        assert sanction_id
        assert await db.create_country_sanction(1, 2, "economic", 3, "дубликат", now + 1) is None
        active = await db.get_active_country_sanctions(2, now + 1)
        assert len(active) == 1 and active[0]["issuer_id"] == 1
        visible = await db.list_country_sanctions(2)
        assert visible and visible[0]["target_id"] == 2
        assert await db.get_active_country_sanctions(2, now + 3 * 86400 + 1) == []
        print("COUNTRY_SANCTIONS_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
