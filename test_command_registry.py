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
    assert len(callbacks) == len(set(callbacks)), f"duplicate message handlers: {callbacks}"
    required = {
        "cmd_start", "cmd_founding", "cmd_country", "cmd_progress", "cmd_top", "cmd_upgrade",
        "cmd_build", "cmd_collect", "cmd_mobilize", "cmd_market", "cmd_buy", "cmd_build_base",
        "cmd_spy", "cmd_attack", "cmd_defend", "cmd_wars", "cmd_action", "cmd_year", "cmd_news", "cmd_myid",
        "cmd_guide", "cmd_policy", "cmd_history", "cmd_alliances", "cmd_alliance_create",
        "cmd_alliance_join", "cmd_alliance_leave", "cmd_alliance_info", "cmd_trade",
        "cmd_trade_offer", "cmd_trade_accept", "cmd_trade_reject", "cmd_world", "cmd_war_history", "cmd_statement", "cmd_statements", "cmd_help",
        "cmd_set_year", "cmd_seed_alliances", "cmd_give_points", "cmd_set_stat", "cmd_kick",
        "cmd_transfer", "cmd_premium", "cmd_premium_grant", "cmd_raid_status", "cmd_world_event",
        "cmd_pmc_create", "cmd_pmc_help", "cmd_pmc_profile", "cmd_pmc_list", "cmd_pmc_request",
        "cmd_pmc_requests", "cmd_pmc_accept", "cmd_pmc_reject", "cmd_pmc_fund", "cmd_pmc_recruit", "cmd_pmc_sanction",
    }
    assert required.issubset(set(callbacks))


if __name__ == "__main__":
    test_command_handlers_are_unique_and_present()
    print("COMMAND_REGISTRY_OK")
