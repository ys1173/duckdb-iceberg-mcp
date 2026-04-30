import duckdb
import pytest

from duckdb_iceberg_mcp.config import Settings
from duckdb_iceberg_mcp.tools.query import run_query


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE t AS "
        "SELECT i AS id, 'val_' || i AS name FROM range(1000) r(i)"
    )
    yield c
    c.close()


@pytest.fixture
def cfg():
    return Settings(mcp_mode="easy", max_rows=10, max_chars=10_000)


def test_basic_select(conn, cfg):
    result = run_query("SELECT id FROM t WHERE id < 5", conn, cfg)
    assert "id" in result
    assert "TRUNCATED" not in result


def test_row_limit_truncates(conn, cfg):
    result = run_query("SELECT * FROM t", conn, cfg)
    assert "TRUNCATED" in result
    lines = [l for l in result.strip().splitlines() if l]
    # header + 10 data rows + the TRUNCATED prefix line
    assert sum(1 for l in lines if "," in l) == 11  # header + 10 rows


def test_write_blocked_by_default(conn, cfg):
    result = run_query("INSERT INTO t VALUES (9999, 'injected')", conn, cfg)
    assert "disabled" in result.lower()


def test_write_allowed_when_enabled(conn):
    cfg = Settings(mcp_mode="full", jwks_url="https://example.com/.well-known/jwks.json", write_mode="enabled")
    result = run_query("INSERT INTO t VALUES (9999, 'inserted')", conn, cfg)
    assert "OK" in result
    count = conn.execute("SELECT count(*) FROM t WHERE id = 9999").fetchone()[0]
    assert count == 1


def test_sql_error_returns_error_string(conn, cfg):
    result = run_query("SELECT * FROM nonexistent_table_xyz", conn, cfg)
    assert "Error" in result


def test_char_limit_truncates(conn):
    cfg = Settings(mcp_mode="easy", max_rows=10, max_chars=50)
    result = run_query("SELECT * FROM t", conn, cfg)
    assert "[truncated" in result
