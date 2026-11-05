# Task 019 supplemental review and delivery evidence

Branch: DEV. Baseline: `624a011`. Focused review, not an exhaustive security audit.
No production credentials, vendor endpoints, shared databases or production restores used.

## Phase 1 findings

| Priority | Finding and affected boundary | Fix and regression evidence |
|---|---|---|
| High | `reconciliation.views.visible_observations` admitted a connector's default site even when linked to an asset in another site. An HQ-scoped reviewer received a Branch raw payload (HTTP 200) while unable to access the Branch asset. | Current links determine access; connector defaults only apply to unmatched observations. Regression reproduces the original 200, then requires list exclusion/404 for HQ and 200 for the authorized Branch reviewer. |
| Medium | `AppShell.UserMenu` cleared session state after a failed logout request although the server session could remain active. | Clear state only after confirmed success; show failure and allow retry. Regression covers failure followed by successful retry. |
| Medium | A retention notification exception escaped before backup finalization, leaving the active operation slot occupied after a verified backup. | Persist completion/release the slot before notification hand-off; isolate and redact notification errors. Regression injects outbox failure and checks completion, audit and the next job. |
| Medium | `backup-worker` inherited connector, SMTP and import-decryption credentials it does not require. | Explicit environment allowlist; connector execution forced off. Configuration regression asserts unrelated secret families are absent. |

Reviewed source paths: account permission/session helpers; canonical asset/site selectors;
reconciliation observations and reference masking; lifecycle/installed-software scoping;
export creator/permission rechecks; integration secret-reference resolution; backup
permissions, jobs, transport, Compose and notification boundaries; shared frontend API,
navigation and forms. Existing asset/export/reconciliation tests remain part of verification.
This review does not prove IdP/host/network configuration or absence of other vulnerabilities.

No TODO/FIXME/HACK markers were found in the reviewed application/ops/infra sources.
Documented operator decisions remain open, especially DEC-09 and DEC-08/14; unresolved
decisions are not reported as implemented production controls.

## Phase 2 UI evidence

Shared dialog titles/actions remain visible while the body scrolls; settings action rows
and section headers wrap; account-panel focus/Escape behavior and breadcrumb semantics
are consistent. Mobile linked-record name columns have a readable minimum width, and the
Discovery default filter has a concise label. The SMTP action-row overflow and cramped
integration name were found by actual browser inspection and corrected.

`pnpm review:ui` uses only loopback Vite and synthetic API fixtures. **29 screenshots** at
1440×900/390×844 cover Assets (28 rows and detail), Discovery, Lifecycle, Integrations
(including a long name), Software & Licenses, domains, administration and security/SMTP/
backup settings, plus loading/error/denied states and a mobile dialog. It asserts no
browser exceptions, unmapped fixture requests or document overflow, visible dialog actions,
and navigation focus return. Artifacts: `frontend/test-results/task019-review/` (ignored).
Forty focused UI tests, typecheck, oxlint and production build passed. The existing
large-bundle warning remains; no performance claim is made from screenshots.

## Remaining phase

Phase 3: close backup manifest/reporting and isolated-storage/restore evidence gaps against
the new request, preserving the current architecture and migration history.

Production readiness still requires approved off-host storage, pinned host identity,
separate recoverable keys, retention/RPO/RTO approval, target-host capacity and timed staging
drills. Local/CI storage on one physical host must never be called off-host protection.
