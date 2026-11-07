# Task 022g - MFA implementation readiness

Owner requested the next task on 7 November 2026. Baseline `b4ef54b`; the previous
CI-remediation slice is complete with green CI 42397841169. This is preparation for
G04, not implemented MFA or production sign-off.

Required owner decision: docs/00 lists identity provider under approvals; DEC-04 and
DEC-11 in docs/17 remain unresolved. docs/09 prefers approved Entra OIDC and requires
two named emergency admins and a tested recovery path. Select enterprise Entra SSO
with IdP-enforced MFA and reviewed local emergency access, or local authenticator
MFA/recovery codes. No credentials or live tenant changes are needed to select the
approach. An inventory connector's Entra consent is not sign-in/IdP approval.

Existing seams reviewed:

- `backend/apps/accounts/services.py`: local authentication immediately establishes
  a Django session, resets failure counts and audits login. Factor completion must
  precede session promotion and the successful-login event.
- `middleware.py`: idle and absolute session expiry; `User.session_epoch` participates
  in the session auth hash. Preserve password/disable/reset revocation and last-admin
  guards. Pending authentication must not appear authenticated to protected APIs.
- `views.py`, `urls.py`, `serializers.py`: CSRF-protected throttled local login,
  provider discovery, identity and settings APIs. Entra remains explicitly Planned.
- `frontend/src/features/auth/LoginPage.tsx`, `app/session.tsx`, admin-security and
  account API types: current sign-in expects completed identity and immediately
  redirects. New provider/challenge/enrolment UI must match the chosen backend flow.

Shared acceptance for the chosen implementation: privileged access requires verified
factors; malformed/expired/replayed credentials fail closed; CSRF/throttling and
non-enumerating failures remain; recovery cannot silently bypass policy or strand
both emergency admins; disabling/resetting credentials revokes affected sessions.
MFA/provider changes are authorized and audited without secrets. No automatic email
identity linking or unreviewed IdP role escalation. Keep explicit application/site
grants and existing UI tokens. A supported server-side OIDC library is required if
SSO is selected; live Conditional Access/MFA enforcement needs commissioning proof.

Baseline: **71 tests passed** across test_auth.py, test_users_api.py and
test_security_settings.py, using the existing explicit local SQLite fallback.
This is functional baseline evidence only; PostgreSQL concurrency, real browser flows
and the selected factor/provider require implementation-specific CI proof.

No authentication behavior, API schema, dependency, account, session, tenant or live
service has changed. Next action depends on the pending owner choice; no method has
been selected or claimed Available. Manual security and host commissioning stay open.
