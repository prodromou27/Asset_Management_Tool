# Task 022c - focused security gate evidence review

Outcome: the evidence review is complete; the production security gate remains open.

Follow-up on 2026-11-06: Task 022d addresses G01 with a pinned HTTPS transport and
verified regression evidence (see TASK022D_REPORT.md). The matrix below preserves
the reviewed baseline; G02-G05 remain open. This does not establish host commissioning.
Owner reaffirmed AlmaLinux acceptance on 2026-11-06. DEC-01 records that approval;
architecture/runtime/SELinux/TLS checks still need observed host evidence. No further
OS-choice question is required, and no host installation or live access occurred.

Scope: docs/14 controls and docs/15 security acceptance, focused on authentication,
site/group authorization, imports/exports, connector HTTP safety, secrets/audit,
production settings and Compose/proxy configuration. Reviewed source ref `d6a2b6e`.
Application source is unchanged from the green CI baseline `b488ac8`; only task
handoff documents differ (`git diff --name-only b488ac8 d6a2b6e`). This is a source
and existing-evidence review, not a complete codebase audit or penetration test.

## Existing evidence

[CI run 42210778953](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42210778953)
passed: 827 backend PostgreSQL/Redis tests, 214 frontend tests, real browser/API
pilot, reference load, production settings check, Compose/image builds and isolated
synthetic recovery. Test names below are supporting regression coverage, not a claim
that every attack or deployment condition is covered. No target builds, tests or
active security probes were executed during this documentation-only review.

| Requirement / boundary | Reviewed implementation | Supporting evidence / limit |
|---|---|---|
| Session auth, CSRF, expiry and revocation | `backend/apps/accounts/services.py`, `middleware.py`, `models.py`; cookie settings in `backend/config/settings/base.py` | `test_auth.py`: generic failures, account lockout, rate limit, CSRF, session rotation/expiry and password revocation. `test_users_api.py`: disable revokes sessions. Task 022a real browser proves CSRF refusal and disabled-session revocation. |
| Site scope and object access | `backend/apps/assets/selectors.py::visible_assets`, `backend/apps/organizations/scope.py`; asset write services | `test_site_scope.py`: filters do not widen scope, unauthorized detail/mutations return 404 and leave data unchanged; forbidden site assignment refused. Browser pilot checks GET/PATCH denial. |
| Groups do not grant asset access | `backend/apps/groups/views.py` scopes previews, member reads and writes through `visible_assets` | `test_groups.py` scope/RBAC cases and mixed-site group browser scenario. |
| Typed query inputs | Asset selectors allowlist filters/orderings; `backend/apps/groups/rules.py` validates typed rules | Existing asset/saved-view/group tests. No full SQL injection review or fuzzing of all endpoints was performed. |
| Malicious import bounds and formula handling | `backend/apps/imports/parsing.py`: file/row/column/cell and XLSX expansion limits; formula detection/output escaping | `test_imports.py`: bad files, limits/zip bombs, formulas, scoped permissions and job ownership. This does not establish parser vulnerability status. |
| Export confidentiality and access changes | `backend/apps/exports/services.py` checks current permission/scope fingerprint, creator and expiry at download; `families.py` scopes rows; retained files encrypted | `test_exports.py`: scoped/personal masking, creator-only downloads, revocation before work, encryption, expiry, formulas and audit. Browser pilot checks scoped JSON export/download. |
| Read-only connector requests and live approval | `backend/apps/integrations/sync.py::check_live_access`; `adapters/http.py` sends GET, verifies TLS, refuses redirects and restricts continuation origin/path | `test_librenms_api.py`: deployment and instance approval gates; `test_librenms_client.py`: no write methods, HTTPS, redirects and token-safe errors. Connection DNS pinning is incomplete: G01 below. |
| Secret reference boundary | `backend/apps/integrations/secrets.py` restricts environment prefixes and resolves files directly inside the configured secrets directory | `test_librenms_client.py`: unsafe references refused and env/file resolution. No repository/history secret scan or host secret-permission inspection performed. |
| Audit integrity and redaction | `backend/apps/audit/services.py` redacts sensitive top-level keys; migration `0002_append_only_trigger.py` blocks update/delete/truncate | `test_audit.py`: redaction, API/model mutation refusal, PostgreSQL trigger and trusted proxy hops. This is not proof that arbitrary nested values or every log emitter are redacted. |
| TLS inventory target control | `backend/apps/domains/checker.py` resolves, validates addresses and connects to the selected address with TLS SNI | `test_domains.py::test_ssrf_guards`; source shows address selection at connect. This is distinct from the connector HTTP path in G01. |
| Production auth/transport settings | `backend/config/settings/production.py` rejects DEBUG/default secrets/wildcard hosts/missing DB password; production requires HTTPS; secure cookies/HSTS | `backend/tests/test_production_settings.py` plus CI deploy check. Plain HTTP is an internal install mode, not production approval. Host chain, DNS, forwarded headers and browser behavior still require commissioning. |
| Container/runtime restrictions | Backend Dockerfile uses `USER itam`; `infra/compose.prod.yaml` sets backend read-only roots, dropped capabilities, no-new-privileges and resource limits; production exposes proxy ports | Existing Compose contract tests and CI build/config gates. Frontend/proxy images use their nginx defaults; do not claim every service is nonroot. No image-CVE evidence yet. |
| Recovery and operational safety | Existing encrypted repository and network-isolated restore drill | Green synthetic CI recovery gates. Approved off-host destination, key recovery, RPO/RTO and real host restore remain DEC-09 commissioning evidence. |

Test file locations: accounts/assets/groups/imports/exports/audit/integrations/domains
tests live under `backend/apps/<module>/tests/`. The named behavior was checked in
source; runtime claims above refer to the linked prior CI run, not new testing.

## Open gates and concrete next actions

These are requirement/evidence gaps, not severity-rated confirmed vulnerabilities.
No deployed system was probed and no adversarial cross-boundary result was reproduced.

| ID | Source/evidence gap | Closure evidence |
|---|---|---|
| G01 - connector connection target | `adapters/http.py::__init__` calls `check_host_addresses`, then HTTPX resolves/connects independently; `_send` does not pin the validated IP. The client also does not explicitly select an ambient-proxy policy. Initial resolution checks alone do not establish docs/14 DNS pin/revalidation at the actual connection. | Next Task 022d: pin validated addresses at the shared transport boundary, preserve HTTPS Host/SNI/certificate verification, define proxy behavior, and regression-test changing/unsafe DNS answers, retries and continuation requests with fixtures. Do not enable live connectors as a substitute for this proof. |
| G02 - dependency/image vulnerability evidence | CI has lint/tests/builds but no dependency or image advisory scan job; Dockerfiles/Compose use version tags rather than immutable image digests. Lockfiles alone do not show current vulnerability status. | Separate supply-chain slice: reproducible dependency and final-image scans, reports with timestamp/database version, reviewed actionable results, image digest policy and justified expiring exceptions. No CVE claim is made here. |
| G03 - browser content policy | `frontend/nginx.conf` and `infra/nginx/https.conf` set framing/nosniff/referrer headers but no Content-Security-Policy; no CSP header definition was found in the reviewed frontend/infra/backend config paths. | Add an application-compatible CSP at the response-owning proxy, test API/SPA/error responses and approved styles/scripts/connections, then check the real browser. This is a missing control, not a demonstrated stored-XSS exploit. |
| G04 - privileged MFA/SSO | `/auth/providers` lists local auth as available and Entra OIDC as planned; ASM-03 explicitly states no local TOTP/MFA. | Resolve DEC-04/DEC-11 and implement/test the chosen IdP MFA or reviewed local MFA before go-live. OS acceptance does not choose an identity provider. |
| G05 - host and operational evidence | No host address/access or observed production TLS/firewall/SELinux/runtime evidence in this session; live-source/SMTP and actual off-host recovery commissioning remain separate. | Complete the existing deployment and recovery runbooks on the approved host, record results and owners, then UAT/cutover sign-off. Owner acceptance closes OS choice; it does not fabricate these observations. |

The full repository was not searched for every vulnerability class; retained media,
all worker/broker paths, identity federation, every log emitter and dependency internals
were not independently audited. No prior full-audit coverage ledger was used; the
linked tests and bounded source paths are the extent of this review's evidence.

Validation: source/test paths checked, prior CI success rechecked and handoff docs
reviewed with `git diff --check`. No application behavior, dependencies or UI changed.
Next: Task 022d shared connector connection-target hardening (G01); keep G02-G05 open.
