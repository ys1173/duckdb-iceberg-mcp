# duckdb-iceberg-mcp

An MCP server that lets AI assistants query Apache Iceberg tables on S3 via AWS Glue Data Catalog, using DuckDB as the embedded query engine.

Built on the official [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk). Tested with LibreChat and OpenAI Codex.

## Features

- Query Iceberg tables on S3 via AWS Glue Data Catalog
- Three transports: `stdio`, Streamable HTTP, SSE
- **Easy mode** — single-tenant, optional static API key, no IdP required
- **Full mode** — JWT/JWKS token validation (Auth0, Cognito, Keycloak, Okta, …)
- Writes disabled by default; only available in full mode with explicit opt-in
- Configurable row and character limits to prevent runaway responses

## Requirements

- Python 3.12+
- AWS credentials with access to Glue Data Catalog and S3

## Installation

```bash
git clone <repo>
cd duckdb-iceberg-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Quick Start

### stdio (local AI client)

Copy the example config and fill in your AWS details:

```bash
cp config/easy.env.example .env
```

```ini
# .env
MCP_MODE=easy
MCP_TRANSPORT=stdio
CATALOG_TYPE=glue
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

Run directly:

```bash
duckdb-iceberg-mcp
```

Or configure in your MCP client (Claude Desktop, OpenAI Codex):

```json
{
  "mcpServers": {
    "duckdb-iceberg-mcp": {
      "command": "/path/to/.venv/bin/duckdb-iceberg-mcp",
      "env": {
        "MCP_MODE": "easy",
        "CATALOG_TYPE": "glue",
        "AWS_REGION": "us-east-1",
        "AWS_ACCESS_KEY_ID": "AKIA...",
        "AWS_SECRET_ACCESS_KEY": "..."
      }
    }
  }
}
```

### Streamable HTTP (network clients, e.g. LibreChat in Docker)

```ini
MCP_MODE=easy
MCP_TRANSPORT=http
MCP_HOST=0.0.0.0
MCP_PORT=8766
MCP_ALLOWED_HOSTS=host.docker.internal:*,localhost:*
CATALOG_TYPE=glue
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

```bash
env $(grep -v '^#' .env | grep -v '^$' | xargs) .venv/bin/duckdb-iceberg-mcp
```

MCP client URL: `http://localhost:8766/mcp`

**LibreChat** (`librechat.yaml`):

```yaml
mcpServers:
  duckdb-iceberg-mcp:
    type: streamable-http
    url: 'http://host.docker.internal:8766/mcp'
    timeout: 60000
    initTimeout: 20000
```

**OpenAI Codex**: add via the Codex UI — Streamable HTTP, URL `http://localhost:8766/mcp`.

---

## AWS Authentication

Configure credentials using one of these methods (key/secret takes priority if both are set):

| Method | Env vars |
|---|---|
| Explicit credentials | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` |
| Named profile | `AWS_PROFILE=my-profile` |
| Default chain | Set neither — falls back to env vars, `~/.aws/credentials`, instance role |

---

## MCP Tools

### `list_tables(database?)`
Lists Glue catalog tables. Optionally filter by database name.

### `describe_table(table_name)`
Returns column names, types, and partition keys. Use `database.table` format.

### `glue_table(table_name)`
Registers a Glue Iceberg table as a queryable DuckDB view. Required for tables where data files live outside the Glue-registered table root (a common layout with shared S3 prefixes).

```
glue_table('mydb.mytable')
→ Registered view 'mydb__mytable'. Query with: SELECT * FROM mydb__mytable
```

### `query_lakehouse(sql)`
Executes a SQL query against registered views or direct S3 paths (`read_parquet()`, `iceberg_scan()`).

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `MCP_MODE` | `easy` | `easy` or `full` |
| `MCP_TRANSPORT` | `stdio` | `stdio`, `http` (Streamable HTTP), `sse` |
| `MCP_HOST` | `127.0.0.1` | Bind address for HTTP/SSE |
| `MCP_PORT` | `8000` | Port for HTTP/SSE |
| `MCP_ALLOWED_HOSTS` | *(empty)* | Comma-separated allowed `Host` headers (e.g. `host.docker.internal:*,localhost:*`). Empty = SDK default |
| `MCP_API_KEY` | *(empty)* | Static bearer token for easy mode HTTP. Empty = no auth |
| `JWKS_URL` | *(required in full mode)* | JWKS endpoint for JWT validation |
| `JWT_AUDIENCE` | `duckdb-iceberg-mcp` | Expected `aud` claim in JWTs |
| `CATALOG_TYPE` | `glue` | Only `glue` supported |
| `AWS_REGION` | `us-east-1` | AWS region |
| `AWS_PROFILE` | *(empty)* | Named AWS profile |
| `AWS_ACCESS_KEY_ID` | *(empty)* | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | *(empty)* | AWS secret key |
| `WRITE_MODE` | `disabled` | `disabled` or `enabled`. Always disabled in easy mode |
| `MAX_ROWS` | `250` | Maximum rows returned per query |
| `MAX_CHARS` | `40000` | Maximum characters in a query response |

---

## Full Mode (JWT Auth)

Full mode validates a JWT bearer token on every request. All authenticated users share one DuckDB connection — per-user session isolation is deferred to a future release.

```ini
MCP_MODE=full
MCP_TRANSPORT=http
MCP_HOST=0.0.0.0
MCP_PORT=8766
JWKS_URL=https://your-idp.example.com/.well-known/jwks.json
JWT_AUDIENCE=duckdb-iceberg-mcp
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

The client passes a JWT as `Authorization: Bearer <token>`. The server validates it against the JWKS endpoint. Any IdP that issues standard JWTs works (Auth0, AWS Cognito, Keycloak, Okta).

See `config/full.env.example` for a full template.

---

## Smoke Test

Run a quick end-to-end check against your real Glue catalog:

```bash
cp config/easy.env.example .env  # fill in AWS credentials
.venv/bin/python scripts/smoke_test.py
```

## Run Tests

```bash
pip install -e ".[dev]"
pytest
```
