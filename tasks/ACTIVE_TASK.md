# Current Task: 008 | Microsoft Intune managedDevice adapter

Status: **Provisionally Complete / Fixture-validated only. Live synchronisation NOT activated**
(2026-11-03, branch DEV). Microsoft Intune source availability is **Beta**.

**Read:** AGENTS.md, docs/00, 05 (§3, shared normalisation, failure behaviour, fixtures),
09, 12, 14, 15, 17.

**Previous:** 007 Endpoint Central (Provisionally Complete, CI run 41638482133 green) and
change request 007a, the stricter strong-match gate (ADR-013 / ASM-32; CI run 41654481991
green on `de8cfa0`).

**Pre-check (done):** the Task 007a matching rules are in force and tested
(`apps/reconciliation/tests/test_matching.py`). A matching serial alone never auto-links:
the manufacturer and category must be known and the same, and conflicting identifiers
create a conflict candidate. Task 008 tests exercise the same rules with Intune data.

## Scope

- A read-only Intune connector on Microsoft Graph **v1.0**:
  `GET /deviceManagement/managedDevices` only.
- Microsoft Entra client-credentials authentication (certificate preferred, secret as
  fallback). Only the application permission `DeviceManagementManagedDevices.Read.All` is
  needed.
- It uses the existing observation/reconciliation pipeline, the sync engine, the gates and
  the admin screens.

Out of scope: Defender (Task 009), M365 licences (Task 010), detected apps/software
(Task 016), any device or policy change, agents, scans and any live tenant connection.

## Outcome

**Connector (`backend/apps/integrations/adapters/intune/`):**
- `auth.py` (token provider):
  - client credentials against the fixed `login.microsoftonline.com/{tenant}` token endpoint
    (its only non-GET request);
  - an RS256 client assertion from a PEM key and certificate, or a client secret;
  - tokens are cached in memory, renewed 5 minutes before expiry and after a 401;
  - Entra errors are reduced to the AADSTS code and first sentence;
  - Retry-After is honoured and retries are bounded.
- `client.py` (`GraphClient`):
  - GET only, fixed to `https://graph.microsoft.com/v1.0`;
  - one token renewal plus a repeat on 401; a 403 names the missing permission;
  - Graph error envelopes are mapped to errors;
  - `@odata.nextLink` is followed only when it is https, on the same host and port 443,
    without userinfo, and for the same collection path.
- `adapter.py`:
  - pagination with protection against incomplete listings (a failed later page, an unsafe
    or repeated link, or the page cap);
  - fallback to full objects if `$select` is rejected;
  - the connection test (`$top=1`) reports whether the read permission is present and any
    excess write or privileged roles; syncs warn about them too.
- `mapping.py`:
  - documented v1.0 properties only;
  - provenance keeps the tenant, managed device ID, Entra device ID and original values;
  - the check-in time stays outside the checksum, but compliance and enrollment changes
    create new observations;
  - phone labels are never used as hostnames;
  - category hints come only from unambiguous models;
  - no user principal name, e-mail or phone data.

**Shared framework:**
- `ReadOnlyClient` gains per-request auth headers, validated absolute continuation URLs,
  a one-time refresh after a 401, and Retry-After on 503.
- Registry `Connector` gains `client_factory`, `fixed_base_url`, `required_settings`,
  `permissions`, setting-applicability flags and per-source defaults.
- The sync engine refuses with `NOT_CONFIGURED` until the tenant and client IDs are set, and
  counts token requests as API requests.

**Reconciliation (all connectors, ASM-36):** an asset already linked to another active
record from the same integration (a re-enrollment or duplicate) turns a new matching record
into a `conflict` candidate. It is never linked automatically.

**Model / migrations:**
- `integrations.0007_intune_oauth_settings`: `tenant_id`, `client_id`, and the auth methods
  `client_secret` and `client_certificate`.
- `integrations.0008_intune_beta`: data migration, Planned → Beta.
- Both are reversible.

**APIs:**
- No new paths.
- The integration adds `tenant_id` and `client_id`; `connector` adds `fixed_base_url`,
  `required_settings`, `permissions`, `uses_source_timezone` and `uses_detail_refresh`.
- Tenant ID (GUID or verified domain) and client ID (GUID) are validated; the Graph endpoint
  is forced; new Intune integrations default to a 24 h sync and stale after 168 h.

**UI:**
- Catalogue: Intune (beta) with the fixed endpoint and a 168 h stale default.
- Integration page:
  - tenant ID and application ID fields;
  - authentication method (certificate recommended, or secret);
  - credential reference help;
  - a "Required permissions" panel with an excess-permission warning;
  - Intune capability labels;
  - the time zone and detail-refresh settings are hidden for Intune;
  - health shows devices, matched assets, candidates, errors and warnings, and history as
    for the other connectors.
- The auto-link option text now reflects ADR-013.

**Fixtures:** `fixtures/intune/graph/responses.json` holds 12 invented devices: laptop,
desktop, Surface, Mac, iPhone, personal Android without a serial, VM, two `KIOSK-01`, a
device with missing properties, a re-enrolled duplicate and OEM placeholders. The fake
serves them as 3 pages.

**Configuration:** `.env.example` and Compose gain `ITAM_INTEGRATION_INTUNE_CLIENT_SECRET`
(the fallback). The README explains how to mount the certificate PEM as a Compose secret.
New dependency: `cryptography>=50.0.2,<51` (RS256 assertions and PEM parsing).

**Docs:** docs/17 updates DEC-07 and adds ASM-33 to ASM-36; README has an Intune section.

## Verification (workstation; SQLite test-only fallback, no Docker/PostgreSQL here)

- **Backend: 465 passed, 6 skipped** (the 6 skips are PostgreSQL/Redis-only). This includes
  46 new tests in `test_intune.py`:
  - multiple pages via nextLink;
  - mapping, provenance and tenant;
  - category hints, phone labels, missing serial and properties, OEM placeholders and
    schema drift;
  - idempotent repeat sync; check-in versus state-change observations;
  - duplicate names never merged; re-enrollment with shared identifiers → conflict;
  - a changed device name keeps the link;
  - strong serial without class corroboration → review only;
  - Endpoint Central + Intune laptop → one asset, with Endpoint Central's OS version kept;
  - locked field never overwritten;
  - removed device → stale only after a complete listing; a device that stopped checking
    in → stale via freshness;
  - a failed later page or 6 kinds of unsafe continuation link → incomplete, nothing stale;
  - a repeated link stops the listing;
  - token 401 with an AADSTS message (secret and trace not shown);
  - Graph 403 naming the permission;
  - expired token renewed once mid-run; persistent 401 fails;
  - token cache and renewal before expiry;
  - Graph 429 Retry-After, token-endpoint 429 and bounded 503 retries;
  - `$select` fallback;
  - certificate assertion signature, header and claims verified; certificate without a key
    refused before any request;
  - secrets and tokens absent from logs and the API;
  - connection test with permissions and excess roles;
  - configuration API (fixed endpoint, ID validation, auth methods, defaults);
  - NOT_CONFIGURED gate, live switch and scheduler.
- Updated tests: Intune is now Beta (Defender is the planned-source example), and the
  connector info assertion for Endpoint Central.
- Ruff check and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and matches the committed file.
- Frontend: typecheck, oxlint, **91 tests** (4 new: 3 on the Intune page, 1 in the
  catalogue) and the build all pass.
- GitHub CI run 41658532706 on `d0419e2` (PostgreSQL 16 + Redis 7): backend **471 passed,
  0 skipped**; migrations applied and reversed; frontend 91 tests; Compose config and image
  builds all pass.
- Not run: the Docker stack, Playwright, a browser review, and **any Microsoft tenant
  connection** (not authorised).

**Activation prerequisites (not done):**
1. The Docker-host verification passes.
2. DEC-07 is approved: the tenant ID, an app registration with only
   `DeviceManagementManagedDevices.Read.All` (application, admin consent), a certificate,
   egress to `login.microsoftonline.com` and `graph.microsoft.com`, a sanitized sample
   response and written approval.
3. Mount the PEM as a secret file, set the tenant and client IDs, run the connection test,
   and confirm that `excess_permissions` is false and the `$select` is accepted.
4. Set `ITAM_ALLOW_LIVE_INTEGRATIONS=true`, record the approval, then enable the schedule.

**Unresolved:**
- ASM-33 to ASM-36 in docs/17.
- Property names and enum values are not verified against a live tenant.
- National clouds are not supported.
- The Entra device ID is not yet a matching key (Task 009).
- There are no phone or tablet categories.
- Not load-tested (Task 022).

Proposed next task: **009 | Defender machine/discovery adapter** (tasks/BACKLOG.md). Do
not start automatically.
