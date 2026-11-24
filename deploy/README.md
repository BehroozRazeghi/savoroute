# SavoRoute PR #31 — single-host HTTPS invite-only beta (operator playbook)

**Not a production launch approval.** See also
`docs/pr31-real-world-release-gates.md` for the source-review and manual
100-query annotation protocol.  The repository provides a concrete
single-host pattern using an unprivileged Python systemd service on loopback and
Caddy HTTPS + HTTP Basic Authentication. The operator must provision a domain,
DNS, accessible host, firewall, genuine reviews and provider account controls.
Do not expose Uvicorn directly, share passwords publicly, or claim user-level
identity: this is one shared beta credential, suitable only for a small trusted
invitation group. It does not include edge WAF, brute-force protections,
per-person revocation, provider dollar-accounting or multi-host coordination.

## Prerequisites

- A maintained Linux host with a public domain pointing to it, public ports
  80/443 available, outbound 443, and port 8000 **not publicly accessible**.
- `caddy` installed by the operator from trusted official packages, Python
  3.11–3.13 and Node 22. Do not copy local virtual environments between hosts.
- A dedicated project-scoped OpenAI API key with a **hard spending limit**
  enabled in the provider platform, separately from app request ceilings.
  If you cannot configure/verify one, disable paid provider features.
- Human-reviewed records in `/var/lib/savoroute-beta/reviews.json`. The empty
  template permits no live web result; it does not fabricate approvals.
- Review the draft privacy notice with the actual hosting/retention settings.

## Install from a verified Git commit

Run as the administrator, choosing a vetted tagged commit/commit hash. This
is a reference layout, not a self-executing installation script:

```bash
sudo useradd --system --user-group --home /opt/savoroute --shell /usr/sbin/nologin savoroute
sudo install -d -m 0755 /opt/savoroute
sudo install -d -o savoroute -g savoroute -m 0700 /var/lib/savoroute-beta
sudo install -d -o root -g root -m 0700 /etc/savoroute-beta
# Deploy the vetted source tree to /opt/savoroute/app as root-owned, readable
# by the savoroute service user, with no .env/private files in that tree.
cd /opt/savoroute/app
sudo python3 -m venv /opt/savoroute/venv
sudo /opt/savoroute/venv/bin/pip install -e '.[api,ai]'
# Build webapp with Node 22 and npm ci, then npm run build; ensure dist exists.
```

Build the React bundle **before starting** the service. Use a vetted Git SHA
and standard supply-chain/OS patching procedures. Ensure SQLite's directory
stays writable by only the app user. Create the review file at a private
location; copy only human-reviewed source decisions there:

```bash
sudo install -o savoroute -g savoroute -m 0600 \
  data/evaluation/live_review_registry_empty.json \
  /var/lib/savoroute-beta/reviews.json
```

## Environment, systemd and Caddy

1. Copy `deploy/examples/server.env.example` to
   `/etc/savoroute-beta/server.env` and `deploy/examples/caddy.env.example` to
   `/etc/savoroute-beta/caddy.env`; **replace every placeholder**. Set
   owner=root, group=root and mode=0600. `SAVOROUTE_BETA_IDENTITY_SECRET` is
   32+ cryptographically random bytes and **must persist across restarts**.
2. Generate the basic-auth password hash with interactive `caddy hash-password`
   (do not put plaintext passwords in shell arguments or Git). Put the
   resulting hash in `SAVOROUTE_BETA_PASSWORD_HASH` and issue the shared login
   only to trusted beta testers; rotate it if compromised.
3. Install `deploy/systemd/savoroute-beta.service` at
   `/etc/systemd/system/savoroute-beta.service` and
   `deploy/caddy/Caddyfile` at `/etc/caddy/Caddyfile` (or integrate into your
   existing Caddy config without overriding existing sites).
4. Have systemd load the Caddy environment file using
   `sudo systemctl edit caddy`, with the override:

   ```ini
   [Service]
   EnvironmentFile=/etc/savoroute-beta/caddy.env
   ```

5. Confirm Caddy reads the site domain/hash and validate the configuration
   using `sudo caddy validate --config /etc/caddy/Caddyfile` **with the same
   Caddy environment configured**. A manual invocation without those
   variables may not validate; use the actual service environment.
6. `sudo systemctl daemon-reload`, `sudo systemctl enable --now
   savoroute-beta`, and `sudo systemctl restart caddy` **only after** DNS,
   firewall and configuration checks are complete.

Never use an additional `SAVOROUTE_API_KEY` in the frontend. Authentication
runs at the proxy and the app runs **only on loopback**. Keep the full backend
port unreachable to remote users. Caddy strips `Authorization` before proxying.
Caddy's HTTPS certificates are managed automatically for qualifying domains;
verify actual HTTPS and redirect behavior before inviting users.

## Pre-invitation smoke checks (operator host)

```bash
sudo systemctl status savoroute-beta --no-pager
sudo systemctl status caddy --no-pager
sudo ss -ltnp | grep ':8000'             # must show 127.0.0.1:8000 only
curl --fail-with-body -H 'Host: beta.example.com' http://127.0.0.1:8000/readyz
curl -I https://beta.example.com/app/  # without auth must be HTTP 401
# Test login with browser HTTPS (never paste passwords in shell command history)
# Verify ordinary catalog, explicit consent, controlled quotas, and manual review.
python scripts/beta_usage.py /var/lib/savoroute-beta/usage.sqlite3
sudo journalctl -u savoroute-beta -n 30 --no-pager
```

For intentional release failure, a missing admission SQLite store must yield
503 readiness; exhausted quota must yield 429; a nonexistent approved review
must never be presented. Disable paid provider features first if unsure.

## Monitoring, incident response, rollback

- Journal contains bounded structured `beta_http` events: endpoint category,
  status, duration and opaque request ID, **no raw user inputs**. Restrict
  journald access, configure log retention on the actual host, and inspect 429,
  503 and 5xx trends. Use `scripts/beta_usage.py` for UTC attempt counts.
- Configure an independent provider hard-spend limit and billing alerts. A
  global attempt budget does not bound spend or guarantee API affordability.
- On observed false cuisine claim, set the exact source review to `rejected`,
  restart the beta backend, and re-evaluate; expired or missing approvals
  automatically disappear. Do not change the source to 'approved' without a
  human evidence note.
- On key leak: immediately revoke the provider key, rotate beta credentials,
  stop the service, preserve restricted incident logs, then restore from a
  verified code revision. For emergency disablement, set
  `SAVOROUTE_AI_ENABLED=0` and `SAVOROUTE_LIVE_ENABLED=0` in the server
  environment and restart, or stop the application/proxy.
- Backup and restore SQLite database safely with `sqlite3.Connection.backup`;
  a plain live-file copy while SQLite WAL is active may omit writes. Keep
  private backups and test restoration before relying on them.
- Single server availability only. Add edge anti-brute-force/rate limits, a
  true identity-aware gateway, audited provider/project spending caps and
  deployed monitoring before any unrestricted audience.

## Release gates

```bash
python -m ruff check src tests scripts
python -m pytest -q
node --test tests/web/*.test.mjs
(cd webapp && npm ci && npm run build && npm run test:e2e)
python scripts/review_live_leads.py check /var/lib/savoroute-beta/reviews.json
python scripts/beta_preflight.py --catalog data/real/boston-osm-2026-11.json
python scripts/review_quality_gate.py /path/to/real_reviewed_100_cases.json
```

The final evaluation command **must fail** on unlabeled template cases. The
100-query template is not a measured relevance benchmark until an actual
human reviewer supplies real results, stable IDs, labels and evidence notes.
The supplied gate thresholds are provisional and should be reviewed against
real error costs. A successful CI check is not human review or real deployment.

## Privacy presentation

The React app includes a collapsible beta data-use summary. The separate
`docs/privacy-controlled-beta.md` is a **draft operator/legal checklist** and
is not a final public policy. Supply an actual operator contact, hosting and
retention details, then publish the approved privacy notice through the
chosen deployment before inviting users.
