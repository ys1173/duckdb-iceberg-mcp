from unittest.mock import Mock

import pytest

pytest.importorskip("boto3")
from duckdb_iceberg_mcp.catalog import glue
from duckdb_iceberg_mcp.config import Settings
from duckdb_iceberg_mcp.tools.schema import register_glue_table


def test_glue_uses_committed_metadata_and_native_scan(monkeypatch):
    client = Mock()
    client.get_table.return_value = {
        "Table": {
            "Parameters": {"metadata_location": "s3://test/metadata/current.json"}
        }
    }
    monkeypatch.setattr(glue, "_glue_client", lambda cfg: client)
    conn = Mock()
    result = register_glue_table(conn, Settings(_env_file=None), "network.logs")
    sql = conn.execute.call_args.args[0]
    assert "iceberg_scan('s3://test/metadata/current.json')" in sql
    assert "read_parquet" not in sql
    assert "Registered" in result


def test_glue_refuses_guessing_metadata(monkeypatch):
    client = Mock()
    client.get_table.return_value = {
        "Table": {"StorageDescriptor": {"Location": "s3://test/root"}}
    }
    monkeypatch.setattr(glue, "_glue_client", lambda cfg: client)
    with pytest.raises(ValueError, match="refusing to guess"):
        glue.metadata_location(Settings(_env_file=None), "network", "logs")
