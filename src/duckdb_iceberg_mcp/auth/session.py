from __future__ import annotations

import re
import threading
from collections import OrderedDict
from contextvars import ContextVar
from contextlib import contextmanager

import duckdb

from duckdb_iceberg_mcp.config import Settings
from duckdb_iceberg_mcp.engine.connection import new_connection

# Set by auth middleware on each HTTP request; stdio sets once in main().
# Defaults cover easy-mode stdio when MCP_SESSION_ID is unset (single "default" slot).
current_session_id: ContextVar[str] = ContextVar("current_session_id", default="")

# Set by auth middleware on each request; read by tool handlers if needed.
# Defaults cover easy-mode stdio (no HTTP request, no middleware).
current_sub: ContextVar[str] = ContextVar("current_sub", default="local-user")
current_token: ContextVar[str] = ContextVar("current_token", default="")

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def normalize_session_id(raw: str) -> str:
    """Return a pool key for DuckDB isolation, or 'default' when empty."""
    s = raw.strip()
    if not s:
        return "default"
    if not _SESSION_ID_RE.fullmatch(s):
        raise ValueError(
            "Invalid X-MCP-Session-ID: use 1–128 chars from [A-Za-z0-9._-] only"
        )
    return s


class SessionPool:
    """LRU-pooled DuckDB connections keyed by MCP client session id.

    Each distinct session id (per MCP client configuration) gets its own
    connection so registered views and session state stay isolated. At most
    ``max_sessions`` connections are retained; excess ids evict the
    least-recently-used connection (closed).
    """

    def __init__(self, config: Settings) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._sessions: OrderedDict[str, duckdb.DuckDBPyConnection] = OrderedDict()

    def get(self, session_id: str) -> duckdb.DuckDBPyConnection:
        key = normalize_session_id(session_id)
        with self._lock:
            if key in self._sessions:
                self._sessions.move_to_end(key)
                return self._sessions[key]

            conn = new_connection(self._config)
            self._sessions[key] = conn
            self._sessions.move_to_end(key)

            while len(self._sessions) > self._config.max_sessions:
                _, old = self._sessions.popitem(last=False)
                try:
                    old.close()
                except Exception:
                    pass

            return conn

    @contextmanager
    def lease(self, session_id: str):
        """Serialize engine work and prevent eviction while a connection is in use."""
        with self._lock:
            yield self.get(session_id)

    def close_all(self) -> None:
        with self._lock:
            for _, conn in self._sessions.items():
                try:
                    conn.close()
                except Exception:
                    pass
            self._sessions.clear()
