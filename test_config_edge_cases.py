import asyncio
import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import config
import db
import market


def test_requested_cooldowns():
    assert config.ATTACK_COOLDOWN_SECONDS == 600
    assert config.WORLD_EVENT_COOLDOWN_SECONDS == 600


def test_invalid_environment_values():
    old_values = {key: os.environ.get(key) for key in ("BAD_INT", "BAD_FLOAT")}
    try:
        os.environ["BAD_INT"] = "-99"
        os.environ["BAD_FLOAT"] = "not-a-number"
        assert config._env_int("BAD_INT", 30) == 0
        assert config._env_int("BAD_INT", 30, minimum=1) == 1
        assert config._env_float("BAD_FLOAT", 1.5) == 1.5
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_market_zero_tick():
    old = config.MARKET_TICK_SECONDS
    try:
        config.MARKET_TICK_SECONDS = 0
        assert market.get_price("wood") >= 1
    finally:
        config.MARKET_TICK_SECONDS = old


async def test_world_year_zero_duration():
    path = os.path.join(tempfile.gettempdir(), "gavan_config_edge_test.db")
    for suffix in ("", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)
    old_path = db.DB_PATH
    old_duration = db.SECONDS_PER_GAME_YEAR
    db.DB_PATH = path
    db.SECONDS_PER_GAME_YEAR = 0
    try:
        await db.init_db()
        await db.set_world_year(2140)
        assert await db.get_current_year() >= 2140
    finally:
        db.DB_PATH = old_path
        db.SECONDS_PER_GAME_YEAR = old_duration
        for suffix in ("", "-wal", "-shm"):
            candidate = path + suffix
            if os.path.exists(candidate):
                os.remove(candidate)


if __name__ == "__main__":
    test_requested_cooldowns()
    test_invalid_environment_values()
    test_market_zero_tick()
    asyncio.run(test_world_year_zero_duration())
    print("CONFIG_EDGE_CASES_OK")
