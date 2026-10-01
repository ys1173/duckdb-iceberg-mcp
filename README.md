# duckdb-iceberg-mcp

A free, local SQL query engine for **FFWD's Iceberg sink**, with optional MCP tools for AI agents. Configure your FFWD connection once, then query tables using a CLI, interactive shell, or MCP client. Other OAuth2 Iceberg REST catalogs are supported using the same connection settings; AWS Glue remains available as an optional backend.

DuckDB runs on your machine and reads the required metadata and data from S3. You do not need a separate hosted query service or a second copy of the lake. S3 request/transfer costs and your own compute costs still apply.

Built on the official [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

This MCP server is complementary to [telemetry-iceberg-adaptor](https://github.com/ys1173/telemetry-iceberg-adaptor), which ingests telemetry data into Apache Iceberg. Use that project to write data and this project to query it through MCP-enabled AI clients.

## What's new in v0.2.0

- FFWD/Lakekeeper Iceberg REST support with OAuth2 client credentials and catalog-vended S3 access.
- One-time setup from the DuckDB connection snippet copied from FFWD's UI; credentials stay in environment configuration, not queries or MCP client definitions.
- Standalone SQL CLI and interactive shell using the same engine as the MCP tools.
- Read-only defaults, single-statement SQL validation, bounded results, query interruption, and configurable memory/thread limits.
- Native Iceberg scanning for Glue using its committed metadata pointer, replacing manual manifest flattening.
- Customer setup examples, an MIT license, and automated tests on Python 3.12 and 3.13.

Start with [FFWD quick start](#ffwd-quick-start). See [live verification](#live-ffwd-verification) for what has actually been tested, and [configuration reference](#configuration-reference) for all settings.

## FFWD quick start

Requires Python 3.12+ and access to the FFWD catalog, OAuth endpoint, and S3 storage. On first use, DuckDB downloads its official `httpfs` and `iceberg` extensions.

### 1. Install locally

```bash
git clone https://github.com/ys1173/duckdb-iceberg-mcp.git
cd duckdb-iceberg-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Import the FFWD connection once

In FFWD, open your **Data Lake Destination → Query Engine → DuckDB** instructions. Use the Copy button to get the complete snippet (long endpoints may be clipped visually). Save it locally as `ffwd-connection.sql`, then run:

```bash
duckdb-iceberg setup --from-sql ffwd-connection.sql --env-file .env
```

### 3. Check connectivity and discover tables

```bash
duckdb-iceberg check --env-file .env
duckdb-iceberg tables --env-file .env
duckdb-iceberg describe ffwd.network.network_logs --env-file .env
```

### 4. Query using SQL, without an agent

```bash
duckdb-iceberg query --env-file .env "SELECT _ts, _event FROM ffwd.network.network_logs WHERE _event ILIKE '%dns%' ORDER BY _ts DESC LIMIT 10;"
duckdb-iceberg query --env-file .env "SELECT _ts, name, type, value, labels FROM ffwd.network.network_metric ORDER BY _ts DESC LIMIT 10;"
duckdb-iceberg shell --env-file .env
```

In the shell, terminate SQL with `;` and use `.quit` to exit. Use `query --file query.sql` to run a file containing one statement. Replace the sample table names with names returned by `tables`.

### 5. Add optional MCP access

Point your agent's MCP client at `duckdb-iceberg-mcp` and the same environment file; see [Connect an MCP client](#connect-an-mcp-client). The CLI works independently of MCP, and both reuse the same connection settings. Customers do not need an AI subscription or agent to use the SQL CLI.

### Credential configuration

`setup` **parses but never executes** the connection snippet. It extracts the catalog endpoint, OAuth endpoint, warehouse, and catalog alias. If the key fields contain placeholders, it asks for your agent key ID and a hidden key secret once. The resulting `.env` is created with owner-only permissions; existing files are never overwritten. Protect or remove the original snippet if it contains credentials. Table names above are examples: discover the actual names with `tables`.

For unattended setup, export `FFWD_CLIENT_ID` and `FFWD_CLIENT_SECRET` first. They take precedence over values in the snippet. `--from-sql -` accepts the snippet on stdin; when stdin is piped, missing credentials must come from the environment.

Alternatively, copy `config/ffwd.env.example` to `.env` and fill it manually:

| UI snippet field | Environment variable |
|---|---|
| `ENDPOINT` | `FFWD_CATALOG_ENDPOINT` |
| `OAUTH2_SERVER_URI` | `FFWD_OAUTH_TOKEN_ENDPOINT` |
| Value after `ATTACH` | `FFWD_WAREHOUSE_ID` |
| `CLIENT_ID` / agent key ID | `FFWD_CLIENT_ID` |
| `CLIENT_SECRET` / agent key secret | `FFWD_CLIENT_SECRET` |

Set `CATALOG_TYPE=rest`. The default alias is `ffwd`; `CATALOG_NAME` overrides it. No separate tenant ID is needed: the UI's endpoint already includes it. Never guess or reconstruct endpoints from a cluster name.

The engine creates a **non-persistent** DuckDB secret and attaches the catalog on connection creation. It does not ask for credentials during queries. Environment variables override the configuration file. By default `.env` is resolved from the current working directory; use `--env-file /absolute/path/.env` or `DUCKDB_MCP_ENV_FILE` when an agent launches from another directory. Values are read literally, without `${VARIABLE}` expansion, to preserve secrets exactly.

For example, if you already have a Glue `.env`, save FFWD settings separately with `duckdb-iceberg setup --from-sql ffwd-connection.sql --env-file .env.ffwd` and pass that path to subsequent CLI/MCP commands. Keep the file private and out of Git. When you change or rotate credentials, restart running MCP servers so they reload the configuration. Credentials are configured once, but can still expire or be revoked by your deployment.

### OAuth and S3 access

Your FFWD key ID/secret authenticate to the OAuth token endpoint using client credentials. DuckDB's Iceberg extension manages catalog authentication; this is separate from any incoming MCP authentication. The default `ACCESS_DELEGATION_MODE=vended_credentials` uses scoped storage credentials returned by the catalog. **No separate AWS keys are required when your deployment supports credential vending.** DuckDB still needs network reachability to S3.

For deployments without vending, install the `glue` extra (which includes AWS credential support), set `ACCESS_DELEGATION_MODE=none`, and configure the AWS profile or keys described below. Use `AWS_SESSION_TOKEN` with temporary credentials. Test expiration/re-authentication with your deployment before relying on long-lived agent sessions.

`check` discovers tables and reads at most one row from the first table (or `--table ffwd.namespace.table`) without printing row contents. An empty catalog cannot prove S3 data access.

### Connect an MCP client

Run `duckdb-iceberg-mcp --env-file /absolute/path/.env` for stdio. A Claude-style MCP configuration is:

```json
{
  "mcpServers": {
    "ffwd-lake": {
      "command": "/absolute/path/.venv/bin/duckdb-iceberg-mcp",
      "args": ["--env-file", "/absolute/path/.env"]
    }
  }
}
```

Use your client's equivalent command/arguments settings; do not copy secrets into the MCP configuration. With REST catalogs the tools are `list_tables`, `describe_table`, and `query_lakehouse`. Tables are queried directly as `ffwd.namespace.table`; **no `glue_table` registration is needed**. Useful agent instruction: “Discover tables and schemas first; use explicit columns and narrow `_ts` time filters; never request credentials in SQL.”

An agent can call `list_tables()`, then `describe_table("ffwd.network.network_logs")`, then `query_lakehouse` with ordinary SQL. Reload the client after changing its MCP command/arguments. Configuration-file paths should be absolute because desktop clients may not inherit your terminal's working directory or exported environment.

### How FFWD querying works

The CLI or MCP tool executes SQL in local DuckDB. DuckDB authenticates to FFWD's OAuth endpoint, attaches the Iceberg REST catalog, and obtains table metadata and delegated storage credentials. It then reads the required S3 metadata/Parquet data directly and performs the query locally. Lakekeeper is the catalog, not a remote SQL execution engine; the catalog does not proxy the S3 data reads. The default FFWD path needs neither Glue nor separate AWS keys when credential vending is enabled.

### Limits and deployment safety

- Read-only by default; single SQL statement per request. `SELECT`, CTEs, unions, `SHOW`, `DESCRIBE`, and read-only `EXPLAIN` are supported. Session-changing `SET`, `USE`, and credential DDL are blocked in read-only mode.
- `MAX_ROWS=250`, `MAX_CHARS=40000`, `QUERY_TIMEOUT_SECONDS=30`, `DUCKDB_MEMORY_LIMIT=1GB`, and `DUCKDB_THREADS=4` are configurable. Memory limits are **per connection**, not a whole-process guarantee; external libraries and result materialization may use additional memory. Limits on returned rows do not limit bytes scanned. Query timeout uses DuckDB interruption and is not a hard deadline for connection setup or every network operation.
- MCP engine operations are serialized off the event loop, preventing concurrent use/eviction of active connections. Up to `MAX_SESSIONS=50` connections are retained; session IDs separate state, not data permissions.
- This is a **single configured warehouse/credential per server process**, not a multi-tenant authorization gateway. Even authenticated users of the same process access the same configured lake. Run separate instances/credentials for separate customer security boundaries.
- SQL read-only checks are **not a sandbox**: SQL can read files and remote resources accessible to the host. Use trusted agents, least-privilege FFWD credentials, and OS/container isolation for untrusted users. HTTP defaults to localhost; require authentication and TLS before exposing it to a network. Full-mode JWT validation does not supply an OAuth login service.
- This queries committed Iceberg snapshots, not FFWD's live ingestion buffer. Freshness depends on sink commits; performance depends on partitioning, file sizes, selected columns, and the client's network distance from S3. Prefer time filters; `ORDER BY ... LIMIT 10` may still scan substantial data.

Troubleshooting: authentication errors → check your key pair and OAuth URL; catalog 403 → check FFWD authorization; S3 403 → check vending/storage permissions and network restrictions. Run `check --table ...` to separate catalog discovery from data reads. For detailed FFWD onboarding, this quick start is the supported path; the following sections retain legacy Glue transport/configuration examples.

## Live FFWD verification

The v0.2.0 implementation was smoke-tested against a live FFWD deployment with a Lakekeeper catalog and S3-backed Iceberg tables on **October 1, 2026**, using DuckDB 1.5.3. These were read-only checks, not just mocks:

- OAuth authentication and native REST catalog attachment succeeded using the supplied FFWD agent key pair.
- Catalog discovery found `ffwd.network.network_logs` and `ffwd.network.network_metric`.
- A live `network_logs` read succeeded using catalog-vended S3 credentials, without separately configuring AWS keys.
- A bounded `_event ILIKE '%dns%'` query confirmed a sample of 10 matching logs.
- A real stdio MCP client initialized, discovered the three REST tools, listed tables, described `network_logs`, and executed an S3-backed query.

The local suite passed **64 tests**, and GitHub Actions passed on Python 3.12 and 3.13. A fresh core-wheel installation also passed its tests without the optional Glue dependency; Glue-specific tests were skipped in that environment.

This confirms basic interoperability, not a production performance guarantee. Credential expiry/re-authentication, sustained load, large-dataset performance, and metric-table data scans were not covered by this repository's live smoke test. Customer endpoints, tenant/warehouse IDs, credentials, local MCP configuration, and returned log contents are not published in the repository.

To reproduce the live log-table check with your own configuration:

```bash
duckdb-iceberg check --env-file .env --table ffwd.network.network_logs
```

Use a table discovered in your own warehouse; the sample namespace is not required. GitHub CI uses synthetic credentials and local fixtures, never a customer lake.

## Legacy Glue architecture

```text
                                              +----------------------+
                                              | MCP Clients          |
                                              | - OpenAI Codex       |
                                              | - Claude Desktop     |
                                              | - OpenCode           |
                                              | - LibreChat          |
                                              +----------------------+
                                                        |
                                                        | MCP Protocol (tools/list · tools/call)
                                                        v
            +--------------------------------------------------------------------------------------------+
            | duckdb-iceberg-mcp                                                                         |
            |                                                                                            |
            | +----------------------------------------------------------------------------------------+ |
            | | MCP Protocol Layer                                                                     | |
            | | stdio · Streamable HTTP · SSE                                                          | |
            | | JWT auth · write guard · row/char limits                                               | |
            | | Session pool: X-MCP-Session-ID (HTTP) · MCP_SESSION_ID (stdio) · LRU max connections   | |
            | +----------------------------------------------------------------------------------------+ |
            |                                          <-->                                              |
            | +----------------------------------------------------------------------------------------+ |
            | | ⚡ DuckDB                                                                               | |
            | | DuckDB columnar execution engine                                                       | |
            | | Vectorized execution · Direct S3 reads                                                 | |
            | | httpfs · iceberg · aws extensions                                                      | |
            | +----------------------------------------------------------------------------------------+ |
            +--------------------------------------------------------------------------------------------+
                          |                                                  |
                          | httpfs extension                                 | boto3
                          | columnar Parquet reads                           | metadata · schema
                          |                                                  | Committed metadata pointer
                          v                                                  v
            +--------------------------------------------------------------------------------------------+
            | AWS                                                                                        |
            | +-------------- Amazon S3 --------------+  +------------ AWS Glue Data Catalog ----------+ |
            | | Apache Iceberg tables                 |  | Databases · Tables · Schema                 | |
            | | Parquet data files                    |  | Iceberg metadata                            | |
            | +---------------------------------------+  +---------------------------------------------+ |
            +--------------------------------------------------------------------------------------------+

```

## Features

- Query FFWD/OAuth2 Iceberg REST catalogs or AWS Glue tables on S3
- Three transports: `stdio`, Streamable HTTP, SSE
- **Easy mode** — single-tenant, optional static API key, no IdP required
- **Full mode** — JWT/JWKS token validation (Auth0, Cognito, Keycloak, Okta, …)
- Writes disabled by default; only available in full mode with explicit opt-in
- Configurable row and character limits to prevent runaway responses
- **Concurrent MCP client sessions** — up to `MAX_SESSIONS` DuckDB connections (default 50), keyed by a client-supplied session id so `glue_table` views and connection state stay isolated when many clients share the same JWT or API key (HTTP: `X-MCP-Session-ID`; stdio: `MCP_SESSION_ID` per process)

## Requirements

- Python 3.12+
- FFWD catalog details and an agent key pair; or AWS credentials for the optional Glue backend

## Optional AWS Glue installation

FFWD users only need the installation above. Install the extra below when using Glue or separately configured AWS storage credentials.

```bash
git clone https://github.com/ys1173/duckdb-iceberg-mcp.git
cd duckdb-iceberg-mcp
python -m venv .venv
source .venv/bin/activate
pip install -e '.[glue]'
```

---

## Legacy AWS Glue quick start

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

Or configure in Claude Desktop or a client using the same JSON format:

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
        "AWS_SECRET_ACCESS_KEY": "...",
        "MCP_SESSION_ID": "codex-laptop-1"
      }
    }
  }
}
```

`MCP_SESSION_ID` is optional. Set a **unique value per client install** if the same host runs several stdio MCP servers or you want a stable pool key; if unset, the process uses the shared `default` session. Session behaviour for HTTP clients is documented in **[MCP client sessions](#mcp-client-sessions)** (after Streamable HTTP below).

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
.venv/bin/duckdb-iceberg-mcp --env-file /absolute/path/.env
```

MCP client URL: `http://localhost:8766/mcp`

See **[MCP client sessions](#mcp-client-sessions)** (next section) for `X-MCP-Session-ID`, pool limits, and limitations of different MCP clients.

**LibreChat** (`librechat.yaml`):

```yaml
mcpServers:
  duckdb-iceberg-mcp:
    type: streamable-http
    url: 'http://host.docker.internal:8766/mcp'
    timeout: 60000
    initTimeout: 20000
```

For other MCP clients, use their Streamable HTTP connection settings with URL `http://localhost:8766/mcp`.

## MCP client sessions

The server keeps **one DuckDB connection per session id**, not per JWT subject. That way LibreChat, Codex, and other clients can share the same credential but not clobber each other’s registered views from `glue_table`.

| Transport | How the session id is chosen | If missing |
|-----------|------------------------------|------------|
| **Streamable HTTP / SSE** | Client sends HTTP header `X-MCP-Session-ID` (rename via `MCP_SESSION_HEADER`). Use a stable string per logical client (e.g. UUID). Allowed characters: letters, digits, `.`, `_`, `-`; length 1–128. Invalid values return HTTP 400. | All requests share the `default` connection. |
| **stdio** | Set env `MCP_SESSION_ID` on that client’s MCP config (one process per client is typical). | Same as empty: `default`. |

**Pool limit:** When the number of distinct session ids exceeds `MAX_SESSIONS`, the **least recently used** connection is closed and removed.

**Client support:** Not every MCP UI can add custom headers. If yours cannot, those clients share `default` unless you run **separate server instances** (different URL or host) per client.

The **`glue_table`** tool is **per session** — each client typically needs to register a table in its own session before **`query_lakehouse`** can use the view.

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

Lists available catalog tables. For REST/FFWD, `database` filters by catalog alias (normally `ffwd`). For Glue, it filters by Glue database name.

### `describe_table(table_name)`

For REST/FFWD, returns column names, DuckDB types, and nullability; use `ffwd.namespace.table`. For Glue, returns catalog columns/types and partition-key information; use `database.table`.

### `glue_table(table_name)`

Available only with `CATALOG_TYPE=glue`; FFWD REST tables need no registration.

Registers a Glue Iceberg table as a native `iceberg_scan` DuckDB view using Glue's committed `metadata_location`. The engine does not guess the latest metadata filename or flatten manifests into raw Parquet scans. Re-register the view to pick up a new committed metadata pointer. Tables without a committed pointer are rejected.

Registrations are **scoped to the current MCP session** (see [MCP client sessions](#mcp-client-sessions)). A new session must call `glue_table` again before querying that view.

```
glue_table('mydb.mytable')
→ Registered view 'mydb__mytable'. Query with: SELECT * FROM mydb__mytable
```

### `query_lakehouse(sql)`

Executes one SQL statement. FFWD tables can be queried directly by fully qualified name, such as `SELECT _ts, _event FROM ffwd.network.network_logs LIMIT 10`. Glue can use registered views or explicit Iceberg metadata paths. Results are CSV text with truncation notices when applicable.

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
| `JWT_AUDIENCE` | `duckdb-mcp` | Expected `aud` claim in JWTs |
| `CATALOG_TYPE` | `glue` | `rest` for FFWD; `glue` for legacy AWS Glue |
| `DUCKDB_MCP_ENV_FILE` | *(empty)* | Explicit environment-file path; CLI `--env-file` takes precedence |
| `CATALOG_NAME` | `ffwd` | REST catalog SQL alias |
| `FFWD_CATALOG_ENDPOINT` | *(required for REST)* | Complete endpoint copied from FFWD UI |
| `FFWD_OAUTH_TOKEN_ENDPOINT` | *(required for REST)* | Complete OAuth token URL |
| `FFWD_WAREHOUSE_ID` | *(required for REST)* | Warehouse identifier from `ATTACH` |
| `FFWD_CLIENT_ID` | *(required for REST)* | Agent key ID |
| `FFWD_CLIENT_SECRET` | *(required for REST)* | Agent key secret; keep private |
| `ACCESS_DELEGATION_MODE` | `vended_credentials` | Set `none` only when configuring separate AWS storage credentials |
| `QUERY_TIMEOUT_SECONDS` | `30` | DuckDB query interruption timeout |
| `DUCKDB_MEMORY_LIMIT` | `1GB` | DuckDB memory limit per connection |
| `DUCKDB_THREADS` | `4` | Threads per connection |
| `AWS_REGION` | `us-east-1` | AWS region |
| `AWS_PROFILE` | *(empty)* | Named AWS profile |
| `AWS_ACCESS_KEY_ID` | *(empty)* | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | *(empty)* | AWS secret key |
| `AWS_SESSION_TOKEN` | *(empty)* | Session token when using temporary AWS credentials |
| `WRITE_MODE` | `disabled` | `disabled` or `enabled`. Always disabled in easy mode |
| `MAX_SESSIONS` | `50` | Max concurrent DuckDB connections per server process, keyed by session id (HTTP header or stdio env). LRU closes evicted connections |
| `MCP_SESSION_HEADER` | `X-MCP-Session-ID` | HTTP header name for the client session id |
| `MCP_SESSION_ID` | *(empty)* | **stdio only:** fixed session key for this process (defaults to shared `default` if empty) |
| `MAX_ROWS` | `250` | Maximum rows returned per query |
| `MAX_CHARS` | `40000` | Maximum characters in a query response |

---

## Full Mode (JWT Auth)

Full mode validates a JWT bearer token on every request. Session isolation is by **`X-MCP-Session-ID`** (not by JWT `sub`), so many clients can share the same credential while keeping separate DuckDB connections up to `MAX_SESSIONS`.

```ini
MCP_MODE=full
MCP_TRANSPORT=http
MCP_HOST=0.0.0.0
MCP_PORT=8766
JWKS_URL=https://your-idp.example.com/.well-known/jwks.json
JWT_AUDIENCE=duckdb-mcp
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
```

The client passes a JWT as `Authorization: Bearer <token>`. The server validates it against the JWKS endpoint. Any IdP that issues standard JWTs works (Auth0, AWS Cognito, Keycloak, Okta).

See `config/full.env.example` for a full template.

---

## Smoke Test

For FFWD, verify catalog discovery and a bounded S3-backed read without displaying row contents:

```bash
duckdb-iceberg check --env-file .env --table ffwd.network.network_logs
```

The compatibility script uses the same CLI engine:

```bash
.venv/bin/python scripts/smoke_test.py --env-file .env --table ffwd.network.network_logs
```

For the optional Glue backend, configure `config/easy.env.example` and specify a Glue table:

```bash
cp config/easy.env.example .env  # fill in AWS credentials
.venv/bin/python scripts/smoke_test.py --env-file .env --table your_database.your_table
```

## Run Tests

```bash
pip install -e ".[dev,glue]"
pytest
```

Unit tests use synthetic credentials and local tables/mocks. GitHub Actions runs them on Python 3.12 and 3.13 without accessing a customer lake. Use `duckdb-iceberg check` for a live deployment test. Supported DuckDB series: 1.5.x (minimum 1.5.3).

## License

MIT; see [LICENSE](LICENSE).
