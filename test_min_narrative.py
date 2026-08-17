import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


async def main():
    old_helper = bot.answer_topic_safe
    old_admin = bot.is_admin
    old_resolver = bot.resolve_country_target
    responses = []

    async def fake_helper(message, text, *args, **kwargs):
        responses.append(text)

    bot.answer_topic_safe = fake_helper
    bot.is_admin = lambda _user_id: True
    async def fake_resolver(_value):
        return {"user_id": 2002, "name": "Бета", "username": "beta_player"}
    bot.resolve_country_target = fake_resolver
    try:
        attack = SimpleNamespace(
            text="/attack @beta_player Слишком коротко",
            from_user=SimpleNamespace(id=2001),
        )
        await bot.cmd_attack(attack)
        assert "минимум 50" in responses[-1]

        event = SimpleNamespace(
            text="/world_event economy | Заголовок | Короткая новость",
            from_user=SimpleNamespace(id=1),
        )
        await bot.cmd_world_event(event)
        assert "минимум 50" in responses[-1]
    finally:
        bot.answer_topic_safe = old_helper
        bot.is_admin = old_admin
        bot.resolve_country_target = old_resolver
    print("MIN_NARRATIVE_OK")


if __name__ == "__main__":
    asyncio.run(main())
