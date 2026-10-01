import re

import duckdb

from duckdb_iceberg_mcp.config import Settings

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")


def list_tables(
    conn: duckdb.DuckDBPyConnection, config: Settings, database: str = ""
) -> str:
    if config.catalog_type == "glue":
        from duckdb_iceberg_mcp.catalog.glue import list_tables as _glue_list

        return _glue_list(config, database)
    return _list_tables_duckdb(conn, database)


def describe_table(
    conn: duckdb.DuckDBPyConnection, config: Settings, table_name: str
) -> str:
    if not _IDENT_RE.match(table_name):
        return "Error: invalid table name — use 'table', 'schema.table', or 'catalog.schema.table'."
    if config.catalog_type == "glue":
        from duckdb_iceberg_mcp.catalog.glue import describe_table as _glue_describe

        return _glue_describe(config, table_name)
    return _describe_table_duckdb(conn, table_name)


def register_glue_table(
    conn: duckdb.DuckDBPyConnection, config: Settings, table_name: str
) -> str:
    """Register a native Iceberg view using Glue's committed metadata pointer.

    The view is named 'database__table' (double underscore) to avoid catalog
    conflicts while still being easy to type in queries.
    """
    if not _IDENT_RE.match(table_name):
        return "Error: invalid table name — use 'database.table_name'."

    parts = table_name.split(".")
    if len(parts) != 2:
        return "Error: Glue tables require 'database.table_name' format."

    database, table = parts
    from duckdb_iceberg_mcp.catalog.glue import metadata_location

    try:
        location = metadata_location(config, database, table)
        escaped = location.replace("'", "''")
        view_name = f"{database}__{table}"
        conn.execute(
            f"CREATE OR REPLACE VIEW {view_name} AS "
            f"SELECT * FROM iceberg_scan('{escaped}')"
        )
        return f"Registered view '{view_name}'. Query with: SELECT * FROM {view_name}"
    except Exception as exc:
        return "Error registering Iceberg table: " + config.redact(str(exc))


def _list_tables_duckdb(conn: duckdb.DuckDBPyConnection, database: str = "") -> str:
    try:
        if database:
            df = conn.execute(
                "SELECT table_catalog, table_schema, table_name, table_type "
                "FROM information_schema.tables "
                "WHERE table_catalog = ? "
                "ORDER BY table_schema, table_name",
                [database],
            ).df()
        else:
            df = conn.execute(
                "SELECT table_catalog, table_schema, table_name, table_type "
                "FROM information_schema.tables "
                "ORDER BY table_catalog, table_schema, table_name"
            ).df()
        if df.empty:
            return "No tables found."
        return df.to_csv(index=False)
    except Exception as exc:
        return f"Error: {exc}"


def _describe_table_duckdb(conn: duckdb.DuckDBPyConnection, table_name: str) -> str:
    parts = table_name.split(".")
    try:
        if len(parts) == 3:
            catalog, schema, table = parts
            df = conn.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_catalog = ? AND table_schema = ? AND table_name = ? "
                "ORDER BY ordinal_position",
                [catalog, schema, table],
            ).df()
        elif len(parts) == 2:
            schema, table = parts
            df = conn.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? "
                "ORDER BY ordinal_position",
                [schema, table],
            ).df()
        else:
            df = conn.execute(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = ? "
                "ORDER BY ordinal_position",
                [table_name],
            ).df()

        if df.empty:
            return f"Table '{table_name}' not found or has no columns."
        return df.to_csv(index=False)
    except Exception as exc:
        return f"Error: {exc}"
