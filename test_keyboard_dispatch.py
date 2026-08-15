import os

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


EXPECTED = {
    "ui:country": "callback_country",
    "ui:economy": "callback_economy",
    "ui:collect": "callback_collect",
    "eco:collect": "callback_economy_collect",
    "eco:market": "callback_economy_market",
    "ui:world": "callback_world",
    "ui:trade": "callback_trade",
    "army:mobilize:1": "callback_army_mobilize",
    "army:base": "callback_army_base",
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
BUILD_CALLBACKS = {
    "build:farm", "build:mine", "build:market", "build:well", "build:granary",
    "build:sawmill", "build:iron_mine", "build:coal_mine", "build:oil_rig",
    "build:uranium_mine", "build:base",
}



def test_callback_handlers_registered():
    names = {}
    for handler in bot.dp.callback_query.handlers:
        magic = handler.filters[0].magic
        # The callback filter is a MagicFilter whose repr is opaque, so verify
        # the callback names and exact count after importing the real dispatcher.
        names[handler.callback.__name__] = names.get(handler.callback.__name__, 0) + 1
    assert set(names) == set(EXPECTED.values()) | {"callback_build_type"}
    assert all(count == 1 for count in names.values())
    actual_build_callbacks = {
        button.callback_data
        for row in bot.BUILD_INLINE.inline_keyboard
        for button in row
        if button.callback_data and button.callback_data.startswith("build:")
    }
    assert actual_build_callbacks == BUILD_CALLBACKS


if __name__ == "__main__":
    test_callback_handlers_registered()
    print("RUNTIME_CALLBACK_ROUTES_OK")
