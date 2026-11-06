# Current task: UI refinement | Category icons and navigation clarity

Owner requested UI improvements and fixes to asset category icons on 2026-11-06.
Baseline c463f55. Preserve the approved IT Glue-inspired layout and current features.
Read: AGENTS.md, docs/00 and docs/07. Task 022c evidence remains in TASK022C_REPORT.md.

Bounded slice: shared category icons for all 13 built-in families and selected subtypes;
custom child inheritance and safe root fallback; consistent sidebar/header/admin icons,
alignment and selected state. Add keyboard-accessible category disclosure so long
lists do not obscure other modules. Reuse Lucide, current category metadata and tokens.

Acceptance: correct category symbols, preserved names/RBAC/filter behavior, custom
category inheritance/fallback and collapse/reopen behavior, desktop/mobile light/dark
browser evidence, no page overflow; relevant tests plus lint/types/build.
Status: implemented. 217 frontend tests passed; after the final focus-trap adjustment,
26 focused checks plus lint/types passed. Build and synthetic browser review passed;
final browser/CI verification is in progress. See CATEGORY_UI_OUTCOME.md.
No API/schema/category data changes.
Next after this UI slice: resume Task 022d shared connector DNS connection pinning.
Task 022/G6 remains open; AlmaLinux choice is accepted (DEC-01).
