from functools import lru_cache

import jwt
from jwt import PyJWKClient
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from duckdb_iceberg_mcp.auth.session import current_sub, current_token
from duckdb_iceberg_mcp.config import Settings


class AuthError(Exception):
    pass


@lru_cache(maxsize=1)
def _jwks_client(jwks_url: str) -> PyJWKClient:
    # PyJWKClient caches the key set internally and handles rotation.
    return PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=360)


def validate_request(authorization: str, config: Settings) -> dict:
    """Validate the Authorization header and populate request-scoped context vars.

    Returns the token payload (easy mode returns a synthetic payload).
    Raises AuthError on any validation failure.
    """
    if config.mcp_mode == "easy":
        if config.mcp_api_key:
            token = authorization.removeprefix("Bearer ").strip()
            if token != config.mcp_api_key:
                raise AuthError("Invalid API key")
        current_sub.set("local-user")
        current_token.set("")
        return {"sub": "local-user"}

    # Full mode: validate JWT against the configured JWKS endpoint.
    if not authorization.startswith("Bearer "):
        raise AuthError("Authorization header must use Bearer scheme")

    raw_token = authorization[7:]
    client = _jwks_client(config.jwks_url)

    try:
        signing_key = client.get_signing_key_from_jwt(raw_token)
        payload = jwt.decode(
            raw_token,
            signing_key.key,
            algorithms=["RS256", "ES256", "RS384", "ES384"],
            audience=config.jwt_audience or jwt.api_jwt.DISABLE_AUDIENCE_VALIDATION,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError(f"Invalid token: {exc}") from exc

    sub = payload.get("sub", "")
    if not sub:
        raise AuthError("Token is missing required 'sub' claim")

    current_sub.set(sub)
    current_token.set(raw_token)
    return payload


class BearerAuthMiddleware:
    """Pure ASGI middleware — safe for SSE and streaming HTTP responses.

    BaseHTTPMiddleware buffers the response body, which breaks long-lived
    SSE connections. This implementation passes scope/receive/send directly.
    """

    def __init__(self, app: ASGIApp, config: Settings) -> None:
        self._app = app
        self._config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        auth = headers.get(b"authorization", b"").decode()
        try:
            validate_request(auth, self._config)
        except AuthError as exc:
            response = Response(str(exc), status_code=401)
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)
