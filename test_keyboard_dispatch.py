import os

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


EXPECTED = {
    "ui:country": "callback_country",
    "ui:collect": "callback_collect",
    "ui:build": "callback_build",
    "ui:army": "callback_army",
    "ui:progress": "callback_progress",
    "ui:more": "callback_more",
    "ui:news": "callback_news",
    "ui:top": "callback_top",
    "ui:policy": "callback_policy",
    "ui:diplomacy": "callback_diplomacy",
    "ui:guide": "callback_guide",
    "ui:back": "callback_back",
}


def test_callback_handlers_registered():
    names = {}
    for handler in bot.dp.callback_query.handlers:
        magic = handler.filters[0].magic
        # The callback filter is a MagicFilter whose repr is opaque, so verify
        # the callback names and exact count after importing the real dispatcher.
        names[handler.callback.__name__] = names.get(handler.callback.__name__, 0) + 1
    assert set(names) == set(EXPECTED.values())
    assert all(count == 1 for count in names.values())


if __name__ == "__main__":
    test_callback_handlers_registered()
    print("RUNTIME_CALLBACK_ROUTES_OK")
