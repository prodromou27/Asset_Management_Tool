# 20 | Administrative Configuration Catalogue

The UI must expose settings grouped by domain; not every setting is safe to edit from a browser. Host-level secrets and encryption keys are managed outside the app and referred to indirectly. Every configurable field has validation, help text, default, audit and test/health behavior.

| Menu | Editable configuration | Verification / permission |
|---|---|---|
| General | Organization label, language, timezone, date format, support contact, retention policy | Admin; preview; audit |
| Sites/Departments | Hierarchy, codes, locations, network/site mapping, asset tags | Admin/ITAM manager; no orphaned references |
| Categories/Custom Fields | Asset family, subtype, required fields, allowed relationships and classification rules | Admin; preview data/template effects |
| Users/Roles | Identity provider, invited/local accounts, group-to-role mapping, site scopes, API account owner/expiry | Admin-only, MFA, access review export |
| Email | SMTP host/port/TLS/auth secret ref, sender, reply-to, recipients, retries, digest schedule | Admin test connection + authorized test message |
| Alert Policies | EOL thresholds, certificate/domain deadlines, group recipients, digest/escalation, suppressions | ITAM manager / admin; next-run preview |
| Integrations | Enabled provider, base URL, source instance ID, read permission, secret ref, schedule, mapping and field authority | Admin test, version/capability, last sync/errors |
| Discovery | LibreNMS-sourced coverage mapping, unknown-device review policy, source stale limits | Admin/engineer; no native scan settings in V1 |
| Lifecycle | Vendor catalogue sources, matching rules, date milestone policy, approval/exception scopes | Approver separation; provenance |
| Licenses | SKU mappings, entitlement metadata, renewal date, allocation policy | ITAM/license manager; audit |
| Import/Export | Template versions, upload limits, export expiration, sensitive-field policy, background job quotas | Admin; simulate permissions |
| Backups | Schedule, encrypted off-host target label, retention, verification interval, RPO/RTO, notification | Admin; no secret reveal; restore separate |
| Storage | Provider type, bucket/path label, quotas, encryption, cleanup policies | Deployment admin and secret store; health |
| Jobs/Queues | Retry limits, concurrency, schedules, stale-job handling, cancellation | Admin; operational logs |
| Security | Session lifetime, MFA policy (via IdP), token TTL, allowed IP admin controls if approved | Restricted admin and audit |
| Audit | Search, retention, export, tamper-resistant storage and protected access | Auditor/admin, never silent mutation |
| Health | DB, Redis, storage, LibreNMS, Endpoint Central, Graph, SMTP and backup states | Read-only status to approved roles |

## Configuration layering

1. Immutable code defaults for secure behavior.
2. Deployment environment for paths/URLs/nonsecret infra values.
3. Secret manager for credentials/keys; only secret references in DB.
4. Admin database settings for business policies.
5. Per-user display preferences (table columns, theme) in separate profile.

Backend must document precedence and reject invalid/conflicting configuration. Startup readiness distinguishes fatal infrastructure config from an optional temporarily degraded source. Provide 'restore defaults' only for safe nonsecret UI preferences, not account/SMTP/backup credentials.

## First-run readiness gate

Administrators must see an actionable checklist:

- [ ] Named admin created, second admin verified, role/site scopes checked.
- [ ] Trusted HTTPS FQDN and secure cookies verified.
- [ ] Backup configured, encrypted off-host copy verified, restore rehearsal documented.
- [ ] SMTP tested and alert recipient set.
- [ ] LibreNMS read-only token and source mapping tested.
- [ ] Endpoint Central on-prem token/API generation tested.
- [ ] M365/Intune/Defender tenant permissions tested or intentionally marked unavailable.
- [ ] EOL source catalogue and Unknown behavior checked.
- [ ] Import/export permission test completed.
- [ ] Logs, monitoring, queue alerts, storage free-space and retention configured.

Production Readiness label must stay **Incomplete** until mandatory gates pass. A connector with no grant can be intentionally Disabled, but must never display healthy sync.
