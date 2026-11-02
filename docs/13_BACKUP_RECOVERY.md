# 13 | Backup, Retention, Restore and Disaster Recovery

Backups are a **release gate**. The application is not production-ready just because PostgreSQL has a named volume. Persistent storage is not backup.

## Assets that must be protected

1. PostgreSQL business database: assets, sources/observations, reconciliation, EOL evidence, users/roles, settings, notification outbox and audit.
2. Object storage/media: attachments, EOL documents, import originals (within retention), exported report artifacts as required.
3. Deployment configuration: Compose manifests, pinned image digests, versioned schema/migrations, TLS/trust configuration and host service metadata.
4. Secrets/keys: backed up through **approved separate secure mechanism**; do not include plaintext secrets in normal backup archives.
5. PostgreSQL global roles/privileges if required for restore.

## V1 backup policy (initial proposal for business approval)

| Item | Proposal |
|---|---|
| RPO | <=24 hours (daily backup); improve to point-in-time recovery if business requires |
| RTO | <=4 hours on same-size replacement host once infra ready; validate by timed drill |
| Database | Nightly consistent pg_dump custom format (-Fc), checksums and manifest; roles/globals as needed |
| Media | Nightly media snapshot or backup manifest synchronized with DB backup epoch |
| Retention | Daily 14–30 days, weekly 8 weeks, monthly 12 months, subject to policy |
| Location | Encrypted backup off the AlmaLinux host, ideally off-site or separate protected account/location |
| Encryption | Authenticated encryption in transit and at rest; key stored separately with recovery test |
| Verification | Daily file/manifest integrity check; monthly actual test restore to isolated staging |
| Alerting | SMTP admin alert when backup age exceeds SLA, upload/checksum fails or restore test fails |

## Scheduled job design

Implement a restricted backup runner or ops/backup.sh with a clear argument contract and logs:

1. Take a transactionally consistent PostgreSQL backup (pg_dump -Fc); record DB schema migration version and app image digests.
2. Export any required PostgreSQL global roles separately.
3. Create time-correlated media/object manifest and copy blobs.
4. Create manifest containing backup ID, timestamps, object counts, hashes, software versions and expected restore prerequisites.
5. Encrypt and transfer to off-host destination using approved credential; verify checksum on destination.
6. Apply retention **only to explicit backup-object prefixes**, after successful new backup verification; never delete all volumes as cleanup.
7. Update backup_jobs status, last_success, size, target and verification; emit audit/operational alert on failure.

Use PostgreSQL official backup/restore facilities and test under the real container user. If DB grows beyond practical logical-backup windows, propose WAL archiving/PITR and separate retention, with business approval; do not call a daily pg_dump equivalent to PITR.

## Restore runbook (staging first)

1. Confirm incident and target. Create a **new empty isolated staging database/volume**; do not restore over production without explicit signed approval.
2. Retrieve selected backup, manifest and encryption key through approved channels; verify signature/hash and version compatibility.
3. Deploy compatible pinned image versions and secrets. Restore DB roles/globals where necessary, then database with pg_restore.
4. Restore media objects and configuration references; validate source/object associations.
5. Run migration health checks, count assets/licenses/source observations, check audit continuity and sample attachments.
6. Disable live connectors and outgoing production emails in staging to prevent unintended external actions.
7. Record actual restoration duration, missing files/rows, RPO point, integrity result and approver.
8. Production cutover only after controlled recovery decision and network/TLS verification.

## Admin UX

Administration → Backups & Recovery shows schedule, target label (not credentials), encrypted/off-host status, last backup, verification, last restore drill, RPO/RTO and incidents. Administrators can request 'Verify backup' and download a summary report. Production restore action is **not a one-click button**. Require runbook, role separation and explicit confirmation.

## Test gates

- Deleted local container does not destroy backed-up DB/media.
- Simulated partial off-host upload fails safely and retains previous good backups.
- Wrong/missing decryption key produces actionable error without exposing secrets.
- Restore into isolated environment recovers representative assets, licenses, certificates, documents, groups and audit.
- Backup job success is not reported before off-host checksum verification.
