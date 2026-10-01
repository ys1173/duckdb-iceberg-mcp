"""Native Iceberg REST catalog access, including FFWD/Lakekeeper."""

import re
from urllib.parse import urlparse

import duckdb

from duckdb_iceberg_mcp.config import Settings


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def setup(conn: duckdb.DuckDBPyConnection, config: Settings) -> None:
    required = {
        "FFWD_CATALOG_ENDPOINT": config.catalog_endpoint,
        "FFWD_OAUTH_TOKEN_ENDPOINT": config.oauth_token_endpoint,
        "FFWD_WAREHOUSE_ID": config.warehouse_id,
        "FFWD_CLIENT_ID": config.client_id,
        "FFWD_CLIENT_SECRET": config.client_secret.get_secret_value(),
    }
    missing = [
        name for name, value in required.items() if not value or value.startswith("<")
    ]
    if missing:
        raise ValueError("Missing connection settings: " + ", ".join(missing))
    for endpoint in (config.catalog_endpoint, config.oauth_token_endpoint):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Catalog and OAuth endpoints must be HTTP(S) URLs without embedded credentials"
            )
        if parsed.scheme == "http" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError(
                "HTTPS is required for non-local catalog and OAuth endpoints"
            )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", config.catalog_name):
        raise ValueError("CATALOG_NAME must be a simple SQL identifier")
    conn.execute(
        "CREATE OR REPLACE SECRET ffwd_iceberg (TYPE iceberg, "
        f"CLIENT_ID {_literal(config.client_id)}, "
        f"CLIENT_SECRET {_literal(config.client_secret.get_secret_value())}, "
        f"OAUTH2_SERVER_URI {_literal(config.oauth_token_endpoint)})"
    )
    options = [
        "TYPE iceberg",
        "SECRET ffwd_iceberg",
        f"ENDPOINT {_literal(config.catalog_endpoint)}",
        f"ACCESS_DELEGATION_MODE {_literal(config.access_delegation_mode)}",
    ]
    if config.access_delegation_mode == "none":
        from duckdb_iceberg_mcp.catalog.glue import setup as setup_storage

        setup_storage(conn, config)
    conn.execute(
        f"ATTACH {_literal(config.warehouse_id)} AS {config.catalog_name} ("
        + ", ".join(options)
        + ")"
    )
