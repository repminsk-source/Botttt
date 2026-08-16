import asyncio
import os
import tempfile
import time

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_war_history.db")
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
        await db.log_war(
            1, "Альфа", 2, "Бета",
            "скрытая атака",
            "draw",
            "Итог без секретных ходов",
        )
        history = await db.get_war_history(1)
        assert len(history) == 1
        assert history[0]["attacker_name"] == "Альфа"
        assert "attack_text" not in history[0]
        assert "defense_text" not in history[0]
        assert not await db.get_war_history(99)
        print("WAR_HISTORY_SCOPE_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
