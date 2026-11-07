# Current task: 022g | MFA authentication policy and implementation (complete)

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
