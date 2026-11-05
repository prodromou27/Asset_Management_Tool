# Current task: IT Glue-inspired UI (2026-11-05)

Owner rejected prior designs and named IT Glue as the visual reference. Baseline
3624584. This supersedes the forest theme and top-only navigation direction.
Read: AGENTS.md, docs/00_MASTER_DECISIONS.md, docs/07_UI_DESIGN_SYSTEM.md.
History: FULL_UI_REDESIGN_REPORT.md and FULL_UI_REDESIGN_OUTCOME.md.

Implement independently written UI using the reference's purple global navigation,
light contextual sidebar, flat white content, teal secondary actions/links, green
create actions, compact inventory lists and right-side detail panels. Adapt to this
single-organization ITAM app; preserve workflows/RBAC/API and usable dark mode.
No IT Glue source/assets/branding are shipped. No new packages or production access.

Acceptance: frontend workflow tests, lint/types/build; desktop/mobile screenshots
and browser checks in both themes; navigation, filtering, persistence, focus and
error states. Status: COMPLETE for implementation and local acceptance: 210 tests,
lint/types/build and 103 browser captures passed. See ITGLUE_UI_REPORT.md.
Next: push DEV, verify CI and hand off the reference-led design for owner review.
Do not start Task 022. Production gates remain disabled.
