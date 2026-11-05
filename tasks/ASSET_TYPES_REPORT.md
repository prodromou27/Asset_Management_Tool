# Asset type navigation — 5 November 2026

Owner approved the IT Glue-inspired UI and requested Workstations, Servers, Printers
and other asset groups/types. Baseline e1d84d0. These types already exist in the
seeded category taxonomy; the sidebar had only a generic Assets link.

`app/AssetTypeNav.tsx` now renders active root categories from the existing shared
category query beneath Assets in the Inventory sidebar. Icons are decorative; names,
ordering and IDs come from the API, including administrator-defined types. Each link
opens `/assets?category=<id>` as a fresh filtered view. Existing backend descendants
and site/RBAC rules apply. Selecting a child highlights its root; the page title shows
the selected category. Assets clears the category view. Inactive roots are hidden;
metadata loading/empty/error/retry states are explicit. No inventory counts are invented.

`AppShell.tsx` mounts type navigation only where the authorized Assets link is visible
(or mobile navigation is open). It keeps only the appropriate Assets/type link active.
`AssetsListPage.tsx` uses the category title. Shared styles retain the approved design.
No API, schema, seed, permission or manual/dynamic Group change is required.

New regression tests cover root links, custom/inactive categories, category query IDs,
child/root highlighting, return to Assets, missing permissions and metadata retry.
Browser fixtures include laptop/server/printer records and verify their distinct lists,
titles, active state, reload and mobile drawer selection in both themes. Evidence:
`frontend/test-results/asset-types-review/`. Final results are recorded below/handoff.

Verification: **214 frontend tests passed** (29 files); lint/typecheck/production
build passed. **26 backend tests passed** for existing category-descendant filtering
and site scope. **112 synthetic Edge captures passed**, with no browser exceptions
or unmapped fixtures. Workstations/Printers desktop lists and the mobile type drawer
were visually inspected. The existing Vite chunk-size advisory remains; build succeeds.
DEV CI validates the pushed revision before handoff. No test was removed or disabled.

Next: push DEV, verify CI and hand off the category navigation. Task 022/live
commissioning remains separate; no live service has been enabled.
