import boto3
import duckdb
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
        aws_session_token=config.aws_session_token or None,
        region_name=config.aws_region,
    )


def _glue_client(config: Settings):
    return _boto_session(config).client("glue", region_name=config.aws_region)


def setup(conn: duckdb.DuckDBPyConnection, config: Settings) -> None:
    """Configure AWS credentials in the DuckDB session for S3 / Iceberg access."""
    if config.aws_access_key_id and config.aws_secret_access_key:
        session_token = (
            f", SESSION_TOKEN '{_e(config.aws_session_token)}'"
            if config.aws_session_token
            else ""
        )
        conn.execute(f"""
            CREATE OR REPLACE SECRET __aws_s3 (
                TYPE S3,
                KEY_ID '{_e(config.aws_access_key_id)}',
                SECRET '{_e(config.aws_secret_access_key)}',
                REGION '{_e(config.aws_region)}'{session_token}
            )
        """)
    else:
        if config.aws_profile:
            conn.execute(f"CALL load_aws_credentials('{_e(config.aws_profile)}');")
        else:
            conn.execute("CALL load_aws_credentials();")


def metadata_location(config: Settings, database: str, table: str) -> str:
    """Use the catalog's committed pointer, never guess the latest S3 filename."""
    info = _glue_client(config).get_table(DatabaseName=database, Name=table)["Table"]
    location = info.get("Parameters", {}).get("metadata_location", "")
    if not location.startswith("s3://"):
        raise ValueError(
            "Glue table has no committed S3 metadata_location; refusing to guess a snapshot"
        )
    return location


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
                    rows.append(
                        {
                            "database": db_name,
                            "table": t["Name"],
                            "type": t.get("TableType", ""),
                            "iceberg_location": location,
                        }
                    )

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
            {
                "column_name": c["Name"],
                "data_type": c["Type"],
                "partition_key": False,
                "comment": c.get("Comment", ""),
            }
            for c in info.get("StorageDescriptor", {}).get("Columns", [])
        ] + [
            {
                "column_name": c["Name"],
                "data_type": c["Type"],
                "partition_key": True,
                "comment": c.get("Comment", ""),
            }
            for c in info.get("PartitionKeys", [])
        ]

        if not columns:
            return f"Table '{table_name}' has no columns in Glue."

        header = f"iceberg_location: {location}\n\n"
        return header + pd.DataFrame(columns).to_csv(index=False)
    except Exception as exc:
        return f"Error: {exc}"
