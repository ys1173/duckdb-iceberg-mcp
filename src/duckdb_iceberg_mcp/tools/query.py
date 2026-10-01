import csv
import io
import threading

import duckdb

from duckdb_iceberg_mcp.config import Settings
from duckdb_iceberg_mcp.engine.guards import (
    is_select_only,
    is_write_statement,
    statement,
)


def run_query(sql: str, conn: duckdb.DuckDBPyConnection, config: Settings) -> str:
    try:
        parsed = statement(sql)
    except ValueError as exc:
        return f"Error: {exc}"
    write = is_write_statement(sql)
    if write and not config.write_enabled:
        return "Error: Write operations are disabled. Set WRITE_MODE=enabled (full mode only) to allow writes."
    normalized = parsed.sql(dialect="duckdb")
    limited_sql = (
        f"SELECT * FROM ({normalized}) AS __q LIMIT {config.max_rows + 1}"
        if is_select_only(sql)
        else normalized
    )
    expired = threading.Event()

    def interrupt() -> None:
        expired.set()
        conn.interrupt()

    timer = threading.Timer(config.query_timeout_seconds, interrupt)
    timer.daemon = True
    try:
        timer.start()
        result = conn.execute(limited_sql)
        if write:
            return "OK: statement executed successfully."
        rows = result.fetchmany(config.max_rows + 1)
        columns = [column[0] for column in result.description]
    except Exception as exc:
        if expired.is_set():
            return (
                "Error: Query timed out. Narrow the time range or simplify the query."
            )
        return "Error: " + config.redact(str(exc))
    finally:
        timer.cancel()
        timer.join()
    truncated = len(rows) > config.max_rows
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows[: config.max_rows])
    result_text = output.getvalue()
    if len(result_text) > config.max_chars:
        result_text = (
            result_text[: config.max_chars]
            + "\n... [truncated: result exceeded character limit]"
        )
    prefix = (
        f"[TRUNCATED: showing first {config.max_rows} of more rows]\n"
        if truncated
        else ""
    )
    return prefix + result_text
