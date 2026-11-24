"""Validate beta configuration without printing secrets or sending network requests.

Run as the eventual service account with the same environment it will use.
This does not prove domain/TLS, edge auth, actual provider billing limits or user relevance.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path

from savoroute.beta.admission import BetaPolicy
from savoroute.live.review import LiveReviewRegistry


def preflight(env: dict[str, str], *, catalog: Path, frontend: Path) -> dict[str, object]:
    policy = BetaPolicy.from_environ(env)
    if policy is None:
        raise ValueError("SAVOROUTE_BETA_ENABLED must be 1")
    if not catalog.is_file():
        raise ValueError("catalog file is missing")
    if not frontend.is_file():
        raise ValueError("React distribution is missing; run npm run build")
    parent = policy.database.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("beta usage directory is missing or a symlink")
    if parent.stat().st_mode & 0o077:
        raise ValueError("beta usage directory must not be accessible by group/others")
    if policy.database.exists():
        state = policy.database.lstat()
        if not stat.S_ISREG(state.st_mode) or state.st_mode & 0o077:
            raise ValueError("beta usage DB must be a private regular file")
    ai_enabled = env.get("SAVOROUTE_AI_ENABLED") == "1"
    live_enabled = env.get("SAVOROUTE_LIVE_ENABLED") == "1"
    if (ai_enabled or live_enabled) and not (
        env.get("SAVOROUTE_OPENAI_API_KEY") or env.get("OPENAI_API_KEY")
    ):
        raise ValueError("a paid provider was enabled without a server-side API key")
    reviewed_count = 0
    if live_enabled:
        path = env.get("SAVOROUTE_LIVE_REVIEW_FILE")
        if not path:
            raise ValueError("live beta requires a human review file")
        registry = LiveReviewRegistry.load(path)
        reviewed_count = sum(
            record.decision == "approved" for record in registry.reviews.values()
        )
    return {
        "configuration": "valid",
        "beta_enabled": True,
        "ai_enabled": ai_enabled,
        "live_enabled": live_enabled,
        "reviewed_leads_in_file": reviewed_count,
        "review_mode": "strict" if live_enabled else "not_applicable",
        "limits_are_attempts_not_usd": True,
        "tls_and_edge_auth_verified": False,
        "real_world_quality_verified": False,
        "provider_hard_spend_limit_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("data/real/boston-osm-2026-11.json"))
    parser.add_argument("--frontend", type=Path,
                        default=Path("src/savoroute/web/consumer_dist/index.html"))
    args = parser.parse_args()
    try:
        result = preflight(dict(os.environ), catalog=args.catalog, frontend=args.frontend)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise SystemExit(f"Beta preflight failed: {exc}") from exc
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
