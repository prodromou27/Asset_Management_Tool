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

## Phase 3 implementation and local proof

Strict SSH identity/host pinning is now enforced by fixed runner options. The existing
backup-only secret mount contains the repository password, private SSH identity and host
pin; inherited hooks and unrelated credentials are excluded. Explicit `backup_repository
init|check` operator commands use the same gated transport and audit operations.

Additive v1 manifests include PostgreSQL version/major/extensions, owner/ACL recovery
information, capture timings, file sizes/checksums, destination and expanded RBAC/outbox
counts. Capture metadata precedes upload; the job report records final verification and
duration. Job/drill report endpoints enforce view permission, audit downloads and disable
caching. UI details/report links, last verification and field-validation summaries use
existing shared components. No new schema migration is required; migration drift is clean.

The new synthetic SFTP fixture generates fresh keys and pins the generated host identity;
it tests real encrypted transfer/read-back, wrong password and wrong host pin. CI exports
the encrypted repository and a separate disposable key, destroys source DB/storage, then
retrieves and restores on another runner into PostgreSQL with `--network none`. Reports
include recovery-point age, retrieval/restore duration and source-removal evidence. Real
Docker/SFTP execution passed in CI; Docker remains unavailable on this workstation.

Local verification: **795 backend tests passed, 7 PostgreSQL/Redis-only skips** (explicit
SQLite fallback); **192 frontend tests passed**. Ruff lint/format, migration drift,
validated OpenAPI/type generation, frontend typecheck/oxlint and production build passed.
The browser suite now records **31 screenshots**, additionally covering job-detail drawers
at both requested sizes with viewport bounds assertions. Long drawer positioning and
strict SSH fixture file ownership were refined during verification.
The existing >500 kB frontend bundle warning remains. No production performance/SLA claim.

Changed areas: backend backups runner/services/API/management/tests; generated OpenAPI
and frontend types; Backups & Recovery UI/tests; synthetic SFTP image; CI; backup/restore
runbooks; ASM-60; active task and this evidence. Earlier phase commits are `98cf2f3`
(targeted fixes) and `73cd62f` (separate UI polish).

## Final CI and measured recovery

[CI run 42016059523](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42016059523)
is green on `7223d65`: **802 PostgreSQL/Redis backend tests, no skips; 192 frontend tests**;
lint/format, migration drift/apply/reversal, OpenAPI/type drift, deploy settings, dev/prod
Compose configuration and production/backup-worker image builds all passed.

The encrypted SFTP backup/read-back and wrong-password/host-pin tests passed. The final
fixture contains real group membership, installed software, lifecycle source/milestone,
license/product and user/role links, audit history, SMTP configuration, queued outbox data
and import/export encrypted file bytes. The first disposable DB restore verifies both
purpose-specific file decryptions. After source DB/container/volume destruction, a separate
runner checks/retrieves the encrypted repository and restores into a fresh network-disabled
PostgreSQL, verifies seven nonempty relationships/audit/outbox checks, migration history,
record counts, database hash and `pg_trgm`/`plpgsql` extension versions, then removes its
own target. No application or worker runs and SMTP remains disabled.

Exact artifact preserved in `tasks/TASK019_RESTORE_REPORT.json` (synthetic data only):

| Measurement | Actual |
|---|---|
| Database restore and verification | 9.953687 seconds |
| Repository retrieval plus restore | 11.372562 seconds |
| Recovery-point age at drill start | 173.266144 seconds |
| Source DB/storage container/storage volume removed | All true |
| Seven representative relationship checks | All one expected row |
| Isolated target removed | True |

These small-fixture measurements do not establish production RPO/RTO or application
readiness with separately recovered secrets. CI artifacts use separately stored disposable
keys; no production key-custody decision is implied. The report uses deliberately synthetic
application revision/image identifiers, not a deployed production image attestation.

Implementation commits: `98cf2f3` review fixes; `73cd62f` UI; `41a952a` backup refinements;
`4c002c6` drawer bounds; `ef2ad6c`, `e17da4b`, `a817286` SFTP fixture ownership/diagnostics/
Debian account correction; `7223d65` stronger relationship/file-recovery evidence.
The first fixture build exposed Debian's pre-existing system `backup` account; the fixture
now uses `itamfixture`, with strict key ownership. Final tests pass without relaxation.

Commands exercised in CI include `uv run python -m pytest -q -rs`, migration application
and reversal, `manage.py spectacular --validate --fail-on-warn`, `pnpm gen:api`, lint,
typecheck, test/build, `bash scripts/compose.sh dev|prod config --quiet`, production image
builds and the restricted backup-worker build. Recovery commands were:

```bash
python3 ops/restore/recover_fixture.py /tmp/itam-drill-fixture /tmp/itam-drill-key/restic_password /tmp/itam-drill-input
python3 ops/restore/drill.py /tmp/itam-drill-input --report /tmp/itam-drill-report.json
```

For approved deployment repository initialization/check and operator recovery commands,
use `ops/backup/README.md` and `ops/restore/README.md`. The application retains its three
existing backup/RBAC migrations (`backups.0001`, `backups.0002`, `accounts.0013`); this
supplement adds no schema migration. Task 020 has not been started.

Production readiness still requires approved off-host storage, pinned host identity,
separate recoverable keys, retention/RPO/RTO approval, target-host capacity and timed staging
drills. Local/CI storage on one physical host must never be called off-host protection.
