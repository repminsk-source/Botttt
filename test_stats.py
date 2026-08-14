import asyncio
import os
import tempfile

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
        await db.create_country(1, 1, "Бразилия", "large")
        await db.create_country(2, 2, "Аргентина", "large")
        await db.create_country(3, 3, "бразилия", "medium")
        assert await db.get_country(3) is None
        c1 = await db.get_country(1)
        c2 = await db.get_country(2)
        assert (c1["economy"], c1["military"], c1["population"], c1["tech"], c1["diplomacy"]) == (10, 10, 10, 10, 10)
        assert (c1["gold"], c1["resources"], c1["manpower"], c1["water"], c1["food"]) == (50, 30, 20, 25, 40)

        await db.update_stat(1, "tech", 3)
        await db.update_stat(1, "points", -2)
        c1 = await db.get_country(1)
        assert c1["tech"] == 13 and c1["points"] == 0

        assert await db.apply_building_upgrade(1, "farm", 20, 10)
        assert await db.apply_building_upgrade(1, "mine", 30, 5)
        c1 = await db.get_country(1)
        buildings = await db.get_buildings(1)
        assert buildings == {"farm": 1, "mine": 1}
        assert (c1["gold"], c1["resources"]) == (0, 15)

        assert await db.apply_collect(1, {"manpower": 6, "resources": 10}, 1, 0, 0, 1000)
        c1 = await db.get_country(1)
        assert (c1["manpower"], c1["resources"], c1["economy"]) == (26, 25, 11)
        assert not await db.apply_collect(1, {"gold": 1}, 0, 0, 0, 1000)
        assert await db.apply_collect(1, {"food": 20}, 0, 50, 1, 1001)
        c1 = await db.get_country(1)
        assert c1["food"] == 10 and c1["population"] == 11

        assert await db.apply_mobilization(1, 10, 15, 1) is False
        assert await db.apply_mobilization(2, 10, 15, 1)
        c2 = await db.get_country(2)
        assert (c2["manpower"], c2["gold"], c2["military"]) == (10, 35, 11)

        assert await db.apply_purchase(2, "wood", 3, 6)
        c2 = await db.get_country(2)
        assert (c2["wood"], c2["gold"]) == (3, 29)
        assert await db.apply_upgrade(2, "tech", 2, 2) is False
        assert await db.apply_base(2, 40, 30) is False
        assert await db.apply_spy_operation(2, 25, 2000)
        c2 = await db.get_country(2)
        assert (c2["gold"], c2["last_spy_at"]) == (4, 2000)
        await db.apply_action_result(2, {"economy": 3, "population": -50}, "Аргентина", "Тест", "Вердикт")
        c2 = await db.get_country(2)
        assert (c2["economy"], c2["population"]) == (13, 0)
        assert len(await db.get_recent_events(1)) == 1

        before = await db.get_country(2)
        await db.apply_war_result(1, 2, {"economy": -100, "military": 2}, {"population": 3}, loot_gold=-5, loot_resources=-4)
        after1 = await db.get_country(1)
        after2 = await db.get_country(2)
        assert after1["economy"] == 0 and after1["military"] == 12
        assert after2["population"] == 3 and after2["gold"] == before["gold"] and after2["resources"] == before["resources"] + 4
        print("ALL DATABASE STATISTICS TESTS: OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
