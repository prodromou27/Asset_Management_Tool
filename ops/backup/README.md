# Backups & Recovery (Task 019)

DEC-09 is unresolved. The implementation starts disabled and does not initialize a live
repository, contact a backup host or provision keys. Approve the target, SSH identity,
host-key fingerprint, key custody/recovery, retention, capacity and recovery objectives
before commissioning. Initial policy proposals are daily at 02:00 UTC, RPO 24h, RTO 4h,
30 daily / 8 weekly / 12 monthly snapshots. Automatic deletion is disabled by default.

## Commissioning on an approved staging host

1. Provision a **dedicated off-host SFTP restic repository**. The destination must use a
   separate protected storage system/account, with capacity and repository access controls.
   A remote hostname alone does not prove physical separation. Restrict SSH forwarding
   and access to the repository; do not share this repository's ITAM tags/host with another
   application. Restic repository initialization is an explicit operator operation.
2. Supply the repository password in `restic_password` inside a protected directory
   mounted as `/run/secrets` **only on backup-worker**. Supply a restricted SSH directory
   with the private identity, pinned `known_hosts` and an SSH config that sets
   `BatchMode yes`, `StrictHostKeyChecking yes` and the identity file. Files must be
   readable by the container's `itam` UID; determine that UID from the built image.
   Keep a tested separate recovery copy of the restic key, application signing/import
   encryption keys, deployment `.env`, SSH credentials and TLS/trust material. None of
   those plaintext files is included in the database archive or the API report.
3. Set the protected deployment configuration:

   ```dotenv
   ITAM_BACKUP_ALLOW_RUN=true
   ITAM_BACKUP_TARGET_LABEL=Approved off-host storage
   RESTIC_REPOSITORY=sftp://backup@backup-host.example.invalid/itam
   ITAM_BACKUP_SECRETS_DIR=/approved/secrets/backup
   ITAM_BACKUP_SSH_DIR=/approved/secrets/backup-ssh
   ITAM_APP_REVISION=<full 40-character tested git commit>
   ITAM_BACKUP_IMAGE_REFERENCE=<registry/image@sha256:64-character-digest>
   ```

4. Build and start the opt-in worker with the same production overrides and env file as
   the application:

   ```bash
   docker compose --env-file .env -f infra/compose.yaml -f infra/compose.prod.yaml \
     --profile backups up -d --build backup-worker
   ```

   Restart API/worker/scheduler after changing deployment variables. The main worker does
   not consume the `backups` queue. The backup worker has no Docker socket. It uses the
   PostgreSQL 16 client and restic from the Debian Bookworm package repository.
5. In Administration → Backups & Recovery, request a backup, wait for **Verified**, and
   perform the isolated restore runbook before enabling the nightly policy. Record the
   result and actual duration. RPO/RTO are objectives, not measured guarantees. Test the
   existing SMTP outbox with approved administrator addresses before relying on alerts.

## Guarantees and limits

The runner exports a PostgreSQL repeatable-read snapshot, takes representative table
counts/migration history from that snapshot, and runs `pg_dump -Fc --snapshot`. The
manifest contains SHA-256, size, UTC recovery point, migration versions and operator-
supplied revision/image references. All current stored blobs are PostgreSQL binary
fields (import originals and export artifacts), so they share the same snapshot. No
external media store currently exists. Adding one requires a synchronized snapshot design.

Restic encrypts and transfers the database and manifest. The job succeeds only after
`restic check --read-data` and remote restore/read-back of the selected immutable snapshot,
with manifest equality and database SHA-256 verified. Partial transfers, wrong keys and
checksum errors fail the job, leaving previous verified job records intact. This is
logical backup, **not PITR**. DB global roles/passwords are not dumped: restore provisions
a new owner and uses `--no-owner --no-acl`. Reapply approved least-privilege roles separately.

Reference: [restic repository integrity checks](https://restic.readthedocs.io/en/stable/045_working_with_repos.html)
and [restoring snapshots](https://restic.readthedocs.io/en/stable/050_restore.html).

Retention runs only after verification and only for `--tag itam --host itam-backup`, with
grouping by host and explicit daily/weekly/monthly counts. Failed retention is audited and
shown as a warning; verified backup status is retained. Job metadata remains after
repository retention, so an old snapshot may no longer be available for re-verification.
Restrict deletion credentials or use immutable storage according to organizational policy.

Plaintext staging uses the worker's private `/tmp` tmpfs, removed on normal completion;
size memory/tmpfs and scratch capacity for the dump plus read-back and restic cache. A
large deployment may need a separately approved encrypted staging volume. Commands time
out after two hours each; the workflow may exceed six hours, triggering an operational
alert. Benchmark backup duration and full-repository checks in Task 022.

One active operation is enforced by a database constraint. Broker outages leave a queued
job for periodic redispatch. A crashed running job keeps its slot: **do not unlock a
repository or clear the slot until an operator has confirmed the old process is stopped**.
Then record the incident and mark the job failed through a supervised Django shell,
setting `finished_at`, a redacted `error_message` and `active_slot=None`; add an audit event.
There is no automatic unlock or production restore API.

SMTP alerts go only to active users with `backups.manage` and an email address, through
the existing outbox; mail disabled means no alert is sent. Failures use job deduplication;
RPO/stuck-job findings are limited to once per UTC day per administrator. Nightly schedule
checks run every five minutes. Failed nightly jobs remain visible and require an operator
retry; they are not repeatedly retried against a failing target.
