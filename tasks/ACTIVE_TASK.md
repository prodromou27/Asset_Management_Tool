# Current task: 022g | MFA authentication policy and implementation

Owner requested next task on 2026-11-07. Baseline b4ef54b; CSP is complete
(TASK022E_REPORT.md). Address G02 from TASK022C_REPORT.md; preserve approved UI.
Read: AGENTS.md, docs/00, docs/07, docs/09, docs/12, docs/14, docs/15 and docs/17.
No host deployment or live identity-provider configuration.

Previous slice complete: TASK022F3_REPORT.md; CI 42397841169 is green. Preserve
the approved UI, strict security gates, RBAC and existing auth/session behavior.

Decision required: DEC-04/DEC-11 leave IdP/MFA/emergency access policy unresolved.
docs/00 explicitly requires identity-provider approval; docs/09 prefers approved
Entra OIDC and requires two named emergency admins with reviewed recovery. Owner
was asked to choose Entra SSO/MFA or local authenticator MFA/recovery codes. Do not
infer that Microsoft inventory integration approval selects the login provider.

Bounded implementation after choice: accounts models/services/views/middleware and
tests, login/account/security UI, OpenAPI/generated types, configuration and operator
recovery documentation as needed. Use supported auth libraries; no homemade OAuth.
Acceptance: no protected access before required factors; token/OTP replay rejection,
safe recovery, session revocation, CSRF/throttling, RBAC and secret-free audit; compatible
named-admin bootstrap. Validate API/browser flows and keep emergency recovery tested.

Status: source review and baseline verification complete; 71 auth/user/security tests
pass locally with the explicit SQLite fallback (functional proof only). No auth or
schema change made pending the required owner choice. See TASK022G_PLAN.md.
Next: apply the owner's DEC-04/DEC-11 choice and implement its smallest complete slice.
G02 manual source/compiler review, commissioning and G6 remain separate open gates.
