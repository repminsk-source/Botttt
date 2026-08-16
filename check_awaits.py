import ast
from pathlib import Path

source = Path(__file__).with_name("bot.py").read_text()
tree = ast.parse(source)
parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
issues = []
for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    if not isinstance(node.func, ast.Attribute) or not isinstance(node.func.value, ast.Name) or node.func.value.id != "db":
        continue
    parent = parents.get(node)
    if isinstance(parent, ast.Await):
        continue
    if isinstance(parent, ast.Attribute):
        continue
    issues.append((node.lineno, node.func.attr))
print("UNAWAITED_DB_CALLS=", sorted(set(issues)))
assert not issues
print("AWAIT_AUDIT_OK")
