import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")
os.environ.setdefault("GLOBAL_MESSAGE_COOLDOWN_SECONDS", "0.01")
os.environ.setdefault("DUPLICATE_MESSAGE_WINDOW_SECONDS", "0.05")
os.environ.setdefault("SPAM_BURST_WINDOW_SECONDS", "0.2")
os.environ.setdefault("SPAM_BURST_LIMIT", "3")

from anti_spam import AntiSpamMiddleware


class FakeMessage:
    def __init__(self, text, user_id=1):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(type="supergroup")
        self.notifications = []
        self.deleted = False

    async def answer(self, text):
        self.notifications.append(text)

    async def delete(self):
        self.deleted = True


async def run_test():
    middleware = AntiSpamMiddleware()
    calls = []

    async def handler(event, data):
        calls.append(event.text)
        return True

    first = FakeMessage("/country")
    await middleware(handler, first, {})
    duplicate = FakeMessage("/country")
    await middleware(handler, duplicate, {})
    assert calls == ["/country"]
    assert duplicate.deleted is True

    await asyncio.sleep(0.06)
    await middleware(handler, FakeMessage("/progress"), {})
    await asyncio.sleep(0.02)
    await middleware(handler, FakeMessage("/news"), {})
    await asyncio.sleep(0.02)
    await middleware(handler, FakeMessage("/top"), {})
    await asyncio.sleep(0.02)
    await middleware(handler, FakeMessage("/help"), {})
    assert len(calls) == 3, calls


if __name__ == "__main__":
    asyncio.run(run_test())
    print("ANTISPAM_OK")
