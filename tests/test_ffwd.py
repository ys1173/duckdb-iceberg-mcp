import asyncio
from unittest.mock import Mock

import duckdb
import pytest

from duckdb_iceberg_mcp.catalog.rest import setup
from duckdb_iceberg_mcp.cli import main
from duckdb_iceberg_mcp.config import Settings, get_settings
from duckdb_iceberg_mcp.onboarding import extract_connection, write_env
from duckdb_iceberg_mcp.tools.query import run_query

SNIPPET = """
CREATE PERSISTENT SECRET ffwd_iceberg (
 TYPE iceberg, CLIENT_ID '<key-id>', CLIENT_SECRET '<key-secret>',
 OAUTH2_SERVER_URI 'https://cluster.example/api/oauth/token'
);
ATTACH 'warehouse-id' AS ffwd (
 TYPE iceberg, SECRET ffwd_iceberg,
 ENDPOINT 'https://cluster.example/api/tenants/tenant-id/iceberg/catalog'
);
SHOW ALL TABLES;
"""


def rest_config(**overrides):
    values = dict(
        _env_file=None,
        catalog_type="rest",
        client_id="test-id",
        client_secret="synthetic-secret",
        warehouse_id="warehouse-id",
        catalog_endpoint="https://cluster.example/catalog",
        oauth_token_endpoint="https://cluster.example/token",
    )
    return Settings(**(values | overrides))


def test_extract_ui_snippet():
    values = extract_connection(SNIPPET)
    assert values["FFWD_WAREHOUSE_ID"] == "warehouse-id"
    assert values["FFWD_CATALOG_ENDPOINT"].endswith("/iceberg/catalog")
    assert values["CATALOG_NAME"] == "ffwd"
    assert values["FFWD_CLIENT_SECRET"] == ""


@pytest.mark.parametrize(
    "extra",
    ["DROP TABLE x;", "SELECT read_text('/private');", "ATTACH 'evil' AS evil;"],
)
def test_import_refuses_extra_sql(extra):
    with pytest.raises(ValueError):
        extract_connection(SNIPPET + extra)


def test_import_escaped_secret():
    values = extract_connection(SNIPPET.replace("<key-secret>", "test''quoted"))
    assert values["FFWD_CLIENT_SECRET"] == "test'quoted"


def test_private_env_roundtrip_and_no_overwrite(tmp_path, monkeypatch):
    for key in ("FFWD_CLIENT_ID", "FFWD_CLIENT_SECRET", "DUCKDB_MCP_ENV_FILE"):
        monkeypatch.delenv(key, raising=False)
    values = extract_connection(SNIPPET)
    values.update(FFWD_CLIENT_ID="test-id", FFWD_CLIENT_SECRET="quote'\\$dollar${HOME}")
    path = tmp_path / "connection.env"
    write_env(path, values)
    cfg = Settings(_env_file=path)
    assert cfg.client_secret.get_secret_value() == values["FFWD_CLIENT_SECRET"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert values["FFWD_CLIENT_SECRET"] not in repr(cfg)
    with pytest.raises(FileExistsError):
        write_env(path, values)


def test_env_overrides_file(tmp_path, monkeypatch):
    path = tmp_path / "connection.env"
    write_env(path, {"FFWD_CLIENT_SECRET": "file-secret", "CATALOG_TYPE": "rest"})
    monkeypatch.setenv("FFWD_CLIENT_SECRET", "env-secret")
    assert Settings(_env_file=path).client_secret.get_secret_value() == "env-secret"


def test_rest_connection_uses_oauth_and_native_attach():
    conn = Mock()
    setup(conn, rest_config())
    statements = [c.args[0] for c in conn.execute.call_args_list]
    assert len(statements) == 2
    assert "CLIENT_SECRET 'synthetic-secret'" in statements[0]
    assert "PERSISTENT" not in statements[0]
    assert "ATTACH 'warehouse-id' AS ffwd" in statements[1]
    assert "vended_credentials" in statements[1]


@pytest.mark.parametrize(
    "overrides",
    [
        {"client_secret": ""},
        {"catalog_name": "x; DROP TABLE x"},
        {"oauth_token_endpoint": "http://external.example/token"},
    ],
)
def test_invalid_rest_configuration_fails_before_any_sql(overrides):
    conn = Mock()
    with pytest.raises(ValueError):
        setup(conn, rest_config(**overrides))
    conn.execute.assert_not_called()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 AS x;",
        "SELECT 1 AS x UNION ALL SELECT 2 AS x;",
        "SHOW TABLES;",
        "EXPLAIN SELECT 1;",
        "WITH a AS (SELECT 1) SELECT * FROM a;",
    ],
)
def test_normal_customer_sql(sql):
    with duckdb.connect(":memory:") as conn:
        assert not run_query(sql, conn, rest_config()).startswith("Error:")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; SELECT 2",
        "SET memory_limit='100GB'",
        "EXPLAIN ANALYZE DELETE FROM t",
        "CREATE SECRET x (TYPE s3)",
    ],
)
def test_read_only_blocks_session_changes_and_multiple_statements(sql):
    with duckdb.connect(":memory:") as conn:
        assert run_query(sql, conn, rest_config()).startswith("Error:")


def test_timeout_connection_remains_usable():
    cfg = rest_config(query_timeout_seconds=0.01)
    with duckdb.connect(":memory:") as conn:
        result = run_query(
            "SELECT SUM(a.i * b.i) FROM range(1000000) a(i), range(1000000) b(i)",
            conn,
            cfg,
        )
        assert "timed out" in result
        assert "Error:" not in run_query("SELECT 1", conn, rest_config())


def test_error_redacts_secret():
    conn = Mock()
    conn.execute.side_effect = RuntimeError("contains synthetic-secret")
    result = run_query("SELECT 1", conn, rest_config())
    assert "synthetic-secret" not in result
    assert "[REDACTED]" in result


def test_cli_setup_and_query(tmp_path, monkeypatch, capsys):
    snippet = tmp_path / "ui.sql"
    snippet.write_text(SNIPPET)
    env = tmp_path / "ffwd.env"
    monkeypatch.setenv("FFWD_CLIENT_ID", "test-id")
    monkeypatch.setenv("FFWD_CLIENT_SECRET", "synthetic-secret")
    assert main(["setup", "--from-sql", str(snippet), "--env-file", str(env)]) == 0
    assert "synthetic-secret" not in capsys.readouterr().out
    monkeypatch.setattr(
        "duckdb_iceberg_mcp.cli.new_connection", lambda cfg: duckdb.connect(":memory:")
    )
    get_settings.cache_clear()
    assert main(["--env-file", str(env), "query", "SELECT 1 AS x;"]) == 0
    assert "x\n1" in capsys.readouterr().out
    get_settings.cache_clear()


def test_mcp_rest_tools_without_glue_registration(monkeypatch):
    from duckdb_iceberg_mcp.auth.session import SessionPool
    from duckdb_iceberg_mcp.server import build_server

    monkeypatch.setattr(
        "duckdb_iceberg_mcp.auth.session.new_connection",
        lambda cfg: duckdb.connect(":memory:"),
    )
    pool = SessionPool(rest_config())
    server = build_server(rest_config(), pool)

    async def exercise():
        tools = await server.list_tools()
        assert {t.name for t in tools} == {
            "query_lakehouse",
            "list_tables",
            "describe_table",
        }
        result = await server.call_tool("query_lakehouse", {"sql": "SELECT 1 AS x;"})
        assert "Error:" not in str(result)
        assert "x" in str(result)

    try:
        asyncio.run(exercise())
    finally:
        pool.close_all()
