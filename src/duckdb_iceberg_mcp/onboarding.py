"""Extract FFWD's UI snippet as configuration. Never execute pasted SQL."""

import os
import re
from pathlib import Path

_LITERAL = r"'((?:[^']|'')*)'"
_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_SNIPPET = re.compile(
    rf"\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:PERSISTENT\s+)?SECRET\s+({_IDENT})\s*"
    rf"\((.*?)\)\s*;\s*ATTACH\s+{_LITERAL}\s+AS\s+({_IDENT})\s*"
    rf"\((.*?)\)\s*;?\s*(?:SHOW\s+ALL\s+TABLES\s*;?\s*)?",
    re.I | re.S,
)


def _fields(block: str, allowed: set[str]) -> dict[str, str]:
    pattern = re.compile(rf"\s*({_IDENT})\s+(?:{_LITERAL}|({_IDENT}))\s*(,|$)", re.S)
    result: dict[str, str] = {}
    offset = 0
    while offset < len(block):
        match = pattern.match(block, offset)
        if not match:
            raise ValueError(
                "Unsupported connection snippet syntax; copy the complete FFWD DuckDB snippet"
            )
        name = match[1].upper()
        if name not in allowed or name in result:
            raise ValueError("Unexpected or duplicated connection field")
        result[name] = (match[2] if match[2] is not None else match[3]).replace(
            "''", "'"
        )
        offset = match.end()
    return result


def extract_connection(sql: str) -> dict[str, str]:
    match = _SNIPPET.fullmatch(sql)
    if not match:
        raise ValueError(
            "Expected only FFWD's CREATE SECRET and ATTACH connection statements"
        )
    secret_name, secret_block, warehouse, alias, attach_block = match.groups()
    secret = _fields(
        secret_block.strip(),
        {"TYPE", "CLIENT_ID", "CLIENT_SECRET", "OAUTH2_SERVER_URI"},
    )
    attach = _fields(attach_block.strip(), {"TYPE", "SECRET", "ENDPOINT"})
    if (
        secret.get("TYPE", "").lower() != "iceberg"
        or attach.get("TYPE", "").lower() != "iceberg"
    ):
        raise ValueError("Both connection statements must use TYPE iceberg")
    if attach.get("SECRET", "").lower() != secret_name.lower():
        raise ValueError("ATTACH must reference the declared Iceberg secret")
    if (
        not attach.get("ENDPOINT")
        or not secret.get("OAUTH2_SERVER_URI")
        or not warehouse
    ):
        raise ValueError(
            "The catalog endpoint, OAuth endpoint, and warehouse are required"
        )
    result = {
        "CATALOG_TYPE": "rest",
        "CATALOG_NAME": alias,
        "FFWD_CATALOG_ENDPOINT": attach["ENDPOINT"],
        "FFWD_OAUTH_TOKEN_ENDPOINT": secret["OAUTH2_SERVER_URI"],
        "FFWD_WAREHOUSE_ID": warehouse.replace("''", "'"),
        "FFWD_CLIENT_ID": secret.get("CLIENT_ID", ""),
        "FFWD_CLIENT_SECRET": secret.get("CLIENT_SECRET", ""),
    }
    for key in ("FFWD_CLIENT_ID", "FFWD_CLIENT_SECRET"):
        if result[key].startswith("<"):
            result[key] = ""
    return result


def write_env(path: Path, values: dict[str, str]) -> None:
    """Create a private config file. Refuse to replace existing customer configuration."""
    for value in values.values():
        if any(c in value for c in ("\n", "\r", "\x00")):
            raise ValueError("Connection values must be single-line strings")
    # Settings reads these literally, with dotenv interpolation disabled.
    lines = []
    for key, value in values.items():
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"{key}='{escaped}'\n")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.writelines(lines)
