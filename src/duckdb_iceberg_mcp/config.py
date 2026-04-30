from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
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
    catalog_type: Literal["glue"] = "glue"

    # ── AWS / Glue ────────────────────────────────────
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_profile: str = ""

    # ── Safety ────────────────────────────────────────
    write_mode: Literal["disabled", "enabled"] = "disabled"
    max_rows: int = 250
    max_chars: int = 40_000

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
