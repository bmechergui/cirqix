"""Security boundary helpers for the Cirqix KiCad microservice."""

from __future__ import annotations

import os
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse


_PUBLIC_PATHS = frozenset({"/health"})
_MIN_SERVICE_TOKEN_LENGTH = 32


async def require_service_auth(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Require an exact Bearer token on every route except the health probe."""
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    expected = os.environ.get("KICAD_SERVICE_TOKEN", "").strip()
    if len(expected) < _MIN_SERVICE_TOKEN_LENGTH:
        return JSONResponse(
            status_code=503,
            content={"error": "service_auth_not_configured"},
        )

    authorization = request.headers.get("authorization", "")
    scheme, separator, provided = authorization.partition(" ")
    valid = (
        separator == " "
        and scheme.lower() == "bearer"
        and bool(provided)
        and secrets.compare_digest(provided, expected)
    )
    if not valid:
        return JSONResponse(
            status_code=401,
            content={"error": "unauthorized"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)
