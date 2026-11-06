# Task 022a — local pilot preparation

Owner requested continuation and chose local preparation before any AlmaLinux host
work. Baseline: 4a6e64d. This is one bounded phase of Task 022; G6 sign-off remains open.

The old browser smoke test assumed an authenticated session and did not exercise the
application API. `pnpm e2e` now orchestrates pytest-django's isolated test database,
real loopback Django HTTP, Vite and Playwright using existing dependencies. Test
settings are mandatory, PostgreSQL hosts must be loopback, remote API targets are
refused, browser requests stay on the UI origin and port conflicts fail. Synthetic
account passwords are generated per run and delivered over stdin, with redacted
failures. No production database, credential file, trace, SMTP or live connector call.

The 14 browser scenarios cover anonymous/CSRF refusal, real login with an HTTP-only
session, scoped inventory and category descendants, cross-site GET/PATCH refusal,
user-admin permission refusal, group member scope, form registration of a non-network
monitor, Unknown lifecycle, real UI JSON export and authenticated scoped download,
and administrator disablement revoking an open browser session. Backend assertions
then verify audit events, unchanged hidden assets, encrypted file/count, inactive
account and an empty mail outbox. Those assertions promote the report from
`browser_passed` to `database_passed`; only successful pytest teardown finalizes
`passed`. Successful evidence is cleared before a fresh run.

Local final proof: **4 pytest checks passed** (one 14-scenario browser/database
rehearsal, two API-target guards, one remote-DB collection guard), in **39.03 s**.
Engine: SQLite test-memory fallback, transport: loopback HTTP, tasks: eager. Ruff
lint/format, frontend lint/typecheck and production build passed. Existing Vite
chunk-size advisory remains. The two authenticated synthetic screenshots were
produced; desktop inventory was visually inspected with the real seeded category tree.
No application UI/API/schema code changed; the existing 214 frontend and 827 backend
tests remain normal CI gates. A new independent PostgreSQL/Chromium CI job runs the
rehearsal and preserves report/screenshots for seven days.

CI proof: [run 42114558567](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42114558567)
passed for commit `38e7343`. PostgreSQL/Chromium pilot: **4 checks passed in 19.60 s**,
including all 14 browser scenarios and successful teardown. The existing **827 backend**
and **214 frontend** tests passed, together with lint/type/build and Compose gates.

Files: `frontend/e2e/pilot.mjs`, `frontend/scripts/run-pilot.mjs`, package E2E command,
`ops/pilot/` harness/runbook, CI workflow, README, docs/12/15 and ASM-63. The obsolete
unauthenticated smoke/config are removed. Existing visual fixtures remain available
through `pnpm review:ui`; they do not substitute for this real-backend rehearsal.

See `ops/pilot/README.md` for commands, evidence matrix and remaining approvals.
No Docker/AlmaLinux host is available locally. SQLite results do not prove PostgreSQL
performance, production TLS, real broker/worker/scheduler operation, live source/SMTP
delivery, supply-chain/image safety or approved off-host recovery. The CI restore is
synthetic evidence; target-host UAT and commissioning remain separate operator gates.

Next: **Task 022b — isolated PostgreSQL reference-load measurements** (30k assets,
1m installations, concurrent p95 and lifecycle timing), with reproducible workload and
sample counts. Keep live/production gates off; do not claim the full Task 022 is done.

Initial PostgreSQL CI ran all four checks successfully but failed during Django's
per-test flush: observation immutability correctly rejected TRUNCATE. The harness
now owns an autocommit test database for the whole rehearsal and lets session
teardown drop it, with keep/reuse disabled. No application triggers are disabled.
