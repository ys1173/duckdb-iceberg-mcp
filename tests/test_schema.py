import duckdb
import pytest

from duckdb_iceberg_mcp.config import Settings
from duckdb_iceberg_mcp.tools.schema import describe_table, list_tables


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute("CREATE SCHEMA myschema")
    c.execute("CREATE TABLE myschema.orders (order_id INTEGER, amount DOUBLE, status VARCHAR)")
    c.execute("CREATE TABLE myschema.customers (customer_id INTEGER, email VARCHAR)")
    yield c
    c.close()


@pytest.fixture
def cfg():
    # Use REST catalog type so tests exercise the DuckDB info_schema path (no boto3 needed)
    return Settings(mcp_mode="easy", catalog_type="rest")


def test_list_tables_no_filter(conn, cfg):
    result = list_tables(conn, cfg)
    assert "orders" in result
    assert "customers" in result


def test_list_tables_database_filter(conn, cfg):
    result = list_tables(conn, cfg, database="memory")
    assert "orders" in result


def test_describe_qualified_table(conn, cfg):
    result = describe_table(conn, cfg, "myschema.orders")
    assert "order_id" in result
    assert "amount" in result
    assert "status" in result


def test_describe_nonexistent_table(conn, cfg):
    result = describe_table(conn, cfg, "myschema.does_not_exist")
    assert "not found" in result.lower()


def test_describe_invalid_identifier_rejected(cfg):
    conn = duckdb.connect(":memory:")
    result = describe_table(conn, cfg, "foo; DROP TABLE bar --")
    assert "invalid" in result.lower()
    conn.close()


def test_describe_three_part_name(conn, cfg):
    result = describe_table(conn, cfg, "memory.myschema.orders")
    assert "order_id" in result
