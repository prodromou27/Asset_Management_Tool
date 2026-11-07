# Current task: 022g | MFA authentication policy and implementation

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

Status: implemented supported Authlib OIDC/PKCE, signed MFA-context validation,
explicit tenant/object account bindings and protected-shell one-use emergency access.
Existing roles/site grants remain authoritative. Configuration defaults stay off.
Local proof: 881 backend tests passed with seven PostgreSQL/restore skips under the
explicit SQLite fallback; 220 frontend tests passed. Ruff/lint/types/build/schema
validation passed. Production-browser CSP review passed with 124 screenshots,
including Entra/binding desktop/mobile light/dark, no errors or normal violations.
Next: obtain PostgreSQL/runtime/security CI proof; record outcome in TASK022G_REPORT.md.
G02 manual source/compiler review, commissioning and G6 remain separate open gates.
