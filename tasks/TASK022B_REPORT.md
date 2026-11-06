# Task 022b - synthetic PostgreSQL reference-load baseline

Requirements: docs/14 common paginated asset search p95 <2 s and 10k cached-date
lifecycle assessments within 900 s; docs/15 reference scale. Owner continued the
local pilot on 2026-11-06. Baseline a7b7f56. Task 022 and G6 remain open.

`ops/load/run_reference.py` runs an explicitly opted-in pytest-django disposable
PostgreSQL test database. Both direct collection and the launcher reject SQLite
and remote hosts. The fixture checks `test_` name and empty assets/users, preserves
append-only database protections and drops the entire database at session teardown.
No production code, dependencies, migrations or UI were changed.

The fixed workload seeds 10k IP-connected laptop facts, 20k monitors without IPs and
1m active software installations. Four HTTP clients use a scoped test session with
normal application timeout metadata; requests exercise auth/RBAC and real loopback
Django HTTP. Five query shapes check exact counts and excluded-site row absence.
Each shape has 40 measured samples, plus four excluded warm-up requests, using
nearest-rank p95. The lifecycle run verifies all 10k hardware assessments against
the exact synthetic product, verified cached support date and EOL announced status.

The ignored JSON report contains raw samples, counts, environment/version metadata,
seed time, per-shape p95 and lifecycle time. Previous success is cleared on launch;
pytest failure, missing evidence or teardown error fails the final report. CI retains
the report for seven days. See `ops/load/README.md` for reproducible commands.

Local verification: two subprocess refusal checks passed in 5.24 s; Ruff lint and
format passed; workflow YAML parsed successfully; `git diff --check` passed.
All 44 existing lifecycle engine checks also passed locally. There is no local
Docker/PostgreSQL; the real workload ran in CI.

Measured CI evidence: [run 42210778953](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42210778953),
commit `b488ac8`. The two database refusal checks passed; the full workload passed
in **158.84 s**, including teardown. The `synthetic-reference-load` artifact retains
the complete JSON report for seven days (artifact ID 13497979855).

| Query shape | Samples | p95 (seconds) | Target |
|---|---:|---:|---:|
| First page | 40 | 0.134 | <2 |
| Name search | 40 | 0.244 | <2 |
| Serial search | 40 | 0.251 | <2 |
| Hostname search | 40 | 0.251 | <2 |
| Category filter | 40 | 0.132 | <2 |

The 10k exact-product hardware assessments completed in **39.617 s** (target <900 s).
All expected product/date/EOL announced results, exact fixture and scoped row counts,
and database teardown checks passed. No application optimization was needed for this
profile. The initial harness corrections supplied required account/session metadata
and aligned the expected future-date status with existing lifecycle rules; they did
not alter product behavior or relax performance thresholds.

All jobs in the same CI run passed: backend PostgreSQL/Redis, frontend checks,
real browser/API pilot, reference load, production image/Compose and isolated
synthetic recovery gates. Full Task 022 production commissioning remains open.

Limits: Ubuntu shared-runner hardware, Django test HTTP without production proxy/TLS,
one million active installations without removal histories, and one initial lifecycle
run. This establishes neither historical growth capacity nor production AlmaLinux,
gunicorn, worker/broker, live connector/SMTP or off-host recovery commissioning.

Next bounded slice: Task 022c security gate evidence review. Keep approved-host load,
UAT and recovery commissioning separate; do not claim Task 022/G6 complete.
