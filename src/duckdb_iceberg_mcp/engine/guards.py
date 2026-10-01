from sqlglot import exp, parse
from sqlglot.errors import SqlglotError


def statement(sql: str) -> exp.Expression:
    try:
        statements = [s for s in parse(sql, read="duckdb") if s is not None]
    except SqlglotError:
        raise ValueError("Invalid or unsupported SQL") from None
    if len(statements) != 1:
        raise ValueError("Exactly one SQL statement is required")
    return statements[0]


def _is_safe(stmt: exp.Expression) -> bool:
    if isinstance(stmt, (exp.Query, exp.Describe, exp.Show)):
        return not any(
            isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop))
            for node in stmt.walk()
        )
    if isinstance(stmt, exp.Command):
        name = str(stmt.this).upper()
        if name == "SHOW":
            return True
        if name == "EXPLAIN":
            inner = str(stmt.expression.this) if stmt.expression is not None else ""
            if inner.upper().startswith("ANALYZE "):
                inner = inner[8:]
            try:
                parsed = statement(inner)
                return isinstance(parsed, exp.Query) and _is_safe(parsed)
            except ValueError:
                return False
    return False


def is_write_statement(sql: str) -> bool:
    try:
        return not _is_safe(statement(sql))
    except ValueError:
        return True


def is_select_only(sql: str) -> bool:
    try:
        stmt = statement(sql)
        return isinstance(stmt, exp.Query) and _is_safe(stmt)
    except ValueError:
        return False
