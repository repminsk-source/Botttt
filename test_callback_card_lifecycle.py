import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


async def test_finish_callback_does_not_overwrite_handler_card():
    old_message_builder = bot.callback_message
    old_key_builder = bot._interface_key
    old_helper = bot.answer_topic_safe
    original_active = dict(bot._ACTIVE_INTERFACE_MESSAGES)
    calls = []

    async def callback_answer():
        calls.append("ack")

    async def handler(_message):
        bot._ACTIVE_INTERFACE_MESSAGES[(1, 2, 0)] = 222

    async def fake_helper(*args, **kwargs):
        calls.append("fallback")

    bot.callback_message = lambda callback, text: SimpleNamespace(text=text)
    bot._interface_key = lambda message, owner_id=None: (1, 2, 0)
    bot.answer_topic_safe = fake_helper
    bot._ACTIVE_INTERFACE_MESSAGES.clear()
    bot._ACTIVE_INTERFACE_MESSAGES[(1, 2, 0)] = 111
    callback = SimpleNamespace(answer=callback_answer, message=object(), from_user=SimpleNamespace(id=2))
    try:
        await bot.finish_callback(callback, "/market", handler, bot.ECONOMY_INLINE)
    finally:
        bot.callback_message = old_message_builder
        bot._interface_key = old_key_builder
        bot.answer_topic_safe = old_helper
        bot._ACTIVE_INTERFACE_MESSAGES.clear()
        bot._ACTIVE_INTERFACE_MESSAGES.update(original_active)
    assert calls == ["ack"]


if __name__ == "__main__":
    asyncio.run(test_finish_callback_does_not_overwrite_handler_card())
    print("CALLBACK_CARD_LIFECYCLE_OK")
