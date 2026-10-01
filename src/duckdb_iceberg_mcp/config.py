from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import DotEnvSettingsSource
from dotenv import dotenv_values


class LiteralDotEnvSource(DotEnvSettingsSource):
    def _read_env_file(self, file_path: Path):
        values = dotenv_values(
            file_path, encoding=self.env_file_encoding or "utf-8", interpolate=False
        )
        return {
            (key if self.case_sensitive else key.lower()): value
            for key, value in values.items()
        }


class Settings(BaseSettings):
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        literal_dotenv = LiteralDotEnvSource(
            settings_cls,
            env_file=dotenv_settings.env_file,
            env_file_encoding=dotenv_settings.env_file_encoding,
        )
        return init_settings, env_settings, literal_dotenv, file_secret_settings

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Mode ──────────────────────────────────────────
    mcp_mode: Literal["easy", "full"] = "easy"
    mcp_transport: Literal["stdio", "http", "sse"] = "stdio"

    # ── Easy mode ─────────────────────────────────────
    mcp_api_key: str = ""  # empty = no auth required

    # ── Full mode ─────────────────────────────────────
    jwks_url: str = ""
    jwt_audience: str = "duckdb-mcp"

    # ── Catalog ───────────────────────────────────────
    catalog_type: Literal["glue", "rest"] = "glue"
    catalog_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("FFWD_CATALOG_ENDPOINT", "catalog_endpoint"),
    )
    oauth_token_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "FFWD_OAUTH_TOKEN_ENDPOINT", "oauth_token_endpoint"
        ),
    )
    warehouse_id: str = Field(
        default="", validation_alias=AliasChoices("FFWD_WAREHOUSE_ID", "warehouse_id")
    )
    client_id: str = Field(
        default="", validation_alias=AliasChoices("FFWD_CLIENT_ID", "client_id")
    )
    client_secret: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("FFWD_CLIENT_SECRET", "client_secret"),
    )
    catalog_name: str = "ffwd"
    access_delegation_mode: Literal["vended_credentials", "none"] = "vended_credentials"

    # ── AWS / Glue ────────────────────────────────────
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    aws_profile: str = ""

    # ── Safety ────────────────────────────────────────
    write_mode: Literal["disabled", "enabled"] = "disabled"
    max_rows: int = Field(default=250, ge=1, le=100_000)
    max_chars: int = Field(default=40_000, ge=1)
    query_timeout_seconds: float = Field(default=30, gt=0)
    duckdb_memory_limit: str = "1GB"
    duckdb_threads: int = Field(default=4, ge=1)

    # ── Sessions (HTTP/SSE: header; stdio: env) ───────
    # Distinct MCP client instances should send X-MCP-Session-ID (name overridable).
    # Empty / missing → shared "default" slot (backward compatible).
    max_sessions: int = Field(default=50, ge=1)
    mcp_session_header: str = "X-MCP-Session-ID"
    # stdio: optional fixed session key for this process (isolates glue_table views per client process).
    mcp_session_id: str = ""

    # ── HTTP transport ────────────────────────────────
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000
    # Comma-separated Host header values accepted by DNS rebinding protection.
    # Empty = let the SDK decide (localhost-only when mcp_host is 127.0.0.1).
    # Example: MCP_ALLOWED_HOSTS=host.docker.internal:*,localhost:*
    mcp_allowed_hosts: str = ""

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        if self.mcp_mode == "full":
            if not self.jwks_url:
                raise ValueError("JWKS_URL is required when MCP_MODE=full")
        else:
            # Easy mode: writes always off.
            # Default MCP_HOST is 127.0.0.1; if user explicitly sets MCP_HOST=0.0.0.0
            # (e.g. for a Docker-internal deployment) that is respected as-is.
            object.__setattr__(self, "write_mode", "disabled")
        return self

    @property
    def write_enabled(self) -> bool:
        return self.mcp_mode == "full" and self.write_mode == "enabled"

    def redact(self, message: str) -> str:
        for value in (
            self.client_secret.get_secret_value(),
            self.aws_secret_access_key,
            self.aws_session_token,
            self.mcp_api_key,
        ):
            if value:
                message = message.replace(value, "[REDACTED]")
        return message


@lru_cache(maxsize=1)
def get_settings(env_file: str | None = None) -> Settings:
    path = env_file or os.environ.get("DUCKDB_MCP_ENV_FILE")
    if path and not Path(path).is_file():
        raise ValueError("Configured environment file does not exist")
    return Settings(_env_file=path or ".env")
