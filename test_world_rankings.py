import asyncio
import os

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


async def main():
    old_get_all = bot.db.get_all_countries
    bot.db.get_all_countries = lambda: asyncio.sleep(0, result=[
        {"name": "Богатая", "gold": 20_000_000, "economy": 90, "resources": 10, "food": 1, "water": 1, "military": 20, "military_bases": 2, "readiness": 40, "tech": 30, "reputation": 30, "war_exhaustion": 0},
        {"name": "Устрашающая", "gold": 1_000_000, "economy": 40, "resources": 1, "food": 1, "water": 1, "military": 900, "military_bases": 20, "readiness": 95, "tech": 80, "reputation": 80, "war_exhaustion": 0},
    ])
    try:
        articles = await bot.build_world_rankings()
        assert len(articles) == 2
        assert articles[0].find("Богатая") < articles[0].find("Устрашающая")
        assert articles[1].find("Устрашающая") < articles[1].find("Богатая")
        assert "индекс угрозы" in articles[1]
        print("WORLD_RANKINGS_OK")
    finally:
        bot.db.get_all_countries = old_get_all


if __name__ == "__main__":
    asyncio.run(main())
