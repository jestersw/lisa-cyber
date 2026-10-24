"""Guard against SQL injection creeping in (#53 follow-up).

All database access in this backend goes through the SQLAlchemy ORM, which binds
values as parameters (data, never SQL text). The only safe way to drop to raw
SQL is `text("<constant>")` / `execute("<constant>")` with a *literal* string and
no interpolation. This scanner fails CI if someone introduces raw SQL built from
runtime data — an f-string, string concatenation, `%`-formatting or `.format()`
inside a `text(...)` or `.execute(...)` call — which is how SQL injection would
slip in.

It is a lightweight AST check over backend/app, not a full taint analysis: it
flags the dangerous *shape* (raw SQL from a non-literal string), which is exactly
what we never want to see. Run: `python scripts/check_no_raw_sql.py`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Calls that take raw SQL. A bare string literal argument is fine; anything
# computed is not.
_RAW_SQL_CALLS = {"text", "execute", "executemany", "exec_driver_sql"}


def _is_literal_str(node: ast.expr) -> bool:
    """True if the node is a plain string literal (incl. implicit concatenation
    of literals), i.e. contains no runtime data."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    # "a" "b" parses as a single Constant, but be defensive about JoinedStr etc.
    return False


def _callee_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast API
        name = _callee_name(node.func)
        if name in _RAW_SQL_CALLS and node.args:
            arg = node.args[0]
            # Acceptable arguments: a plain string literal, or a nested raw-SQL
            # call like execute(text("...")) — the inner text(...) is visited and
            # validated on its own, so we don't double-flag the wrapper.
            inner_is_sql_call = (
                isinstance(arg, ast.Call) and _callee_name(arg.func) in _RAW_SQL_CALLS
            )
            # Anything else (f-string, concatenation, %/.format(), a variable)
            # means the query text is built from runtime data.
            if not _is_literal_str(arg) and not inner_is_sql_call:
                self.violations.append(
                    (node.lineno, f"{name}(...) with a non-literal SQL argument")
                )
        self.generic_visit(node)


def scan(root: Path) -> list[str]:
    problems: list[str] = []
    for py in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - would fail lint first
            problems.append(f"{py}: could not parse ({exc})")
            continue
        visitor = _Visitor(py)
        visitor.visit(tree)
        for lineno, msg in visitor.violations:
            problems.append(f"{py}:{lineno}: {msg}")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "app"
    problems = scan(root)
    if problems:
        print("Potential raw-SQL / SQL-injection risk (use the ORM, or text() with")
        print("a literal string only):")
        for p in problems:
            print(f"  {p}")
        return 1
    print("OK: no raw SQL built from runtime data under app/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
