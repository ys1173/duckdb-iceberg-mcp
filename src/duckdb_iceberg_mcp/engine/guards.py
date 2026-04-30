from sqlglot import exp
from sqlglot import parse
from sqlglot.errors import ParseError

# Structured statement types that are always read-only.
_SAFE_TYPES = (
    exp.Select,
    exp.Describe,
    exp.Use,
    exp.Set,
)

# sqlglot falls back to exp.Command for EXPLAIN and SHOW — whitelist by keyword.
_SAFE_COMMANDS = frozenset({"EXPLAIN", "SHOW"})


def _is_safe(stmt: exp.Expression) -> bool:
    if isinstance(stmt, _SAFE_TYPES):
        return True
    if isinstance(stmt, exp.Command):
        return stmt.this.upper() in _SAFE_COMMANDS
    return False


def is_write_statement(sql: str) -> bool:
    """Return True if sql contains any write or DDL operation.

    Unparseable SQL is treated as a write (conservative / fail-closed).
    """
    try:
        statements = parse(sql)
    except ParseError:
        return True

    for stmt in statements:
        if stmt is None:
            continue
        if not _is_safe(stmt):
            return True
    return False


def is_select_only(sql: str) -> bool:
    """Return True when every statement is a plain SELECT (safe to wrap with LIMIT)."""
    try:
        statements = parse(sql)
    except ParseError:
        return False
    return all(isinstance(s, exp.Select) for s in statements if s is not None)
