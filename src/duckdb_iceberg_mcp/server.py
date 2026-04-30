import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from duckdb_iceberg_mcp.auth.middleware import BearerAuthMiddleware
from duckdb_iceberg_mcp.auth.session import SessionPool, current_sub, current_token
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


def build_server(config: Settings, pool: SessionPool) -> FastMCP:
    mcp = FastMCP(
        "duckdb-mcp",
        host=config.mcp_host,
        port=config.mcp_port,
        transport_security=_transport_security(config),
    )

    @mcp.tool()
    async def query_lakehouse(sql: str) -> str:
        """Execute a SQL query. Use read_parquet() or iceberg_scan() for S3 paths,
        or use the glue_table tool first to register a Glue table by name."""
        conn = pool.get(sub=current_sub.get(), token=current_token.get())
        return _qtool.run_query(sql, conn, config)

    @mcp.tool()
    async def list_tables(database: str = "") -> str:
        """List available tables. Optionally filter by database name."""
        conn = pool.get(sub=current_sub.get(), token=current_token.get())
        return _stool.list_tables(conn, config, database)

    @mcp.tool()
    async def describe_table(table_name: str) -> str:
        """Describe a table's schema. Use 'database.table' format for Glue."""
        conn = pool.get(sub=current_sub.get(), token=current_token.get())
        return _stool.describe_table(conn, config, table_name)

    if config.catalog_type == "glue":
        @mcp.tool()
        async def glue_table(table_name: str) -> str:
            """Register a Glue Iceberg table as a queryable DuckDB view.

            Resolves the actual data files from the Iceberg manifest (handles
            tables where data files live outside the Glue-registered table root).

            Usage: glue_table('database.table_name')
            After calling this, query with: SELECT * FROM database__table_name
            """
            conn = pool.get(sub=current_sub.get(), token=current_token.get())
            return _stool.register_glue_table(conn, config, table_name)

    return mcp


def main() -> None:
    config = get_settings()
    pool = SessionPool(config)
    mcp = build_server(config, pool)

    if config.mcp_transport == "stdio":
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
