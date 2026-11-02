# Prompt Templates for Codex / Claude Code

## First message (paste after extracting this repository)

> Read AGENTS.md and tasks/ACTIVE_TASK.md. Use docs/00_MASTER_DECISIONS.md and only the docs the active task lists. Implement Task 001, including tests and reproducible local Docker Compose setup. Do not connect to production networks, invent credentials or create a generic AI-style UI. Stop when the acceptance criteria pass and report changed files, executed tests and next task.

## Every following message (token-efficient)

> Continue the single task in tasks/ACTIVE_TASK.md. Read only the references listed there and inspect relevant source files with rg. Reuse existing conventions. Implement, test, document and update task status. No unrelated refactors or full project rewrite.

## UI review prompt

> Inspect docs/07_UI_DESIGN_SYSTEM.md and docs/08_UI_SCREENS.md. Review the implemented [specific screen] at 1440x900 and 390x844. Fix layout, dense table behavior, statuses, forms, accessibility and error states; do not add gradients, oversized dashboard cards, demo metrics or decorative clutter. Run frontend tests and report screenshots/changes.

## Connector implementation prompt

> Implement only connector [name] from docs/05_INTEGRATIONS_DISCOVERY.md behind the common read-only adapter interface. Use sanitized fixtures, pagination/retry/checkpoint, source+external IDs, provenance, health and permission diagnostics. Do not call a real instance unless explicitly authorized. Include contract tests.

## Deployment verification prompt

> Follow docs/12_DEPLOY_DOCKER_ALMALINUX.md, docs/13_BACKUP_RECOVERY.md and docs/20_ADMIN_CONFIGURATION_CATALOG.md to prepare an AlmaLinux staging deployment, not production. Verify host version first. Do not disable SELinux/firewalld or install packages without approval. Prepare compose/config/backup/restore procedures and security tests, then ask for missing operational values.

## Bug report prompt

> Diagnose this one behavior with a reproduction test. Locate the narrowest related source files and read the matching contract doc. Make a minimal fix, include regression test, run it and report root cause and test result. Do not regenerate unrelated code.

## Session completion format

1. Implemented: one sentence.
2. Files changed: exact paths.
3. Verification: commands and observed pass/fail.
4. Blocker/decision: only if necessary.
5. Next task: one ID.

## Token discipline

- Avoid asking agent to 'build the entire platform' in one prompt.
- Keep full docs in repo, load only task-specific references.
- Do not paste the same long PRD into every session.
- Prefer precise constraints and acceptance criteria to lengthy discussion.
- When stuck, inspect real errors/diffs first instead of speculative redesign.
