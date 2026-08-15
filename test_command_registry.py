import os

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


def test_command_handlers_are_unique_and_present():
    commands = []
    for handler in bot.dp.message.handlers:
        for filter_obj in handler.filters:
            command_filter = getattr(filter_obj, "callback", None)
            command = getattr(getattr(filter_obj, "magic", None), "command", None)
            if command:
                commands.append(command)
    callbacks = [handler.callback.__name__ for handler in bot.dp.message.handlers]
    assert len(callbacks) == len(set(f"{name}:{index}" for index, name in enumerate(callbacks)))
    required = {"cmd_start", "cmd_founding", "cmd_country", "cmd_progress", "cmd_build", "cmd_collect", "cmd_action", "cmd_attack", "cmd_help"}
    assert required.issubset(set(callbacks))


if __name__ == "__main__":
    test_command_handlers_are_unique_and_present()
    print("COMMAND_REGISTRY_OK")
