import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


async def test_market_command_keeps_navigation_markup():
    captured = {}
    old_helper = bot.answer_topic_safe

    async def fake_helper(message, text, reply_markup=None, owner_id=None):
        captured["text"] = text
        captured["markup"] = reply_markup
        return SimpleNamespace(message_id=9001)

    bot.answer_topic_safe = fake_helper
    try:
        await bot.cmd_market(SimpleNamespace(text="/market"))
    finally:
        bot.answer_topic_safe = old_helper
    assert "Рынок сырья" in captured["text"]
    assert captured["markup"] is bot.ECONOMY_INLINE


async def test_market_callback_does_not_append_second_card():
    captured = {}
    old_finish = bot.finish_callback

    async def fake_finish(callback, command, handler, markup=bot.MAIN_INLINE):
        captured.update(command=command, handler=handler, markup=markup)

    bot.finish_callback = fake_finish
    try:
        await bot.callback_economy_market(SimpleNamespace())
    finally:
        bot.finish_callback = old_finish
    assert captured["command"] == "/market"
    assert captured["handler"] is bot.cmd_market
    assert captured["markup"] is None


if __name__ == "__main__":
    asyncio.run(test_market_command_keeps_navigation_markup())
    asyncio.run(test_market_callback_does_not_append_second_card())
    print("MARKET_UI_OK")
