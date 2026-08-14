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
    "founding", "country", "top", "upgrade", "build", "collect", "mobilize",
    "market", "buy", "build_base", "spy", "attack", "wars", "action", "year", "news",
    "myid", "guide", "alliances", "alliance_create", "alliance_join", "alliance_leave",
    "alliance_info", "set_year", "seed_alliances", "give_points", "set_stat", "kick", "transfer", "help",
}
missing = expected - set(commands)
assert command_start, "missing CommandStart handler"
assert not missing, f"missing command handlers: {sorted(missing)}"
print(f"COMMAND HANDLERS: OK ({len(set(commands))} commands)")

import db
required_db = [
    "apply_upgrade", "apply_base", "apply_spy_operation", "apply_collect", "apply_purchase",
    "apply_mobilization", "apply_action_result", "apply_war_result",
]
missing_db = [name for name in required_db if not hasattr(db, name)]
assert not missing_db, f"missing db functions: {missing_db}"
print("DATABASE API: OK")
