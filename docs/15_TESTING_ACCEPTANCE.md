# 15 | Validation Plan and Definition of Done

No feature is 'done' without automated tests, audit/permission behavior and a usable UI state where relevant.

## Test layers

| Layer | What to test |
|---|---|
| Backend unit | Normalization, model mapping, identity matching, lifecycle dates, dynamic groups, permissions and config validators |
| Adapter contract | Sanitized LibreNMS/Endpoint Central/Graph/Defender fixtures: pagination, missing fields, token expiry, 429, partial results, source drift |
| Database integration | Migrations, FK/unique constraints, concurrent merges, soft archival, failed import transaction rollback |
| API | OpenAPI contract, all statuses, auth/403, paginated filtering and idempotent jobs |
| Frontend | All screen states, keyboard access, table density/filter persistence, forms, import wizard, status labeling |
| E2E | Source import → reconciliation → category/group → EOL finding → report/export → notification |
| Security | RBAC/IDOR, malicious import, XSS/CSRF/SSRF, secret redaction, Docker hardening |
| Operations | Compose boot, migrations, health, SMTP test, encrypted backup and timed isolated restore |
| Performance | 10k devices + 20k other assets + 1m installations and histories |

## V1 acceptance scenarios

| ID | Given / action | Expected |
|---|---|---|
| A01 | LibreNMS reports switch with hostname/model/IP/MAC | Asset candidate created with source timestamp and suggested Networking category |
| A02 | Same laptop in Endpoint Central, Intune and Defender | One canonical asset, three source links, no duplicate physical devices |
| A03 | Source changes IP or hostname | Existing canonical asset retained, address history preserved |
| A04 | IP is reused by another physical device | No automatic merge on IP alone |
| A05 | Serial/model missing | Unknown support and review queue, no invented EOL |
| A06 | Authorized user reclassifies Workstation to Server | Same UUID, hardware/software/relationships/history intact, audited override |
| A07 | User creates static/dynamic groups | Correct member sets, preview, no RBAC expansion, membership audit |
| A08 | Source disappears for one day | Asset remains, source shows stale/degraded |
| A09 | Vendor support bulletin changes deadline | Evidence history preserved, assessment recalculated, alerts deduplicated |
| A10 | Hardware supported but OS EOS | Distinct findings by dimension |
| A11 | One certificate on two TLS endpoints | One certificate, two deployment records, expiry reported correctly |
| A12 | Domain registrar expiry unavailable | Unknown, never inferred from TLS certificate |
| A13 | User imports 100 assets with 5 duplicates | Preview counts, guarded matching, per-row errors and safe idempotent reimport |
| A14 | User exports 1:N software/IP relationships | Stable IDs, complete related sheets/JSON and field/site masking |
| A15 | Cross-site operator requests unauthorized export | 403 or scope-limited output; no leaked rows |
| A16 | LibreNMS API returns 429/401 | Connector degraded, retries/checkpoint or actionable auth error, no asset deletion |
| A17 | SMTP relay refuses delivery | Queue retry/dead-letter visible; business transaction succeeds |
| A18 | Admin sets SMTP and sends test | Verified authenticated/TLS test reaches authorized recipient |
| A19 | Backup nightly job executes | Encrypted off-host artifact verified and status recorded |
| A20 | Restore rehearsal | Separate staging restored with assets/groups/EOL/media/audit, no production emails sent |
| A21 | Planned integration selected | Clearly Planned; cannot falsely test/connect as working |
| A22 | UI rendered at 1440x900 and phone width | Tables usable, no generic AI gradients, keyboard focus and semantic status labels |
| A23 | Non-network monitor/TV asset imported | Complete valid record despite no IP/agent/serial |
| A24 | LibreNMS has FDB but not LLDP API access | Display observed MAC/port only; no fabricated physical link |
| A25 | User account disabled | Permissions/session revoked per policy; audit/ownership history retained |

## Phase quality gates

G0 Foundation: compose dev stack, auth/RBAC, DB migrate/backup, health and CI.
G1 Asset register: CRUD, types, groups, history, imports, API filtering.
G2 Integrations: real/sanitized adapter contracts, no false merges, source freshness.
G3 Discovery: LibreNMS API mapping, model/IP/MAC, unknown queue and limited topology.
G4 Lifecycle: verified source/milestone, Unknown safe default, licenses/certificates.
G5 Administration: SMTP, named users, service tokens, backups/restore, export security.
G6 Production pilot: security/load/UAT/recovery and documented sign-off.

## Agent definition of done

Task 022a adds `pnpm e2e`: a real React/Playwright to Django test-database rehearsal,
distinct from the mocked `pnpm review:ui` visual fixtures. Run instructions, evidence
scope and the remaining Task 022 load/host/security/recovery gates are in
`ops/pilot/README.md`. SQLite can prove local functional paths only; CI uses PostgreSQL.
This does not satisfy G6 production pilot sign-off by itself.

Task 022b's isolated PostgreSQL workload is documented in `ops/load/README.md`.
It records 30k assets, 1m installations, concurrent per-shape search p95 and 10k
cached-date lifecycle assessments. CI hardware/test HTTP results are a reference
baseline; approved-host production stack capacity and historical growth remain open.

Task 022c's focused security evidence review is in `tasks/TASK022C_REPORT.md`.
It maps existing source/tests and the green CI baseline to security requirements,
and records open hardening/commissioning gates. It is not a penetration test,
dependency/image vulnerability scan or G6 security sign-off.

- Requirement/AC ID cited in commit/task report.
- DB migration, typed API, backend authorization and audit present if relevant.
- Unit/contract/E2E tests added at proportional level.
- No placeholders claiming an unbuilt feature works.
- UI conforms to design tokens and is manually screenshot-checked at representative sizes.
- Documentation and task status updated. No secrets, no unexpected writes to live environments.
