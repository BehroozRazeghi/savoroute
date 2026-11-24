"""Minimal privacy-preserving operational events; no URLs, prompts, images or identities."""

from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from fastapi import Request, Response

# Uvicorn configures this logger with a console handler at INFO. Using it
# ensures sanitized events reach journald even when the root logger is WARNING.
LOGGER = logging.getLogger("uvicorn.error")


def endpoint_bucket(path: str) -> str:
    if path == "/readyz":
        return "readiness"
    if path == "/healthz":
        return "liveness"
    if path == "/v1/ai/interpret":
        return "ai_interpret"
    if path == "/v1/live/discover":
        return "live_discover"
    if path.startswith("/app/") or path == "/app":
        return "consumer_app"
    if path.startswith("/v1/"):
        return "other_api"
    return "other"


async def log_request(request: Request, call_next) -> Response:
    """No raw path, query, client address, authorization header or body in logs."""
    started = time.monotonic()
    request_id = uuid4().hex[:16]
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        LOGGER.info(json.dumps({
            "event": "beta_http", "request_id": request_id,
            "category": endpoint_bucket(request.scope.get("path", "")),
            "method": request.method if request.method in {"GET", "POST", "HEAD"} else "other",
            "status": status, "duration_ms": round((time.monotonic() - started) * 1000),
        }, separators=(",", ":")))
