# 17 | Architecture Decisions and Open Operator Inputs

## Approved decisions

| ID | Decision | Status |
|---|---|---|
| ADR-001 | Custom application, not a GLPI/IT Glue fork | Accepted |
| ADR-002 | Single organization, sites/departments | Accepted |
| ADR-003 | AlmaLinux OS 10.2 stable (verified 2026-11-02), Docker Engine + Compose v2; reconfirm current GA at deployment | Accepted |
| ADR-004 | React/TypeScript, Django/DRF, PostgreSQL, Redis/Celery modular monolith | Proposed implementation baseline; change requires documented reason |
| ADR-005 | LibreNMS API is V1 primary network discovery | Accepted |
| ADR-006 | Endpoint Central is on premises | Accepted |
| ADR-007 | Intune, Defender, M365/Entra integrations | Accepted design; permissions TBD |
| ADR-008 | Categories and groups are separate | Accepted |
| ADR-009 | EOL is evidence-backed, Unknown safe default | Accepted |
| ADR-010 | API-first connector design and CSV/XLSX/JSON portability | Accepted |
| ADR-011 | Admin SMTP, auth, backups and recovery are V1 release gates | Accepted |
| ADR-012 | Original, restrained enterprise UI (no generic AI dashboard) | Accepted |

## Operator decisions needed before staging/production

| ID | Needed input | Safe default while unresolved |
|---|---|---|
| DEC-01 | OS version selected: 10.2 GA as of 2026-11-02. Confirm CPU architecture and current GA at deployment; test Docker compatibility on this derivative | No host installation, package repository approval or production runtime change yet |
| DEC-02 | CPU/RAM/disks, DB/media size expectations | Reference 8 vCPU/24–32GB proposal pending load test |
| DEC-03 | ITAM internal FQDN, DNS zone, TLS certificate method | example.invalid placeholder; localhost dev only |
| DEC-04 | User authentication: Entra OIDC, LDAP/LDAPS, or local pilot | Local named admin in dev; integration withheld |
| DEC-05 | LibreNMS version, HTTPS URL, REST token, scopes and sample payload | Mock fixtures only |
| DEC-06 | Endpoint Central on-prem version, HTTPS URL/port, API token/permission | Mock fixtures only |
| DEC-07 | Microsoft tenant IDs and app permission consent | Mock fixtures only |
| DEC-08 | SMTP provider/relay hostname, port, sender, TLS/auth, recipient groups | Mail capture in dev; prod email disabled |
| DEC-09 | Backup off-host destination, encryption key custody, retention, RPO/RTO approval | Local test backups only, not production ready |
| DEC-10 | Domain/TLS approved list, registrar and owners | Manual sample fixtures only |
| DEC-11 | SSO/MFA and local emergency access policy | Secure local pilot accounts and no public access |
| DEC-12 | EOL vendor support portal/API entitlements | Official public source/import workflow; Unknown otherwise |
| DEC-13 | Site/location hierarchy, asset tag policy and sample inventory files | Configurable schema; no real import |
| DEC-14 | ITAM report recipients and escalation thresholds | Notifications disabled until SMTP/owners approved |
| DEC-15 | Data retention and privacy policy | Initial proposed retention with documented review flag |

## Recorded implementation assumptions

| ID | Assumption | Guardrail |
|---|---|---|
| ASM-01 (Task 001) | Backend pinned to Django 5.2 LTS (5.2.18 at bootstrap); 5.1 is end-of-life. Revisit the LTS line before 5.2 support ends (April 2028). | `pyproject.toml` bounds `django>=5.2.18,<5.3`; uv.lock committed. |
| ASM-02 (Task 001) | SQLite is allowed **only** as an opt-in shortcut for running the backend test suite on a workstation without Docker (`ITAM_TEST_DB_SQLITE=1`, `config.settings.test`). PostgreSQL is mandatory for Docker development, CI, staging and production. | Fallback exists only in test settings; raises if `CI` is set; CI fails on any skipped PostgreSQL/Redis integration test; a test asserts the engine is PostgreSQL unless the opt-in is set. |

| ASM-03 (Task 002) | Local accounts only. **No local TOTP/MFA yet** and no OIDC; Entra is listed as `planned` by `/auth/providers`. Per docs/09, privileged local access must stay restricted (internal network, named admins, no public exposure) until DEC-11 is decided. | Production readiness gate: DEC-11 must be resolved (IdP MFA or reviewed local TOTP) before go-live. |
| ASM-04 (Task 002) — **closed in Task 003** | Site scoping implemented: users have `all_sites` or explicit `UserSiteGrant`s; a grant on a site includes its child sites. All asset reads go through `assets.selectors.visible_assets(user)`; out-of-scope IDs return 404 and out-of-scope site/location IDs in payloads return the same 422 as unknown IDs. Department scoping is **not** implemented (departments are org-wide reference data). | Cross-site denial tests cover list, filters, detail, history, PATCH, archive, restore, classification (and preview) and create/reassign. Future export/report jobs must start from `visible_assets()`. |
| ASM-05 (Task 002) | Role definitions are seeded and read-only in V1 UI; editing role→permission grants is not exposed yet. System Admin must always keep users.manage/users.view/roles.view/audit.view (`MANDATORY_ADMIN_PERMISSIONS`). | Enforce the mandatory set when role editing is added. |
| ASM-06 (Task 002) | Audit events are append-only: model guard + PostgreSQL trigger blocks UPDATE/DELETE/TRUNCATE. Retention purge (future) must run under a separate, audited maintenance role. | Trigger is created by migration `audit.0002`; tested in CI on PostgreSQL. |
| ASM-07 (Task 002) | Frontend API types are generated with openapi-typescript 6.7.x because 7.x requires the TypeScript 5 compiler API, which TypeScript 7 (native) does not expose. | CI fails if `schema.d.ts` or `openapi.yaml` drift from the backend schema. Revisit when openapi-typescript supports TS 7. |

| ASM-08 (Task 003) | Asset owner is an ITAM user account (FK). People who are not users cannot be owners yet; directory/HR sync is a later integration. Owner choices come from `GET /users/lookup/` (active users; id, username, display name only). | Revisit with Entra/M365 directory objects (Task 010). |
| ASM-09 (Task 003) | No field masks yet: Asset Operator and ITAM Manager can edit all asset fields in their sites; Infrastructure Engineer and Security Analyst are read-only. docs/09 field-level rights (curated vs technical fields) are deferred. | Add field masks before discovery writes technical fields (Task 004). |
| ASM-10 (Task 003) | Custom field values are stored in `Asset.custom_fields` (JSONB) and validated against typed definitions on write. Definitions inherit down the category tree; key and type are immutable. Values that stop applying after reclassification are retained read-only, never dropped. Required fields are enforced on create and reclassification; ordinary edits report `missing_required_fields` instead of blocking unrelated changes. | If reporting needs typed SQL filtering on custom fields, add typed value tables or expression indexes. |
| ASM-11 (Task 003) | Manufacturer/model are free text until the vendor/model catalogue (Task 015). Observation and support status are read-only via the API (defaults `manual_only`, `unknown`) and will be set by discovery and the EOL engine. | Catalogue task links assets to canonical models without dropping the free-text values. |
| ASM-12 (Task 003) | Manual network identifiers (hostnames, interfaces/MACs, IPs) are edited as replace-sets of `source="manual"` rows only; rows from other sources are never modified by manual edits. No global uniqueness on IP, MAC, hostname or serial. | Task 004 writes discovered rows with their source, reference and observed time. |

## Change-control rule for agents

If a decision would change data identity, security, deployment, scope or business semantics, propose a short ADR with context, options, decision and consequences. Do not silently choose a dangerous default. For cosmetic/local code choices within approved architecture, decide and proceed.

## GLPI licensing note

GLPI repository is GPLv3. Use product concepts and independently written code. Forking or copying GLPI source is a **separate** licensing/product strategy requiring owner approval. Do not casually mix GPL files into a differently licensed custom codebase.
