"""
Smoke test for easy mode against real AWS Glue + Iceberg on S3.

Usage:
    cp .env.easy .env          # fill in your AWS details first
    .venv/bin/python scripts/smoke_test.py

Or with inline env vars:
    AWS_REGION=us-east-1 AWS_PROFILE=myprofile \
    CATALOG_TYPE=glue \
    .venv/bin/python scripts/smoke_test.py
"""

import os
import sys
import textwrap

# Allow running without installing: add src/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from duckdb_iceberg_mcp.config import get_settings
from duckdb_iceberg_mcp.engine.connection import new_connection
from duckdb_iceberg_mcp.tools.query import run_query
from duckdb_iceberg_mcp.tools.schema import describe_table, list_tables


def hr(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print("─" * 60)


def main() -> None:
    settings = get_settings()

    print(f"mode        : {settings.mcp_mode}")
    print(f"transport   : {settings.mcp_transport}")
    print(f"catalog     : {settings.catalog_type}")
    print(f"aws_region  : {settings.aws_region}")
    print(f"write_mode  : {settings.write_mode}")

    hr("1 / 4  Connecting to DuckDB + loading extensions")
    conn = new_connection(settings)
    print("OK")

    hr("2 / 4  list_tables()")
    tables_csv = list_tables(conn, settings)
    print(tables_csv[:2000])

    # Parse first table name for the next tests
    first_table = None
    first_location = None
    lines = [l for l in tables_csv.splitlines() if l and not l.startswith("database")]
    if lines:
        parts = lines[0].split(",")
        if len(parts) >= 2:
            first_table = f"{parts[0]}.{parts[1]}"
        if len(parts) >= 4:
            first_location = parts[3].strip()

    if not first_table:
        print("No tables found — check your Glue credentials and region.")
        return

    hr(f"3 / 4  describe_table('{first_table}')")
    schema_out = describe_table(conn, settings, first_table)
    print(schema_out[:2000])

    if first_location:
        hr(f"4 / 4  query_lakehouse — SELECT first 5 rows of {first_table}")
        sql = f"SELECT * FROM iceberg_scan('{first_location}') LIMIT 5"
        print(f"SQL: {sql}\n")
        result = run_query(sql, conn, settings)
        print(result[:3000])
    else:
        hr("4 / 4  query_lakehouse — SKIPPED (no iceberg_location in table list)")
        print("Run a query manually:")
        print("  SELECT * FROM iceberg_scan('s3://your-bucket/path/to/table')")

    print("\n✓ smoke test complete")


if __name__ == "__main__":
    main()
