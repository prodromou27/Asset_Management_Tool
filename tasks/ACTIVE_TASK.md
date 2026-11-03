# Current Task: 006 | LibreNMS read-only adapter + fixtures

Status: **Provisionally Complete / Fixture-validated only. Live synchronisation NOT activated**
(2026-11-03, branch DEV). LibreNMS source availability is **Beta**.

**Read:** AGENTS.md, docs/00, 02, 03, 05, 14, 15, 17.

## Preconditions verified (Task 004 audit)

Observation storage, identity matching, field authority and reconciliation were complete.
Gaps that blocked a connector, resolved here:

1. No place for FDB/LLDP/CDP evidence → new `network` app (`NeighborEvidence`).
2. `reconciliation.ingest` could not use a connector-owned run, report progress or be told
   the listing was incomplete → `run=`, `on_progress=`, `complete=` parameters.
3. No credential storage → secret references (`env:ITAM_INTEGRATION_*`, `file:<name>`).
4. LibreNMS timestamps carry no zone → per-instance `source_timezone`.

Non-blocking and still open: raw payload retention (DEC-15), candidate free-text search.

## Acceptance (from the task request)

- Read-only: GET only, HTTPS with certificate validation, no redirects, no LibreNMS changes,
  no scanning, no agents.
- Tokens never in the DB, API responses, audit or logs.
- Records pass through Task 004 observation/reconciliation; locks never overwritten; no
  auto-merge on hostname, IP or MAC; unmatched devices in the reconciliation queue.
- Initial, scheduled and manual runs; idempotent; checkpoint/progress; retries and rate
  limits; partial failure recovery; staleness; per-run statistics.
- Admin configuration and health screen with sync history.
- No live connection without the Docker-host verification and an approved read-only account.

## Outcome

**Migrations:** `integrations.0003` (connection, schedule, approval and health fields on
IntegrationInstance; progress/warning fields on SyncRun; `queued` status),
`integrations.0004_librenms_beta` (data: LibreNMS Planned → Beta), `network.0001_initial`
(NeighborEvidence). All reversible; CI reverses `network` too.

**APIs (4 new paths, 63 total):**
- `POST /integrations/{id}/test/`: connection test (system, route listing, one device).
- `POST /integrations/{id}/sync/`: queue a manual sync (202; 409 if one is active).
- `POST /integrations/{id}/live-access/`: approve or revoke live access (reason required).
- `GET /assets/{id}/network-evidence/`: FDB and neighbour evidence, scoped to visible assets.
- `GET/PATCH /integrations/{id}/` now expose and validate the connector configuration and
  health; `GET /integrations/{id}/runs/` shows progress, warnings and request counts.

All connector actions require `integrations.manage` and are audited.

**Engine:** Celery task `integrations.run_sync` plus a beat dispatcher every 5 minutes.
Runs have an abandoned-run heartbeat reclaim (30 min) and one active run per integration.
Device enrichment is cached by LibreNMS `last_discovered` and age. The FDB/links pass runs
every N hours. Optional routes are detected and degrade to warnings. Auth failures and
listing failures fail the run without marking anything stale.

**UI:** Integration detail page (`/admin/integrations/:id`) with:
- gate notices;
- a status strip;
- health;
- a live-access panel;
- capabilities;
- configuration;
- sync history with progress polling.

The Integrations list links to it and shows Beta / "Live access not approved". The asset
Network tab gains "Observed network evidence" (observed, not a confirmed cable).

**Fixtures:** `fixtures/librenms/api/responses.json` contains sanitized data for Cisco,
Fortinet, HPE Aruba, Huawei, Check Point, Dell, an unknown vendor, a missing serial, a
duplicate serial, conflicting serials, an IP-literal hostname and a disabled device, plus
FDB and links.

**Verification (workstation; SQLite test-only fallback):**
- Backend: **383 passed, 6 skipped** (the skips are PostgreSQL-only). This includes 68 new
  connector tests covering:
  - vendor mapping;
  - GET-only requests and both auth headers;
  - secret stripping;
  - timezone handling;
  - idempotent repeat sync (1 request) and re-enrichment;
  - auth failure, timeouts with backoff, 429 Retry-After and partial enrichment failure;
  - missing optional routes;
  - stale devices, duplicate serials and hostname-only cases (no auto-link);
  - locked fields and cross-site scope;
  - evidence upsert and retirement;
  - gates, queueing, scheduler and abandoned runs;
  - API permissions, audit and validation;
  - SSRF, redirect and URL refusal;
  - secret references.
- Ruff check and format clean; `makemigrations --check` clean; OpenAPI validates with
  `--fail-on-warn` and matches `openapi.yaml`.
- Frontend: typecheck, oxlint, **85 tests** (9 new) and the production build all pass.
- PostgreSQL CI: see the commit after this one (recorded below once the run finishes).
- Not run: the Docker dev stack, Playwright, a manual browser review, and **any live
  LibreNMS connection** (not authorised).

**Activation prerequisites (not done; do not skip):**
1. Docker-host verification on AlmaLinux 10.2 passes.
2. DEC-05: a read-only LibreNMS API account is approved, along with its URL, the installed
   version, the server time zone and a sanitized real sample.
3. Put the token in the host secret (`ITAM_INTEGRATION_LIBRENMS_TOKEN` or a file in
   `ITAM_SECRETS_DIR`).
4. Set `ITAM_ALLOW_LIVE_INTEGRATIONS=true`, record the approval on the integration, and run
   a connection test (confirm Bearer vs X-Auth-Token).
5. Compare real field names with the fixtures before enabling the schedule.

**Unresolved:** see ASM-21 to ASM-27 in docs/17. The 2k–10k device figure is not
load-tested (Task 022). FDB VLAN shows the LibreNMS row id. Port names are known only for
IP-bearing ports. The adapter stays Beta until live-validated.

Proposed next task: **007 | Endpoint Central on-prem adapter** (tasks/BACKLOG.md).
Do not start automatically.
