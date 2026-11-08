# Task 022g1 - Local users with optional MFA

Owner clarification, 8 November 2026: local accounts remain available with optional
MFA, alongside Entra. This supersedes the Entra-only restriction in 022g. Optional
enrollment applies to every local role, including named admins; enrolled factors
are mandatory until verified removal or protected-shell recovery.

Behavior:

- Local-only deployment is permitted. Entra keeps its signed-token/PKCE/MFA-context
  checks when enabled. `ITAM_ENTRA_ENFORCE` is retired. Per-user local access is
  controlled by an authorized, versioned/audited profile update, with session revocation.
- Existing unbound local accounts retain access. Migration 0018 leaves existing
  linked accounts local-disabled. New/replaced Entra bindings disable local login;
  an admin deliberately enables both when intended. No outage-triggered fallback.
- Account menu → Local account MFA supports fresh-password authenticator setup,
  ten-minute pending enrollment, code-confirmed activation and verified removal.
  Sign-in accepts the local password plus a TOTP or one-use recovery code when
  enrolled; it creates no protected session before verification. MFA is off by default.
- PyOTP supplies TOTP (6 digits/30 seconds, one-step drift). Encrypted seeds reuse
  the existing Fernet primitive with a factor purpose. Ten random 128-bit recovery
  codes are shown once and stored as hashes. Row locks consume factors and reject
  replay; failures use existing throttling/lockout. Changes revoke other sessions.
- Protected-shell `reset_local_mfa --username ... --reason ...` handles lost factors
  after operator identity review, with audit and session revocation. It does not
  change sign-in permission, password, account status or bindings. Admin password
  reset preserves enrolled MFA and cancels pending setup. Emergency admin windows
  now disable ordinary local login, preventing their password from outliving the grant.

Paths: `backend/apps/accounts/` (services/endpoints/models/migration/tests/command),
readiness wording in `backend/apps/health/operations.py`,
`frontend/src/features/auth/`, user profile/menu, generated API types, deployment
checks/configuration and [operator instructions](../ops/auth/README.md). Decisions:
docs/00, docs/09, docs/14 and docs/17 ASM-73.

Local proof:

- Full SQLite fallback run: **894 passed, seven PostgreSQL/restore skips**. Additional
  focused tests cover the final migration-preservation/audit changes. CI must prove
  all cases with PostgreSQL and the production-derived runtime, without skips.
- **224 frontend tests** pass, including enrollment confirmation, one-time recovery
  display/dismissal, verified removal, local-disabled UI and login factor submission.
- Ruff/format, frontend lint/types/build, migration drift and OpenAPI/type generation
  pass. Existing nonblocking Vite chunk advisory remains.
- Production-build browser/CSP review passes with **136 screenshots**, including
  setup/recovery/settings and sign-in on desktop/mobile in both themes. No overflow,
  browser errors, missing fixtures or normal-use CSP violations; negative probes pass.

Implementation: `57122a9`, branch `DEV`; readiness wording correction `0b21447`
also passed 10 focused health tests. Initial feature CI
[42473972064](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42473972064)
passed all six jobs for the core implementation. Final CI
[42474781375](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42474781375)
is **green: all six jobs** for `0b21447`.

Final proof: native PostgreSQL/Redis and production-derived runtime each report
**902 passed, no skips**. Migration 0018 forward/reverse/reapply, production checks,
224 frontend tests, 14 real API/browser scenarios, 136 production CSP screenshots,
synthetic reference load and both isolated restore checks pass. Real isolated Nginx
verifies 22 response cases with callback parameters absent from logs. Redis nonroot
startup and network-disabled AOF/RDB recovery pass. No security gate was bypassed.

Dependency artifact **13614708949**, SHA-256
`5feb28c6ea7755851794ab1e18e49b770cdf7e808cb81411e2a3df6d9a876274`,
was verified before parsing its JSON summary in memory without extraction. It
records source `0b214478b576e0eae9653c4b3097e791827dcba0`, Trivy 0.76.2,
DB update `2026-11-08T06:39:21.614725497Z`, and zero findings in both lock reports.

Image artifact **13615495768**, SHA-256
`a398d94a2b653a9aebffb4cd51511a2d97bda696b2a61a94a69930d677342a45`,
and restore artifact **13615495715**, SHA-256
`464d910e7898f59cf935f1c6badf624fb1bbe4f06b2712b75db6c6ed76683b4c`,
were likewise hash-verified before JSON parsing in memory without extraction.
All six exact-image reports identify the final source and have **zero HIGH/CRITICAL**.
Lower findings remain: API/backup each eight MEDIUM/seven LOW; frontend, proxy,
PostgreSQL and Redis each one MEDIUM, plus one PostgreSQL UNKNOWN. Manual G02
applicability remains open. Restore proves synthetic PostgreSQL 16.15 recovery,
relationship/audit continuity, network isolation, source removal and target cleanup;
it does not sign off production factor/key custody or host RPO/RTO.

Operational limits:

- Enrollment is a deliberate security choice; enabling Entra does not add MFA to
  independent local passwords. Review intended local access and MFA status per user.
- Maintenance deployment only: stop old API/workers, migrate and exclusively deploy
  new code before enrollment. Old binaries do not enforce these new factor fields;
  mixed versions or a password-only rollback after enrollment would bypass policy.
  Reversing 0018 drops factor state/local flags. Restore compatible backup/code and
  revoke sessions before exposure; no live migration occurred here.
- Older database restores can resurrect consumed recovery-code hashes. Maintain
  isolation and verify/re-enroll affected factors with new recovery codes before
  resuming normal access; do not silently expose cleared-MFA password-only accounts.
- Preserve the configured import Fernet key or deriving Django secret in restricted
  key custody. Do not rotate without a tested re-encryption/recovery plan. TOTP fails
  closed on key loss; recovery codes/protected operator recovery remain separate.
- Setup/recovery responses are TLS-only operationally, no-store/no-referrer, and
  kept only in component memory. Secrets never enter audit, URLs, persistent browser
  storage or ordinary account reads. Browser evidence uses public synthetic fixtures.
- Tenant Conditional Access (when enabled), independently protected host recovery,
  actual TLS, backup/key custody, host capacity, G02 manual applicability and G6
  still require commissioning/review. No live IdP/host/service was contacted.

Outcome: requested local-account/optional-MFA implementation and automated proof
complete, pushed to DEV. Next: return to 022h G02 source/compiler applicability review.
