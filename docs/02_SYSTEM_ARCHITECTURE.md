# 02 | Technical Architecture

## Decisions

- Backend: Python/Django + Django REST Framework, modular monolith, versioned REST/OpenAPI.
- Frontend: React + TypeScript, Vite, typed client generated from OpenAPI.
- Storage: PostgreSQL, JSONB only for raw vendor payloads and truly flexible values. Typed relational tables for canonical identity.
- Background: Celery + Redis (separate worker, beat/scheduler, retry/checkpoint).
- Reverse proxy: Nginx container, HTTPS, secure headers, forwarded-proto checks.
- Auth: OIDC/Entra preferred if granted; secure local break-glass; RBAC in backend.
- Docker Compose v2 on AlmaLinux, no Kubernetes/microservices for V1.
- S3-compatible or local persistent object storage for attachments/evidence/exports. Use pluggable storage interface.

## Runtime services

~~~text
Administrator Browser
       |
 HTTPS reverse proxy (443)
       |                         on-prem LibreNMS / Endpoint Central
       +-- React static UI                ^  HTTPS, read-only
       +-- Django API ---- Job Queue -----+
             |               |            +-- Microsoft Graph / Defender APIs
             |          Celery Worker      +-- Vendor lifecycle sources
             |               |
          PostgreSQL      Celery Beat
             |               |
         Audit + DB       SMTP relay / file evidence storage
~~~

Note: the above describes software relationships, not a network topology. No separate network scanning container is deployed in V1.

## Backend modules

django apps: accounts, organizations (single-org with sites), assets, catalogs, observations, reconciliation, groups, lifecycles, software, licenses, domains, certificates, integrations, network, documents, imports, exports, notifications, settings, audit, health.

Boundaries:
- Connectors translate external API records into normalized immutable observations, never direct asset updates.
- Reconciliation owns candidate matching and source links; category service owns classification.
- EOL engine reads approved model/release matches + evidence, not raw hostnames.
- Notification outbox handles dedup/retries; no SMTP network call inside a DB transaction or HTTP handler.
- All heavy imports, exports, syncs and EOL recomputation run in worker jobs.

## Integration contract

Each connector implements: capabilities, validate_config, test_connection, fetch_full_or_incremental, normalize, checkpoints, health and errors. Inputs are from allowlisted endpoints; credentials referenced through secrets, not plaintext JSON in DB. Source states: planned, available, configured, degraded, disconnected.

## Job semantics

Persist job ID, type, source/actor, version, cursor, start/end, counters, exception type and retry state. Jobs are idempotent and cancelable. Failure of one connector must not stall other sources. API requests and sync jobs are rate-limited; use Retry-After when supplied and exponential backoff with jitter.

## Config patterns

- Typed settings with environment overrides for infrastructure; business settings controlled through versioned admin API.
- All UTC instants in DB, Asia/Nicosia for display (admin-selectable).
- Feature flags: all V1 features enabled only after migration and health; planned connectors visible but not actionable.
- Migrations run as a separate one-off pre-deployment step, not by every replica at application startup.

## Environments

Local: Docker Compose, synthetic fixtures, mock API servers and local SMTP capture.
Staging: AlmaLinux host, realistic volumes, valid TLS, integration test tokens/scopes, test mailbox, restore exercises.
Production: approved host/FQDN/cert, actual integrations, backup target, two admins, monitoring, documented operator runbook.

## Versioning

Use supported releases pinned by lockfiles/container digest at implementation time and record versions in the deployment manifest. Do not choose an outdated or hypothetical major version from this spec. API version starts /api/v1; schema migrations are backward-compatible where possible; document breaking changes.
