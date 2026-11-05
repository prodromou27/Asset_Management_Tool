# Current Task: 021 | Lifecycle, coverage, asset/group reports and digests

Owner requested continuation on 2026-11-05. DEV baseline ded41a1; Task 020 complete.
History: TASK020_OUTCOME.md and TASK020_REPORT.md. Do not start Task 022.
Read: AGENTS.md, docs/00, 07 (tokens), 08 (reports/overview), 10, 11;
docs/09 (RBAC), 14 (export/mail protection), 15 (A14/A15/A17/A22), 17 (assumptions).

Deliver four scoped report views: inventory breakdowns, per-dimension lifecycle including
missing assessments as Unknown, observed Endpoint Central/Defender coverage (no inferred
agent/compliance claims), and group replacement/ownership summaries. Site/group filters,
pagination, CSV/XLSX/JSON through existing encrypted export jobs. Protect completed files
against subsequent scope/permission changes. Add self-owned daily/weekly authenticated-link
digests through the existing outbox with current-user checks, dedup, audit and scheduling.
Email contains no inventory rows or attachments. No arbitrary recipients or new SMTP stack.

Acceptance: site/field/RBAC isolation, scoped counts and Unknown behavior, export/download
revocation, schedule ownership/version/validation, duplicate dispatch/retry/disabled SMTP,
recipient revocation, frontend filters/forms/errors/permissions and desktop/mobile browser
checks; schema/type sync, lint/build, PostgreSQL/Redis/migration/Compose/restore CI.
Non-goals: live SMTP/vendor calls, production commissioning, full BI/report designer,
new topology/compliance inference, new authentication architecture, Task 022 pilot.
Status: COMPLETE. Implementation cc88815 pushed to DEV; CI run 42090787679 passed:
827 PostgreSQL/Redis backend tests (no skips), 206 frontend tests, migration reversal,
schema/type drift, lint/typecheck/build, deploy/Compose/images and real encrypted
SFTP/isolated restore. Local browser review: 53 desktop/mobile captures, no browser
errors or unmapped API requests. Details and rollout limits: TASK021_REPORT.md.
Next: Task 022 pilot requires approved target-host/operator inputs. Do not silently
start it. No live services or production gates have been enabled.
