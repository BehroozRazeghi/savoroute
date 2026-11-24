# SavoRoute PR #30 — Controlled beta admission (not public-launch approval)

This increment adds **optional**, default-off, shared (multi-process) SQLite admission
limits to the two billable APIs: `POST /v1/ai/interpret` and `POST /v1/live/discover`.
No prompted text, images, raw IP addresses, provider responses, or credentials are
written to the admission database. It records only global request-attempt totals
and HMAC-hashed client-address minute counters.

## Deployment boundary

**Not production-ready by itself.** This is deliberately *not* authentication,
web-application firewalling, an accurate dollar spending cap, user-level limits,
privacy-policy compliance, or HTTPS/TLS. Before inviting external users:

1. Deploy behind an authenticated HTTPS reverse proxy (e.g. an identity-aware
   access gateway). Restrict inbound port exposure; keep Uvicorn bound to
   `127.0.0.1`; this beta mode rejects non-loopback binding. Protect `/docs` and API access
   at the edge. Terminate TLS and configure HSTS there. Never put OpenAI keys
   or `SAVOROUTE_API_KEY` in browser JavaScript, query strings or tracked files.
2. Set explicit allowed `Host` values and a provider-side spending ceiling.
   **A request-attempt limit cannot bound USD cost**: per-call tokens, web-search
   usage and billing rates vary. Consult provider usage/billing independently.
3. Configure edge authentication and **per-user** anti-abuse rate limits. The
   app sees `request.client.host`, which may be the reverse proxy's IP. It
   configures Uvicorn with `proxy_headers=False`, so its per-client limiter
   may throttle everyone behind one proxy; do not rely on that alone.
4. Set up centralized monitoring and error collection without logging prompts,
   images or secrets; verify consent UX and data retention requirements.
5. Run the labeled real-world search relevance evaluation. A source-linked URL
   is **not independent evidence** of cuisine/menu/operating status. Manually
   review questionable leads, including broad Mediterranean matches.

## Configure an invite-only beta on a private host

```bash
# Use your deployment host, not inside a publicly served or git-tracked tree.
install -d -m 700 "$HOME/.local/share/savoroute-beta"
export SAVOROUTE_BETA_ENABLED=1
export SAVOROUTE_BETA_USAGE_DB="$HOME/.local/share/savoroute-beta/admission.sqlite3"
read -rsp 'Generate/store a private 32+ character HMAC secret: ' SAVOROUTE_BETA_IDENTITY_SECRET
printf '\n'
export SAVOROUTE_BETA_IDENTITY_SECRET
export SAVOROUTE_BETA_TRUSTED_HOSTS='localhost,127.0.0.1'
export SAVOROUTE_BETA_AI_DAILY=20
export SAVOROUTE_BETA_LIVE_DAILY=10
export SAVOROUTE_BETA_CLIENT_MINUTE=3
# Additional authorized domain must be explicitly appended for real deployment.
```

Never use the HMAC secret as a substitute for the OpenAI provider key. Admission
checks execute only after valid consent and input validation, **before** the
paid provider call. A failed call still consumes a slot to avoid cost bypass.
Counters are shared among processes using the SAME SQLite DB on the SAME local
host/file system with SQLite file locking. This is not a distributed service
across multiple servers, containers with independent volumes, or network file
systems. Use managed Redis or a proper DB and edge quotas for multi-host use.
The fixed-minute per-client limit is not a sliding window. Built-in process-local
semaphores remain active and separate.

Startup **refuses** a missing/misconfigured beta database, secret or trusted host
list. After startup, an unavailable DB fails closed (503), and an exhausted
budget returns 429 with `Retry-After`. `/readyz` checks DB readiness but does not
report usage. `/healthz` remains a liveness check. Both are unauthenticated.

## Offline usage inspection

```bash
python scripts/beta_usage.py "$SAVOROUTE_BETA_USAGE_DB"
```

This reports the current UTC day's **attempt counts**, never dollars. For a
separate new day use `--day YYYY-MM-DD`. All spent tokens and web searches must
be monitored at the provider's billing/account level.

## Verification

```bash
python -m pytest -q tests/test_beta_admission_pr30.py
python -m ruff check src tests scripts
python -m pytest -q
node --test tests/web/*.test.mjs
cd webapp && npm ci && npm run build && npm run test:e2e
```

The PR does not modify the retrieval engine, matching logic, MCP or UI. User
identity, full request logging, tracing, and self-service accounts are outside
scope. Do not publicly expose the local development server simply because
these limits exist.
