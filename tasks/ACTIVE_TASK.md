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
Status: complete. All jobs passed on PostgreSQL CI run 42210778953 for b488ac8.
Search p95 0.132-0.251s per shape; 10k lifecycle assessments in 39.617s. Two local
refusal checks, 44 lifecycle engine checks and Ruff passed. TASK022B_REPORT.md records
evidence and limits. Backend/frontend, real browser, Compose and isolated restore
gates also passed.
Next: Task 022c security gate
review. Task 022 overall remains open for security/UAT/recovery/AlmaLinux gates.
