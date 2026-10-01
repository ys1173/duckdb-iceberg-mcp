import duckdb

from duckdb_iceberg_mcp.config import Settings


def _bootstrap(conn: duckdb.DuckDBPyConnection, config: Settings) -> None:
    extensions = ["httpfs", "iceberg"]
    if config.catalog_type == "glue" or config.access_delegation_mode == "none":
        extensions.append("aws")
    for ext in extensions:
        conn.execute(f"INSTALL {ext}; LOAD {ext};")


def new_connection(config: Settings) -> duckdb.DuckDBPyConnection:
    """Create a bootstrapped in-memory DuckDB connection with the catalog configured."""
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("SET memory_limit = ?", [config.duckdb_memory_limit])
        conn.execute("SET threads = ?", [config.duckdb_threads])
        _bootstrap(conn, config)
        if config.catalog_type == "rest":
            from duckdb_iceberg_mcp.catalog.rest import setup
        else:
            from duckdb_iceberg_mcp.catalog.glue import setup
        setup(conn, config)
        return conn
    except Exception as exc:
        conn.close()
        raise RuntimeError("Connection failed: " + config.redact(str(exc))) from None
