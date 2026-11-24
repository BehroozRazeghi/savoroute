"""Opt-in development server. Do not expose directly to untrusted networks."""

from __future__ import annotations

import os
from pathlib import Path


def serve(
    *, catalog: str | Path | None = None, index: str | Path | None = None,
    evidence: str | Path | None = None,
    osm: str | Path | None = None, reviewed_media: str | Path | None = None,
    source_facts: str | Path | None = None,
    recipe_notes: str | Path | None = None,
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

    # AI is disabled by default. Enabling it requires deliberate operator opt-in
    # and a server-only provider secret. Never place this secret in webapp code.
    ai_provider = None
    if os.environ.get("SAVOROUTE_AI_ENABLED") == "1":
        from savoroute.ai.provider import OpenAIResponsesProvider

        secret = os.environ.get("SAVOROUTE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not secret:
            raise ValueError("SAVOROUTE_AI_ENABLED=1 requires SAVOROUTE_OPENAI_API_KEY")
        ai_provider = OpenAIResponsesProvider(
            api_key=secret, model=os.environ.get("SAVOROUTE_AI_MODEL", "gpt-6.1-terra"),
        )
    # Live discovery is a SEPARATE opt-in paid web-search feature; AI
    # interpretation can work without it, and vice versa.
    live_provider = None
    if os.environ.get("SAVOROUTE_LIVE_ENABLED") == "1":
        from savoroute.live.provider import OpenAIWebSearchProvider

        secret = os.environ.get("SAVOROUTE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not secret:
            raise ValueError("SAVOROUTE_LIVE_ENABLED=1 requires SAVOROUTE_OPENAI_API_KEY")
        live_provider = OpenAIWebSearchProvider(
            api_key=secret, model=os.environ.get("SAVOROUTE_LIVE_MODEL", "gpt-6.1-terra"),
        )
    # The opt-in beta policy enforces cross-worker admission. It is not an
    # authentication, TLS, edge abuse, or provider-side USD-spending limit.
    from savoroute.beta.admission import BetaAdmission, BetaPolicy

    beta_policy = BetaPolicy.from_environ(os.environ)
    if beta_policy is not None and host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("controlled beta must bind to loopback behind a trusted HTTPS proxy")
    beta_admission = BetaAdmission(beta_policy) if beta_policy is not None else None
    review_registry = None
    review_file = os.environ.get("SAVOROUTE_LIVE_REVIEW_FILE", "")
    if review_file:
        from savoroute.live.review import LiveReviewRegistry

        review_registry = LiveReviewRegistry.load(review_file)
    # Public-facing invite beta never promotes unreviewed web leads to recommendations.
    if beta_policy is not None and live_provider is not None and review_registry is None:
        raise ValueError("Live beta requires SAVOROUTE_LIVE_REVIEW_FILE with human reviews")
    # An HTTP API key alone is not equivalent to TLS or hardened hosting.
    application = create_app(catalog_path=catalog, index_path=index,
                             evidence_path=evidence, osm_path=osm,
                             reviewed_media_path=reviewed_media,
                             source_facts_path=source_facts, recipe_notes_path=recipe_notes,
                             api_key=api_key, ai_provider=ai_provider,
                             live_provider=live_provider, beta_admission=beta_admission,
                             live_review_registry=review_registry)
    options = {"host": host, "port": port, "reload": False, "access_log": beta_policy is None and osm is None}
    if beta_policy is not None:
        # Never use X-Forwarded-For as an anonymous client's identity. An
        # authenticated edge should apply real per-user limits separately.
        options["proxy_headers"] = False
    uvicorn.run(application, **options)
