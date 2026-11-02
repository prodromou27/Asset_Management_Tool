# 04 | Application API Contract

API prefix /api/v1. JSON, UTC RFC3339 timestamps, UUID IDs, stable pagination (cursor for high-volume records), filtering/sorting allowlists, idempotency keys for mutations/jobs and correlation IDs. Generate and publish OpenAPI; generate frontend types from it. Avoid ad hoc frontend fetch definitions.

## Generic response behavior

- GET collections return items, next_cursor, count where affordable, and applied_filters.
- Mutations return resource ID, version, modified_at. PATCH requires If-Match/current version to prevent lost updates.
- Failures return stable machine code plus human message and optional field errors; never include credentials or upstream raw secrets.
- HTTP 401 unauthenticated, 403 out of scope, 404 unavailable/not visible, 409 conflicts, 422 invalid input, 429 too many requests, 503 temporary connector unavailable.

Example failure contract:

~~~json
{
  "error": {
    "code": "IDENTITY_CONFLICT",
    "message": "More than one asset matches this observation.",
    "request_id": "illustrative-id",
    "field_errors": {}
  }
}
~~~

## Routes (initial specification)

| Area | Endpoints | Purpose |
|---|---|---|
| Auth | GET /auth/me, POST /auth/logout, POST /auth/local/login, POST /auth/local/mfa, GET /auth/providers | Session and provider state; use OIDC callback with provider library |
| Users | GET/POST /users, GET/PATCH /users/{id}, POST /users/{id}/disable, GET /roles, GET /permissions | Admin-only identity and RBAC |
| Scopes | GET/POST /sites, GET/POST /locations, GET/POST /departments | Administrative ownership hierarchy |
| Assets | GET/POST /assets, GET/PATCH /assets/{id}, GET /assets/{id}/history, GET /assets/{id}/observations | Asset CRUD and field provenance |
| Asset details | GET /assets/{id}/interfaces, /software, /relationships, /certificates, /lifecycle | Typed related records |
| Categories | GET/POST /asset-categories, PATCH /asset-categories/{id}, POST /assets/{id}/classification | Category templates and manual reclassification |
| Groups | GET/POST /groups, PATCH /groups/{id}, POST /groups/{id}/preview, GET /groups/{id}/assets, POST /groups/{id}/members | Static/dynamic membership; preview before change |
| Discovery | GET /discovery/sources, GET /discovery/coverage, GET /discovery/candidates, GET /network/hosts/lookup | LibreNMS-derived network evidence and unmanaged queue |
| Reconciliation | GET /reconciliation/candidates, POST /reconciliation/{id}/approve, /reject, /hold | Human decision and reversible link |
| EOL | GET /lifecycle/findings, /products, /sources, POST /lifecycle/matches/{id}/approve, POST /lifecycle/exceptions | Versioned support milestones and assessments |
| Software/licenses | GET /software/products, /software/installations, /licenses/products, /licenses/entitlements, /licenses/subscriptions, /licenses/allocations | Separate installs, subscriptions and entitlements |
| Domain/TLS | GET/POST /domains, GET /certificates, GET /certificates/deployments, POST /tls-endpoints | Owned domains and approved endpoint checks |
| Integrations | GET /integration-catalogue, GET/POST /integrations, GET/PATCH /integrations/{id}, POST /integrations/{id}/test, /sync, GET /integrations/{id}/runs | Wizard, readiness, health and jobs |
| Import/export | GET /imports/templates, POST /imports, GET /imports/{id}/preview, POST /imports/{id}/commit, GET /imports/{id}/errors, POST /exports, GET /exports/{id} | Async data portability |
| Admin settings | GET/PATCH /settings/{area}, POST /smtp/test, GET /notifications/rules, GET /jobs, POST /backups/verify, GET /backups/status | Strictly role-protected controls |
| Reporting | GET /reports/inventory, /reports/eol, /reports/licenses, /reports/coverage, POST /reports/export | Filtered summaries and job-backed output |
| Health | GET /health/live, GET /health/ready, GET /health/dependencies | Ready includes DB/queue and last-known integration health, but avoid making all vendor APIs readiness dependencies |

## Example asset payload

~~~json
{
  "id": "8f37192d-7e99-4c83-8b28-56c4120bc2f4",
  "asset_tag": "IT-001254",
  "category": {"id": "network-switch", "label": "Networking / Switch"},
  "hostname": "sw-core-01",
  "manufacturer": "Cisco",
  "model": "C9300-48T-A",
  "serial": null,
  "site": "HQ",
  "business_status": "Deployed",
  "observation_status": "Recently Seen",
  "support_status": "Unknown",
  "interfaces": [
    {"mac": "02:00:00:00:00:01", "addresses": ["10.10.0.2"]}
  ],
  "sources": [{"system": "librenms", "external_id": "317", "observed_at": "2026-11-02T12:00:00Z"}],
  "version": 7
}
~~~

Example is fictitious; never seed production with fabricated EOL/serial evidence.

## Authorization and auditing

Authenticate on every request. Enforce object/site/field permission in queryset/service layer and export jobs, not only React. Service tokens are hashed, scope-limited, rotated and auditable. Every manual merge, category change, group rule, EOL exception, export, import, SMTP or backup configuration change emits an audit record. Use explicit approval for high-impact bulk writes.

## Idempotency and compatibility

- X-Idempotency-Key on POST jobs/import commits; duplicate request returns original job result.
- External resource ID is (integration instance, external ID), not just hostname.
- Never silently change the shape of published v1 fields; migrations and OpenAPI contract tests are mandatory.
- Background job created returns 202 with job ID; progress via GET. No synchronous 1m-row export or full sync requests.
