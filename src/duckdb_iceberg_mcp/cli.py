"""SQL-first CLI sharing the MCP engine and configuration."""

import argparse
import getpass
import os
from pathlib import Path
import sys

from duckdb_iceberg_mcp.config import get_settings
from duckdb_iceberg_mcp.engine.connection import new_connection
from duckdb_iceberg_mcp.onboarding import extract_connection, write_env
from duckdb_iceberg_mcp.tools.query import run_query
from duckdb_iceberg_mcp.tools.schema import (
    describe_table,
    list_tables,
    register_glue_table,
)


def _setup(args: argparse.Namespace) -> int:
    sql = (
        sys.stdin.read()
        if args.from_sql == "-"
        else Path(args.from_sql).read_text(encoding="utf-8")
    )
    values = extract_connection(sql)
    for key in ("FFWD_CLIENT_ID", "FFWD_CLIENT_SECRET"):
        values[key] = os.environ.get(key) or values[key]
        if not values[key]:
            if not sys.stdin.isatty():
                raise ValueError(
                    f"Set {key} in the environment, or run setup interactively"
                )
            values[key] = (
                getpass.getpass("Agent key secret: ")
                if key.endswith("SECRET")
                else input("Agent key ID: ").strip()
            )
        if not values[key] or values[key].startswith("<"):
            raise ValueError(f"{key} is required")
    output = Path(args.env_file or os.environ.get("DUCKDB_MCP_ENV_FILE", ".env"))
    write_env(output, values)
    print(f"Connection configuration saved to {output.resolve()} (credentials hidden).")
    print(
        "Run duckdb-iceberg check with the same --env-file to test catalog and S3 access."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Query FFWD/Iceberg using local DuckDB; MCP is optional."
    )
    # Accept --env-file both before and after the subcommand.
    parser.add_argument(
        "--env-file", help="Explicit .env path (or DUCKDB_MCP_ENV_FILE)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "setup", help="Extract FFWD's copied SQL snippet; never executes the snippet"
    )
    setup.add_argument("--from-sql", required=True, help="Snippet file, or - for stdin")
    check = commands.add_parser(
        "check", help="Check catalog discovery and read one row from S3"
    )
    check.add_argument(
        "--table", help="Table to read; otherwise choose the first discovered table"
    )
    tables = commands.add_parser("tables", help="List tables")
    tables.add_argument("--database", default="")
    describe = commands.add_parser("describe", help="Describe a table")
    describe.add_argument("table")
    query = commands.add_parser("query", help="Run one SQL statement and return CSV")
    query.add_argument("sql", nargs="?", help="SQL, or read from --file")
    query.add_argument("--file", help="SQL file")
    commands.add_parser("shell", help="Interactive SQL shell; .quit exits")
    for sub in commands.choices.values():
        sub.add_argument("--env-file", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    conn = None
    try:
        if args.command == "setup":
            return _setup(args)
        config = get_settings(args.env_file)
        conn = new_connection(config)
        if args.command == "tables":
            result = list_tables(conn, config, args.database)
        elif args.command == "describe":
            result = describe_table(conn, config, args.table)
        elif args.command == "query":
            if bool(args.sql) == bool(args.file):
                raise ValueError("Provide either SQL or --file")
            sql = Path(args.file).read_text(encoding="utf-8") if args.file else args.sql
            result = run_query(sql, conn, config)
        elif args.command == "check":
            print("DuckDB extensions and catalog connection: OK")
            result = list_tables(conn, config)
            if result.startswith("Error:"):
                print(result, file=sys.stderr)
                return 1
            print(result, end="" if result.endswith("\n") else "\n")
            if config.catalog_type != "rest" and not args.table:
                print("Supply --table database.table to verify Glue storage access.")
                return 0
            table = args.table
            if not table:
                rows = conn.execute("SHOW ALL TABLES").fetchall()
                rows = [r for r in rows if r[0] == config.catalog_name]
                if not rows:
                    print(
                        "Catalog access OK; no tables exist, so S3 data access could not be verified."
                    )
                    return 0
                table = ".".join(
                    '"' + str(p).replace('"', '""') + '"' for p in rows[0][:3]
                )
            # Check identifiers before building a customer-supplied query.
            if args.table:
                schema = describe_table(conn, config, args.table)
                if schema.startswith("Error:") or "not found" in schema.lower():
                    raise ValueError("Check table could not be described")
                if config.catalog_type == "glue":
                    registration = register_glue_table(conn, config, args.table)
                    if registration.startswith("Error:"):
                        raise ValueError(registration)
                    table = args.table.replace(".", "__")
            result = run_query(f"SELECT * FROM {table} LIMIT 1", conn, config)
            if not result.startswith("Error:"):
                print("Table/S3 read: OK (row contents not displayed)")
                return 0
        else:
            print(
                "Connected. End SQL with ;. Use .quit to exit. Results are bounded CSV."
            )
            pending = []
            while True:
                try:
                    line = input("sql> " if not pending else "...> ")
                except EOFError:
                    break
                if line.strip() in {".quit", ".exit"}:
                    break
                pending.append(line)
                if line.rstrip().endswith(";"):
                    print(run_query("\n".join(pending), conn, config), end="\n")
                    pending.clear()
            return 0
        print(result, end="" if result.endswith("\n") else "\n")
        return 1 if result.startswith("Error:") else 0
    except (Exception, KeyboardInterrupt) as exc:
        # Never print a Settings ValidationError containing submitted secret values.
        from pydantic import ValidationError

        if isinstance(exc, ValidationError):
            message = "Invalid configuration: " + ", ".join(
                ".".join(map(str, e["loc"])) for e in exc.errors()
            )
        else:
            message = str(exc) or "Interrupted"
        if "config" in locals():
            message = config.redact(message)
        print("Error: " + message, file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
