# Local accounts, optional MFA and Entra

Owner clarification (2026-11-08, Task 022g1): local accounts are available with
optional MFA, including named admins. Entra is optional; when enabled it retains
its required IdP MFA policy. No real tenant or host has been changed by this task.

## Local users and optional MFA

Existing unbound local accounts can continue using their passwords. In the account
menu, choose **Local account MFA** to enroll an authenticator. Enter the current
local password, add the displayed setup key to a compatible authenticator (TOTP,
6 digits, 30 seconds), and verify its code within ten minutes. Enrollment is not
active until confirmation. Save the ten recovery codes securely: shown once, each
works once **with your password**. Wait for the next authenticator code after a
successful confirmation/login; an already-used code cannot authenticate again.

The local login form accepts an authenticator or recovery code when MFA is enrolled;
otherwise leave it blank. Missing/incorrect factors cannot establish a session and
use existing lockout/throttling. To disable MFA, verify the current local password
and an unused authenticator/recovery code on the same account page. This revokes
other sessions. Admin password reset preserves enrolled MFA; it cancels pending setup.

System Admins control **Allow local password sign-in** on user profiles. Linking or
replacing an Entra identity disables local login by default. To intentionally allow
both methods, explicitly enable that checkbox after linking. Disabling local access
requires a ready linked Entra route and revokes sessions. Local MFA is independent
of the Entra policy; existing linked users remain local-disabled on upgrade.

For lost factors and exhausted recovery codes, verify the person's identity through
the approved operator procedure, then use the protected shell:

```sh
docker compose -f infra/compose.yaml exec api python manage.py reset_local_mfa \
  --username <named-user> --reason <incident-reference>
```

The reset audits the operator/reference and revokes sessions; it does not enable
local access, unlock/enable the account, change its password or change Entra identity.
The user can re-enroll. There is no public admin MFA-reset endpoint.

Seeds use the existing Fernet primitive with a local-factor purpose, using the
configured `ITAM_IMPORT_ENCRYPTION_KEY` if present, otherwise a key derived from
`DJANGO_SECRET_KEY`. Preserve that key with restricted backups. Do not rotate keys
without a tested re-encryption/recovery plan. Neither setup keys, OTPs, passwords nor
recovery codes belong in logs, URLs, tickets, screenshots or persistent browser storage.

## Configure and stage

1. Obtain the approved internal HTTPS FQDN/TLS and tenant/app registration. Use a
   dedicated **single-tenant Web** application in the Microsoft global cloud, with
   exact redirect `https://<approved-fqdn>/api/v1/auth/entra/callback/`. No wildcard,
   SPA implicit grant, Graph inventory permission or offline scope is required.
   This flow requests only `openid`. Keep inventory connector credentials separate.
2. Create an authentication context (`c1`–`c99`) and an enabled Conditional Access
   policy targeting it that requires MFA for **every permitted ITAM account**.
   Review exclusions, guest access, authentication strength and licensing (Microsoft
   documents Entra ID P1 for this feature). An `acrs` value alone does not prove MFA:
   Entra can issue it when no policy applies. Test users must actually be covered.
3. In the restricted deployment environment, set `ITAM_ENTRA_TENANT_ID`,
   `ITAM_ENTRA_CLIENT_ID`, `ITAM_ENTRA_REDIRECT_URI`, `ITAM_ENTRA_AUTH_CONTEXT` and
   `ITAM_ENTRA_CLIENT_SECRET_REF=env:ITAM_ENTRA_CLIENT_SECRET`. Provision the secret
   through the protected runtime environment or a supported mounted secret reference
   (`file:<name>` directly inside `ITAM_SECRETS_DIR`, normally `/run/secrets`);
   never paste it into a command, Git, logs or a ticket.
   The API alone receives the client secret in Compose. Arrange expiry/rotation.
4. While `ITAM_ENTRA_ENABLED=false`, create/retain at least two **named** active
   System Admins using the existing protected-shell `bootstrap_admin` command. In
   Users & roles → account → Microsoft Entra sign-in, explicitly bind the tenant
   UUID and the person's user **object ID**, not app object ID, email or device ID.
   Initially link one admin and retain an independent named local admin. Linking
   revokes that user's sessions and disables local sign-in. After enabling Entra
   and testing the first linked admin, use that session to link the second admin
   and an ordinary test user. Roles/site scope stay local; claims do not grant them.
5. After reviewing the actual MFA policy, set `ITAM_ENTRA_MFA_POLICY_VERIFIED=true`
   and `ITAM_ENTRA_ENABLED=true` in isolated staging. Restart the API. Retain an
   independent named local admin while testing the second SSO account. The former
   `ITAM_ENTRA_ENFORCE` flag is retired and no longer controls local login.
6. Test both admins and an ordinary user in separate browsers. Confirm sign-in logs
   show the required Conditional Access MFA policy applied, app/site authorization
   matches existing grants, unmapped/disabled/wrong-tenant users are rejected, and
   failure/cancel/expired requests reveal no tokens. Record evidence without codes,
   passwords or tokens. Confirm the recovery procedure below independently.
7. Run `python manage.py check --deploy` through normal release settings. When
   Entra is enabled it checks configuration, policy acknowledgement, two admins
   and a linked admin. Local-only production is permitted. This check cannot
   inspect live Conditional Access. Test each account's intended methods and MFA;
   local-disabled accounts must reject local passwords, including old sessions.

Read-only `/api/v1/auth/providers/` advertises Entra only when configuration and
admin prerequisites are ready. Its availability is not tenant sign-off. Browser
start is CSRF-protected and throttled; the five-minute attempt is single-use. Tokens
remain server-side and are discarded after sign-in. SSO expires at token expiry or
the shorter existing idle/absolute limit. Local password changes are not an Entra
password-management workflow. App logout ends the ITAM session, not the Entra one;
sign out of Microsoft separately on shared devices.

There is no back-channel logout or continuous-access notification subscription in
this slice. An Entra-only disable/policy change is not pushed into an already
established ITAM session; its signed-token deadline still applies. For immediate
application revocation, disable the ITAM account (or reset/rebind it through the
authorized account workflow). Include this limit in the incident procedure.

Binding updates require `users.manage` and the current `If-Match` version, revoke
sessions and cancel pending recovery. A signed-in Entra admin cannot change their
own binding; another admin must do it. The last active linked admin cannot be
unlinked/disabled/demoted while Entra is enabled. Review account access regularly.

## Protected-host emergency recovery

Before commissioning, approve independently protected SSH/console access (MFA or
equivalent), named operator custody for **two** admins, incident handling, audit
export and an observed recovery drill. Docker/host access is privileged. This is a
protected operator procedure, **not local TOTP** or an automatic password fallback.
Entra does not need to be reachable or enabled for protected local recovery.

From the approved host, using the normal protected Compose environment:

```sh
docker compose -f infra/compose.yaml exec api python manage.py emergency_access \
  --username <named-admin> --reason <incident-reference>
```

Use the interactive hidden password prompt to enter a fresh strong password twice.
For approved noninteractive tooling, `--password-stdin` reads one line from a secure
pipe; never use a literal `echo`, argument, environment variable or recorded shell
session for the password. No password argument is supported. The command validates
active System Admin status and policy, rotates the hash, revokes old sessions,
clears lockout and opens one sign-in opportunity ending **15 minutes after opening**.
It disables ordinary local login, so the emergency password cannot become a normal
password-only fallback after the window. Re-enable local login deliberately through
another authorized admin after completing recovery, if that method is intended.
The resulting emergency session has that same deadline; a second login fails.
An existing grant cannot be extended through the browser. The CLI records the
operator label and incident reference, so exclude credentials from the reason.

Use the local sign-in form over approved internal HTTPS. Confirm
`auth.emergency_opened` and `auth.emergency_login` events, perform the needed repair,
then sign out. Rebinding, password reset, Entra sign-in and disable cancel pending
windows; expiration terminates the emergency session. If recovery expires, the
authorized operator must explicitly run the command again with a new password.
If fewer than two active admins survive, use `bootstrap_admin` from that same
protected shell to create a new **named** admin, then open its recovery window.
Never create a shared default account or weaken the configured Entra MFA policy.

## Restore and rollback

0018 adds local-access/MFA fields and preserves linked accounts as local-disabled.
Use a maintenance window: stop old API/workers, migrate, then run only the new code
before anyone enrolls. An old binary does not enforce the new local MFA fields, so
mixed versions or exposing a password-only rollback after enrollment are unsafe.
Reverse migration loses local MFA state. Recover using compatible backup/code and
revoke sessions before exposure; validate local access, MFA and key custody again.

Keep identity configuration/secret custody with the restricted deployment backup.
Before exposing a restored database, clear restored Django sessions, OIDC attempt
receipts and pending emergency deadlines from the protected operator shell. Recheck
bindings against the approved tenant, two-admin custody, MFA policy and audit
continuity; do not replay an old recovery window. Test recovery after restoration.

Migration `accounts.0017_entra_oidc` is additive. Validate forward migration on a
backup clone before deployment. A rollback must be isolated and clear sessions,
attempts and recovery grants before reverting application/schema; backing out 0017
destroys identity bindings. Restore from the protected backup if those mappings
are needed. Password-only pilot rollback is not approved for production access.

Nginx deliberately logs paths without query/referrer and suppresses callback logs.
Do not enable debug/request-body logs, APM query capture or query-bearing upstream
access logs for the callback. Keep `DEBUG=false`. Revalidate these controls after
proxy/observability changes. Do not export authorization URLs or provider tokens.

Reference: [Microsoft authentication context and policy requirements](https://learn.microsoft.com/en-us/entra/identity-platform/developer-guide-conditional-access-authentication-context).
