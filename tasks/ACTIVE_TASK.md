# Current task: 022e | Enforced browser CSP and response proof

Owner requested next tasks on 2026-11-06. Baseline 0b58c3e; Task 022d is complete
(TASK022D_REPORT.md). Address G03 from TASK022C_REPORT.md; preserve approved UI.
Read: AGENTS.md, docs/00, docs/12, docs/14, docs/15 and docs/17. No host deployment.

Bounded slice: one canonical enforced CSP for frontend and HTTP/HTTPS proxy modes,
always emitted on response errors/redirects with upstream CSP suppressed. Scripts and
connections stay self-only; inline CSS and sandboxed email preview remain compatible.
Add production-build browser denial/compatibility probes and real isolated Nginx
response checks. No application behavior, dependencies, APIs or deployment approvals.

Acceptance: zero CSP violations during normal desktop/mobile/theme flows; styled
sandboxed email preview works; script/handler/eval/connection/base/object/framing
probes blocked; exactly one canonical CSP on 19 real Nginx responses (including API
401/403/404/500, generated 502 and HTTPS redirect). Config tests/Ruff/frontend/CI green.
Status: complete. CI run 42282210154 passed for 79376d9: 851 backend tests,
217 frontend tests, real API pilot, 116 production CSP browser captures with zero
ordinary violations/all denial probes passing, all 19 real Nginx response checks,
reference load and isolated restore. Local checks also passed. See TASK022E_REPORT.md
and ops/csp/README.md. G03 is addressed; Task 022/G6 and commissioning remain open.
Next bounded slice: 022f dependency/image vulnerability evidence (G02); MFA and
commissioning remain separate open gates.
