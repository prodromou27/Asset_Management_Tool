# Current Task: 009 | Microsoft Defender for Endpoint machine adapter

Status: **Provisionally Complete / Fixture-validated only. Live synchronisation NOT activated**
(2026-11-03, branch DEV). Defender for Endpoint source availability is **Beta**.

**Read:** AGENTS.md, docs/00, 02, 03, 04, 05 (§4, shared normalisation, failure behaviour,
fixtures), 07, 08, 09, 14, 15, 17.

**Previous:** 008 Intune (Provisionally Complete, CI run 41658532706 green on `d0419e2`).

## Scope

- A read-only Defender for Endpoint connector:
  - Entra client credentials with a **certificate**, using the Defender API audience
    `https://api.securitycenter.microsoft.com/.default`;
  - only the application permission `Machine.Read.All`;
  - only `GET https://api.security.microsoft.com/api/machines`.
- It uses the Task 004 observation and reconciliation services and the Task 006–008
  sync engine, gates and admin screens.
- Security facts are kept apart from asset fields and shown on a Security tab.

Out of scope: remote response or device actions (isolation, scans, quarantine,
remediation, software removal), Advanced Hunting, M365 licensing (Task 010) and any live
tenant connection.

## Outcome

**Connector (`backend/apps/integrations/adapters/defender/`):**
- `client.py` (`DefenderClient`, a `GraphClient` subclass):
  - GET only, fixed to `api.security.microsoft.com/api`;
  - at most one request per 0.6 s, and a run stops before 1,400 requests in an hour (the
    published limits are 100 per minute and 1,500 per hour);
  - a 403 names `Machine.Read.All (WindowsDefenderATP API)`;
  - continuation links are limited to `/api/machines`.
- `adapter.py`:
  - `$top=1000` paging with `@odata.nextLink` or `$skip`;
  - incremental `$filter=lastSeen gt …`;
  - protection against incomplete listings (a failed later page, an unsafe or repeated
    link, the request budget, or the page cap);
  - the connection test reports the read permission and any device-action or write roles
    (for example `Machine.Isolate`, `Machine.Scan`, `*.ReadWrite.*`); syncs warn about
    them too;
  - `store_security_states` saves the security facts.
- `mapping.py`:
  - DNS name, OS, Entra device ID, and NIC MACs and IPs (link-local and loopback dropped)
    go into the observation;
  - security facts and original values go to `raw.fields`;
  - `lastSeen` becomes the observation time, kept outside the checksum;
  - category hints come only from VM metadata or a server OS platform.

**Shared changes:**
- `adapters/entra.py`: the token provider moved from `intune/auth.py` and now takes a
  `scope`; only the Graph and Defender scopes are allowed.
- `registry.py`: a shared Microsoft client factory and a new `store_facts` hook.
  `sync.py` runs the `security` phase after reconciliation.
- `GraphClient` takes its host, prefix, labels and permission from class attributes.

**Identity (ADR-014, ASM-38):**
- The normaliser now has `entra_device_id`, emitted by both Intune and Defender.
- Matching treats it as a strong key, but only between integrations of the same tenant.
- A different Entra ID already reported for the asset is a conflict.
- Auto-link through the Entra ID requires the instance policy, no conflict, and
  corroboration by hostname, MAC or serial; IP never counts.
- Hostname or IP alone still never links.

**Security observation model (new app `apps.security`, ASM-39):**
- `EndpointSecurityState` holds one row per integration and machine: tenant, Entra ID, DNS
  name, OS, onboarding, sensor health, exposure, risk, tags, device group, first and last
  seen, original values, latest observation, last synced, last run, `missing_since` and
  `changed_at`.
- Assets are never written. Rows are never deleted: a machine missing from a complete full
  listing only gets `missing_since`.

**Migrations:**
- `security.0001_endpoint_security_state` (new table).
- `integrations.0009_defender_beta` (data: Planned → Beta).
- Both are reversible; CI now also runs `migrate security zero`.

**APIs:**
- New: `GET /api/v1/assets/{id}/security/`. It needs `discovery.view` plus site access to
  the asset, and returns freshness, link status, source last success, `missing_since` and
  original values.
- Integrations: Defender `connector.permissions` is `["Machine.Read.All"]` and its only
  auth method is `client_certificate`; the endpoint is forced to
  `https://api.security.microsoft.com`.
- Defaults for a new Defender integration: 24 h sync, stale after 168 h, 1 request per
  second.

**UI:**
- Asset detail has a new **Security** tab, shown only with `discovery.view`. It shows
  onboarding, sensor health, exposure, risk, tags, group, first seen, "last report
  received" (labelled as not a live online status), last synchronised, last change, IDs,
  OS and the original values. It has a freshness badge and a note when the machine is
  missing from the latest listing that says this does not mean the device is gone.
- Catalogue: Defender (beta) with the fixed endpoint and a 168 h stale default.
- Integration page: certificate reference, permission panel, Defender capability labels,
  and a "Storing security observations" run phase.

**Fixtures:** `fixtures/defender/api/responses.json` holds 10 invented machines in the
Intune fixture tenant: cross-source Entra IDs, a server without an Entra ID, duplicate DNS
names, an Azure VM, Linux with no sensor data, a not-onboarded device, missing `lastSeen`,
a zero Entra ID and schema drift.

**Docs:**
- docs/17: ADR-014, DEC-16 (Defender operator inputs), ASM-37 to ASM-40, and ASM-35
  updated.
- README has a Defender section; `.env.example` explains the certificate-only credential.

## Verification (workstation; SQLite test-only fallback, no Docker/PostgreSQL here)

- **Backend: 504 passed, 6 skipped** (the 6 skips are PostgreSQL/Redis-only). This includes
  39 new tests in `test_defender.py`:
  - Defender audience and certificate assertion;
  - `$skip` and nextLink paging; empty response;
  - mapping and provenance; security facts stored apart from assets;
  - category hints and missing Entra IDs;
  - idempotent repeat; `lastSeen` alone is not a change;
  - onboarding and sensor-health changes;
  - duplicate DNS names never merged;
  - Entra ID cross-source auto-link with corroboration (Intune → Defender), with Intune
    keeping the OS version (field authority);
  - Entra ID without corroboration → review; another tenant → no match;
  - changed Entra ID → duplicate conflict; Entra versus hostname/MAC clash → conflict;
  - locked field;
  - missing machine → stale link and `missing_since`, asset kept;
  - partial enumeration and 4 kinds of unsafe link → nothing stale or missing;
  - hourly budget; 0.6 s floor; incremental `lastSeen` filter;
  - 401 AADSTS, 403 naming `Machine.Read.All`, expired token renewed, 429 Retry-After,
    persistent 429 bounded;
  - connection test and device-action roles; configuration API;
  - security API site access (other site 404, no `discovery.view` 403); freshness;
  - no certificate or token in logs or the API;
  - scheduler and live switch; mapping helpers.
- Updated tests: Defender is now Beta (M365 is the planned-source example).
- Ruff check and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and matches the committed file.
- Frontend: typecheck, oxlint, **96 tests** (5 new: 4 Security tab, 1 Defender integration
  page) and the build all pass.
- GitHub CI (PostgreSQL 16 + Redis 7, migration reversal, OpenAPI drift, production image
  build): pending at the time of writing.
- Not run: the Docker stack, Playwright, a browser review, and **any Defender tenant
  connection** (not authorised).

**Activation prerequisites (not done):**
1. The Docker-host verification passes.
2. DEC-16 is approved: the tenant ID, an app registration with only `Machine.Read.All`
   (application, admin consent), a certificate, egress to `login.microsoftonline.com` and
   `api.security.microsoft.com`, a sanitized sample response and written approval.
3. Mount the PEM, set the tenant and client IDs, run the connection test, and confirm that
   `excess_permissions` is false.
4. Set `ITAM_ALLOW_LIVE_INTEGRATIONS=true`, record the approval, then enable the schedule.

**Outstanding issues:**
- Property names, enum values, the token audience and the `@odata.nextLink` behaviour are
  from documentation, not a live tenant.
- Regional API hosts are not configurable.
- The hourly budget is per run, not shared across processes.
- No phone or tablet categories.
- The `discovery.view` permission is reused for security data (ASM-40).
- Not load-tested (Task 022).

Proposed next task: **010 | Entra/M365 SKU + license assignments** (tasks/BACKLOG.md). Do
not start automatically.
