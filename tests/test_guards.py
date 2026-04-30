import pytest
from duckdb_iceberg_mcp.engine.guards import is_select_only, is_write_statement


@pytest.mark.parametrize("sql", [
    "SELECT * FROM foo",
    "SELECT id, name FROM users WHERE id = 1",
    "WITH cte AS (SELECT 1 AS x) SELECT * FROM cte",
    "EXPLAIN SELECT * FROM foo",
    "DESCRIBE foo",
    "SHOW TABLES",
])
def test_read_statements_are_not_write(sql):
    assert not is_write_statement(sql)


@pytest.mark.parametrize("sql", [
    "INSERT INTO foo VALUES (1, 2)",
    "UPDATE foo SET x = 1 WHERE id = 1",
    "DELETE FROM foo WHERE id = 1",
    "CREATE TABLE foo (id INT)",
    "DROP TABLE foo",
    "ALTER TABLE foo ADD COLUMN x INT",
    "TRUNCATE foo",
    "CREATE TABLE result AS SELECT * FROM foo",
])
def test_write_statements_are_detected(sql):
    assert is_write_statement(sql)


def test_unparseable_sql_is_treated_as_write():
    assert is_write_statement("NOT $$ VALID @@ SQL ;;")


def test_select_only_true():
    assert is_select_only("SELECT * FROM foo")


def test_select_only_false_for_show():
    assert not is_select_only("SHOW TABLES")


def test_select_only_false_for_write():
    assert not is_select_only("INSERT INTO foo VALUES (1)")
