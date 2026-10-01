import duckdb
import pytest
import threading

from duckdb_iceberg_mcp.auth.session import SessionPool, normalize_session_id


def test_normalize_session_id_default_when_empty():
    assert normalize_session_id("") == "default"
    assert normalize_session_id("   ") == "default"


def test_normalize_session_id_accepts_safe_token():
    assert normalize_session_id("codex-1") == "codex-1"
    assert normalize_session_id("a.b_c-9") == "a.b_c-9"


def test_normalize_session_id_rejects_bad_chars():
    with pytest.raises(ValueError):
        normalize_session_id("has space")
    with pytest.raises(ValueError):
        normalize_session_id("../../x")


def test_normalize_session_id_rejects_too_long():
    with pytest.raises(ValueError):
        normalize_session_id("a" * 129)


def test_pool_reuses_same_connection(monkeypatch):
    def fake_new(_cfg):
        return duckdb.connect(":memory:")

    monkeypatch.setattr(
        "duckdb_iceberg_mcp.auth.session.new_connection",
        fake_new,
    )
    from duckdb_iceberg_mcp.config import Settings

    cfg = Settings(mcp_mode="easy", max_sessions=10)
    pool = SessionPool(cfg)
    c1 = pool.get("client-a")
    c2 = pool.get("client-a")
    assert c1 is c2


def test_pool_lru_evicts_and_closes(monkeypatch):
    created: list[duckdb.DuckDBPyConnection] = []

    def fake_new(_cfg):
        c = duckdb.connect(":memory:")
        created.append(c)
        return c

    monkeypatch.setattr(
        "duckdb_iceberg_mcp.auth.session.new_connection",
        fake_new,
    )
    from duckdb_iceberg_mcp.config import Settings

    cfg = Settings(mcp_mode="easy", max_sessions=2)
    pool = SessionPool(cfg)
    pool.get("s1")
    pool.get("s2")
    pool.get("s3")

    assert len(created) == 3
    with pytest.raises(duckdb.ConnectionException):
        created[0].execute("SELECT 1")


def test_pool_different_keys_distinct_connections(monkeypatch):
    def fake_new(_cfg):
        return duckdb.connect(":memory:")

    monkeypatch.setattr(
        "duckdb_iceberg_mcp.auth.session.new_connection",
        fake_new,
    )
    from duckdb_iceberg_mcp.config import Settings

    pool = SessionPool(Settings(mcp_mode="easy", max_sessions=5))
    a = pool.get("a")
    b = pool.get("b")
    assert a is not b


def test_lease_prevents_active_connection_eviction(monkeypatch):
    monkeypatch.setattr(
        "duckdb_iceberg_mcp.auth.session.new_connection",
        lambda cfg: duckdb.connect(":memory:"),
    )
    from duckdb_iceberg_mcp.config import Settings

    pool = SessionPool(Settings(_env_file=None, max_sessions=1))
    started = threading.Event()
    finished = threading.Event()

    def second_client():
        started.set()
        with pool.lease("b") as conn:
            assert conn.execute("SELECT 2").fetchone() == (2,)
        finished.set()

    with pool.lease("a") as conn:
        worker = threading.Thread(target=second_client)
        worker.start()
        assert started.wait(1)
        assert not finished.wait(0.05)
        assert conn.execute("SELECT 1").fetchone() == (1,)
    worker.join(2)
    assert finished.is_set()
    pool.close_all()
