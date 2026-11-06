# Current task: 022d | Connector DNS connection-target hardening

Owner requested continuation on 2026-11-06. Baseline 678a20b; approved UI/category
refinement remains complete (CATEGORY_UI_OUTCOME.md). Address G01 in TASK022C_REPORT.md.
Read: AGENTS.md, docs/00, docs/05, docs/14, docs/15 and docs/17. No live calls/deployment.

Bounded slice: shared direct HTTPS transport resolves/revalidates all DNS answers per
request and connects only to validated literal IPs while retaining original Host/SNI
and certificate verification. Use it for inventory GETs and fixed Entra token exchange;
ignore ambient proxy/CA overrides, preserve explicit private CAs and existing fixture
transports. Block metadata/mixed/empty answers; retain API paths, retries and live gates.

Acceptance: rebinding/retry/continuation/IPv6/origin/failover/proxy regression tests;
real loopback TLS success with private CA and original SNI, wrong-host/untrusted-cert
refusal even with verify=False; nearest connector suite, Ruff and PostgreSQL CI green.
Status: implemented; 235 connector tests passed locally, then all 21 final transport
regressions passed (including real loopback TLS and IPv6). Ruff lint/format passed.
Await PostgreSQL CI evidence; see TASK022D_REPORT.md.
No new dependencies, schemas, UI or live-source approvals. Task 022/G6 remains open.
Next after this slice: 022e browser CSP hardening (G03); supply-chain scans, MFA and
commissioning remain separate open gates. AlmaLinux choice is accepted (DEC-01).
