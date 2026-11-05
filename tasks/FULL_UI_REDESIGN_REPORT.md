# Full UI replacement — forest and charcoal

Owner rejected the navy refresh and requested different colours, themes, layouts
and CSS. Baseline: 47d608e. This task replaces that direction, preserving existing
data, permissions and workflows. Task 022 commissioning remains separate.

## Delivered design

- Full-width forest masthead, top section navigation and a separate module row;
  the former persistent sidebar CSS is removed. Sections expose authorized modules
  without navigating away from the current record. Active modules scroll into view.
- Forest/stone light theme and charcoal/mint dark theme. A sun/moon control appears
  in the app and on sign-in. Browser-local preference survives navigation/reload;
  blocked storage falls back safely without disabling the control.
- Inventory filter/saved-view rail beside the table on desktop, stacked above it
  on mobile with the existing filter disclosure and URL state preserved.
- New shared typography, filled controls, sentence-case table headers, alternating
  rows, status summaries, segmented detail tabs, ownership panels, dialog footers,
  sign-in layout and mobile drawer. Theme-aware checkboxes and control borders.
- Mobile drawer makes masthead/content inert, traps keyboard focus and restores it
  on close. Account control has a descriptive name even with its text hidden.

## Files

`frontend/src/styles/tokens.css` defines both semantic palettes;
`workspace.css` owns the new shell and shared design. The old sidebar styles are
removed from `global.css`; `main.tsx` loads the replacement. `app/theme.tsx` provides
appearance state, `App.tsx` wraps all routes, `AppShell.tsx` rebuilds navigation.
`AssetsListPage.tsx` adds the filter rail; sign-in adds theme selection, and general
settings describes the workspace header. Tests/browser fixtures and docs/07 are updated.
No package, API, schema, authentication policy, live access or production change.

## Verification

Final frontend workflow suite: **210 tests passed** (28 files), including three new
tests for persisted themes, blocked storage and section selection. Lint, typecheck
and production build passed. The existing Vite chunk-size advisory remains; the
build succeeds. No test was removed or disabled.

Synthetic Edge browser review captures both themes at 1440x900 and 390x844 across
inventory/detail, reports, discovery, software, lifecycle and administration, plus
dialogs and sign-in. It checks reload persistence, section visibility, current-module
position, mobile table visibility, filter URL updates, overflow, unmapped fixtures,
browser errors and drawer focus. **100 captures passed**, with no browser errors or
unmapped API fixtures. Evidence: `frontend/test-results/forest-workspace-review/`.
`results.json` records the final count. The last CSS-only focus adjustment gives
masthead controls a high-contrast focus ring; CI builds the complete final source.

Representative inventory/detail, dark settings, dark mobile digest dialog and sign-in
layouts were visually inspected. Contrast spot checks: light body 13.85:1,
secondary/muted 5.28:1, action label 7.11:1; dark body 13.24:1,
secondary/muted 6.82:1, action label 8.43:1. Control bottom borders exceed 3:1 on
their muted fills. This is not a complete accessibility audit.

The normal DEV CI workflow validates frontend gates, unchanged PostgreSQL/Redis
backend, migrations, schema drift, production settings, images and isolated recovery.
The handoff provides the actual run result after push. Production gates remain off.

Next: owner review of the new light/dark design. No new epic is started.
