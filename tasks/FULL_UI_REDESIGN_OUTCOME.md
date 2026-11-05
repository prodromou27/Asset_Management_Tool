# Current task: Full UI replacement (2026-11-05)

Owner rejected the previous navy refresh and explicitly requested different colours,
themes, layouts and CSS. Baseline 47d608e. This supersedes earlier navy constraints.
Read: AGENTS.md, docs/00_MASTER_DECISIONS.md, docs/07_UI_DESIGN_SYSTEM.md.
History: UI_REDESIGN_REPORT.md / UI_REDESIGN_OUTCOME.md; Task 021 is complete.

Deliver a forest/stone light theme and charcoal dark theme, persistent local theme
selection, full-width top section/module navigation instead of a sidebar, desktop
inventory filter rail, redesigned shared surfaces/forms/tables/dialogs and sign-in.
Retain existing workflows, permissions, URL state and API contracts. No new packages,
live services or Task 022 commissioning.

Acceptance: frontend workflow and theme/navigation tests, lint/typecheck/build;
desktop/mobile browser evidence in both themes, no overflow or unmapped fixtures;
keyboard navigation, theme persistence, disclosure behavior, contrast spot checks.
Status: COMPLETE for implementation and local acceptance. 210 frontend tests,
lint/typecheck/build and 100 browser captures across both themes passed.
Details: FULL_UI_REDESIGN_REPORT.md. Next: push DEV, verify CI and hand off for
owner design review. Production gates remain disabled; no new epic is started.
