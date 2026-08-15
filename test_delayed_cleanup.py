import asyncio
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


async def main():
    old_delay = bot.config.INTERFACE_MESSAGE_DELETE_SECONDS
    old_tasks = dict(bot._INTERFACE_DELETE_TASKS)
    bot.config.INTERFACE_MESSAGE_DELETE_SECONDS = 30
    bot._INTERFACE_DELETE_TASKS.clear()
    bot._ACTIVE_INTERFACE_MESSAGES.clear()
    delete = AsyncMock()
    try:
        with patch.object(bot.bot, "delete_message", delete), patch.object(bot.asyncio, "sleep", new=AsyncMock()) as sleep:
            bot._schedule_interface_deletion(-1001, 777)
            task = bot._INTERFACE_DELETE_TASKS[(-1001, 777)]
            await task
            sleep.assert_awaited_once_with(30)
            delete.assert_awaited_once_with(chat_id=-1001, message_id=777)
        assert (-1001, 777) not in bot._INTERFACE_DELETE_TASKS
        print("DELAYED_CLEANUP_OK")
    finally:
        bot.config.INTERFACE_MESSAGE_DELETE_SECONDS = old_delay
        bot._INTERFACE_DELETE_TASKS.clear()
        bot._INTERFACE_DELETE_TASKS.update(old_tasks)


if __name__ == "__main__":
    asyncio.run(main())
