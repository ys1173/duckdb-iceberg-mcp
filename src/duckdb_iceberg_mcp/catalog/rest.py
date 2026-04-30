# REST catalog support (Polaris, Lakekeeper) — deferred, not yet wired up.
# Kept here as a starting point for a future implementation.

import duckdb

from duckdb_iceberg_mcp.config import Settings


def _e(val: str) -> str:
    return val.replace("'", "''")


def setup(conn: duckdb.DuckDBPyConnection, config: Settings, token: str = "") -> None:
    """Configure the Iceberg REST catalog secret (Polaris, Lakekeeper, etc.)."""
    if not config.catalog_endpoint:
        return
    effective_token = token or config.catalog_token
    conn.execute(f"""
        CREATE OR REPLACE SECRET __iceberg_rest (
            TYPE ICEBERG,
            TOKEN '{_e(effective_token)}',
            ENDPOINT '{_e(config.catalog_endpoint)}'
        )
    """)
