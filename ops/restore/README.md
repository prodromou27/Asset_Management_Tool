# Isolated restore rehearsal

This is an operator workflow. No production restore/cutover is authorized by Task 019.
Use an approved staging machine with sufficient RAM for a temporary PostgreSQL database,
Docker, Python 3.12 and restic. Recover repository credentials through the separate approved
mechanism. Pin the approved PostgreSQL 16 image digest at commissioning and pass it
with `--image <reference>`. The historical default remains `postgres:16-bookworm`;
CI explicitly tests the production `itam-postgres:16.15` build. The option is an
operator CLI argument, never a web/API input. Production backup tools also use major 16.

1. Select a **full 64-character snapshot ID** from a verified job. Set repository/password
   file and SSH configuration in the operator environment. Verify repository integrity:

   ```bash
   restic check --read-data
   mkdir -m 700 /approved/staging/restore-unique
   restic restore <full-snapshot-id> --target /approved/staging/restore-unique
   python ops/restore/drill.py /approved/staging/restore-unique \
     --report /approved/staging/drill-unique.json
   ```

2. The script verifies the manifest/database hash, starts a unique ephemeral PostgreSQL
   container with **`--network none`**, no published ports, no existing volume and tmpfs
   database storage, then restores with `pg_restore --exit-on-error --no-owner --no-acl`.
   It checks migration history and recorded asset/group/software/license/domain/lifecycle/
   source/audit/import/export table counts. SMTP is disabled in the recovered database.
   No app or worker starts, so outgoing connectors, TLS checks, scheduled mail and queued
   jobs cannot run. On exit only its uniquely named container is removed; a JSON report
   records timestamps, duration, counts and result. Failed checks raise an error and
   leave a failed report where possible. It never changes the source application database.
   New manifests must declare PostgreSQL major 16; extension versions must match after
   restore. Older v1 manifests remain readable. The report records recovery-point age
   and preserves a failed result even if container cleanup fails; inspect `target_removed`
   and remove only that unique drill container after diagnosing cleanup errors.
3. The automated drill checks structural recovery, not all business semantics. On a
   separately approved isolated application staging stack, restore the separately escrowed
   signing/import encryption keys, disable **SMTP, integration approvals and schedules,
   TLS endpoint checks, notifications, backups and all existing pending/running jobs**
   before starting workers. Keep outbound networking blocked. Check sample asset identity,
   group membership, lifecycle evidence, software/license records, certificates, audit
   continuity and decryption/download of retained import/export files. Resolve queued
   backup slots from the recovered database as incident records, never resume them.
4. Record success or failure with the matching verified backup, isolated target label,
   start/finish times and check results in Administration → Backups & Recovery. The UI
   explicitly labels these as operator-recorded results. A failed drill queues an admin
   alert when SMTP is enabled. Download the recovery summary for the incident record.
5. Compare measured time and recovery point with the approved RTO/RPO; retain reports
   according to DEC-15. Production cutover needs a separately authorized incident plan,
   compatible pinned application images, new DB roles, production network/TLS verification
   and explicit approval. Never restore over an existing production volume.

Keep staging data confidential. Remove only the explicitly created staging directory after
the rehearsal according to the organization's data handling procedure. The script does not
delete operator-provided directories or encrypted off-host snapshots.

CI additionally uses `recover_fixture.py` for synthetic artifacts only. It refuses recovery
without the original source-removal flags, checks the encrypted repository, restores the
full immutable snapshot, and passes retrieval metadata to the isolated drill. Reported
retrieval-plus-restore time is a small-fixture observation, not production RTO acceptance.
