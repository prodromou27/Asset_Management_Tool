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
   mounted as `/run/secrets` **only on backup-worker**. In that same protected directory,
   supply `restic_ssh_key` and `restic_known_hosts` with the approved host fingerprint.
   The runner forces batch/key-only authentication and strict host checking, ignoring
   user/global SSH configuration and inherited restic hooks. Files must be
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
   Initialize the approved repository explicitly, then check it using the same pinned
   transport (substitute `check` for `init` for a full integrity check):

   ```bash
   docker compose --env-file .env -f infra/compose.yaml -f infra/compose.prod.yaml \
     --profile backups run --rm backup-worker python manage.py backup_repository init
   ```
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

The additive v1 manifest also records capture start/completion, PostgreSQL version/major,
extensions, owner role, per-file size/checksum, destination label and representative counts
including application users/RBAC, notification configuration and outbox. The immutable
payload says `pending_destination_verification`: upload verification happens afterwards.
Download the job report for the final verification result, total duration and warning/error.
Job and drill reports require `backups.view` and their downloads are audited.

Restic encrypts and transfers the database and manifest. The job succeeds only after
`restic check --read-data` and remote restore/read-back of the selected immutable snapshot,
with manifest equality and database SHA-256 verified. Partial transfers, wrong keys and
checksum errors fail the job, leaving previous verified job records intact. This is
logical backup, **not PITR**. DB global roles/passwords are not dumped: restore provisions
a new owner and uses `--no-owner --no-acl`. Reapply approved least-privilege roles separately.
Object ACLs are retained in the custom dump; isolated drills intentionally do not apply
production privileges. Global role passwords and application decryption keys remain in
the separately approved recovery mechanism under ADR-016.

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

## Synthetic SFTP destination and destructive-source recovery proof

With disposable PostgreSQL/Redis and Docker available, run the dedicated integration test:

```bash
cd backend
ITAM_BACKUP_TEST_SFTP=1 uv run pytest apps/backups/tests/test_postgres_backup.py -q
```

The harness builds `infra/backup-test`, creates a unique SFTP storage container/volume,
generates fresh client/server/repository keys, binds SSH to loopback only, and pins the
generated public host key directly. It tests a real encrypted SFTP backup/read-back,
wrong encryption password and wrong host pin. Its source database, restored test database,
storage container and volume are newly created and removed by this invocation only.
This service is development/CI-only and **does not demonstrate physical off-host protection**.

CI exports the synthetic encrypted repository and recovery key as separate one-day
artifacts, then deletes the source DB/container/volume. A separate job downloads those
artifacts, checks/decrypts the repository and restores into a new network-disabled DB.
Its seven-day JSON report records retrieval/restore time, recovery-point age and source
removal flags. No production data, credentials or infrastructure are involved.
