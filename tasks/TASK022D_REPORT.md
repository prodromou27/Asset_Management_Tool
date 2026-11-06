# Task 022d - connector DNS connection-target hardening

Requirement: docs/14 SSRF DNS pin/revalidation and TLS hostname validation; closes the
source gap G01 from TASK022C_REPORT.md. Baseline 678a20b, owner continuation 2026-11-06.
No live service, credential, network scan or host deployment was used.

Root cause: `ReadOnlyClient` checked DNS before creating HTTPX, but HTTPX separately
resolved the hostname for the actual connection. Its request/retry/continuation path
did not bind the validated address to the socket. Entra's fixed token endpoint also
used an independent HTTPX client with ambient environment defaults.

The shared `PinnedTransport` uses HTTPX's public BaseTransport/HTTPTransport API.
It validates every DNS answer at construction and again per request, rejects changed
origins and mixed/empty/unsafe answers, and passes only validated literal IPv4/IPv6
addresses to the network transport. Original Host and HTTPCore's documented
`sni_hostname` extension preserve routing and certificate hostname checks. All answers
must pass before credentials can reach the underlying transport. No global resolver
patch, private HTTPX implementation API, dependency or schema migration is introduced.

Connection establishment may fail over to another address from the same validated
answer set. Read/write failures are not replayed by the transport. Existing outer
retry/continuation behavior re-enters validation. Private inventory addresses remain
allowed; loopback/link-local/multicast/unspecified/reserved addresses and the explicit
metadata targets 100.100.100.200/fd00:ec2::254 are refused. Empty answers now fail closed.

Inventory clients and fixed Entra token exchange both use this transport by default;
inventory API operations remain GET-only and Entra keeps its existing token POST.
Deployment/per-instance approval gates, instance CA references and injected fixture
transports remain intact. Ambient proxy/CA variables are ignored at both HTTPX layers.
Default trust cannot be disabled; a private CA uses an explicit SSL context/file.
Deployments need direct approved-host HTTPS egress; proxy support requires a separate
reviewed design rather than an implicit environment override (ASM-66).

Regression proof uses mocked wire/resolver fixtures and a temporary loopback HTTPS
server with a generated test-only trust anchor. The socket fixture asserts the
production transport receives the validated private IP, then connects solely to the
test server on 127.0.0.1. Real TLS confirms the original SNI/Host, accepts the explicit
CA, rejects a mismatched hostname and rejects an untrusted certificate even with
`verify=False`. Other cases cover rebinding, mixed DNS, metadata, empty answers, IPv6,
retry, continuation, origin/port/userinfo changes, connection failover without read
replay, and inventory/OAuth proxy/CA environment isolation. No external DNS/server
is required for these regressions.

Local checks: **235 connector tests passed** in 56.41 s before the additional IPv6
case; the final **21 transport cases passed** in 4.02 s. Backend Ruff lint and format
passed; `git diff --check` passed. Tests use the SQLite functional fallback locally;
PostgreSQL/Redis and the full application gates run in CI. No frontend change.

Files: `adapters/base.py`, `http.py`, `entra.py`, new `transport.py`,
`tests/test_transport.py` under `backend/apps/integrations/`; docs/05, ASM-66,
ACTIVE_TASK and this report. CI evidence is recorded after verification.

API references: [HTTPX transports](https://www.python-httpx.org/advanced/transports/),
[HTTPCore SNI extension](https://www.encode.io/httpcore/extensions/),
[HTTPX environment variables](https://www.python-httpx.org/environment_variables/).

Limits: this is connection-target regression proof, not a complete SSRF/egress audit,
live source interoperability check or network firewall policy. Approved-host outbound
connectivity/CA/DNS behavior still needs commissioning; live access remains gated.
G02 supply-chain scans, G03 CSP, G04 MFA and G05 commissioning remain open.
Next bounded slice: Task 022e browser CSP hardening; Task 022/G6 is not complete.
