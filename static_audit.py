import ast
from pathlib import Path

root = Path(__file__).parent
bot_tree = ast.parse((root / "bot.py").read_text())
db_tree = ast.parse((root / "db.py").read_text())

def function_names(tree):
    return {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

db_names = function_names(db_tree)
commands = []
handler_names = []
for node in ast.walk(bot_tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        handler_names.append(node.name)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Command" and node.args:
        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            commands.append(node.args[0].value)
missing_db = []
for node in ast.walk(bot_tree):
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "db":
        if node.attr.startswith("__"):
            continue
        if node.attr not in db_names and node.attr not in {"DB_PATH"}:
            missing_db.append((node.lineno, node.attr))
print(f"COMMAND_COUNT={len(commands)}")
print(f"DUPLICATE_COMMANDS={sorted({c for c in commands if commands.count(c) > 1})}")
print(f"DUPLICATE_HANDLER_NAMES={sorted({n for n in handler_names if handler_names.count(n) > 1})}")
print(f"MISSING_DB_REFERENCES={sorted(set(missing_db))}")
assert not {c for c in commands if commands.count(c) > 1}
assert not {n for n in handler_names if handler_names.count(n) > 1}
assert not missing_db
print("STATIC_AUDIT_OK")
