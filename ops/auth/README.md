# Entra MFA and emergency access

Task 022g implements the owner's Entra choice. Fixture tests do not commission a
tenant or prove Conditional Access. Keep the pilot internal until all steps below
have evidence. No real tenant or host has been changed by this task.

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
   Bind two separate admins and an ordinary test user. Application roles and site
   scope must already be assigned; Entra claims do not create privileges.
5. After reviewing the actual MFA policy, set `ITAM_ENTRA_MFA_POLICY_VERIFIED=true`,
   `ITAM_ENTRA_ENABLED=true` and **temporarily** `ITAM_ENTRA_ENFORCE=false` in isolated
   staging. Restart the API. This test mode deliberately retains local pilot login
   so a second SSO account can be tested before enforcement. Deployment checks
   reject it; never expose it publicly or release it.
6. Test both admins and an ordinary user in separate browsers. Confirm sign-in logs
   show the required Conditional Access MFA policy applied, app/site authorization
   matches existing grants, unmapped/disabled/wrong-tenant users are rejected, and
   failure/cancel/expired requests reveal no tokens. Record evidence without codes,
   passwords or tokens. Confirm the recovery procedure below independently.
7. Set `ITAM_ENTRA_ENFORCE=true`, restart and run the deployment check through the
   normal release settings (`python manage.py check --deploy`). It checks required
   configuration, the operator acknowledgement, two admins and a linked admin.
   Production (`ITAM_ENV=production`) rejects disabled Entra. The check cannot
   inspect your live Conditional Access policy. Verify ordinary local login and
   old pilot sessions fail; do not disable enforcement to work around an outage.

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
Entra does not need to be reachable. Keep Enabled and Enforce true during recovery.

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
The resulting emergency session has that same deadline; a second login fails.
An existing grant cannot be extended through the browser. The CLI records the
operator label and incident reference, so exclude credentials from the reason.

Use the local emergency form over approved internal HTTPS. Confirm
`auth.emergency_opened` and `auth.emergency_login` events, perform the needed repair,
then sign out. Rebinding, password reset, Entra sign-in and disable cancel pending
windows; expiration terminates the emergency session. If recovery expires, the
authorized operator must explicitly run the command again with a new password.
If fewer than two active admins survive, use `bootstrap_admin` from that same
protected shell to create a new **named** admin, then open its recovery window.
Never create a shared default account or weaken Entra enforcement.

## Restore and rollback

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
