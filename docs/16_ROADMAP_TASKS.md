# 16 | Phases, Dependencies and Implementation Sequence

Estimated team-scale roadmap: **36–40 weeks** for two experienced developers plus part-time security/QA/infrastructure. A solo coding agent can assist implementation but must not interpret this as a guaranteed calendar. Design/acceptance are fixed; adjust schedule after first vertical slice.

| Phase | Indicative weeks | Deliverable and exit gate |
|---|---|---|
| 0 Discovery and decisions | 1–2 | AlmaLinux 10.2 GA baseline validated for Docker on staging (and current GA rechecked), FQDN, ID provider, source API access, sample data, SMTP/backup ownership documented |
| 1 Platform core | 3–6 | Repo, Compose local stack, API/React skeleton, DB/Redis/Celery, lint/CI, auth/RBAC/audit/health |
| 2 Asset register and groups | 7–13 | Categories, CRUD, relationships, observations, static/dynamic groups, import dry-run, asset table UI |
| 3 API integrations | 14–21 | Endpoint Central, Intune/Defender, Entra/M365, integration catalogue, source ID matching |
| 4 LibreNMS discovery | 22–25 | LibreNMS device/port/IP/FDB/inventory sync, reconciliation, coverage and source freshness |
| 5 Lifecycle/licenses/domain/TLS | 26–31 | Evidence-backed EOL, independent OS/firmware, subscriptions, domain/cert expiry, exceptions |
| 6 Reports/admin/data portability | 32–35 | Polished UI, CSV/XLSX/JSON, SMTP, scheduled reporting, settings and backup status |
| 7 Hardening and pilot | 36–40 | Security tests, performance, staging deployment, off-host backup/restore, UAT, cutover decision |

**Important sequencing change:** Basic SMTP, admin users and backup skeletons belong in **Phase 1** even if their full UI/automation is completed in Phase 6. Do not postpone all backup/security work to the end.

## Vertical slices (preferred order for an agent)

1. Smallest deployable Compose + Django/React + PostgreSQL + Redis stack with health endpoint and tests.
2. Local admin bootstrap, accounts/RBAC, migrations and audit middleware.
3. One Asset CRUD route and attractive table/detail UI with typed state and tests.
4. Source observation, source link and manual field authority, reconciliation queue.
5. LibreNMS connector full sync of a fixture and one real staging sample.
6. Endpoint Central on-prem connector fixture and integration health; Microsoft adapters in independent increments.
7. Group rule builder and bulk import/export.
8. EOL catalogue and exact match approval, report and alert.
9. Domain/TLS and license views with independently tracked dates.
10. SMTP admin/test/send and backup staging/restore; production hardening.

## Dependency map

- Asset DB + auth required before imported canonical data.
- Observations/source links required before real connectors.
- Normalized product catalogue required before EOL.
- Outbox + SMTP required before notifications.
- Stable IDs/RBAC required before imports, exports and groups.
- Backup and restore must work before production API keys enter system.

## Concurrency rules

Parallel work is fine across frontend static screens and backend contracts only after OpenAPI/schema is agreed. Avoid both agents editing migrations, auth or the same shared components simultaneously. Assign ownership by module and merge via reviewed PRs. Treat tasks/ACTIVE_TASK.md as the single next task.

## V1 cutline

If time constrained, defer deeper topology, vendor APIs, procurement and complex SAM; do **not** cut auth, provenance, import/export, SMTP configuration, backup/restore or evidence-backed EOL correctness.
