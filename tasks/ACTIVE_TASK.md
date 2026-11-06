# Current task: 022b | Isolated PostgreSQL reference-load measurements

Owner requested continuation on 2026-11-06; local preparation remains authorized.
Baseline a7b7f56. Task 022a proof is in TASK022A_REPORT.md.
Read: AGENTS.md, docs/00, docs/12-17 and docs/20. Do not deploy to a host.

Bounded slice: opt-in PostgreSQL-only synthetic test database, 10k IP assets + 20k
other assets + 1m installations; four concurrent loopback HTTP clients, five common
search shapes with 40 samples each, exact count/site-scope checks and per-shape p95.
Assess 10k assets against a cached verified synthetic support date and verify results.
No new dependencies, application changes, public listeners, live calls or migrations.

Acceptance: exact fixture counts, search p95 <2s per shape, assessment <900s;
raw timings/sample counts and environment recorded without credentials; failures or
DB teardown errors cannot produce a passed report. Remote/SQLite collection refused.
Status: harness implemented; two local refusal checks and Ruff passed. PostgreSQL
measurements pending CI (no local Docker/PostgreSQL). See ops/load/README.md.
Next: verify measured CI evidence and close this slice; then Task 022c security gate
review. Task 022 overall remains open for security/UAT/recovery/AlmaLinux gates.
