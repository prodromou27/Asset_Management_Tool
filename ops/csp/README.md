# Browser CSP rehearsal

`frontend/content-security-policy.conf` is the single enforced policy. The frontend
image copies it; the production reverse proxy mounts it read-only in both HTTP install
and HTTPS modes. `always` covers error/redirect responses. The proxy hides an upstream
CSP before emitting its own, avoiding accidental policy intersections or duplication.

The default is deny. Scripts, connections, fonts and forms use the app origin only;
inline script/event handlers, eval, objects, base overrides, workers and embedding
are blocked. Images may also use data URLs. Same-origin frames retain the existing
sandboxed `srcdoc` email preview. Inline CSS remains allowed for React layout values
and email HTML styles; this is an explicit compatibility limit, not script permission.
No broad external/CDN hosts, reporting service, dependency or runtime toggle is added.

Local browser proof (backend/vendor/SMTP responses are synthetic; loopback only):

```powershell
cd frontend
pnpm.cmd build
pnpm.cmd review:csp
```

Use `pnpm` on Linux. The existing development-only `pnpm review:ui` remains available.
The CSP command serves `dist` through Vite preview with the exact canonical response
header; Vite's development HMR is not subject to the production policy. It runs the
existing desktop/mobile/light/dark workflow review, checks styled sandboxed email,
then adds script/handler/eval/connection/base/object/framing denial probes. A browser
violation during ordinary UI flows fails. Probes use `.invalid` URLs and external
requests are also blocked by fixture routing; no external endpoint is contacted.

Evidence: ignored `frontend/test-results/csp-review/results.json` and screenshots,
retained by CI for seven days. Chromium in CI, Edge locally. This is Chromium-family
coverage, not a complete cross-browser accessibility or XSS audit.

Actual Nginx proof in Linux CI, after the standard production image builds:

```bash
bash ops/csp/check_nginx.sh
```

This reuses cached production builds and a generated one-day fixture certificate.
The production frontend image supplies the Nginx runtime for frontend and proxy
configuration checks; the backend image runs a stdlib synthetic upstream/client.
No Django services, real data or production secrets are loaded. Containers share a
new internal-only Docker network, publish no ports, use read-only roots and resource
limits, and are removed by task-owned names on exit. No Docker socket enters them.
The fixture checks 19 responses across static assets/SPA paths, API 200/401/403/404/500,
a Nginx-generated 502 and the HTTPS redirect. It asserts exactly one canonical CSP,
including when the synthetic upstream tries to supply a permissive header. HTTPS
uses certificate/hostname verification against the generated fixture trust anchor.

Rollout uses the normal approved deployment process: rebuild frontend, keep the
canonical file with Compose manifests, recreate frontend/proxy, then inspect headers
and browser console on the approved host. No deployment is performed by this harness.
CSP is defense in depth; authentication/RBAC/CSRF/escaping remain required. G6,
dependency/image scans, MFA and live commissioning remain separate gates.
