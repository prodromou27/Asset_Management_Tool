# Current task: Asset type navigation (2026-11-05)

Owner approved the IT Glue-inspired UI and requested missing asset group/type links:
Workstations, Servers, Printers and other existing categories. Baseline e1d84d0.
Read: AGENTS.md, docs/00_MASTER_DECISIONS.md, docs/07_UI_DESIGN_SYSTEM.md.

Expose active root asset categories in the Inventory sidebar using existing metadata,
category-filtered asset queries and site/RBAC rules. Root filters include descendants.
Keep static/dynamic Groups separate. No hardcoded category data, new schema or API.
Category pages use the selected type name; allow return to all assets. Preserve UI.

Acceptance: root/child selection, inactive/custom categories, permissions, metadata
errors/retry, page titles and URL filtering; existing workflow tests, lint/types/build,
desktop/mobile browser review in both themes. Status: COMPLETE for local acceptance:
214 frontend tests, 26 backend scope/category tests, lint/types/build and 112 browser
captures passed. Details: ASSET_TYPES_REPORT.md. Next: push DEV, verify CI and hand
off category navigation. Do not start Task 022 or enable live services.
