# Synthetic PostgreSQL reference load

Task 022b measures docs/14's search p95 <2 s and 10k lifecycle assessments <900 s.
Use an otherwise disposable, loopback PostgreSQL 16 service with permission to
create/drop test databases. No application or production database is seeded.
Prepare the existing backend venv (`uv sync --frozen --group dev` in `backend`).
Set existing `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
through your test environment; never put real credentials in command arguments.
Unset `ITAM_TEST_DB_SQLITE`; set `POSTGRES_HOST=localhost`. From the repository root:

```powershell
$env:POSTGRES_HOST = 'localhost'
backend/.venv/Scripts/python.exe ops/load/run_reference.py
```

```bash
POSTGRES_HOST=localhost backend/.venv/bin/python ops/load/run_reference.py
```

The launcher selects test settings and explicit opt-in. Direct pytest collection also
rejects SQLite, remote databases and missing opt-in before connecting. The test checks
the generated `test_` database name and empty assets/users before inserting fixtures.
It does not retain/reuse the test database: session teardown drops it without weakening
immutable-table protections. Run only this workload in that test database.

Fixture: 10k laptops with IP/hostname facts, 20k monitors without IPs, 100 software
versions on every laptop (1m installations). Every tenth asset belongs to an excluded
site. Four authenticated HTTP clients share a scoped user's session, exercise five
search shapes in rotating order and verify exact counts and absence of excluded rows.
Each client excludes one warm-up per shape; each shape records 40 measured samples
(200 requests total). p95 uses nearest rank, independently per shape; timeouts/errors,
scope violations or thresholds fail the job. Raw durations and sample counts remain
in the report; one slow shape cannot be hidden by pooling all requests.

After search, 10k laptop assessments use a synthetic exact hardware match and a verified
cached future support date. Every resulting hardware assessment must have that product,
date and EOL announced status. This is one measured initial assessment run, including writes,
not a percentile estimate. No vendor requests, mail, workers or network scanning occur.
The IPs are stored synthetic facts, never contacted. Installation data has no prior
removal history; the assessment itself creates history. Historical growth is a separate
capacity dimension and is not established by this fixture.

`results/report.json` is ignored by git and retained by CI for seven days. The launcher
clears previous evidence, preserves measured failures and marks `passed` only after
pytest succeeds including teardown. Missing evidence fails. Hardware/OS, Python,
PostgreSQL version, counts, seed time and raw timings are recorded without session data.

CI uses PostgreSQL 16 on Ubuntu and Django's loopback test HTTP server, test authentication
hashing and no TLS/proxy. Results establish a synthetic baseline, not production capacity
or AlmaLinux sign-off. Repeat on the approved host with comparable resources, then test
production gunicorn/proxy/TLS and workers separately. Live configuration and G6 approvals
remain outstanding. Local SQLite refusal checks are guard proof only.
