import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import config
import db
from bot import format_country_economy, format_country_summary, progression_snapshot


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_beginner_playtest.db")
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
            "gdp_per_capita_usd": 2300,
            "life_expectancy": 64,
        }
        assert await db.create_country(1001, 777, "Гана", "medium", profile)
        country = await db.get_country(1001)
        assert country["gold"] == config.START_GOLD
        assert country["resources"] == config.START_RESOURCES
        assert country["wood"] == config.START_WOOD
        assert country["military_bases"] == config.START_MILITARY_BASES
        print("01 registration: OK")

        buildings = await db.get_buildings(1001)
        assert buildings == {}
        first_collect = await db.apply_collect(1001, {"manpower": 100, "food": 20}, 0, 0, 0, config.POINTS_PER_COLLECT, 1000)
        assert first_collect
        country = await db.get_country(1001)
        assert country["gold"] == config.START_GOLD + config.FIRST_COLLECT_GOLD_BONUS
        print("02 first collection and bonus: OK")

        farm = config.BUILDINGS["farm"]
        assert await db.apply_building_upgrade(1001, "farm", farm["cost_gold"], farm["cost_resources"])
        country = await db.get_country(1001)
        buildings = await db.get_buildings(1001)
        assert buildings["farm"] == 1
        print("03 first building: OK")

        await db.update_stat(1001, "population", 1000)
        await db.update_resource(1001, "manpower", 1000)
        country = await db.get_country(1001)
        assert country["population"] == 1000
        assert country["manpower"] == 1100
        assert await db.apply_mobilization(1001, 100, 50, 5, 2000)
        await db.update_stat(1001, "population", 2000)
        await db.update_resource(1001, "manpower", 1000)
        assert await db.apply_mobilization(1001, 625, 1250, 25, 3000)
        country = await db.get_country(1001)
        assert country["military"] == 30
        assert await db.apply_purchase(1001, "wood", 10, 10)
        mine = config.BUILDINGS["mine"]
        assert await db.apply_building_upgrade(1001, "mine", mine["cost_gold"], mine["cost_resources"])
        assert await db.apply_collect(1001, {"resources": 6000}, 0, 0, 0, config.POINTS_PER_COLLECT, 4000)
        assert await db.apply_base(1001, config.BASE_COST_GOLD * 2, config.BASE_COST_RESOURCES * 2, config.MILITARY_PER_BASE)

        country = await db.get_country(1001)
        assert country["military_bases"] == 2
        print("04 population, mobilization, market, and base: OK")

        assert await db.set_policy(1001, "development", 3000, config.POLICY_COOLDOWN_SECONDS)
        country = await db.get_country(1001)
        assert country["policy"] == "development"
        snapshot = progression_snapshot(country, buildings)
        assert snapshot["score"] >= 0
        summary = await format_country_summary(country)
        economy = await format_country_economy(country)
        assert "Гана" in summary and "Следующий шаг" in summary
        assert summary.count("\\n") <= 10
        assert economy.count("\\n") <= 12 and "Экономика" in economy
        print("05 policy, progress, and compact cards: OK")
        print("BEGINNER_PLAYTEST_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
