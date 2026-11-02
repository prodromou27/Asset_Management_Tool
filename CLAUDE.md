# Claude Code Project Instructions

Follow the same requirements as [AGENTS.md](AGENTS.md). This file exists so Claude Code finds the project contract without duplicating the whole specification.

Read in order:

1. AGENTS.md
2. docs/00_MASTER_DECISIONS.md
3. tasks/ACTIVE_TASK.md
4. Only the reference documents listed in the active task.

Execute one small vertical slice at a time, use existing code conventions, keep changes reviewable, and run tests. Do not implement planned integrations as if they were functioning or invent manufacturer lifecycle dates. Treat staging/prod credentials and network access as external prerequisites. For the UI, honor docs/07_UI_DESIGN_SYSTEM.md even when using a component library.

At the end report only: changed files, behavior, verification result, blocker (if any) and next task. Update task status in the repository.
