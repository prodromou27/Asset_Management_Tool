# Task 022e - enforced browser CSP

Requirement: docs/14 browser-content controls, G03 in TASK022C_REPORT.md. Owner
requested continuation on 2026-11-06; baseline 0b58c3e. No host deployment/live calls.

Root cause: frontend and proxy configurations set framing/nosniff/referrer headers
but supplied no CSP. The canonical `frontend/content-security-policy.conf` is now
copied into the frontend image and mounted read-only into the reverse proxy. Both
HTTP install and HTTPS configurations include it, including the HTTP-to-HTTPS
redirect server. `always` covers errors; proxy suppression prevents duplicate or
unexpected upstream CSP policies. Application authorization and TLS remain separate.

Default deny; scripts, API connections, fonts, forms and frames are self-only. Inline
scripts/handlers/eval, objects, embedding, base changes and workers are denied.
Inline CSS is explicitly retained for React layout values and sandboxed email HTML;
image data URLs remain allowed. There are no external/CDN exceptions, reporting
service, new dependency, nonce service or runtime switch. This policy is defense in
depth, not proof of complete XSS protection. See ASM-67 for design references.

`pnpm build` then `pnpm review:csp` serves the production bundle under the exact
canonical header, reusing the existing synthetic UI workflow and adding denial
probes. Ordinary desktop/mobile, light/dark, navigation/filter/dialog/error flows
must generate zero CSP violations. Email preview text and computed style are checked
inside the unchanged sandbox. Injection flags stay unset for inline script, handlers
and eval; browser policy events verify external script/connect, base and object
denial. A separate framing page observes frame-ancestors rejection. All external
probe URLs use `.invalid` and fixture routing also blocks external requests.

Local proof: **217 frontend tests passed**, lint/typecheck/build passed, **3 CSP config
tests passed**, Ruff/config format and workflow YAML checks passed. The production
browser review passed with **116 screenshots**, no ordinary CSP violations, no page
errors or unmapped fixture responses, and all denial probes passed (Edge). Existing
Vite chunk-size advisory remains. Local Docker is unavailable; runtime Nginx proof
and Chromium behavior run in CI. These are not silently treated as local evidence.

CI adds the CSP production-build browser review to the existing pilot job and retains
its report/screenshots for seven days. After production image builds, an internal-only
Docker fixture checks **19 Nginx responses**: direct frontend/SPA, HTTP/HTTPS proxy,
API 200/401/403/404/500, generated 502 and the HTTPS redirect. It requires exactly
one canonical enforced CSP even when the upstream supplies a permissive policy.
Fixture certificate trust/hostname checking remains enabled. No published ports,
real accounts, Django database or SMTP/vendor calls are used. Task-owned containers,
network and temporary image tags are cleaned up. Commands/limits: ops/csp/README.md.

Files: canonical policy, frontend Docker/Nginx and proxy configs/mount, UI review mode
and verification helper, package script, configuration tests, ops/csp fixture/runbook,
CI steps, docs/15, ASM-67 and task handoff. No UI source, API or schema changes.
Policy commit: `90b425b`; final browser helper correction: `79376d9`.
The first CI run passed 851 backend tests and all 19 Nginx checks but caught a
Playwright timeout trying to stabilize/scroll text inside the sandboxed iframe.
The content/style assertions had already passed. The fixture now scrolls the outer
iframe in the parent document, keeping all preview and CSP assertions intact.

Final CI evidence: [run 42282210154](https://github.com/prodromou27/Asset_Management_Tool/actions/runs/42282210154).
The Chromium review passed with 116 production-build captures, zero ordinary CSP
violations and every denial probe. All jobs are green: 851 PostgreSQL/Redis backend
tests, 217 frontend tests, real API/browser pilot, reference load, production builds,
all 19 Nginx response checks and isolated synthetic recovery. G03's source/regression
gap is addressed; this does not close the remaining security or commissioning gates.

Limits: Chromium-family browser proof and the current source configuration; no full
cross-browser/a11y audit, live-host security sign-off or dependency/image vulnerability
scan. Inline styles are a deliberate remaining allowance. G02 supply-chain, G04 MFA,
G05 commissioning and G6 remain open. Next slice: 022f dependency/image scan evidence.
