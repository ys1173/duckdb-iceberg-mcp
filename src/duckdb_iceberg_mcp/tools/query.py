import duckdb

from duckdb_iceberg_mcp.config import Settings
from duckdb_iceberg_mcp.engine.guards import is_select_only, is_write_statement


def run_query(sql: str, conn: duckdb.DuckDBPyConnection, config: Settings) -> str:
    if is_write_statement(sql):
        if not config.write_enabled:
            return (
                "Error: Write operations are disabled. "
                "Set WRITE_MODE=enabled (full mode only) to allow writes."
            )
        try:
            conn.execute(sql)
            return "OK: statement executed successfully."
        except Exception as exc:
            return f"Error: {exc}"

    # Read path: wrap SELECT queries with a row-limit guard.
    limited_sql = (
        f"SELECT * FROM ({sql}) AS __q LIMIT {config.max_rows + 1}"
        if is_select_only(sql)
        else sql
    )

    try:
        df = conn.execute(limited_sql).df()
    except Exception as exc:
        return f"Error: {exc}"

    truncated = len(df) > config.max_rows
    if truncated:
        df = df.head(config.max_rows)

    result = df.to_csv(index=False)

    if len(result) > config.max_chars:
        result = result[: config.max_chars] + "\n... [truncated: result exceeded character limit]"

    prefix = f"[TRUNCATED: showing first {config.max_rows} of more rows]\n" if truncated else ""
    return prefix + result
