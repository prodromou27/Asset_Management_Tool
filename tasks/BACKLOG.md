# Execution Backlog: One Bounded Ticket per Coding Session

This file is a sequencing index, **not permission to implement everything in one pass**. The active ticket is tasks/ACTIVE_TASK.md. Before each task, copy only the relevant requirements and acceptance IDs into ACTIVE_TASK; keep it short.

| ID | Task | Prerequisites | Read docs |
|---|---|---|---|
| 001 | Bootstrap Docker/Django/React/PostgreSQL/Redis/CI | None | 00,02,12,19 |
| 002 | Named admin bootstrap, local auth/RBAC + audit | 001 | 03,04,09,14 |
| 003 | Asset/category/site schema + CRUD | 002 | 01,03,04,07,08 |
| 004 | Source observations, identity matching and manual field locks | 003 | 03,05,14,15 |
| 005 | Asset list/detail UI, search, filters, provenance drawer | 003–004 | 07,08,04 |
| 006 | LibreNMS read-only adapter + fixtures | 004 | 05,03,15 |
| 007 | Endpoint Central on-prem adapter | 004 | 05,15 |
| 008 | Intune managedDevice adapter | 004 | 05,15 |
| 009 | Defender machine/discovery adapter | 004 | 05,15 |
| 010 | Entra/M365 SKU+license assignments | 004 | 05,06,15 |
| 011 | Reconciliation review and category reclassification | 004–010 | 01,03,07,08 |
| 012 | Static/dynamic groups + editor | 003,011 | 01,03,07,08,11 |
| 013 | CSV/XLSX imports with preview/guarded upsert | 003–004 | 04,11,14 |
| 014 | CSV/XLSX/JSON exports with RBAC and async jobs | 003,013 | 04,11,14 |
| 015 | EOL source/model catalogue + evidence and assessment | 011 | 06,03,15 |
| 016a | Software catalogue, installations, connector reads, software lifecycle | 010–011, 015 | 06,08,03,05 |
| 016b | License entitlements/allocations + Software & Licenses area with M365 | 016a | 06,08,03,11 |
| 017 | Domain and TLS certificate inventory/expiry | 003 | 06,08,14 |
| 018a | SMTP config UI, template engine, outbox and test mail | 002 | 10,09,14,15 |
| 018b | Notification rules: certificate/domain/EOL thresholds, integration failures, recipients, dedup | 015,017,018a | 10,06,09 |
| 019 | Backups, off-host encryption and isolated restore | 001,002 | 12,13,14,15 |
| 020 | Admin settings/integration catalogue/health screens | 002,006 | 08,09,20 |
| 021 | Lifecycle/coverage/asset/group reports and digests | 012,014–018 | 08,10,11 |
| 022 | Security/load/e2e/restore pilot on AlmaLinux staging | All applicable | 12–16,20 |

## Prioritize correctness

Integrations must never write remote systems. EOL must never be guessed. Assets/groups must preserve audit and RBAC. SMTP/backup/users are **required**, not optional polish. Native discovery scanners and advanced topology are **not V1 tasks**.

## Task move rule

After successful completion, mark current ticket done, select the next unblocked ID, write a concise objective/AC/read list into ACTIVE_TASK and stop for human review if risk, scope or architecture changes.
