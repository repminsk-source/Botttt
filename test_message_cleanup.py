import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot
from aiogram.exceptions import TelegramForbiddenError


async def main():
    bot._ACTIVE_INTERFACE_MESSAGES.clear()
    sent_ids = iter([101, 102, 201, 302])

    async def answer(*args, **kwargs):
        return SimpleNamespace(message_id=next(sent_ids))

    message = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=7),
        message_thread_id=None,
        answer=answer,
    )
    other_player = SimpleNamespace(
        chat=SimpleNamespace(id=-1001),
        from_user=SimpleNamespace(id=8),
        message_thread_id=None,
        answer=answer,
    )

    delete = AsyncMock()
    with patch.object(bot.bot, "delete_message", delete):
        await bot.answer_topic_safe(message, "first")
        await bot.answer_topic_safe(message, "second")
        await bot.answer_topic_safe(other_player, "other player")

    delete.assert_awaited_once_with(chat_id=-1001, message_id=101)
    assert bot._ACTIVE_INTERFACE_MESSAGES[( -1001, 7, 0)] == 102
    assert bot._ACTIVE_INTERFACE_MESSAGES[( -1001, 8, 0)] == 201

    bot._ACTIVE_INTERFACE_MESSAGES[( -1001, 7, 0)] = 301
    delete.side_effect = TelegramForbiddenError(method="deleteMessage", message="not an admin")
    with patch.object(bot.bot, "delete_message", delete):
        await bot.answer_topic_safe(message, "permission failure")
    assert bot._ACTIVE_INTERFACE_MESSAGES[( -1001, 7, 0)] == 302
    print("MESSAGE_CLEANUP_OK")


if __name__ == "__main__":
    asyncio.run(main())
