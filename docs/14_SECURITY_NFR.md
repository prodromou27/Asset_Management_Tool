# 14 | Security and Nonfunctional Requirements

This is a cybersecurity-sensitive inventory system containing network topology, asset vulnerabilities implied by EOL status, software lists and identities. Assume attackers could abuse its connectors and exports. All checks are release gates.

## Threat model and controls

| Risk | Control |
|---|---|
| Unauthorized asset access | Session/OIDC auth, object/site/field RBAC, no user-controlled query bypass, audit |
| Credential leakage | Secret manager/secret files, no token display/log, scoped identities and rotation |
| SSRF via vendor connector or TLS check | Approved endpoint allowlist, DNS pin/revalidation, block metadata/internal targets unless explicitly registered, no redirects |
| Arbitrary network scanning | V1 no scanner; API-only LibreNMS. Future scanner requires scoped approval and local enforcement |
| Untrusted file upload | Size/type/schema validation, archive bombs prevention, isolated parsing, import job quotas |
| CSV/Excel formula injection | Escape cells beginning with formula operators before export and import preview |
| XSS/content injection | Framework autoescaping, CSP, sanitize rich text, no untrusted HTML in tooltips |
| SQL injection | ORM/parameterized queries; validated filter AST, no raw SQL from user |
| Privilege escalation | Role checks in backend, permission tests for sensitive APIs, no UI-only gating |
| Supply-chain issues | Pinned dependencies/images, lockfile audit, CI scanning, reviewed upgrades |
| Data exfiltration | Export audit, field filtering, short-lived private URLs, encryption and download expiry |
| Missing backups | Verified encrypted off-host backup and restore drill |
| Data poisoning from discovery | Source provenance, immutable observations, confidence threshold, human review for conflicting strong IDs |
| EOL false claims | Vendor source verification, exact model/release match, Unknown/unverified states |

## Transport and host

TLS 1.2+ minimum subject to approved security policy, valid CA chain, strict TLS hostname validation. Proxy sanitizes forwarded headers; Django ALLOWED_HOSTS, secure cookies, CSRF trusted origins and deploy checklist enforced. AlmaLinux firewalld and SELinux Enforcing remain on. PostgreSQL/Redis not externally published. No root/privileged containers or Docker socket exposed to web app. Outbound HTTPS to configured API hosts only where feasible.

## Secrets and privacy

No plaintext secrets in repo, .env committed, attachments, logs, Docker images, job payloads or HTTP responses. Secret refs and reveal-once service tokens. Separate export permission for personal data (assigned users, device names) from technical inventory access. Retention must be admin-configurable and reviewed under applicable organizational privacy policy. Avoid retaining full Defender raw responses longer than operationally necessary.

## Audit and logging

Audit actions: login/session changes, user/group/role edits, asset changes, reconciliation, category override, lifecycle evidence/exception, integration/token settings, imports, exports, SMTP configuration, backup verification and restore authorization. Store UTC timestamp, actor/service, object key, old/new redacted values, request/correlation ID and source.

Structured application logs with redaction, no bearer token, credential, full e-mail body or private key. Alert on failed backup, sync stale, notification queue backlog, high export volume and unusual admin actions. Metrics for API p95, queue latency, DB size, job failures, source freshness and mail delivery rate.

## Initial measurable targets (validate under load)

| Measure | Target |
|---|---|
| Active IP-connected devices | >=10,000 |
| Other physical/logical records | >=20,000 |
| Software installations | >=1,000,000 |
| Common paginated asset search | p95 <2s at defined reference load |
| Lifecycle assessment | 10,000 assets within 15 minutes using cached source dates |
| Duplicate prevention | No known false auto-merges in curated pilot |
| API recovery | Partial/throttled source sync resumes without duplicate canonical assets |
| Backup | RPO <=24h, RTO <=4h as initial goals subject to approved drill |
| Mail | Delivery retries and dedup; failures visible without blocking asset writes |
| Uptime | Single-node best-effort until separate HA architecture approved; no fabricated 99.99% SLA |

## Security test checklist

- Cross-site access denied in GET, PATCH, bulk import, group dynamic query and export.
- CSRF/XSS/injection testing, IDOR on attachments, rate limits and token expiry.
- Connector base-URL allowlisting, redirect/SSRF/metadata service avoidance.
- File upload zip/CSV/formula edge cases and database query budget tests.
- Docker image and dependency vulnerability checks, no secrets in image layers.
- Restore using encrypted off-host backup and isolated credentials.
- Review all default configs under DEBUG off, TLS on and secure cookies.

## Non-goals

Do not embed a penetration-test tool, credential harvester, VPN management or password vault in this ITAM. Security scanning of endpoints is an external integration concern.
