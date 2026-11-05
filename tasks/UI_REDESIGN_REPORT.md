# UI redesign — 5 November 2026

Owner requested a whole-UI redesign after Task 021. Baseline: 3d337a9.

Shared tokens and styles now define a cooler slate canvas, stronger ink/blue accents,
232px navy navigation with outlined current item and separated section labels, a 64px
header, clearer title hierarchy, baseline tabs, quieter filters and crisp table surfaces.
Forms, dialogs, account controls and sign-in share the refreshed visual language.
Existing Inter/Lucide components, dense rows, status semantics, focus/reduced-motion
behavior, workflows and permissions are retained. No new dependencies or API changes.

Mobile asset search stays visible. Secondary filters and sorting have an accessible
keyboard-operable disclosure with an active-filter count; closing it preserves the
URL filters. Desktop keeps the full filter set visible. The browser gate verifies the
mobile table appears within the first viewport before expanding filters, keyboard
toggle behavior, category URL changes and visibility on collapse.

Files: `frontend/src/styles/{tokens,global}.css`, `app/AppShell.tsx`,
`features/assets/AssetsListPage.tsx` and its regression tests; browser review script,
docs/07 and active-task history. All other modules receive the shared styling.

Validation: **207 frontend tests passed**, lint, typecheck and production build passed.
The existing Vite chunk-size advisory remains (build succeeds). Synthetic Edge review
produced **57 screenshots**, no browser exceptions/unmapped API requests. Desktop/mobile
inventory/detail, reports, settings and dialogs were inspected; sign-in and form
validation are captured too. Screenshots: `frontend/test-results/ui-redesign-review/`.
Contrast spot checks exceeded 4.5:1 for primary/secondary text, action labels and nav
labels; this is not a claim of a comprehensive accessibility audit.

CI: pending DEV push. Backend/schema were unchanged. No production services or live
calls were enabled. Task 022 remains a separately authorized pilot with operator inputs.
