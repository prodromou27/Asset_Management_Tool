# Current task: 022g1 | Local users with optional MFA

Owner clarified policy on 2026-11-08: local accounts remain available alongside
Entra, with optional MFA. This supersedes the Entra-only local-emergency restriction
in 022g and postpones 022h until this bounded change is complete.
Read: AGENTS.md, docs/00, docs/07, docs/09, docs/14 and docs/17.
Files: accounts model/services/auth endpoints/tests/migration, login/account/user
UI, generated API types, deployment checks and operator/policy documentation.
Acceptance: password-only local login; optional verified TOTP enrollment/removal;
no protected session before enrolled MFA; OTP/recovery replay rejection, encryption,
secret-free audit, CSRF/throttling, recovery and explicit Entra/local coexistence.
Existing linked accounts stay local-disabled on migration; new links disable local
by default. Admins can explicitly enable both. No live host/tenant changes.
Status: implemented; 224 frontend tests, lint/types/build/API generation and 136
production-browser CSP screenshots pass. Full local SQLite suite: 894 passed,
seven PostgreSQL/restore skips; the additional migration-preservation test is
covered by focused validation. Await full PostgreSQL/runtime/security CI proof.
Stop after validation and handoff. Historical
022g evidence below remains evidence of its original policy, not the revised one.

Owner requested next task on 2026-11-07. Baseline b4ef54b; CSP is complete
(TASK022E_REPORT.md). Address G02 from TASK022C_REPORT.md; preserve approved UI.
Read: AGENTS.md, docs/00, docs/07, docs/09, docs/12, docs/14, docs/15 and docs/17.
No host deployment or live identity-provider configuration.

Previous slice complete: TASK022F3_REPORT.md; CI 42397841169 is green. Preserve
the approved UI, strict security gates, RBAC and existing auth/session behavior.

Owner decision accepted (2026-11-07): Microsoft Entra SSO with MFA, plus reviewed
local emergency access. DEC-04/DEC-11 now select this approach. Live app registration,
Conditional Access enforcement and protected-host recovery still need commissioning.

Bounded implementation after choice: accounts models/services/views/middleware and
tests, login/account/security UI, OpenAPI/generated types, configuration and operator
recovery documentation as needed. Use supported auth libraries; no homemade OAuth.
Acceptance: no protected access before required factors; token/OTP replay rejection,
safe recovery, session revocation, CSRF/throttling, RBAC and secret-free audit; compatible
named-admin bootstrap. Validate API/browser flows and keep emergency recovery tested.

Outcome: implemented supported Authlib OIDC/PKCE, signed MFA-context validation,
explicit tenant/object account bindings and protected-shell one-use emergency access.
Existing roles/site grants remain authoritative. Configuration defaults stay off.
Final proof (handoff 2026-11-08): implementation 4f1a934, fixture fix 2e72b5e;
CI 42418403056 all six jobs green. 888 native and 888 production-derived backend
tests (no skips), three fixture regressions, 220 frontend tests, migration reverse,
schema/types/lint/build/deploy checks, 14 real browser scenarios, 124 CSP screenshots,
22 Nginx responses with callback-log privacy, reference load and isolated restore
checks pass. Six exact images have zero HIGH/CRITICAL; lower findings remain visible.
Evidence and limits: TASK022G_REPORT.md; operator runbook: ops/auth/README.md.

Next bounded task: 022h, remaining G02 source/compiler applicability review
(including SQLite/Go coverage). Do not silently start another epic or deploy.
Live Entra/Conditional Access and protected-host recovery review/drill, host capacity,
integration/SMTP/backup commissioning and G6 remain open; no live services changed.
