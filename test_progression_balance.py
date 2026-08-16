import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import config
import db
from bot import progression_snapshot


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_progression_balance.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        profile = {
            "iso_code": "GHA",
            "selected_year": 2020,
            "population": 31_000_000,
            "gdp_usd": 72_000_000_000,
        }
        assert await db.create_country(3001, 1, "Гана", "medium", profile)

        timestamp = 1_000
        for _ in range(10):
            assert await db.apply_collect(
                3001,
                {"manpower": 100, "resources": 2_000, "food": 100},
                economy_growth=1,
                food_spend=50,
                population_growth=1,
                points_growth=config.POINTS_PER_COLLECT,
                timestamp=timestamp,
            )
            timestamp += config.COLLECT_COOLDOWN_SECONDS

        country = await db.get_country(3001)
        assert country["gold"] == config.START_GOLD + config.FIRST_COLLECT_GOLD_BONUS
        assert country["points"] == 10 * config.POINTS_PER_COLLECT
        assert country["population"] == 10
        assert country["food"] == 500

        for building_type in ("farm", "mine", "market", "granary"):
            info = config.BUILDINGS[building_type]
            assert await db.apply_building_upgrade(3001, building_type, info["cost_gold"], info["cost_resources"])

        buildings = await db.get_buildings(3001)
        snapshot = progression_snapshot(country, buildings)
        assert snapshot["score"] >= 0
        assert country["points"] == 10 * config.POINTS_PER_COLLECT
        assert country["gold"] >= 0 and country["resources"] >= 0
        print("PROGRESSION_BALANCE_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
