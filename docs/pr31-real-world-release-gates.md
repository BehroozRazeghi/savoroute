# PR #31 — source review, real-world evaluation and invite-only release gates

This is an operational protocol. **It does not certify restaurants or create
human relevance judgments.** The existing 100 queries are unreviewed prompts;
there are deliberately no invented ground-truth labels or fabricated venues.

## A. Collect actual web leads *locally*, outside strict beta mode

Use a privately operated dev instance bound to `127.0.0.1`, with
`SAVOROUTE_BETA_ENABLED=0`, `SAVOROUTE_LIVE_ENABLED=1`, a privately configured
server API key, and real explicit consent. Each request is charged by the
external provider. Save responses outside the Git checkout:

```bash
install -d -m 700 "$HOME/.local/share/savoroute-review"
# In a separate terminal, after starting the local development server:
# curl --fail-with-body ... POST /v1/live/discover > \
#   "$HOME/.local/share/savoroute-review/live-response.json"
python scripts/review_live_leads.py prepare \
  "$HOME/.local/share/savoroute-review/live-response.json" \
  --output "$HOME/.local/share/savoroute-review/reviews.json"
```

The tool never approves a restaurant itself. For each record, check the
**exact entity, city, cuisine claim and linked original source**, independently
of the model-generated label. Use a real public HTTPS evidence URL, dated
human reviewer ID and a substantive evidence note. Mark `approved` only with
sufficient evidence, `rejected` for false/broad cuisine or wrong city, or
`pending` when uncertain. A broad “Mediterranean” tag is **not** evidence of
Persian cuisine. Review decisions on web leads must be revisited at most 90
days after the recorded date. Search source links and evidence links are not
independent proof of current operating hours or menu dishes.

```bash
python scripts/review_live_leads.py check \
  "$HOME/.local/share/savoroute-review/reviews.json"
```

During invite-only beta, set `SAVOROUTE_LIVE_REVIEW_FILE` to the reviewed file
owned by the service account and restart the server. The API will display only
fresh, exact-source `approved` web leads. Catalog matches remain separately
labeled source-recorded and may be stale. The reviewer registry should not be
published into the repo if it contains private reviewer notes or identifiers.

## B. Independently evaluate the real queries

The unreviewed 100-query template is
`data/evaluation/live_discovery_100_query_review_template.json`. For each
query: run real searches and capture actual API results. Do not create or edit
labels from AI suggestions. `scripts/prepare_review_case.py` converts a saved
request/response pair into a single **unreviewed** case, generating stable web
IDs from the visible candidate identity and source URL.

```bash
python scripts/prepare_review_case.py \
  --case-id review_001 \
  --request /private/location/request-001.json \
  --response /private/location/response-001.json \
  --output /private/location/case-001.json
```

For evaluation, aggregate these into one `cases` array, preserving the case
IDs and captured result order. Independently identify relevant establishments,
including when none were returned, and annotate `answerable`, `relevant_ids`,
`review_status=reviewed`, `reviewed_by`, `reviewer_notes` and `reviewed_at`
(ISO YYYY-MM-DD). Relevant IDs must be the exact `results[].id` values. For
an answerable case where no restaurant was returned, a reviewer still needs to
establish independently that a qualifying real candidate exists; do not simply
label all empty responses “unanswerable.” Note the evaluation compares the
WEB candidates only, not the separate recorded catalog group.

Set the top-level dataset type to `real_reviewed` only after genuine review.
The gate refuses `synthetic`, `fixture`, `template`, `unreviewed` and missing
labels. Run:

```bash
python scripts/review_quality_gate.py \
  /private/location/real_reviewed_100_cases.json
```

Initial provisional gate: at least 100 reviewed cases, at least 20 known
answerable and 20 independently identified unanswerable cases, zero hard
constraint violations, >=80% success@5 on answerable, >=90% correct abstention
on unanswerable, >=95% valid public HTTPS source URL coverage. These
thresholds are *proposed release targets*, not measured performance.
Coverage of source URLs is not evidence that those URLs actually substantiate
claims; use the manual source review separately. Report Wilson or bootstrap
confidence intervals and query-stratified metrics before interpreting the
results for product positioning. Do not claim public-beta readiness from unit
fixtures or unreviewed datasets.

## C. Infrastructure and launch

- Complete `deploy/README.md`, validating DNS, Caddy HTTPS and edge login;
  publicly accessible backend port is prohibited.
- Configure provider-side **enforced** hard spending cap and billing alarms;
  verify with the provider platform, not with local attempt counters.
- Verify privacy notice with contact, actual processing and retention, log
  policy and jurisdiction; current privacy file is an incomplete draft.
- Conduct a controlled end-to-end test with a real invited tester, including
  accessible UI, correct consent, no bogus cuisine results, 429/503 recovery,
  negative access-control test, and monthly provider spending review.
- Ensure the operator can stop AI/live immediately and revoke exposed secrets.
  Keep a tagged rollback commit and a private SQLite backup procedure.
- Separate beta credentials per tester and enforce edge WAF/abuse policy
  before growing beyond a small trusted group. Shared Basic Auth is not a
  general-public authentication system.

**Decision rule:** no invitations until all criteria are evidenced and signed
off by an operator. This repository cannot supply a domain, real manual
judgments, live credentials, hosted TLS or legal sign-off automatically.
