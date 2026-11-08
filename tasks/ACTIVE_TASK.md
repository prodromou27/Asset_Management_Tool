# Current task: 022g1 | Local users with optional MFA (complete)

Owner clarified on 2026-11-08 that local users remain available with optional MFA,
alongside Entra. This supersedes the Entra-only/local-emergency restriction in 022g.
Read: AGENTS.md, docs/00, docs/07, docs/09, docs/14 and docs/17.

Outcome: local-only and combined deployments are supported. Optional authenticator
enrollment/removal lives under Account menu -> Local account MFA. Enrolled accounts
require a TOTP/recovery code at local login. Admins explicitly control per-account
local sign-in; linked accounts remain local-disabled unless deliberately enabled.
Entra keeps its IdP MFA checks. Migration 0018, recovery CLI, session revocation,
encryption, one-use recovery, RBAC/CSRF/throttling, audit and operator docs included.

Source: 57122a9 plus readiness wording correction 0b21447. Final CI 42474781375:
all six jobs green. Native and production-derived backend each 902 passed/no skips;
224 frontend tests, three CSP fixture tests, schema/types/lint/build/deploy checks,
migration forward/reverse, 14 real browser scenarios, 136 CSP screenshots, 22 real
Nginx responses/log privacy, reference load, Redis persistence and isolated restore
checks pass. Six exact images have zero HIGH/CRITICAL; lower findings stay visible.
Evidence: TASK022G1_REPORT.md; policy: docs/17 ASM-73; operator: ops/auth/README.md.
Prior 022g evidence: TASK022G_REPORT.md (its policy is superseded).

Issue/rollout: no host/tenant/live service changed. Maintenance deployment required:
stop old auth servers before migration/new code and enrollment. Preserve factor
encryption keys; old binaries/older restore codes require isolated recovery review.
Live TLS/host/recovery/backup custody and Entra policy (when enabled) still need
commissioning. Optional local enrollment is an approved choice, not a blocker.

Next bounded task: 022h, remaining G02 source/compiler applicability review
(including SQLite/Go coverage). Do not silently start another epic or deploy.
Actual host capacity, live integration/SMTP/backup commissioning and G6 stay open.
