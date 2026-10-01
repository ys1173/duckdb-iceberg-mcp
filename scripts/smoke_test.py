"""Compatibility wrapper for the shared connection check.

Usage: python scripts/smoke_test.py --env-file .env.ffwd --table ffwd.network.network_logs
For Glue: use --table database.table with a configured Glue environment.
"""

import os
import sys

# Allow running without installing: add src/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from duckdb_iceberg_mcp.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["check", *sys.argv[1:]]))
