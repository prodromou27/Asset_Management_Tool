# Local pilot rehearsal (Task 022a)

This starts a real React browser session against Django's disposable **test database**.
It does not deploy, migrate an application database, contact vendor/SMTP endpoints or
approve production readiness. Docker is not needed for the local SQLite fallback.
The full Task 022 AlmaLinux/security/load/UAT/restore pilot remains open.

## Run

Sync existing backend/frontend dependencies first. `pnpm e2e` uses the backend virtual
environment, forces `config.settings.test` and runs the opt-in pytest harness. Override
the executable with `ITAM_PILOT_PYTHON` only if using another prepared environment.

On a machine with local PostgreSQL (test role needs CREATE DATABASE):

```sh
cd frontend
pnpm exec playwright install chromium
pnpm e2e
```

PostgreSQL settings use the existing `POSTGRES_*` variables. Only loopback database
hosts are accepted, checked during collection before a test database is created.
The database name used by the rehearsal must have pytest's `test_` prefix (or be
SQLite's test memory database). It refuses pre-existing asset/user fixture data.
Use a disposable database service, never a production database server.

Local Windows sandbox without Docker/PostgreSQL, using installed Microsoft Edge:

```powershell
cd frontend
$env:ITAM_TEST_DB_SQLITE = '1'
pnpm.cmd e2e
```

On Linux the equivalent is `ITAM_TEST_DB_SQLITE=1 pnpm e2e`. Chromium must be installed;
Windows defaults to Edge. `ITAM_UI_BROWSER_CHANNEL=chromium` selects Chromium explicitly.
CI refuses SQLite and runs this against a disposable PostgreSQL 16 service. The
separate backend job continues to cover real Redis and transport/recovery tests.

The UI binds **127.0.0.1:5198** and Django uses a temporary loopback port. The script
refuses arbitrary remote browser/API targets; browser requests outside the local UI
origin are blocked. Port conflicts fail instead of attaching to another service.
Account passwords are generated per run, sent to the browser subprocess over stdin
and redacted from failures; no password argument, credential file, trace or login
screenshot is produced. Authenticated screenshots contain synthetic data only.

## What it proves

- Real UI login and HTTP-only session cookie; anonymous inventory denied and login
  without CSRF rejected.
- A scoped ITAM Manager sees HQ assets and laptop descendants through Workstations;
  cross-site GET/PATCH and access to user administration are refused.
- A mixed-site group's visible members do not grant additional asset access.
- Real form registration of a monitor without IP/agent/serial; audited DB mutation.
- Unassessed lifecycle remains Unknown, with scoped report results.
- JSON export through the UI, eager Celery task, encryption at rest, authenticated
  download, scoped contents and download audit/count.
- An administrator disables the manager through the real API, revoking an existing
  browser session; the UI returns to sign-in.
- Backend assertions confirm audit events, unchanged hidden data, encrypted artifact,
  revoked account and no notification outbox rows.

The harness has four pytest checks: one 14-scenario browser/database rehearsal,
two invalid API-target guards and a remote-database collection guard. Browser output
initially says `browser_passed`; only successful backend assertions finalize the
report as `passed`. Failed runs cannot reuse an old successful report.
401/403/404 entries in the test-server log are expected for the denial scenarios;
the final pytest result and report determine success.

## Evidence and remaining gates

`frontend/test-results/pilot/report.json` records engine, scenario names, timestamps,
task mode and limitations. Two screenshots show authenticated inventory at desktop
and mobile widths. CI uploads the synthetic evidence with a seven-day retention.

| Gate | Evidence / next action |
|---|---|
| A05/A23/A25 | Local real-API/browser Unknown, non-network registration and revocation |
| A07/A14/A15 | Group scope and scoped JSON download here; full rule/import/1:N cases remain in backend suites |
| A01-A04/A08-A13/A16/A24 | Existing sanitized adapter/reconciliation/import/lifecycle tests; approved live samples still needed |
| A17/A18 | Existing outbox transport tests; this rehearsal leaves SMTP off; approved relay/delivery test outstanding |
| A19/A20 | Existing real encrypted SFTP/isolated restore CI; approved destination, key custody and target-host recovery outstanding |
| A21/A22 | Existing catalogue/UI regression suites and synthetic visual review; target-browser UAT outstanding |
| Scale | Existing 10k asset query budget is a single-request approximation; 30k total assets/1m installations, concurrent p95 and 10k lifecycle timing outstanding |
| Supply chain | Dependency/image vulnerability and secret-layer review outstanding; no certification implied |
| AlmaLinux | No host proof: OS/architecture, Docker compatibility, SELinux/firewalld, resources, DNS/TLS and host monitoring require approved staging |
| Runtime | Eager task execution is not proof of worker/scheduler health, broker recovery or queue latency |

Next bounded work: Task 022b, prepare/run isolated PostgreSQL reference-load measurements
and capture workload/sample counts. Before any host rehearsal, resolve the operator
inputs in docs/17 (including host/identity/SMTP/backup decisions) and follow docs/12,
ops/backup and ops/restore. Keep real sources, email, backup execution and production
gates disabled until their specific approvals and commissioning checks are complete.
