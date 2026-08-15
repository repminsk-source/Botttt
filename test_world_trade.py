import asyncio
import os
import tempfile

import config
import db


async def main():
    path = os.path.join(tempfile.gettempdir(), "gavan_world_trade_test.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    db.DB_PATH = path
    try:
        await db.init_db()
        profile = {"iso_code": "AAA", "selected_year": 2020, "population": 1_000_000, "gdp_usd": 10_000_000}
        assert await db.create_country(3001, 1, "Альфа", "small", profile)
        profile["iso_code"] = "BBB"
        assert await db.create_country(3002, 2, "Бета", "small", profile)
        event_id = await db.create_world_event("Новый торговый маршрут", "Порты двух стран открыты для международной торговли.", "economy", 2020)
        events = await db.get_world_events()
        assert events and events[0]["id"] == event_id and events[0]["event_type"] == "economy"
        await db.log_event(3001, "Альфа", "Тест", "Локальное решение")
        assert len(await db.get_recent_events_for_user(3001)) == 1
        assert len(await db.get_recent_events_for_user(3002)) == 0
        await db.update_resource(3001, "wood", 1000)
        contract_id = await db.create_trade_contract(3001, 3002, "wood", 500, 700, int(__import__("time").time()) + 3600)
        assert contract_id
        assert not await db.accept_trade_contract(contract_id, 3001)
        assert await db.accept_trade_contract(contract_id, 3002)
        alpha = await db.get_country(3001)
        beta = await db.get_country(3002)
        assert alpha["wood"] == config.START_WOOD + 500
        assert beta["wood"] == config.START_WOOD + 500
        assert alpha["gold"] == config.START_GOLD + 700
        assert beta["gold"] == config.START_GOLD - 700
        second = await db.create_trade_contract(3001, 3002, "wood", 100, 10)
        assert second and not await db.reject_trade_contract(second, 3001)
        assert await db.reject_trade_contract(second, 3002)

        profile["iso_code"] = "CCC"
        assert await db.create_country(3003, 3, "Гамма", "small", profile)
        alliance_id = await db.create_alliance("AUD", "Аудит")
        assert alliance_id
        alliance = await db.get_alliance_by_tag("AUD")
        await db.join_alliance(3001, alliance["id"])
        transferred_contract = await db.create_trade_contract(3001, 3003, "wood", 10, 10)
        assert transferred_contract
        assert await db.transfer_country(3001, 3004)
        transferred = await db.get_trade_contract(transferred_contract)
        assert transferred["proposer_id"] == 3004 and transferred["target_id"] == 3003
        assert (await db.get_user_alliance(3004))["tag"] == "AUD"
        assert await db.get_country(3001) is None

        assert await db.delete_country(3004)
        cancelled = await db.get_trade_contract(transferred_contract)
        assert cancelled["status"] == "cancelled"
        print("WORLD_TRADE_OK")
    finally:
        db.DB_PATH = old_path
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    asyncio.run(main())
