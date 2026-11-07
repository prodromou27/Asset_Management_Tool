# 09 | User Accounts, RBAC and Administration

## Authentication choices

Preferred enterprise sign-in: OpenID Connect against Microsoft Entra ID, if app registration and consent are approved. Alternative: on-prem LDAP/LDAPS/AD if demanded by environment. Local secure accounts required for initial bootstrap and at least two documented emergency admins; no public self-registration. Do not implement a weak homemade OAuth protocol. Use supported server-side OIDC library and standards-based code/PKCE flow as applicable.

Owner selected Entra MFA plus reviewed local emergency access on 7 November 2026.
Task 022g implements this approach with Authlib, explicit tenant/object bindings
and protected-shell one-use recovery. See ASM-72 and [operator instructions](../ops/auth/README.md).
Live Conditional Access and emergency custody/recovery evidence are required before release.

## Authentication requirements

- TLS on every login and session; secure HttpOnly SameSite cookies, CSRF protection for session-authenticated unsafe methods, session rotation after login.
- SSO subject issuer+sub (or Entra tenant+object ID), never display name/email alone for identity.
- MFA required for privileged access via IdP; local emergency admins use MFA/TOTP if implemented, otherwise access restricted until a reviewed secure method exists. No shared default administrator.
- Passwords (for local accounts) are hashed with an approved adaptive password hash; no reversible storage or plaintext logging.
- Login throttling and lockout/alerting, inactivity timeout, absolute session timeout, revoked token/session handling.
- SCIM or automated provisioning is a future option; V1 supports invited/provisioned users and explicit disable.

## RBAC roles and default access

| Role | Asset edit | EOL approval | Groups | Import/export | Integrations/settings | Users/backup |
|---|---|---|---|---|---|---|
| System Admin | All authorized | Can administer sources | CRUD | Full authorized | Full | Full |
| ITAM Manager | Curated fields | Approve/except | CRUD | Authorized bulk | View health | No secrets/restore |
| Infrastructure Engineer | Technical comments/candidates | Propose matches | Member operations | Technical exports | View/source diagnostics | No |
| Security Analyst | Read/investigate | View/flag high risk | Read | Restricted exports | Security source health | No |
| Asset Operator | Authorized business fields | No | Static membership | Authorized import/export | No | No |
| Auditor | Read | Read evidence | Read | Approved export only | Health read-only | Audit read-only |
| Read Only | Site-scoped read | Read allowed | Read | Limited filtered export | None | None |

Rights are **verbs on resource types + site/department scope + field mask**. A group membership never widens permission scope. Application roles should be configurable, with mandatory high-risk constraints that cannot be switched off without a security decision.

## Administrator workflows

1. First-run setup creates a named admin through an authenticated local CLI/bootstrap command with one-time input; no static username/password in compose or code.
2. Admin sets organization name, timezone Asia/Nicosia display, retention and sites.
3. Admin configures IdP and tests SSO with a second account before disabling direct login.
4. Admin provisions users, maps role and site scope, selects notification recipients.
5. Admin tests LibreNMS/Endpoint Central/Graph integration read permissions.
6. Admin configures SMTP, backups, storage, certificate, health and scheduled jobs.
7. Admin validates all readiness checks before production enablement.

## Settings areas

General, Users, Roles/Scopes, Identity Providers, SMTP, Notifications, Integrations, Discovery Source Status, Categories, Group Templates, Lifecycle Source Policies, Data Retention, Imports/Exports, Backup Policies, Audit, Diagnostics.

Implement GET/PATCH settings APIs with validation, version guard, RBAC and before/after audit. Store nonsecret business settings in DB. Store secret references in DB only if necessary, encrypted values in a vetted secrets store. Show 'Configured' not actual secret in UI; rotate without seeing original.

## API/service accounts

Service accounts have purpose, owner, scopes, expiry, rotation status and last used; tokens are hashed and reveal-once. Export is separately permissioned. Do not allow service API tokens to create administrator accounts or manipulate connector credentials.

## Account lifecycle

Disable/lock/suspend users; preserve audit attribution and historical ownership. Reassign active jobs/notifications when owner disabled. Role or site changes take effect at next authorized request, not after user relogin only. Account access review export is available to admins/auditors with appropriate permission.

## Acceptance

- Unauthorized user cannot export or edit another site's data by altering URL/query.
- MFA/SSO setup has tested fail-safe recovery path, no hard-coded bypass.
- Two named admins can log in; regular user role cannot read SMTP/API secret or backup file.
- User disable revokes active sessions/tokens under documented policy.
