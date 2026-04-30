import re

import duckdb

from duckdb_iceberg_mcp.config import Settings

_IDENT_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$"
)


def list_tables(conn: duckdb.DuckDBPyConnection, config: Settings, database: str = "") -> str:
    if config.catalog_type == "glue":
        from duckdb_iceberg_mcp.catalog.glue import list_tables as _glue_list
        return _glue_list(config, database)
    return _list_tables_duckdb(conn, database)


def describe_table(conn: duckdb.DuckDBPyConnection, config: Settings, table_name: str) -> str:
    if not _IDENT_RE.match(table_name):
        return "Error: invalid table name — use 'table', 'schema.table', or 'catalog.schema.table'."
    if config.catalog_type == "glue":
        from duckdb_iceberg_mcp.catalog.glue import describe_table as _glue_describe
        return _glue_describe(config, table_name)
    return _describe_table_duckdb(conn, table_name)


def register_glue_table(conn: duckdb.DuckDBPyConnection, config: Settings, table_name: str) -> str:
    """Resolve an Iceberg table's data files via manifest and register a DuckDB view.

    The view is named 'database__table' (double underscore) to avoid catalog
    conflicts while still being easy to type in queries.
    """
    if not _IDENT_RE.match(table_name):
        return "Error: invalid table name — use 'database.table_name'."

    parts = table_name.split(".")
    if len(parts) != 2:
        return "Error: Glue tables require 'database.table_name' format."

    database, table = parts
    from duckdb_iceberg_mcp.catalog.glue import describe_table as _glue_describe, resolve_iceberg_files

    # Get the S3 location from Glue
    schema_out = _glue_describe(config, table_name)
    location_line = next((l for l in schema_out.splitlines() if l.startswith("iceberg_location:")), "")
    if not location_line:
        return f"Error: could not determine S3 location for '{table_name}'."
    s3_location = location_line.split(":", 1)[1].strip()

    # Resolve actual data files from the Iceberg manifest
    try:
        data_files = resolve_iceberg_files(config, s3_location)
    except Exception as exc:
        return f"Error resolving Iceberg manifest: {exc}"

    if not data_files:
        return f"No data files found for '{table_name}' (table may be empty)."

    view_name = f"{database}__{table}"
    paths_sql = ", ".join(f"'{p}'" for p in data_files)
    conn.execute(
        f"CREATE OR REPLACE VIEW {view_name} AS "
        f"SELECT * FROM read_parquet([{paths_sql}], union_by_name=true)"
    )
    return (
        f"Registered view '{view_name}' — {len(data_files)} data file(s).\n"
        f"Query with: SELECT * FROM {view_name}"
    )


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
