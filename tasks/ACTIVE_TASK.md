# Current Task: 007 | Endpoint Central on-prem adapter

Status: **Provisionally Complete / Fixture-validated only. Live synchronisation NOT activated**
(2026-11-03, branch DEV). Endpoint Central source availability is **Beta**.

**Read:** AGENTS.md, docs/00, 05 (§2, shared normalisation, failure behaviour, fixtures), 15, 17.
Previous task: 006 LibreNMS (Provisionally Complete, CI run 41629185647 green).

## Scope

- A read-only adapter for ManageEngine Endpoint Central on-premises that uses the Task 004
  observation and reconciliation pipeline and the Task 006 sync engine, gates and admin
  screen.
- docs/05 §2:
  - verify the API generation by handshake (`/dcapi` current, `/api/1.4` older);
  - least privilege, no device or patch actions;
  - data covers endpoint ID, hostname/domain, OS/build, manufacturer/model/serial/UUID,
    and interface MAC/IP.
- docs/05 fixtures: normal, empty, missing serial, duplicate hostname, changed IP,
  pagination, unauthorized, rate limit, incomplete date and schema drift.

Out of scope: installed software (Task 016), monitors and peripherals (need a real
payload), and any live connection.

## Outcome

**Shared connector framework (refactor; LibreNMS behaviour unchanged, its 68 tests pass):**
- `adapters/http.py` is a generic GET-only client, now used by both connectors.
- `adapters/registry.py` lists the available connectors.
- The sync engine and serializers no longer hard-code LibreNMS.
- Allowed auth headers are validated per source on save; new integrations get the source
  default.
- The API exposes `connector` (allowed auth headers, whether there is an evidence pass).

**Endpoint Central adapter (`adapters/endpoint_central/`):**
- **Detection:** the API generation is detected during the connection test or the first
  sync and stored as a capability.
- **Server version:** the build is read from `api/1.4 serverproperties` when available.
- **Listing:** the computer list is paginated (500 per page). Duplicate IDs, repeated
  pages, a failed later page or a short total are processed as an incomplete listing, so
  nothing is marked stale.
- **Details:** they are cached by successful-scan time and age, and re-read only for new or
  rescanned computers.
- **Mapping:** fields are looked up tolerantly so modest schema drift works.
  - The device type is guessed only from chassis, server OS or VM model.
  - OEM placeholders are treated as unknown.
  - Scan time falls back to agent contact time, with a warning.
- **Errors:** error envelopes are mapped to auth or source errors.

**Migrations:** `integrations.0005_authorization_scheme` (new `authorization` raw-header
choice) and `integrations.0006_endpoint_central_beta` (data: Planned → Beta). Both are
reversible.

**APIs:** no new paths (63 total). `GET /integrations/{id}/` adds `connector`. PATCH/POST
validate `auth_scheme` per source.

**UI:** the integration page is generic. Texts, placeholders and the auth-header options
come from the source/connector. FDB and neighbour settings are shown only for connectors
with an evidence pass. The capability labels cover the EC API generation and the fact that
software is not collected.

**Also changed:** interface names may contain `( ) # + ,` (Windows adapter names), which
also applies to manual entry (ASM-31).

**Fixtures:** `fixtures/endpoint_central/api/responses.json` covers both generations, with
10 computers for api/1.4 and 3 for dcapi (see its README for the scenarios).

**Verification (workstation; SQLite test-only fallback):**
- Backend: **413 passed, 6 skipped** (the skips are PostgreSQL-only). This includes 30 new
  Endpoint Central tests:
  - generation detection and preference;
  - per-computer mapping;
  - placeholders, schema drift and scan-time fallback;
  - GET only, raw Authorization header, no software reads and no stored secrets;
  - pagination, a failed later page, a short total and stale removal;
  - detail failure;
  - 401 and error-envelope auth failures, 429 Retry-After and transport retries;
  - idempotent repeat sync (list only);
  - re-read on a newer scan, with an IP change, and refresh after max age;
  - same hostname never merged;
  - strong-serial auto-link only when enabled;
  - locked fields;
  - connection test, per-source auth header validation, Beta status and the scheduler.
- Ruff and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and was regenerated.
- Frontend: typecheck, oxlint, **86 tests** (1 new) and the build all pass.
- GitHub CI run 41638482133 on `747c7bf` (PostgreSQL 16 + Redis 7): backend **419 passed,
  0 skipped**; frontend, Compose config and image builds all pass.
- Not run: the Docker stack, Playwright, a browser review, and **any live Endpoint Central
  connection** (not authorised).

**Activation prerequisites (not done):**
1. The Docker-host verification passes.
2. DEC-06 is approved: a read-only API key, the build, the listener URL and port, and
   sanitized real responses.
3. Compare the real responses with the fixtures and adjust the mapping key lists if needed.
4. Put the key in `ITAM_INTEGRATION_ENDPOINT_CENTRAL_KEY`, set
   `ITAM_ALLOW_LIVE_INTEGRATIONS=true`, record the approval, run a connection test, then
   enable the schedule.

**Unresolved:** ASM-28 to ASM-31 in docs/17. The `dcapi` envelope and pagination parameter
names are unconfirmed. No software, monitor or peripheral data yet. Not load-tested
(Task 022).

## Change request 007a | Stricter strong-match gate (2026-11-03)

Status: **Complete (workstation-verified)**. Operator direction: a matching serial alone must
not merge assets; the manufacturer, asset class and other identifiers must also agree.
Recorded as ADR-013 / ASM-32 in docs/17. This aligns the code with docs/03 step 2.

- **Auto-link:** happens only when the instance allows it and all of these hold:
  - the manufacturer is known and the same on both sides;
  - the category root is known and the same;
  - no identifier contradicts the match.
- **Conflict candidates:** these clashes now produce a `conflict` candidate; previously
  they gave `strong` with a note, or a silent `new_device`:
  - a different manufacturer or category;
  - a different serial on the asset;
  - a hardware UUID that differs from what other linked sources report;
  - another asset sharing several identifiers;
  - the same serial with a different manufacturer (new `serial_other_make` key, strength
    `conflicting`).
- **Unknown values:** an unknown manufacturer or class stays a `strong` candidate for review.
- **API:** each match adds `manufacturer_agrees` (nullable, so old candidates still
  serialise), and the key strength gains `conflicting`. No migration is needed.
- **UI:** the candidate page shows a Manufacturer column and a red "Conflicting" key badge.
- **Verification:**
  - backend 419 passed, 6 skipped (6 new and 2 updated matching tests);
  - ruff clean; OpenAPI regenerated with `--fail-on-warn`;
  - frontend typecheck, lint, 87 tests (1 new) and build pass.

Proposed next task: **008 | Intune managedDevice adapter** (tasks/BACKLOG.md). It needs
DEC-07 (tenant, app registration and consent) before any live test. Do not start
automatically.
