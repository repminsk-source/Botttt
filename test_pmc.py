import asyncio
import os
import tempfile

import config
import db


async def main():
    old_path = db.DB_PATH
    fd, path = tempfile.mkstemp(prefix="gavan_pmc_", suffix=".sqlite3")
    os.close(fd)
    db.DB_PATH = path
    try:
        await db.init_db()
        profile = {"iso_code": "AAA", "real_population": 1_000_000, "real_gdp_usd": 1_000_000}
        assert await db.create_country(1001, 1, "Альфа", "medium", profile)
        profile2 = {"iso_code": "BBB", "real_population": 1_000_000, "real_gdp_usd": 1_000_000}
        assert await db.create_country(1002, 2, "Бета", "medium", profile2)
        assert await db.create_country(1003, 3, "Гамма", "medium", {"iso_code": "CCC", "real_population": 1_000_000})
        standalone_id = await db.create_pmc(9000, "Свободный Щит", "pmc", 100)
        assert standalone_id
        standalone = await db.get_pmc(standalone_id)
        assert standalone["inventory_gold"] == config.PMC_STARTING_FUNDS

        pmc_id = await db.create_pmc(1001, "Щит", "pmc", 100)
        assert pmc_id
        assert await db.create_pmc(1002, "Копьё", "pmc", 100)
        pmc = await db.get_pmc(pmc_id)
        assert pmc["owner_id"] == 1001

        request_id = await db.create_pmc_request(pmc_id, 1002, "Нужна охрана инфраструктуры и защита транспортного коридора.", 100)
        assert request_id
        pending = await db.list_pmc_requests(pmc_id)
        assert pending and "country_id" not in pending[0]
        result = await db.resolve_pmc_request(request_id, 1001, True, 101)
        assert result["accepted"] is True and result["country_id"] == 1002

        request2 = await db.create_pmc_request(pmc_id, 1003, "Нужна охрана инфраструктуры и защита транспортного коридора.", 100)
        assert request2
        result2 = await db.resolve_pmc_request(request2, 1001, True, 101)
        assert result2["accepted"] is True
        second_pmc = await db.get_pmc_by_owner(1002)
        request3 = await db.create_pmc_request(second_pmc["id"], 1002, "Ещё один заказ на охрану инфраструктуры и транспортного коридора.", 100)
        assert request3
        result3 = await db.resolve_pmc_request(request3, 1002, True, 101)
        assert result3["accepted"] is True
        request4 = await db.create_pmc_request(pmc_id, 1002, "Повторный контракт той же ЧВК не должен быть создан.", 100)
        assert request4 is None

        pmc_row = await db.get_pmc(pmc_id)
        assert await db.fund_pmc(pmc_id, 1001, 100_000, 100)
        funded = await db.get_pmc(pmc_id)
        assert funded["inventory_gold"] == config.PMC_STARTING_FUNDS + 100_000
        ok, reason = await db.recruit_pmc(pmc_id, 1001, 2500, 100)
        assert ok, reason
        ok2, why = await db.recruit_pmc(pmc_id, 1001, 2500, 101)
        assert not ok2 and why == "cooldown"
        assert await db.sanction_pmc(pmc_id, "inventory_clear", "Тест санкции", 999, 102)
        after = await db.get_pmc(pmc_id)
        assert after["personnel"] == 0 and after["inventory_gold"] == 0

        first_news = await db.create_pmc_statement(pmc_id, "Щит", "Официальное сообщение организации о защите транспортного коридора.", 2020, 200)
        assert first_news
        assert await db.create_pmc_statement(pmc_id, "Щит", "Повторная публикация не должна пройти в рамках кулдауна.", 2020, 201) is None
        later_news = await db.create_pmc_statement(pmc_id, "Щит", "Новое официальное сообщение после завершения установленного кулдауна публикаций.", 2020, 200 + config.STATEMENT_COOLDOWN_SECONDS)
        assert later_news
        assert await db.get_recent_pmc_statements(10)

        assert await db.get_pmc_action_cooldown(pmc_id, 300) == 0
        assert await db.touch_pmc_action(pmc_id, 1001, 300)
        assert await db.get_pmc_action_cooldown(pmc_id, 301) == config.PMC_ACTION_COOLDOWN_SECONDS - 1
        assert not await db.touch_pmc_action(pmc_id, 9999, 302)
        assert await db.sanction_pmc(pmc_id, "disqualify", "Финальная проверка", 999, 400)
        assert await db.create_pmc_statement(pmc_id, "Щит", "Публикация после дисквалификации запрещена.", 2020, 400 + config.STATEMENT_COOLDOWN_SECONDS) is None
        print("PMC_ANONYMOUS_REQUEST_OK")
        print("PMC_LIMITS_OK")
        print("PMC_SANCTIONS_OK")
    finally:
        db.DB_PATH = old_path
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
