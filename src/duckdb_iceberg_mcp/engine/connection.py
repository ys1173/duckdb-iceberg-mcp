import duckdb

from duckdb_iceberg_mcp.config import Settings

_EXTENSIONS = ["httpfs", "iceberg", "aws"]


def _bootstrap(conn: duckdb.DuckDBPyConnection) -> None:
    for ext in _EXTENSIONS:
        conn.execute(f"INSTALL {ext}; LOAD {ext};")
    # Allow DuckDB to glob the metadata dir to locate the latest Iceberg version
    # when no version-hint.text is present. Safe for read-only workloads.
    conn.execute("SET unsafe_enable_version_guessing = true;")


def new_connection(config: Settings) -> duckdb.DuckDBPyConnection:
    """Create a bootstrapped in-memory DuckDB connection with the catalog configured."""
    conn = duckdb.connect(":memory:")
    _bootstrap(conn)

    from duckdb_iceberg_mcp.catalog.glue import setup
    setup(conn, config)

    return conn
