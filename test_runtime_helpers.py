import os

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


def test_format_duration():
    assert bot.format_duration(0) == "0 сек"
    assert bot.format_duration(59) == "59 сек"
    assert bot.format_duration(60) == "1 мин 0 сек"
    assert bot.format_duration(3661) == "1 ч 1 мин 1 сек"


if __name__ == "__main__":
    test_format_duration()
    print("RUNTIME_HELPERS_OK")
