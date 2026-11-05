# 07 | Forest workspace design system

Owner direction: 5 November 2026. The owner rejected the navy refresh and explicitly
requested a full new design with different colours, themes, layouts and CSS. This
replaces all previous navy-sidebar requirements. Keep a professional, useful ITAM
interface with real data, readable density and traceable evidence.

## Visual direction

Warm stone canvas, white paper-like surfaces and forest-green actions in light mode;
charcoal canvas, layered dark surfaces and mint accents in dark mode. No neon,
decorative charts, invented metrics or external fonts/images. Reuse bundled Inter,
IBM Plex Mono and Lucide. Main headings are 32px (28px mobile), section headings 15px,
body 14px, table text 13px. Control heights 38px, default rows 46px, corners 8-12px,
dialog corners 16px. Use subtle shadows for overlays; keep content surfaces quiet.

## Themes and tokens

Source: frontend/src/styles/tokens.css. Shared components use semantic variables.

| Token | Forest light | Charcoal dark |
|---|---|---|
| Canvas | #F4F2ED | #181C1A |
| Surface | #FFFFFF | #222825 |
| Muted surface | #F7F6F2 | #2A322E |
| Primary text | #292E28 | #EDF2EC |
| Secondary text | #60695E | #B0BEB4 |
| Border | #E0E3DA | #3B4740 |
| Strong border | #84917B | #7E9286 |
| Primary action | #256347 | #A0D8AD |
| Action label | #FFFFFF | #173321 |
| Link | #215A3E | #A9DFB4 |
| Masthead | #183F32 | #122C23 |

The sun/moon control changes theme immediately; `itam.appearance` stores only the
local browser preference. Storage failure leaves the control usable. The ThemeProvider
wraps authenticated and sign-in routes, so the preference survives navigation/reload.
No account, organization, API or authorization setting is changed. Native form controls
follow color-scheme. Email HTML previews intentionally retain their own white document.

## Navigation and workspace

Remove the persistent sidebar. A full-width forest masthead contains organization,
asset search, theme and account actions. Below it are section buttons (Inventory,
Sources, Administration, System) and a horizontally scrolling module navigation row.
Selecting a section reveals its modules without changing the current record; following
a module updates the URL and restores the appropriate section. Permissions determine
both sections and modules. Active links retain aria-current and explicit text/icons.

At <=767px, the masthead remains compact; navigation becomes a right-hand drawer with
all authorized sections. Opening it makes page/masthead inert, traps focus, locks body
scroll and focuses Close. Escape/link/close returns focus; resizing to desktop closes
it. The account menu has an explicit accessible name even when its visual text is hidden.

Content fills the workspace, capped at 1920px, with 4vw margins on desktop and 16px on
mobile. Breadcrumbs sit above page titles; a ruled title/action row anchors each page.
Inventory uses a 240px filter/saved-view rail beside the table (210px on small desktop).
On mobile the rail stacks above the table and secondary filters use a disclosure with
an active-filter count. Closing filters never clears them or changes URL semantics.

## Components

- Tables: sentence-case headers, tabular numbers, gentle alternating rows, forest/mint
  selection, internal horizontal scrolling and text-based statuses. Preserve column
  selection, saved views, bulk actions and evidence links.
- Detail: segmented tabs, bordered status summary, wider main evidence panel and
  separate ownership/record panels. Stack on narrower screens.
- Forms: muted filled controls with a lower border; visible labels/help, explicit
  validation and clear focus. No placeholder-only labels. Preserve fields and actions.
- Dialogs: larger title, rounded surface, separated muted action footer, independently
  scrolling body and persistent actions within viewport. Retain focus/escape behavior.
- Sign-in: centred paper surface on the theme canvas, large heading, full-width action
  and its own theme control. No changes to authentication or password behavior.
- Status: supported green, near EOS amber, EOS red, Unknown/stale neutral. Adjust each
  theme's semantic colours for legibility. Text carries meaning alongside colour.

## Accessibility and verification

Aim for WCAG AA contrast, visible keyboard focus and no colour-only status. Preserve
existing reduced-motion handling, labelled fields, async/error messages, tables and
keyboard tabs. Functional regression tests cover workflow permissions, theme persistence,
blocked storage and section selection. Browser fixtures exercise both themes at
1440x900 and 390x844, plus dialogs, error/denied/loading states and sign-in validation.
Check theme persistence on reload, page overflow, mobile filter state and drawer focus.
Synthetic evidence: frontend/test-results/forest-workspace-review/. No live API/SMTP
calls are part of UI verification. These checks do not constitute a full accessibility
or production commissioning audit.
