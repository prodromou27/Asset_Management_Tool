# Current Task: 018a | SMTP config UI, template engine, outbox and test mail

Status: **Complete (CI run 41889402046 green)** (2026-11-04, branch DEV). Owner decisions: split
Task 018 into 018a (this) and 018b (alert rules, recipients, dedup); SMTP password as a
secret reference. No real mail server contacted: tests use a local SMTP server with a
generated test CA.

**Read:** AGENTS.md, docs/00, 03 (Operations), 04 (settings, /smtp/test), 09, 10, 12 (Email),
14 (audit, logging, mail), 15 (A17, A18), 17 (ADR-011, DEC-08, DEC-14).

**Previous:** 017 domains and certificates (CI run 41877536180 green).

## Outcome (ASM-57)

- **App `apps.notifications`** (`notifications.0001`, `0002` seeds the `smtp_test`
  template): SMTP profile (single, disabled by default), versioned templates, outbox.
- **Permissions** (`accounts.0012`): `notifications.manage` System Admin;
  `notifications.view` System Admin and Auditor.
- **SMTP:** STARTTLS required/never downgraded or implicit TLS; credentials only over TLS;
  certificate and host name validated (optional internal CA `file:`); password as
  `env:ITAM_SMTP_<NAME>`/`file:` reference (secret helper now takes a prefix); Compose passes
  `ITAM_SMTP_PASSWORD`. Test connection (no send) and test email to the admin only.
- **Outbox:** one row per recipient, dedup key, after-commit hand-off, worker every minute,
  rate limit, 4xx/connection retries with backoff and jitter, 5xx dead letter, 6 attempts,
  config errors wait without using attempts, disabled mail waits then expires (72 h), body
  purge after 14 days, retry/cancel.
- **Templates:** whitelisted tags/filters, HTML escaping, header-safe subjects, preview.
- **Frontend:** Administration → SMTP & notifications (Settings, Templates, Delivery queue)
  with a delivery alert; System health shows mail delivery. Vitest test timeout 20 s (above
  the 5 s query wait) so slow runs fail with a clear message.

## Verification (workstation; SQLite test-only fallback)

- Backend **757 passed, 6 skipped (PostgreSQL/Redis-only)**. New: 13 tests (profile rules and no credential values, defaults
  from environment, connection test sends nothing and reports login failure, no STARTTLS
  downgrade and untrusted certificate refused, test email to the admin only over TLS with
  login and correct headers, A17 outage → retries with backoff → dead letter → retry →
  delivered once, 4xx deferral vs 5xx bounce, dedup/disabled/expiry/cancel, configuration
  error keeps attempts, body purge, escaping and forbidden template constructs, template
  preview/versioning, permissions).
- Migrations applied, reversed (`notifications zero`, `accounts 0011`) and reapplied; no
  drift. OpenAPI validates with `--fail-on-warn`; types regenerated. Ruff clean.
- Frontend: typecheck, oxlint, **177 tests** (6 new) and build pass. Screenshots (mocked
  API) of settings, templates, queue and System health led to shorter security labels and the
  template layout.
- GitHub CI run 41889402046 on `e0e6f15`: backend **763 passed, 0 skipped** (PostgreSQL 16 +
  Redis 7), frontend 177, Compose config and image builds pass.
- Not run: Docker stack with Mailpit, A18 against the real relay (needs DEC-08).

**Open (ASM-57):** alert rules and recipients (018b); OAuth SMTP; production relay and
sender (DEC-08); recipients and escalation (DEC-14).

Proposed next task: **018b | Notification rules** (tasks/BACKLOG.md). Do not start
automatically.

---

# Previous record: Task 017 | Domain and TLS certificate inventory/expiry

Status: **Complete (CI run 41877536180 green)** (2026-11-04, branch DEV). No real hosts contacted:
checks were tested against a local TLS server on 127.0.0.1 with generated test certificates.

**Read:** AGENTS.md, docs/00, 03 (Domains), 04 (Domain/TLS endpoints), 06 (Domain and TLS),
08 (§7), 10 (thresholds), 11 (domain and TLS endpoint templates), 14 (SSRF row), 15 (A11,
A12), 17.

**Previous:** 016b license entitlements (CI run 41869188389 green).

## Outcome (ASM-56)

- **App `apps.domains`** (`domains.0001_domains_and_certificates`): domains (expiry Unknown
  unless recorded with evidence; verifier stored), certificates (unique SHA-256, public PEM
  only), approved TLS endpoints, certificate deployments (rotation history).
- **Permissions** (`accounts.0011_certificate_permissions`): `certificates.view` all roles;
  `certificates.manage` System Admin, ITAM Manager, Infrastructure Engineer.
- **Checks:** TLS handshake only, DNS pinned, metadata/link-local/multicast/reserved/
  unspecified refused (loopback outside tests), TLS 1.2+, 5 s timeout; every 15 min for
  endpoints due after 24 h (max 200 per run); "Check now" once a minute; failures keep the
  last certificate. Settings `ITAM_CERT_WARNING_DAYS`, `ITAM_TLS_CHECK_INTERVAL_HOURS`,
  `ITAM_TLS_CHECK_TIMEOUT_SECONDS` (Compose pass-through).
- **API:** domains, certificates (upload), deployments, TLS endpoints (retire, check),
  `/assets/{id}/certificates/`. **Imports:** `domain`, `tls_endpoint`.
- **Frontend:** sidebar "Domains & Certificates" with Certificates, TLS endpoints and
  Domains tabs; certificate page (identifiers, where seen, PEM); asset Certificates tab.
  Test setup: async query timeout 5 s (parallel suite was flaky at the 1 s default).

## Verification (workstation; SQLite test-only fallback)

- Backend **744 passed, 6 skipped** (PostgreSQL/Redis-only). New: 14 tests (name
  normalisation and URL refusal, thresholds and last day, A12 domain expiry Unknown and never
  from a certificate, evidence rule and verifier, upload dedup and private-key refusal, real
  TLS check with rotation history and hostname match, A11 one certificate on two endpoints,
  failure keeps last certificate, SSRF guards incl. DNS answer to metadata/loopback with no
  connection attempted, schedule picks only due enabled endpoints, asset link site scope,
  permissions, retire closes deployments, domain/endpoint imports with rollback).
- Migrations applied, reversed (`domains zero`, `accounts 0010`) and reapplied; no drift.
  OpenAPI validates with `--fail-on-warn`; types regenerated. Ruff clean.
- Frontend: typecheck, oxlint, **171 tests** (7 new) three consecutive full runs, build pass.
  Screenshots (mocked API) led to the identifiers layout, wrapping endpoint rows and the
  top-bar context on certificate pages.
- GitHub CI run 41877536180 on `de1955c`: success; backend **750 passed, 0 skipped** (PostgreSQL
  16 + Redis 7), frontend 171, Compose config and image builds.
- Not run: Docker stack, checks against real hosts (needs approved endpoints on the server).

**Open (ASM-56):** chain validation against an internal CA bundle; manage rights for
Security Analyst; registrar/WHOIS lookups (none: Unknown stays Unknown); domain/certificate
export family; firewall rules for the outbound checks; expiry notifications (Task 018).

---

# Previous record: Task 016b | License entitlements/allocations + Software & Licenses area

Status: **Complete (CI run 41869188389 green)** (2026-11-04, branch DEV). Owner decisions from 016a
apply (two slices; this is the second). No live sources or credentials used.

**Read:** AGENTS.md, docs/00, 03 (licensing tables), 04 (/licenses endpoints), 06 (software and
license model), 08 (§6 Software & Licenses), 09 (roles), 11 (license import template), 17
(ASM-29, ASM-52, ASM-54).

**Previous:** 016a software inventory (CI run 41842547955 green).

## Outcome (ASM-55)

- **Models** (`licensing.0003_license_entitlements`): `LicenseProduct`, `LicenseEntitlement`,
  `EntitlementAllocation` (asset or named user). Retire/end with reasons; nothing deleted.
- **Permission** `licenses.manage` (`accounts.0010_license_manage_permission`): System Admin,
  ITAM Manager. Reading stays `licenses.view`.
- **Totals:** purchased (entitlements in term), allocated (all sites), available (negative shown
  as "N more allocated than purchased"), installed assets in your sites from linked software.
  Labelled as arithmetic, never compliance.
- **API:** products, entitlements (filters: product, q, status incl. "ending" within 90 days),
  retire, allocate, allocation list (site-scoped for assets) and end. If-Match on edits;
  everything audited.
- **Bulk:** import family `license_entitlement` (create/update, auto-creates the product,
  rollback); export family `license_entitlements` + `allocations`; asset export table `licenses`.
- **Frontend:** sidebar "Software & Licenses" (one entry, shown with `assets.view` or
  `licenses.view`); tabs Installed software, Installations, Entitlements, Allocations,
  Microsoft 365. License product page with totals, entitlements (record, edit, allocate,
  retire) and allocations (end). `/licenses` and `/licenses/subscriptions/{id}` redirect.

## Verification (workstation; SQLite test-only fallback)

- Backend **730 passed, 6 skipped (PostgreSQL/Redis-only)**. New: 10 licensing tests (permissions; product uniqueness and
  If-Match; entitlement rules, status filters and in-term totals; allocations with site scope,
  duplicates, over-allocation, listing hides other sites, end and audit; expired/retired
  entitlements end allocations; installed assets from linked software, site-scoped; import
  create/update/conflict/errors/rollback; import needs `licenses.manage`; export hides other
  sites' allocations; last day of term). Family-list tests updated for the new families.
- Migrations applied, reversed (`licensing 0002`, `accounts 0009`) and reapplied; no drift.
  OpenAPI validates with `--fail-on-warn`; types regenerated. Ruff clean.
- Frontend: typecheck, oxlint, **164 tests** (4 new; 3 updated for the combined area) and
  build pass. Screenshots (mocked API) of Entitlements, Allocations and the product page led to
  section spacing and link-style fixes.
- GitHub CI run 41869188389 on `c9a4ed2`: backend **736 passed, 0 skipped** (PostgreSQL 16 +
  Redis 7), frontend 164, Compose config and image builds pass.
- Not run: Docker stack, live sources.

**Open (ASM-55):** role grants for `licenses.view`/`licenses.manage` beyond the defaults;
allocation to directory users/asset owners instead of free text; per-site entitlements;
renewal notifications (Task 018).

---

# Previous record: Task 016a | Software catalogue, installations and software lifecycle

Status: **Complete (CI run 41842547955 green)** (2026-11-04, branch DEV). Owner decisions: split
Task 016 into 016a (this) and 016b (entitlements, allocations, Software & Licenses area with
M365); connector software reads for both Endpoint Central and Intune, off by default.

**Read:** AGENTS.md, docs/00, 03 (software tables), 04 (software endpoints, asset software),
05 (Endpoint Central softwareInfo, Intune detectedApps), 06, 08 (asset Software tab), 11, 15
(A14, performance target), 17 (ASM-29, ASM-33, ASM-53).

**Previous:** 015 lifecycle (CI run 41833135237 green).

## Outcome (ASM-54)

- **App `apps.software`** (migration `software.0001_software_inventory`): products, versions
  (with per-version lifecycle match and assessment), installations (discovered rows keyed by
  source device and resolved through source links; manual rows on the asset; removal only
  after a complete read; restore when reported again).
- **Connectors** (`integrations.0011_collect_software`, switch per integration, default off):
  Endpoint Central `softwareInfo` (dcapi only; refreshed computers plus first read); Intune
  `detectedApps` + per-app `managedDevices` (complete-read rule, 20,000-app cap). Graph
  continuation check extended to the new paths only. Sync phase "facts" replaces "security".
- **Lifecycle:** `match_software` (exact / alias / review for builds, unknown publishers,
  several hits); per-version assessment with the ASM-53 rules; review (approve with optional
  alias, reject) with If-Match; reassessment hooked into catalogue changes and the hourly run.
  Software never changes `Asset.support_status`.
- **API:** `GET /software/products/`, `GET /software/products/{id}/`,
  `GET /software/installations/`, `POST /software/installations/{id}/remove/`,
  `POST /software/versions/{id}/lifecycle/approve|reject/`, `GET|POST /assets/{id}/software/`.
  Site scope via the resolved asset; counts are scoped too.
- **Exports:** asset export related table `software`.
- **Frontend:** Software page (products with counts and lifecycle flags, installations),
  product page (versions with lifecycle, suggested matches, approve/reject, installations),
  asset Software tab (discovered/manual, show removed, record/remove manual), integration
  switch "Collect installed software" for Endpoint Central and Intune. Sidebar: Software.
- **Fixtures:** fictitious `softwareInfo` (EC 301/302) and `detectedApps` (Intune), with README
  notes that envelopes are assumptions to verify.

## Verification (workstation; SQLite test-only fallback)

- Backend **720 passed, 6 skipped** (PostgreSQL/Redis-only). New: 15 software tests
  (EC reads once per refresh and request budget, removal after complete read, failed read
  removes nothing, dcapi/switch required, Intune per-app reads and budget, no app requests
  when off, complete vs partial reads and restore, site-scoped products/installations/detail,
  unlinking hides software without deleting, manual add/duplicate/permission/remove with
  audit, store rules, software lifecycle review and assessment with If-Match and asset status
  unchanged, rejection, approval permission, export table) and 3 software matching unit tests.
- Migrations applied, reversed (`software zero`, `integrations 0010`) and reapplied; no
  drift. OpenAPI validates with `--fail-on-warn`; types regenerated. Ruff clean.
- Frontend: typecheck, oxlint, **160 tests** (7 new) and build pass. Screenshots of the
  Software products and product pages (mocked API) led to clearer suggested-match text,
  pluralisation and heading spacing.
- GitHub CI run 41842547955 on `1bb5734`: backend **726 passed, 0 skipped** (PostgreSQL 16 +
  Redis 7; `software` migration reversed), frontend 160, Compose config and image builds pass.
- Not run: Docker stack, live sources, the 1m-installation performance target (Task 022).

**Open (ASM-54):** sanitized EC/Graph captures (DEC-06/07); request volume with real tenants;
software CSV import family; Software & Licenses area and entitlements (016b).

---

# Previous record: Task 015 | EOL catalogue, evidence and assessment

Status: **Complete (CI run 41833135237 green)** (2026-11-04, branch DEV).

**Read:** AGENTS.md, docs/00, 01 (support states, Review EOL), 03 (lifecycle tables), 04 (EOL
endpoints, asset lifecycle), 06 (whole), 07, 08 (sections 3 and 5), 09 (EOL approval column),
14, 15 (A05, G4), 17 (ADR-009, DEC-12, ASM-11), 20 (Lifecycle, alert thresholds).

**Previous:** 014 exports (CI run 41822280216 green).

## Scope

Vendor lifecycle catalogue with evidence, per-asset matching for hardware and OS/firmware,
assessment, review queue, exceptions, UI and API. No lifecycle data is seeded, no external
source is contacted, no adapter is enabled. Software assessments wait for software
installations (Task 016); the catalogue already accepts software products.

## Outcome (ASM-53)

- **App `apps.lifecycle`** (migration `lifecycle.0001_lifecycle_catalogue`): products,
  vendor aliases, product aliases, sources, milestones, revisions, matches, assessments,
  assessment history, exceptions. `accounts.0009_lifecycle_permissions`.
- **Matching** (`matching.py`, pure): exact / approved alias / candidate / no match /
  not applicable; ambiguity, revisions, family names, builds and firmware-only always go
  to review; hostnames never used; observed values stored with their provenance.
- **Assessment** (`assessment.py`, pure): verified evidence only, source precedence,
  conflicts, standard vs extended support, thresholds 180/90, UTC calendar rule, vendor
  statements for Supported/Not announced; Unknown otherwise. Asset `support_status` =
  worst applicable dimension (no other asset data changes).
- **Review and audit:** entry by `lifecycle.manage` stays unverified; `lifecycle.approve`
  verifies/rejects dates, approves/rejects matches (optional alias), grants and revokes
  exceptions. Every change audited; product revisions numbered with snapshots; If-Match
  on products, milestones, sources, matches and exceptions.
- **Reassessment:** on commit after catalogue changes, on demand (asset, product, all),
  hourly beat `lifecycle.reassess_all`.
- **API** (`/api/v1/lifecycle/`): `products/` (GET, POST), `products/{id}/` (GET, PATCH),
  `products/{id}/statement|aliases|milestones|revisions|assets|reassess/`,
  `aliases/{id}/remove/`, `milestones/{id}/` (PATCH), `milestones/{id}/review/`,
  `sources/` (GET, POST), `sources/{id}/` (GET, PATCH), `vendor-aliases/` (GET, POST),
  `vendor-aliases/{id}/remove/`, `findings/`, `summary/`, `policy/`, `matches/`,
  `matches/{id}/approve|reject/`, `exceptions/`, `exceptions/{id}/revoke/`, `reassess/`;
  `/api/v1/assets/{id}/lifecycle/`, `.../lifecycle/reassess/`, `.../lifecycle/exceptions/`.
- **Exports:** asset export gains a `lifecycle` related table (needs `lifecycle.view`; site
  scope from Task 014).
- **Frontend:** Lifecycle page (totals, findings with filters, review queue with
  approve/reject, exceptions with revoke, reassess all); Lifecycle catalogue (products,
  sources, vendor aliases, new product/source); product page (milestones with source links
  and verification, add/edit date, aliases, support statement, matched assets in your sites,
  change history, reassess); asset Lifecycle tab (per-dimension status, governing date, days,
  support level, evidence links, observed values with source, match state, exception dialog
  and history). Calendar dates are formatted without timezone shifts. Sidebar: Lifecycle
  (Inventory), Lifecycle catalogue (Administration).
- **Config:** `ITAM_LIFECYCLE_WARNING_DAYS`, `ITAM_LIFECYCLE_COUNT_EXTENDED_SUPPORT`,
  `ITAM_LIFECYCLE_MAX_EXCEPTION_DAYS` in settings, Compose and `.env.example`. CI reverses
  the `lifecycle` migration. README and docs/17.

## Verification (workstation; SQLite test-only fallback)

- Backend **702 passed, 6 skipped** (PostgreSQL/Redis-only). New: 41 engine tests
  (`test_engine.py`: thresholds, last-day rule, security end, extended support on/off, final
  date, end-of-sale only, conflicts, source precedence, third-party label, statements,
  summary; exact/alias/vendor-alias/unknown vendor/missing model/ambiguous/revision/family/
  rejected/OS release/build alias/patch candidate/missing version/firmware-only) and 22 API
  tests (`test_api.py`: end-to-end flow, manual data preserved, not applicable, candidate
  approval with alias, rejection, wrong dimension, decision reset on changed observations,
  rematch after edit, re-verification after date change with history, conflicting evidence,
  extended support, exception override and expiry, exception rules and revoke, permissions,
  cross-site denial, audit and revisions, concurrent edits 409/428, duplicates, vendor alias,
  support statement, policy and reassess all); 1 new export test.
- Migrations applied, reversed (`lifecycle zero`, `accounts 0008`) and reapplied; no drift.
  OpenAPI validates with `--fail-on-warn` (lifecycle serializers prefixed to avoid component
  name collisions); frontend types regenerated. Ruff clean.
- Frontend: typecheck, oxlint, **153 tests** (11 new) and build pass. Screenshots at 1440x900
  (findings, product page, asset tab; mocked API) led to single-line findings rows and an
  exact-match sidebar entry. One existing test (`admin-sites` categories) failed once under
  full-suite load and passed in isolation and in two further full runs.
- GitHub CI run 41833135237 on `e3c58a9`: backend **708 passed, 0 skipped** (PostgreSQL 16 +
  Redis 7; `lifecycle` migration reversed), frontend 153, Compose config and image builds pass.
- Not run: Docker stack, Playwright against a real backend.

**Open (ASM-53):** third-party-only dates setting a status; extended-support policy;
not-applicable category lists; separate verifier (four-eyes) not enforced; "EOL evidence
missing" data-quality queue and notifications (Task 018/021); vendor feed adapters (DEC-12).

---

# Previous record: Task 014 | CSV/XLSX/JSON exports with RBAC and async jobs

Status: **Complete (CI run 41822280216 green: backend 644 passed, 0 skipped; frontend 142)** (2026-11-04, branch DEV).

**Read:** AGENTS.md, docs/00, 04 (Import/export endpoints, async 202), 07 (ExportDialog), 08
(section 10 Import/Export Center), 09 (role matrix), 11 (Export), 14 (formula injection, data
exfiltration, separate personal-data export permission), 15 (A14, A15), 17.

**Previous:** UI redesign (CI run 41819113769 green).

## Scope

Export framework (async job, encrypted artifact, short-lived download, audit, RBAC/site
masking at query time) for the families that exist: assets (with related tables) and
groups (with members). Other families arrive with their tasks; scheduled report delivery
needs SMTP (Task 018); report endpoints are Task 021.

## Outcome (ASM-52)

- **App `apps.exports`:** `ExportJob` (status queued/running/completed/failed/expired, family,
  format, scope, filters, ids, columns, related, counts, masked columns, encrypted file,
  checksum, expiry, download count).
- **Families** (`families.py`): assets (29 columns + `cf.<key>`; related hostnames,
  interfaces/MACs, IP addresses, group memberships) and groups (related members, only assets
  in the viewer's sites). Rows start from `visible_assets` / `visible_groups`; personal columns
  (owner, owner name, modified by, group owner, added by) need `exports.personal`, otherwise
  they are dropped and listed.
- **Writers:** CSV (UTF-8 BOM; ZIP of tables + `about.csv` when related data is chosen), XLSX
  (sheet per table, numbered sheets beyond the row limit, `about` sheet, numbers stay
  numbers), JSON (`itam.export` v1, related lists nested). Formula-looking text escaped in CSV
  and XLSX.
- **Jobs:** POST returns 202; worker re-checks permissions and scope; max 3 active per user
  (429); max `ITAM_EXPORT_MAX_ROWS` records; file Fernet-encrypted (separate key context from
  imports); creator-only download until `ITAM_EXPORT_RETENTION_HOURS` (24), then purged by an
  hourly beat task that also fails jobs stuck over 60 minutes. Audit `exports.create`,
  `exports.complete`, `exports.fail`, `exports.download`. `audit.view` sees all job records,
  never other people's files.
- **Permissions** (`accounts.0008`): `exports.run` for every role; `exports.personal` for System
  Admin, ITAM Manager, Asset Operator.
- **API:** `GET /exports/families/`, `GET|POST /exports/`, `GET /exports/{id}/`,
  `GET /exports/{id}/download/` (no-store, attachment).
- **Frontend:** Export dialog (records, format, related data, columns, privacy note) on the
  Assets list and "Export members" on group pages; Exports page (sidebar, Sources) with
  status, polling while preparing, counts, expiry, download link, failure reasons. Dialogs
  now scroll within the viewport.
- **Config:** `ITAM_EXPORT_RETENTION_HOURS`, `ITAM_EXPORT_MAX_ROWS` in settings, Compose,
  `.env.example` and `install.sh`. CI reverses the `exports` migration. README and docs/17.

## Verification (workstation; SQLite test-only fallback)

- Backend **638 passed, 6 skipped** (PostgreSQL/Redis-only). 25 new tests in
  `apps/exports/tests/test_exports.py`: families and masking; role grants; no permission;
  validation (422); 3-job limit; filtered CSV with formula escaping; **A15** cross-site
  (all/selected/filtered never leak); masked personal columns; **A14** related tables with
  stable IDs; XLSX sheets, escaping, numbers; XLSX segmentation; JSON nesting; column choice;
  groups with in-scope members only; creator-only download, auditor visibility; expiry 410
  and purge; encryption at rest; permission removed before run; row limit; stuck jobs;
  audit trail.
- Migrations applied, reversed (`exports zero`, `accounts 0007`) and reapplied; grants checked.
- OpenAPI schema validates (`--fail-on-warn`); frontend types regenerated. Ruff clean.
- Frontend: typecheck, oxlint, **142 tests** (8 new) and build pass. Screenshots at 1440x900
  of the dialog and Exports page (mocked API); the first showed an over-tall dialog and an
  unformatted count, both fixed.
- Not run: Docker stack, live PostgreSQL (CI covers), Playwright e2e against a real backend.

**Open:** ASM-52 role grants (Auditor/Security Analyst personal data) and retention to
confirm; EOL evidence IDs in exports with Task 015; asset-list row selection for "Selected
records" (the API supports it).

---

# Previous record: UI redesign

Status: **Complete (CI run 41819113769 green)** (2026-11-04, branch DEV). Owner feedback: "I
don't like the UI" - plain/dated, colours, layout/navigation. Owner chose the dark navy
sidebar direction, light mode only, and to redesign before Task 014.

**Read:** AGENTS.md, docs/00, 07 (whole), 08 (shell), 15 (UI quality gate).

## Outcome

- **Design tokens** (`tokens.css`, docs/07 updated): navy sidebar, blue accent #2563EB,
  refreshed neutrals, muted surface, strong border, backdrop, nav colours, surface shadow.
  Hard-coded colours in `global.css` replaced by tokens.
- **Fonts and icons bundled** (no CDN, works on isolated networks): Inter Variable, IBM
  Plex Mono 400/500, Lucide icons (one family). New dependencies `@fontsource-variable/inter`,
  `@fontsource/ibm-plex-mono`, `lucide-react`.
- **Shell** (`AppShell.tsx`, new `navigation.ts`):
  - dark sidebar with brand mark, sections Inventory / Sources / Administration / System,
    icons on every entry and an active marker; sections with no permitted entries are hidden;
  - top bar with section / page context, asset search (goes to `/assets?q=`; hidden without
    `assets.view` or with a temporary password) and a user menu with initials and roles;
  - below 768px the sidebar becomes an overlay drawer (menu button, close button, backdrop,
    Escape closes).
- **Components:** page title, panels (8px radius, faint shadow), buttons (6px radius, hover
  states), inputs (focus halo), tables (uppercase header band, hover tint, asset rows on one
  line with sideways scroll), status badges (pill with dot, text darkened to keep AA
  contrast), dialogs, sign-in screen (navy band, raised panel).
- Docs: docs/07 tokens, typography, icons, radii and layout.

## Verification

- Frontend: typecheck, oxlint, **134 tests** (12 new in `AppShell.test.tsx`: navigation
  placement, grouped sections and active state, user menu, top-bar search, search hidden
  without permission, drawer open/close/Escape) and the production build pass.
- Screenshots with mocked data via Playwright + system Edge at 1440x900 and 390x844 (assets
  list with 28 rows, system health, mobile drawer); temporary harness not committed. The
  first round showed wrapped asset rows, fixed to one line.
- Contrast computed for every token pair: all text >= 4.5:1; badge text 5.3-6.2:1 after the fix.
- Bundle +11 kB JS (the pre-existing >500 kB chunk warning is unchanged); fonts are separate files.
- GitHub CI run 41819113769 on `a0555f7`: frontend 134, backend 619 passed (0 skipped),
  Compose config and production image builds (fonts and icons bundle in Docker) pass.
- Not done: page-by-page restyle beyond shared components (pages use the shared classes);
  dark mode (deferred by owner).

---

# Previous record: Simple installation

Status: **Complete (CI run 41811176901 green)** (2026-11-04, branch DEV). Owner request: make
the installation simpler, run on port 80 without a certificate, and let an administrator
add a certificate later. Replaces the earlier five-script staging kit.

## Outcome

- `ITAM_PUBLIC_SCHEME=http|https` (default https; ASM-51):
  - Django: http turns off the HTTPS redirect, HSTS and secure cookies, and silences
    only those deploy checks. `ITAM_ENV=production` refuses http.
  - Proxy: `infra/nginx/http.conf` serves the app on 80; `https.conf` (was `prod.conf`)
    serves 443 and redirects 80. nginx-proxy publishes 80 and 443; the certificate
    directory defaults to an empty placeholder.
- `scripts/install.sh`: one command for install and update. Installs Docker if missing
  (official repository, signing-key fingerprint checked), writes `.env` with generated
  secrets on first run (http, server IP), builds, migrates, starts, opens http in
  firewalld, checks health and offers to create the first admin.
- `scripts/enable_https.sh <fullchain> <privkey> [hostname]` or `--self-signed`: checks
  that the key matches and the certificate has not expired, installs to `/etc/itam/tls`,
  switches `.env` (backup kept), opens https and restarts.
- Removed `scripts/staging/`. docs/12 section 9 rewritten; README; `.env.example`;
  docs/17 ASM-51. CI checks ports 80,443 and that http mode selects `http.conf`.
- Kept from the previous step: api healthcheck fix and `CSRF_TRUSTED_ORIGINS` passthrough.

## Verification (workstation; no Docker or AlmaLinux host here)

- Backend 613 passed, 6 skipped (PostgreSQL/Redis-only). New production-settings tests:
  http mode turns off TLS-only settings; http with `ITAM_ENV=production` and an unknown
  scheme are refused.
- `check --deploy --fail-level WARNING` passes in both modes. Ruff clean. `bash -n` on
  both scripts.
- GitHub CI run 41811176901 on `ce1a7ee`: backend **619 passed, 0 skipped**, frontend 122,
  Compose config (ports 80,443; http mode selects http.conf) and image builds pass.
- Not run: the scripts on AlmaLinux or the Docker stack.

---

# Previous record: Task 013

Status: **Complete (CI run 41797570026 green)**
(2026-11-04, branch DEV).

**Read:** AGENTS.md, docs/00, 04 (Import/export endpoints, idempotency), 08 (§10 Import/Export
Center), 09 (role matrix), 11 (Import), 14 (untrusted upload, formula injection), 15 (A13,
A23), 17.

**Previous:** 012 static/dynamic groups (CI run 41793548771 green: backend 588 passed,
frontend 116).

## Scope

- Import framework: templates, upload, mapping, dry run, commit, receipt, error report and
  rollback.
- Families for the entities that exist now: assets, locations, groups and static group
  memberships.

Out of scope:
- The other docs/11 families (categories, manufacturers/models, software entitlements,
  domains, TLS endpoints, relationships) arrive with their tasks.
- Exports are Task 014.

## Outcome

**Parsing (`apps/imports/parsing.py`, ASM-49):**
- CSV: UTF-8/BOM or Windows-1252; delimiter sniffed.
- XLSX: openpyxl read-only with defusedxml; zip-bomb, path and macro checks.
- Limits: 5 MB, 10,000 rows, 100 columns, 10,000 characters per cell.
- Duplicate or blank headers and binary data are refused.
- Formula detection, and cell escaping on all outputs.

**Storage:** the original file is kept Fernet-encrypted (`crypto.py`) until
`ITAM_IMPORT_RETENTION_DAYS` (default 90), then purged by a daily Celery beat task; row
results remain.

**Models:**
- `ImportJob`: status flow, mode, mapping, totals, warnings, checksum, idempotency key,
  committer and rollback.
- `ImportRow`: planned action, key, target, messages, values, changes, result and
  version after.

**Families (ASM-50):**
- **Assets:**
  - matches on id or asset tag only;
  - manufacturer + serial and name + site are review-only conflicts; never hostname/IP;
  - in-file duplicates are conflicts;
  - blank cells mean no change; category changes are refused;
  - locked fields become conflicts; discovery-sourced values need technical rights;
  - site scope; `cf.<key>` custom fields with required-field enforcement;
  - create, update and rollback use the existing asset services (history, audit).
- **Locations:** site + name.
- **Groups:** name; dynamic rules validated.
- **Static memberships:** add only.

**Workflow:**
- Upload: suggests a mapping (names, labels, aliases, `cf.`) and warns when the exact file
  was imported before.
- Mapping and mode changes invalidate the preview.
- Preview is a dry run with no business writes, giving totals per action.
- Commit needs `X-Idempotency-Key` (a repeated key returns the original job) and If-Match.
  Each row is re-planned against current data and applied in its own savepoint; a row
  whose plan changed since the preview fails and the others continue.
- Rollback archives created records and restores updated ones only where unchanged since
  the import; the rest are listed for supervised correction.
- Missing rows never delete anything.
- Audit entries: `imports.upload`, `imports.commit`, `imports.complete`,
  `imports.rollback`.

**Permissions:** new `imports.run` (System Admin, ITAM Manager, Asset Operator;
`accounts.0007`) plus the family permission (assets create/edit, `sites.manage`,
`groups.manage`, `groups.members`) and site scope. Jobs are visible to their uploader, and
read-only to `audit.view` holders.

**Migrations (reversible; CI reverses `imports`):**
- `imports.0001_import_jobs`
- `imports.0002_widen_row_target`: a CI fix, see below
- `accounts.0007_import_permission`

**APIs:**

| Method | Path | Notes |
|---|---|---|
| GET | `/imports/templates/` | Template list |
| GET | `/imports/templates/{family}/csv/` | CSV template download |
| GET, POST | `/imports/` | POST is a multipart upload |
| GET, PATCH | `/imports/{id}/` | PATCH sets mapping and mode |
| POST | `/imports/{id}/preview/` | Dry run |
| GET | `/imports/{id}/rows/` | Filters `action`, `result` |
| GET | `/imports/{id}/errors/` | CSV report |
| POST | `/imports/{id}/commit/` | Needs If-Match and X-Idempotency-Key |
| POST | `/imports/{id}/rollback/` | Needs If-Match and a reason |

**Frontend:**
- The API client sends `FormData` and extra headers.
- **Imports** page (history) in the sidebar, plus an Import button on the Assets page.
- Wizard:
  1. Choose: family, template download and column help, file.
  2. Map: column → field with sample values, and mode.
  3. Dry run: totals, rows with messages and change details, report download, change
     mapping, "Import N rows".
  4. Import: progress, then a receipt with results, checksum, retention, report and
     rollback with a reason.

**Config:**
- nginx `client_max_body_size 6m` on `/api/`.
- `ITAM_IMPORT_ENCRYPTION_KEY` and `ITAM_IMPORT_RETENTION_DAYS` in Compose and
  `.env.example`.
- New dependencies `openpyxl` and `defusedxml`.

**Docs:** docs/17 ASM-49 and ASM-50; README section.

## Verification (workstation; SQLite test-only fallback, no Docker/PostgreSQL here)

- **Backend: 606 passed, 6 skipped** (the 6 skips are PostgreSQL/Redis-only). 22 new tests
  in `apps/imports/tests/test_imports.py`:
  - templates and download;
  - format, encoding and mapping detection with encrypted storage and audit;
  - Windows-1252 and XLSX;
  - 4 bad files; row limit, zip bomb and macro;
  - formula detection; mapping validation;
  - **A13**: 100 assets with 5 duplicates → 95 create / 5 conflict, commit, report, safe
    re-import;
  - **A23**: monitor/TV with no IP or serial;
  - review-only serial/name matches;
  - update by id/tag with lock, category and duplicate checks;
  - formulas and custom fields;
  - site scope and permissions;
  - commit rules: preview first, 428 without key, re-planning, duplicate key;
  - rollback of untouched rows only; missing rows never archive;
  - location, group and membership families; purged originals; other users cannot see
    jobs.
- Ruff check and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and matches the committed file.
- Frontend: typecheck, oxlint, **122 tests** (6 new) and the build all pass.
- First CI run 41797061711 on `424e924` **failed** on PostgreSQL. Membership rows store
  `<group id>:<asset id>` (73 characters) in `ImportRow.target_id`, which was 40
  characters wide. SQLite does not enforce lengths, so the workstation run passed. The
  failed check also left the job in "previewing".
  - Fix: widen the column to 100 (`imports.0002_widen_row_target`), and any unexpected
    preview failure now returns the job to "uploaded" with a message.
  - Regression tests added for both; backend now 606 passed locally.
- GitHub CI run 41797570026 on `ccddf26` (PostgreSQL 16 + Redis 7): backend **612 passed,
  0 skipped**; migrations applied and reversed (including `imports`); OpenAPI drift check;
  frontend 122 tests; Compose config and production image builds pass.
- Not run: Docker stack, Playwright, browser review at 1440×900 and 390×844.

**Open:**
- Retention period pending DEC-15.
- Limits to be confirmed by load tests (Task 022).
- Remaining families come with Tasks 015 to 017.
- Earlier open items: DEC-15, DEC-16 and DEC-17; regional Defender hosts; whether excess
  roles should block syncs; phone and tablet categories; ASM-46 severities; group
  re-evaluation on asset change.
