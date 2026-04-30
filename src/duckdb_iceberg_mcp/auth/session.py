from contextvars import ContextVar

import duckdb

from duckdb_iceberg_mcp.config import Settings
from duckdb_iceberg_mcp.engine.connection import new_connection

# Set by auth middleware on each request; read by tool handlers.
# Defaults cover easy-mode stdio (no HTTP request, no middleware).
current_sub: ContextVar[str] = ContextVar("current_sub", default="local-user")
current_token: ContextVar[str] = ContextVar("current_token", default="")


class SessionPool:
    """Single shared DuckDB connection for all authenticated users.

    Multi-tenant per-user session isolation is deferred — JWT auth still
    validates every request, but all users share one DuckDB instance.
    """

    def __init__(self, config: Settings) -> None:
        self._conn = new_connection(config)

    def get(self, sub: str = "", token: str = "") -> duckdb.DuckDBPyConnection:
        return self._conn
