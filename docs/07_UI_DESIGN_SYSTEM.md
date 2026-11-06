# 07 | IT Glue-inspired interface

Owner direction: 5 November 2026. The owner rejected prior navy/forest designs and
named IT Glue as the visual reference. This replaces previous visual requirements.
Keep original ITAM code, branding, data semantics, workflows and permission checks.

## Reference and adaptation

Official reference pages inspected, including their configuration/admin screenshots:
- https://help.itglue.kaseya.com/help/Content/2-using/get-to-know-it-glue/structure-and-navigation.html
- https://help.itglue.kaseya.com/help/Content/2-using/organizations/organizations-sidebar.html
- https://help.itglue.kaseya.com/help/Content/2-using/documentation-guide/configurations.html

Adopt the purple global bar, light-grey contextual left sidebar, organization context,
white workspace, teal links/secondary actions, green create actions, compact lists,
lightweight page titles and right-side record panels. Implement independently;
reference screenshots remain ignored review artifacts, never application assets.
Do not add IT Glue logos, copied code, passwords/vault features, multiple organizations,
invented metrics or nonfunctional navigation. This app remains single-organization.

## Tokens and typography

Semantic variables live in frontend/src/styles/tokens.css. Both light and dark mode
are supported through the existing browser-local theme control and itam.appearance.
Storage failure leaves theme switching usable. Sign-in shares the same themes.

| Token | Light | Dark |
|---|---|---|
| Masthead | #7B2D70 | #64255C |
| Sidebar | #F3F3F3 | #222229 |
| Surface | #FFFFFF | #25252C |
| Muted surface | #F7F7F7 | #2E2E36 |
| Text | #333333 | #EEEEEF |
| Secondary text | #666666 | #BABAC1 |
| Links | #416E78 | #9ECDD5 |
| Secondary action | #497780 | #3B6973 |
| Primary action | #287D4B | #92D3A9 |
| Navigation accent | #7B2D70 | #DBA9D2 |

Use bundled Inter and IBM Plex Mono with Lucide icons. Titles 32px/weight 350
(28px mobile), body 14px, table text 13px, labels 12px. Standard control 34px,
row minimum 38px, corners 2-3px, no decorative shadows or large rounded cards.
Action colours are darker than reference screenshots for legible white labels.

## Layout and navigation

56px purple masthead: ITAM identity, authorized area buttons, asset search, theme
and account actions. Area selection changes sidebar contents without navigating away;
opening a module restores its appropriate area. Preserve permission filtering and
aria-current. At narrower desktop widths global areas scroll horizontally within the
header. A 220px light contextual sidebar contains organization identity, area heading
and module links, with a purple active marker. Sidebar scrolls independently.

Main content has a muted breadcrumb strip, organization context on inventory/source
pages, a light title/action row and flat white data surface. Inventory saved-view
controls sit above a wide search/filter bar and table. Filters/sorting expand on both
desktop and mobile, expose their active count and preserve URL state when collapsed.
Do not reintroduce the separate filter rail or top-only module navigation.

The Inventory sidebar includes an Asset types section beneath Assets. Links use
active root categories from the existing category API, including Workstations,
Servers, Printers and administrator-defined types. They open a fresh category-filtered
asset list; backend category filters include descendants and retain current site/RBAC
scope. The selected category names the page; child filters highlight their root type.
Assets returns to the unfiltered authorized list. Inactive roots are hidden. No counts
or fallback categories are fabricated. Metadata errors offer Retry. Existing manual/
dynamic Groups remain separate and do not grant access. No new category data is seeded.

Category symbols come from the shared `CategoryIcon` component using stable category
codes, with distinct Lucide icons for all thirteen built-in root families. Supported
subtypes (for example laptops, virtual machines, routers and scanners) use a specific
symbol. Custom children inherit their parent's icon; custom roots use a neutral boxes
symbol. Renaming a category does not change its icon. Keep icons decorative with the
category name as the accessible label. Use the same mapping in the sidebar, filtered
asset page heading and category administration. Sidebar icons are 18px with a consistent
1.75 stroke; selected icons use the navigation accent in both themes.

Asset types can be collapsed with a keyboard-operable disclosure to shorten long
sidebars. Collapsing does not clear a category filter or change module permissions;
navigation still scrolls independently, including in the mobile drawer.

Detail pages use compact baseline tabs, restrained status chips, a main evidence/form
column and a muted right-side ownership/record panel. Stack at narrow widths. Forms
use labelled white controls with clear borders; dialogs have simple divided action
footers and bounded scrolling. Retain all existing editing/export/evidence actions.

Below 768px the sidebar becomes a left drawer showing all authorized areas. Opening
it makes masthead/content inert, traps keyboard focus and locks body scroll. Escape,
close and navigation restore focus. Theme, account and asset search remain available
in the compact masthead. Tables scroll internally; do not overflow the page.

## Accessibility and acceptance

Keep text statuses alongside colour, explicit account/field names, focus rings and
reduced-motion behavior. Status colours retain supported/expiring/EOS/Unknown meanings.
No unsupported sidebar counts or fictitious client data. Email HTML preview keeps its
own white document. Existing organization/site/field/RBAC scope remains authoritative.

Run frontend workflow tests, lint/types/build, synthetic browser checks at 1440x900
and 390x844 in both themes, and 1024/768 inventory checks. Verify desktop/mobile
filter disclosure, section switching, saved filters, theme reload, account/dialog/drawer
focus, overflow and loading/error/denied states. Evidence is written under
frontend/test-results/category-icons-review/. No live connector or SMTP call is used.
Functional and contrast spot checks are not a full accessibility/commissioning audit.
