# Codex Repository Instructions (high priority, intentionally short)

This is a custom ITAM application for one organization. Its canonical requirements are in docs/00_MASTER_DECISIONS.md. The current task is in tasks/ACTIVE_TASK.md.

## Every coding session

1. Read this file, docs/00_MASTER_DECISIONS.md, tasks/ACTIVE_TASK.md and **only** the docs listed in that task.
2. Inspect current source/tests before changing files. Do not regenerate completed work or overwrite unrelated changes.
3. State the intended files and acceptance test in 3–5 lines, then implement the smallest vertical slice.
4. Use existing modules, service interfaces, API schemas and UI tokens. Avoid new frameworks without an ADR.
5. Include database migrations, validation, RBAC, audit, tests and relevant documentation when the change needs them.
6. Run the smallest relevant tests plus lint/type check where possible. Report real results, blockers and files changed.
7. Update tasks/ACTIVE_TASK.md with outcome and next action. Do not silently start another epic.

## Locked choices

- React + TypeScript frontend, Django + DRF API, PostgreSQL, Celery + Redis; Docker Compose v2 on AlmaLinux OS 10.2 (stable baseline as of 2026-11-02). Recheck GA at host deployment.
- Read-only LibreNMS REST as primary network inventory; read-only Endpoint Central **on-premises**, Intune, Defender and M365/Entra adapters.
- Canonical assets separate from raw source observations, field authority and discovery identities.
- Clean, dense, restrained enterprise interface described in docs/07_UI_DESIGN_SYSTEM.md. No generic AI-style dashboard.
- Configurable SMTP, users/RBAC/SSO, backup/restore, health, logs and export/import are release gates, not nice-to-haves.
- Never store secrets in git, print credentials, or run network scans against real networks without approval.

## Token budget discipline

- Read targeted files/line ranges; search with rg before dumping entire files.
- One task per run; no repeated PRD summary or restatement of unchanged design.
- Request clarification only if the answer changes architecture/security. Record assumptions in docs/17_ADR_OPEN_DECISIONS.md.
- After changes, provide: outcome, paths, tests, issue, next task. Keep the handoff short.
