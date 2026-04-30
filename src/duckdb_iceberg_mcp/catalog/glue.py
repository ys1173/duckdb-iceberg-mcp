import io
import json

import boto3
import duckdb
import fastavro
import pandas as pd

from duckdb_iceberg_mcp.config import Settings


def _e(val: str) -> str:
    return val.replace("'", "''")


def _boto_session(config: Settings) -> boto3.Session:
    if config.aws_profile:
        return boto3.Session(profile_name=config.aws_profile)
    return boto3.Session(
        aws_access_key_id=config.aws_access_key_id or None,
        aws_secret_access_key=config.aws_secret_access_key or None,
        region_name=config.aws_region,
    )


def _glue_client(config: Settings):
    return _boto_session(config).client("glue", region_name=config.aws_region)


def _s3_client(config: Settings):
    return _boto_session(config).client("s3", region_name=config.aws_region)


def setup(conn: duckdb.DuckDBPyConnection, config: Settings) -> None:
    """Configure AWS credentials in the DuckDB session for S3 / Iceberg access."""
    if config.aws_access_key_id and config.aws_secret_access_key:
        conn.execute(f"""
            CREATE OR REPLACE SECRET __aws_s3 (
                TYPE S3,
                KEY_ID '{_e(config.aws_access_key_id)}',
                SECRET '{_e(config.aws_secret_access_key)}',
                REGION '{_e(config.aws_region)}'
            )
        """)
    else:
        if config.aws_profile:
            conn.execute(f"CALL load_aws_credentials('{_e(config.aws_profile)}');")
        else:
            conn.execute("CALL load_aws_credentials();")


def resolve_iceberg_files(config: Settings, s3_location: str) -> list[str]:
    """Walk the Iceberg manifest chain and return the exact data file paths.

    This handles tables where data files live outside the registered table root —
    a layout that DuckDB's iceberg_scan cannot resolve on its own.
    """
    s3 = _s3_client(config)
    s3_location = s3_location.rstrip("/")
    path = s3_location.removeprefix("s3://")
    bucket, prefix = path.split("/", 1)

    # 1 — Find the latest metadata JSON
    metadata_prefix = f"{prefix}/metadata/"
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=metadata_prefix)
    meta_keys = sorted(
        (obj["Key"] for obj in resp.get("Contents", []) if obj["Key"].endswith(".metadata.json")),
        reverse=True,  # lexicographic sort: 00001-... > 00000-...
    )
    if not meta_keys:
        return []

    meta_obj = s3.get_object(Bucket=bucket, Key=meta_keys[0])
    metadata = json.loads(meta_obj["Body"].read())

    current_snapshot_id = metadata.get("current-snapshot-id")
    if current_snapshot_id is None:
        return []

    snapshots = {s["snapshot-id"]: s for s in metadata.get("snapshots", [])}
    snapshot = snapshots.get(current_snapshot_id)
    if not snapshot:
        return []

    # 2 — Read the manifest list (Avro) to get manifest file paths
    manifest_list_url = snapshot["manifest-list"]
    ml_key = manifest_list_url.removeprefix(f"s3://{bucket}/")
    ml_obj = s3.get_object(Bucket=bucket, Key=ml_key)
    manifest_paths = [
        record["manifest_path"]
        for record in fastavro.reader(io.BytesIO(ml_obj["Body"].read()))
    ]

    # 3 — Read each manifest (Avro) to get data file paths
    data_files: list[str] = []
    for manifest_url in manifest_paths:
        mf_key = manifest_url.removeprefix(f"s3://{bucket}/")
        mf_obj = s3.get_object(Bucket=bucket, Key=mf_key)
        for record in fastavro.reader(io.BytesIO(mf_obj["Body"].read())):
            data_file = record.get("data_file", {})
            path = data_file.get("file_path") if isinstance(data_file, dict) else None
            if path:
                data_files.append(path)

    return data_files


def list_tables(config: Settings, database: str = "") -> str:
    """List Glue catalog tables with their Iceberg S3 locations via boto3."""
    glue = _glue_client(config)
    try:
        if database:
            db_names = [database]
        else:
            paginator = glue.get_paginator("get_databases")
            db_names = [
                db["Name"]
                for page in paginator.paginate()
                for db in page["DatabaseList"]
            ]

        rows = []
        for db_name in db_names:
            paginator = glue.get_paginator("get_tables")
            for page in paginator.paginate(DatabaseName=db_name):
                for t in page["TableList"]:
                    location = t.get("StorageDescriptor", {}).get("Location", "")
                    rows.append({
                        "database": db_name,
                        "table": t["Name"],
                        "type": t.get("TableType", ""),
                        "iceberg_location": location,
                    })

        if not rows:
            return "No tables found."
        return pd.DataFrame(rows).to_csv(index=False)
    except Exception as exc:
        return f"Error: {exc}"


def describe_table(config: Settings, table_name: str) -> str:
    """Describe a Glue table's schema and S3 location via boto3."""
    parts = table_name.split(".")
    if len(parts) != 2:
        return "Error: Glue tables require 'database.table_name' format."
    database, table = parts

    glue = _glue_client(config)
    try:
        info = glue.get_table(DatabaseName=database, Name=table)["Table"]
        location = info.get("StorageDescriptor", {}).get("Location", "")

        columns = [
            {"column_name": c["Name"], "data_type": c["Type"],
             "partition_key": False, "comment": c.get("Comment", "")}
            for c in info.get("StorageDescriptor", {}).get("Columns", [])
        ] + [
            {"column_name": c["Name"], "data_type": c["Type"],
             "partition_key": True, "comment": c.get("Comment", "")}
            for c in info.get("PartitionKeys", [])
        ]

        if not columns:
            return f"Table '{table_name}' has no columns in Glue."

        header = f"iceberg_location: {location}\n\n"
        return header + pd.DataFrame(columns).to_csv(index=False)
    except Exception as exc:
        return f"Error: {exc}"
