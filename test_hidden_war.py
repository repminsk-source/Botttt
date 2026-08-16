import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


class FakeMessage:
    def __init__(self, chat_type):
        self.chat = SimpleNamespace(type=chat_type)
        self.deleted = False

    async def delete(self):
        self.deleted = True


async def main():
    group = FakeMessage("supergroup")
    await bot.hide_group_command(group)
    assert group.deleted is True

    private = FakeMessage("private")
    await bot.hide_group_command(private)
    assert private.deleted is False
    print("HIDDEN_WAR_INPUT_OK")


if __name__ == "__main__":
    asyncio.run(main())
