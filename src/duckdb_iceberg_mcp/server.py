import argparse
import asyncio
import sys

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from duckdb_iceberg_mcp.auth.middleware import BearerAuthMiddleware
from duckdb_iceberg_mcp.auth.session import (
    SessionPool,
    current_session_id,
    normalize_session_id,
)
from duckdb_iceberg_mcp.config import Settings, get_settings
from duckdb_iceberg_mcp.tools import query as _qtool
from duckdb_iceberg_mcp.tools import schema as _stool


def _transport_security(config: Settings) -> TransportSecuritySettings | None:
    hosts = [h.strip() for h in config.mcp_allowed_hosts.split(",") if h.strip()]
    if hosts:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
        )
    return None  # let FastMCP decide based on host


def _pool_session_key(config: Settings) -> str:
    """Resolve DuckDB pool key for this request (HTTP: middleware; stdio: env)."""
    raw = current_session_id.get()
    if raw:
        return raw
    return normalize_session_id(config.mcp_session_id)


def build_server(config: Settings, pool: SessionPool) -> FastMCP:
    mcp = FastMCP(
        "duckdb-mcp",
        instructions="Discover tables first. For REST catalogs query catalog.schema.table directly; no registration is needed. Prefer explicit columns and bounded time ranges. Credentials are configured by the operator, never requested in SQL.",
        host=config.mcp_host,
        port=config.mcp_port,
        transport_security=_transport_security(config),
    )

    async def invoke(function, *args) -> str:
        key = _pool_session_key(config)

        def work() -> str:
            try:
                with pool.lease(key) as conn:
                    return function(conn, config, *args)
            except Exception as exc:
                return "Error: " + config.redact(str(exc))

        return await asyncio.to_thread(work)

    @mcp.tool()
    async def query_lakehouse(sql: str) -> str:
        """Execute one SQL statement. For FFWD use ffwd.namespace.table directly.
        Prefer a time filter on _ts and explicit columns. Results and runtime are bounded."""
        return await invoke(
            lambda conn, cfg, text: _qtool.run_query(text, conn, cfg), sql
        )

    @mcp.tool()
    async def list_tables(database: str = "") -> str:
        """Discover available tables. For REST, database filters the catalog (usually ffwd)."""
        return await invoke(_stool.list_tables, database)

    @mcp.tool()
    async def describe_table(table_name: str) -> str:
        """Describe columns. Use ffwd.namespace.table for FFWD, database.table for Glue."""
        return await invoke(_stool.describe_table, table_name)

    if config.catalog_type == "glue":

        @mcp.tool()
        async def glue_table(table_name: str) -> str:
            """Register a Glue Iceberg table as a queryable DuckDB view.

            Uses Glue's authoritative metadata pointer and native Iceberg scanning.

            Usage: glue_table('database.table_name')
            After calling this, query with: SELECT * FROM database__table_name
            """
            return await invoke(_stool.register_glue_table, table_name)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="DuckDB Iceberg MCP server")
    parser.add_argument("--env-file", help="Explicit environment-file path")
    args = parser.parse_args()
    try:
        config = get_settings(args.env_file)
    except Exception:
        print(
            "Invalid configuration; check your environment variables and --env-file path.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    pool = SessionPool(config)
    mcp = build_server(config, pool)

    try:
        run_server(config, mcp)
    finally:
        pool.close_all()


def run_server(config: Settings, mcp: FastMCP) -> None:

    if config.mcp_transport == "stdio":
        # One stable key per client process; override with MCP_SESSION_ID for isolation.
        current_session_id.set(normalize_session_id(config.mcp_session_id))
        mcp.run(transport="stdio")
        return

    # HTTP or SSE: wrap with auth middleware and hand off to uvicorn.
    # We wrap manually rather than using app.add_middleware() because
    # Starlette's add_middleware wraps in BaseHTTPMiddleware which
    # buffers responses — incompatible with SSE streaming.
    if config.mcp_transport == "sse":
        inner = mcp.sse_app()
    else:
        inner = mcp.streamable_http_app()

    app = BearerAuthMiddleware(inner, config=config)
    uvicorn.run(app, host=config.mcp_host, port=config.mcp_port)


if __name__ == "__main__":
    main()
