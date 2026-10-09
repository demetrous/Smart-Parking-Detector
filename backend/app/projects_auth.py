"""Operator-token auth and size limits for project write endpoints (R0.1).

All settings are read from the environment at request time so tests (and a
restarted process) pick up changes without re-importing the module.
"""

from __future__ import annotations

import hmac
import logging
import os

from fastapi import HTTPException, status
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

TOKEN_ENV = "PARKINGSPOTTER_PROJECTS_TOKEN"
MAX_UPLOAD_MB_ENV = "PARKINGSPOTTER_MAX_UPLOAD_MB"
MAX_ZIP_ENTRIES_ENV = "PARKINGSPOTTER_MAX_ZIP_ENTRIES"
MAX_ZIP_UNCOMPRESSED_MB_ENV = "PARKINGSPOTTER_MAX_ZIP_UNCOMPRESSED_MB"

DEFAULT_MAX_UPLOAD_MB = 512
DEFAULT_MAX_ZIP_ENTRIES = 2000
DEFAULT_MAX_ZIP_UNCOMPRESSED_MB = 1024

# JSON writes (create/patch) carry a small manifest; assets travel as uploads.
MAX_JSON_BODY_BYTES = 1024 * 1024
# Room for multipart boundaries and part headers on top of the file itself.
MULTIPART_OVERHEAD_BYTES = 1024 * 1024

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MB = 1024 * 1024


def _positive_number(env: str, default: float) -> float:
    raw = os.getenv(env, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using %s", env, raw, default)
        return default
    if value <= 0:
        logger.warning("%s=%r must be positive; using %s", env, raw, default)
        return default
    return value


def projects_token() -> str:
    return os.getenv(TOKEN_ENV, "").strip()


def max_upload_bytes() -> int:
    return int(_positive_number(MAX_UPLOAD_MB_ENV, DEFAULT_MAX_UPLOAD_MB) * _MB)


def max_zip_entries() -> int:
    return int(_positive_number(MAX_ZIP_ENTRIES_ENV, DEFAULT_MAX_ZIP_ENTRIES))


def max_zip_uncompressed_bytes() -> int:
    return int(_positive_number(MAX_ZIP_UNCOMPRESSED_MB_ENV, DEFAULT_MAX_ZIP_UNCOMPRESSED_MB) * _MB)


def format_mb(num_bytes: int) -> str:
    """Human-readable size for limit messages: 512 MB, 0.5 MB."""
    return f"{num_bytes / _MB:g} MB"


def payload_too_large(detail: str) -> HTTPException:
    return HTTPException(status_code=413, detail=detail)


def token_matches(authorization: str | None) -> bool:
    """True when no token is configured, or the bearer token matches it."""
    expected = projects_token()
    if not expected:
        return True
    if not authorization:
        return False
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(supplied.strip().encode("utf-8"), expected.encode("utf-8"))


def route_path(scope: Scope) -> str:
    """The path the router matches on: scope["path"] minus any root_path.

    Uvicorn's --root-path (and FastAPI(root_path=...)) put the prefix into
    scope["path"], and Starlette strips it before routing. Matching the raw
    path would let /projects writes skip the guard behind a path prefix.
    """
    path = scope["path"]
    root_path = scope.get("root_path", "")
    if root_path and path.startswith(root_path):
        rest = path[len(root_path):]
        if rest == "" or rest.startswith("/"):
            return rest
    return path


def is_project_write(method: str, path: str) -> bool:
    if method.upper() not in _WRITE_METHODS:
        return False
    return path == "/projects" or path.startswith("/projects/")


def warn_if_projects_open() -> None:
    if not projects_token():
        logger.warning(
            "%s is not set: project write endpoints are open. "
            "Set it before exposing this backend beyond localhost.",
            TOKEN_ENV,
        )


class ProjectWriteGuard:
    """Rejects unauthenticated or oversized project writes before the body is read.

    Pure ASGI (not BaseHTTPMiddleware) so request bodies keep streaming. The
    token and Content-Length checks run before the app sees the request, so an
    unauthenticated upload is never spooled. Bodies without a usable
    Content-Length are counted as they stream; crossing the limit raises a 413
    from inside the body read, which FastAPI turns into the response.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_project_write(scope["method"], route_path(scope)):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not token_matches(headers.get("authorization")):
            response = JSONResponse(
                {"detail": "Missing or invalid projects token"},
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        content_type = headers.get("content-type", "").lower()
        if content_type.startswith("multipart/"):
            stated_limit = max_upload_bytes()
            limit = stated_limit + MULTIPART_OVERHEAD_BYTES
        else:
            stated_limit = limit = MAX_JSON_BODY_BYTES
        too_large_detail = f"Request body exceeds the {format_mb(stated_limit)} limit"

        declared = headers.get("content-length")
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = False  # malformed header: fall back to counting the stream
            if too_large:
                response = JSONResponse(
                    {"detail": too_large_detail},
                    status_code=413,
                )
                await response(scope, receive, send)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise payload_too_large(too_large_detail)
            return message

        await self.app(scope, limited_receive, send)
