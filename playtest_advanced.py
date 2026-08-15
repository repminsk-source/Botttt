import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import ai
import config
import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_advanced_playtest.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        profile = {"iso_code": "PRT", "selected_year": 2020, "population": 10_000_000, "gdp_usd": 200_000_000_000}
        assert await db.create_country(2001, 1, "Португалия", "medium", profile)
        profile["iso_code"] = "IRL"
        assert await db.create_country(2002, 1, "Ирландия", "medium", profile)
        assert await db.create_alliance("SEA", "Морской союз")
        alliance = await db.get_alliance_by_tag("sea")
        await db.join_alliance(2001, alliance["id"])
        await db.join_alliance(2002, alliance["id"])
        assert len(await db.get_alliance_members(alliance["id"])) == 2
        assert await db.leave_alliance(2002)
        assert not await db.leave_alliance(2002)
        print("01 diplomacy and alliance lifecycle: OK")

        await db.update_resource(2001, "gold", 10000)
        await db.update_resource(2002, "gold", 10000)
        await db.update_stat(2001, "military", 10)
        await db.update_stat(2002, "military", 8)
        await db.apply_war_result(
            2001, 2002,
            {"military": -2, "economy": 1},
            {"military": -3, "stability": -4},
            loot_gold=100,
            loot_resources=20,
        )
        attacker = await db.get_country(2001)
        defender = await db.get_country(2002)
        assert attacker["military"] == 8 and defender["military"] == 5
        assert attacker["gold"] == config.START_GOLD + 10100
        assert defender["gold"] == config.START_GOLD + 9900
        print("02 atomic war result and loot: OK")

        assert config.ACTION_COOLDOWN_SECONDS <= 600
        assert config.BUILD_COOLDOWN_SECONDS <= 60
        assert config.COLLECT_COOLDOWN_SECONDS == 2700
        assert config.GLOBAL_MESSAGE_COOLDOWN_SECONDS < 2
        assert config.SPAM_BURST_LIMIT <= 10
        safe = ai._safe_error(RuntimeError("https://x.test/?key=SECRET Bearer SECRET2"))
        assert "SECRET" not in safe and "REDACTED" in safe
        print("03 timers, spam limits, and AI failure safety: OK")
        print("ADVANCED_PLAYTEST_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
