import os
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


def test_callback_identity_is_clicker():
    original_message = SimpleNamespace(from_user=SimpleNamespace(id=111), chat=SimpleNamespace(id=-1001))
    original_message.model_copy = lambda update: SimpleNamespace(
        from_user=update["from_user"], text=update["text"], chat=original_message.chat
    )
    callback = SimpleNamespace(message=original_message, from_user=SimpleNamespace(id=222))
    routed = bot.callback_message(callback, "/collect")
    assert routed.from_user.id == 222
    assert routed.text == "/collect"


if __name__ == "__main__":
    test_callback_identity_is_clicker()
    print("OWNERSHIP_GUARD_OK")
