"""Opt-in development server. Do not expose directly to untrusted networks."""

from __future__ import annotations

import os
from pathlib import Path


def serve(
    *, catalog: str | Path | None = None, index: str | Path | None = None,
    evidence: str | Path | None = None,
    host: str = "127.0.0.1", port: int = 8000,
    api_key_env: str = "SAVOROUTE_API_KEY",
) -> None:
    """Run the read-only API; require an access key for non-loopback binding."""
    if not isinstance(api_key_env, str) or not api_key_env:
        raise ValueError("api_key_env must be a nonempty environment variable name")
    if not 1 <= port <= 65535:
        raise ValueError("port must be in [1, 65535]")
    api_key = os.environ.get(api_key_env) or None
    if host not in {"127.0.0.1", "::1", "localhost"} and api_key is None:
        raise ValueError("non-loopback binding requires an API key environment variable")
    try:
        import uvicorn

        from savoroute.api.app import create_app
    except ImportError as exc:
        raise RuntimeError('Install HTTP dependencies: python -m pip install -e ".[api]"') from exc

    # An HTTP API key alone is not equivalent to TLS, rate limits, or hardened hosting.
    application = create_app(catalog_path=catalog, index_path=index, evidence_path=evidence, api_key=api_key)
    uvicorn.run(application, host=host, port=port, reload=False)
