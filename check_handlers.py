import ast
from pathlib import Path

source = Path("bot.py").read_text()
tree = ast.parse(source)
commands = []
command_start = False
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "CommandStart":
        command_start = True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Command" and node.args:
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            commands.append(value.value)
expected = {
    "founding", "country", "progress", "top", "upgrade", "build", "collect", "mobilize",
    "market", "buy", "build_base", "spy", "attack", "defend", "wars", "action", "year", "news",
    "myid", "guide", "policy", "history", "alliances", "alliance_create", "alliance_join",
    "alliance_leave", "alliance_info", "trade", "trade_offer", "trade_accept", "trade_reject",
    "world", "world_event", "war_history", "set_year", "seed_alliances", "give_points", "set_stat", "kick", "transfer", "help", "premium", "premium_grant", "raid_status",
    "pmc_create", "pmc_help", "pmc_profile", "pmc_list", "pmc_request", "pmc_requests", "pmc_accept", "pmc_reject", "pmc_fund", "pmc_recruit", "pmc_sanction",
}
missing = expected - set(commands)
assert command_start, "missing CommandStart handler"
assert not missing, f"missing command handlers: {sorted(missing)}"
print(f"COMMAND HANDLERS: OK ({len(set(commands))} commands)")

import db
required_db = [
    "apply_upgrade", "apply_base", "apply_spy_operation", "apply_collect", "apply_purchase",
    "apply_mobilization", "apply_action_result", "apply_war_result", "create_pending_war", "get_pending_war", "list_pending_wars_for_attacker", "claim_pending_war", "reset_pending_war", "complete_pending_war", "create_world_event",
    "get_world_events", "get_latest_world_event_created_at", "get_premium_balance", "get_premium_items", "grant_premium", "purchase_premium", "consume_premium_item", "create_trade_contract", "accept_trade_contract", "reject_trade_contract",
    "create_alliance", "join_alliance", "leave_alliance", "transfer_country", "delete_country", "get_war_history", "create_country_statement", "get_recent_country_statements", "create_diplomatic_pact", "list_diplomatic_pacts", "resolve_diplomatic_pact", "create_country_sanction", "get_active_country_sanctions", "list_country_sanctions", "set_tax_rate", "set_labor_focus",
    "create_pmc", "get_pmc", "get_pmc_by_owner", "list_active_pmcs", "create_pmc_request", "list_pmc_requests", "get_pmc_request",
    "resolve_pmc_request", "recruit_pmc", "sanction_pmc", "fund_pmc",
]
missing_db = [name for name in required_db if not hasattr(db, name)]
assert not missing_db, f"missing db functions: {missing_db}"
print("DATABASE API: OK")
