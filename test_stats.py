import asyncio
import os
import tempfile

import config
import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_stats_audit.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        profile = {
            "iso_code": "BRA",
            "selected_year": 2020,
            "population": 212_000_000,
            "gdp_usd": 1_000_000,
            "gdp_per_capita_usd": 1000,
            "life_expectancy": 75,
        }
        assert await db.create_country(1, 1, "Бразилия", "large", profile)
        assert not await db.create_country(2, 2, "бразилия", "medium", profile)
        country = await db.get_country(1)
        assert country["economy"] == config.START_STATS["economy"]
        assert country["military"] == config.START_STATS["military"]
        assert country["population"] == config.START_STATS["population"]
        assert country["gold"] == config.START_GOLD
        assert country["resources"] == config.START_RESOURCES
        assert country["wood"] == config.START_WOOD
        assert country["military_bases"] == config.START_MILITARY_BASES

        await db.update_stat(1, "tech", 3)
        await db.update_resource(1, "manpower", 1000)
        await db.update_stat(1, "population", 1000)
        country = await db.get_country(1)
        assert country["tech"] == 3
        assert country["manpower"] == 1000
        assert country["population"] == 1000

        assert await db.apply_building_upgrade(1, "farm", 300, 150)
        buildings = await db.get_buildings(1)
        assert buildings == {"farm": 1}
        country = await db.get_country(1)
        assert country["gold"] == config.START_GOLD - 300
        assert country["resources"] == config.START_RESOURCES - 150

        assert await db.apply_collect(1, {"manpower": 6}, 0, 0, 0, config.POINTS_PER_COLLECT, 1000)
        country = await db.get_country(1)
        assert country["manpower"] == 1006
        assert country["points"] == config.POINTS_PER_COLLECT
        assert country["gold"] == config.START_GOLD - 300 + config.FIRST_COLLECT_GOLD_BONUS
        assert not await db.apply_collect(1, {"manpower": 6}, 0, 0, 0, 1, 1000)

        assert await db.apply_mobilization(1, 5 * config.MOBILIZE_MANPOWER_PER_POINT, 5 * config.MOBILIZE_GOLD_PER_POINT, 5, 2000)
        country = await db.get_country(1)
        assert country["military"] == 5
        assert country["manpower"] == 1006 - 5 * config.MOBILIZE_MANPOWER_PER_POINT

        assert await db.apply_purchase(1, "wood", 3, 6)
        country = await db.get_country(1)
        assert country["wood"] == config.START_WOOD + 3

        await db.apply_action_result(1, {"economy": 3, "population": -50}, "Бразилия", "Тест", "Вердикт")
        country = await db.get_country(1)
        assert country["economy"] == 3
        assert country["population"] == 950
        assert len(await db.get_recent_events(1)) == 1
        print("ALL DATABASE STATISTICS TESTS: OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
