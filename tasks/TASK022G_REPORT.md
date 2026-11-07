# Task 022g - Entra MFA and controlled emergency access

Work began 7 November; final validation/handoff continued on 8 November 2026
(Asia/Nicosia).

Owner selected **Microsoft Entra SSO with MFA, plus reviewed local emergency
access** on 7 November 2026. Implementation `4f1a934`, fixture correction `2e72b5e`,
branch `DEV`.
This completes the bounded authentication implementation; live G04 sign-off and
host/recovery commissioning remain separate.

Implemented:

- Authlib authorization-code/PKCE using fixed single-tenant endpoints and signed
  RS256 ID tokens. Enforces issuer/audience/nonce/expiry, tenant/object mapping,
  browser-bound one-use state and the selected `acrs` context. Requests `openid`
  only; no email auto-linking, provisioning, token role grants or persisted tokens.
- Explicit versioned, audited tenant/object account bindings in Users & roles,
  with RBAC, identity uniqueness, session revocation and last-linked-admin guards.
  Existing site/role authority and the approved UI/themes remain intact.
- Enforced SSO rejects ordinary local passwords and legacy local sessions.
  Restricted staging test mode supports testing a second account before enforcement;
  deployment checks reject release in that mode. Defaults remain disabled until
  configured, and production deployment checks reject disabled Entra.
- Protected-shell `emergency_access` rotates a named active admin's password and
  revokes sessions, then opens one sign-in within 15 minutes. Consumption is atomic,
  and the resulting session retains the original deadline. No HTTP grant-opening
  endpoint or automatic outage fallback exists; two named admins must remain.
- Additive migration 0017, generated OpenAPI/types, Compose/secret configuration,
  deployment checks and operator rollout/recovery instructions. Nginx omits query
  strings/referrers and suppresses callback logs to protect authorization codes.

Local validation:

- 125 account tests pass, including real RSA-signed fixture tokens, PKCE exchange,
  invalid signatures/claims/algorithm, replay/cross-browser/expired state, policy
  changes, provider denial, RBAC/version conflicts, binding/session revocation,
  two-admin/last-linked-admin guards and bounded one-use emergency recovery.
- Full explicit SQLite fallback: **881 passed, seven skipped**. The seven require
  PostgreSQL/restore tooling and remain mandatory in CI; this is not PostgreSQL proof.
- **220 frontend tests pass**; binding refinement rechecked with 14 user tests.
  Ruff, frontend lint/type check/build, migration drift and validated OpenAPI/types
  generation pass. Existing Vite chunk-size advisory remains nonblocking.
- Production-build browser/CSP review passes: **124 screenshots**, desktop/mobile,
  light/dark, including Entra login and binding panels; no browser errors, unmapped
  fixtures, overflow or normal-use CSP violations. Negative CSP probes still block
  scripts/handlers/eval/foreign connections/embedding; email preview remains sandboxed.

Initial CI: [42417537503](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42417537503)
validated `4f1a934`. Frontend and dependency gates pass (both lock reports have
zero findings). Real loopback API/browser pilot passes all 14 scenarios and database
assertions; its production CSP review passes with the same 124 screenshots and zero
normal violations. PostgreSQL forward/reverse migration and schema checks pass.
The native PostgreSQL/Redis suite reports **888 passed, no skips**, and production
settings deployment checks pass. The synthetic reference-load job is green.
The production-derived runtime also passes **888 tests** on disposable internal-only
PostgreSQL/Redis/SFTP. The final job then caught a CSP fixture defect: the synthetic
upstream parsed the callback query as a numeric status and disconnected (502).
Correction `2e72b5e` handles that callback explicitly with the expected 404; three
loopback regressions prove callback queries, ordinary statuses and broken upstream
behavior. The log-leak check now collects logs before grep, so pipefail/SIGPIPE
cannot mask a match. No production authentication/proxy code or gate was weakened.

Final CI: [42418403056](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42418403056)
is **green: all six jobs**, source `2e72b5e`. The native and production-derived
runtime suites each pass **888 tests, no skips**. Three fixture regressions,
220 frontend tests, schema/types/lint/build, migrations forward/reverse, production
deploy checks, 14 real API/browser scenarios, 124 production CSP screenshots and
the synthetic reference-load job pass. Real isolated Nginx verifies **22 responses**
and confirms callback parameters absent from logs. Redis nonroot startup and
network-disabled AOF/RDB recovery pass. Both isolated restore checks pass.

All six exact runtime image reports have **zero HIGH/CRITICAL**. Lower findings
remain visible: API and backup each have eight MEDIUM/seven LOW; frontend, proxy,
PostgreSQL and Redis each have one MEDIUM, with one additional PostgreSQL UNKNOWN.
No ignored advisories, severity changes, skipped jobs or test bypasses were added.

Corrected-run dependency artifact **13592581610**, SHA-256
`5dc5965195124ccb9dba4278fdd1ac9e753db1e9f358e635bbea88501888f252`,
was verified before parsing `summary.json` in memory, without archive extraction.
It records source `2e72b5e5bbe1006f4edbfae300b2b1fec26dc124`, Trivy 0.76.2,
database update `2026-11-07T18:32:58.034005789Z`, and zero findings for both locks.

Image artifact **13592267904**, SHA-256
`3c7d9d18863e24898479c7ba5f8e04429d80017b5ed6af472aece8d373ed8a59`,
and restore artifact **13592677498**, SHA-256
`ddb397c2326fd07df7e05d3f426a5d34239006523f068a6b2544bde6f4ff88a9`,
were also hash-verified before parsing JSON in memory without archive extraction.
The image summary identifies the corrected source, Trivy 0.76.2 and the same DB
update; it retains each exact image identity. Restore records PostgreSQL 16.15,
verified migration/table/relationship/audit continuity, network isolation, source
removal and temporary-target cleanup. These are synthetic restore fixtures, not
production RPO/RTO or secret-key recovery sign-off.

Limits and commissioning:

- `acrs` alone is not evidence of MFA. Review actual Conditional Access coverage,
  exclusions, authentication strength and licensing before setting the protected
  operator acknowledgement; verify both admins and a regular user in tenant sign-in
  logs. No real tenant/app registration/secret/policy has been configured or contacted.
- Review independent host MFA/console protection, two-admin credential custody,
  incident/audit export and an observed recovery drill before enabling emergency
  access operationally. This implementation uses protected-shell authorization,
  **not local TOTP**. No host is deployed or existing database migrated here.
- Existing app sessions have no Entra back-channel logout/continuous-access push;
  local disable/reset/rebind provides immediate application revocation, otherwise
  the token/idle/absolute deadlines apply. App logout does not end the Entra session.
- Migration is additive; CI must prove forward/reverse on synthetic databases.
  Isolated rollback clears sessions/attempts/grants before source/schema reversal;
  reversing 0017 loses identity bindings. Restore requires clearing recovered auth
  state and revalidating tenant policy/custody before exposure. Password-only pilot
  rollback is not an approved production fallback.
- G02 manual source/compiler applicability review (including SQLite/Go), actual host
  capacity, live integrations/SMTP/backup destination, MFA commissioning and G6 stay open.

Paths: `backend/apps/accounts/` (implementation/tests/migration),
`frontend/src/features/{auth,admin-users}/`, generated API files,
`infra/{compose.yaml,nginx/}`, `frontend/nginx.conf`, `ops/csp/`,
[operator runbook](../ops/auth/README.md), docs/09 and docs/17 ASM-72.

Outcome: Task 022g implementation and automated validation complete; commissioning
remains held as listed above. Next bounded task: remaining G02 source/compiler applicability
review, without treating scanner success as full security sign-off. Actual Entra and
host commissioning waits for approved tenant/host/FQDN and recovery evidence.
