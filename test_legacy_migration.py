import asyncio
import os
import sqlite3
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_legacy_migration.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)

    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE countries (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            name TEXT NOT NULL,
            economy INTEGER NOT NULL,
            military INTEGER NOT NULL,
            population INTEGER NOT NULL,
            tech INTEGER NOT NULL,
            diplomacy INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        );
        INSERT INTO countries VALUES (9001, 1, 'Тестовая страна', 0, 0, 0, 0, 0, 1);
        """
    )
    conn.commit()
    conn.close()

    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        assert await db.check_integrity()
        country = await db.get_country(9001)
        assert country["stability"] == 70
        assert country["readiness"] == 50
        assert country["gold"] == 0
        assert country["last_collect_at"] == 0
        async with db._connect() as conn:
            cur = await conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            tables = {row[0] for row in await cur.fetchall()}
        assert {"pmcs", "pmc_requests", "pmc_contracts", "premium_wallets", "pending_wars"} <= tables
        print("LEGACY_MIGRATION_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
