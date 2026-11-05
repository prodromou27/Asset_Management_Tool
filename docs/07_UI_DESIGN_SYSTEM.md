# 07 | UI Art Direction: Serious, Calm, Information-Dense

**This is a business operations tool, not a SaaS marketing site or a generic AI-generated dashboard.** Visual references are understated professional enterprise tools, modern network consoles and thoughtfully designed admin software. The UI must feel deliberately designed for an infrastructure/security engineer who spends hours investigating assets.

## Visual principles (non-negotiable)

1. Information hierarchy before decoration. Prioritize data tables, context, filters, status and traceable evidence.
2. Neutral canvas with restrained color. No gradients, purple/blue neon, glassmorphism, playful illustrations, oversized floating cards or excessive shadows.
3. Dense but readable. More rows above the fold; persistent table header; generous whitespace **between sections**, efficient spacing **within data**.
4. Realistic empty/error/loading states, no fake 100% metrics or fabricated company names.
5. Consistent alignment, one icon family and predictable components. Distinguish business, observation and support statuses.
6. No emoji icons in navigation or dashboard. No giant welcoming hero/banner.
7. Make dangerous actions visually quieter until intentionally selected, then explicit confirmation.

## Design tokens (navy console; broader visual refinement requested 2026-11-05)

The owner rejected the first implementation as plain and dated (style, colours, navigation) and chose a dark navy sidebar with a blue accent. Values live in `frontend/src/styles/tokens.css`; change them only through design review. Dark mode is deferred (the tokens are structured for it).

| Token | Light | Use |
|---|---|---|
| Page background | #F6F8FB | Canvas |
| Main surface | #FFFFFF | Panels, tables, top bar |
| Muted surface | #F8FAFC | Table header band, search field |
| Primary text | #152033 | Body |
| Secondary text | #536276 | Metadata, labels (AA contrast on white) |
| Hairline / strong border | #DCE3ED / #BCC8D8 | Dividers / control outlines |
| Brand/action | #2563EB (hover #1D4ED8) | Primary buttons, brand mark (white text 5.2:1) |
| Link | #1D4ED8 | Links |
| Success | #15803D | Supported, healthy |
| Warning | #B45309 | Expiring, needs attention |
| Danger | #C62828 | End of support, destructive |
| Neutral/unknown | #64748B | Unknown, stale |
| Focus ring | #3B82F6 | Keyboard focus (halo on inputs) |
| Navigation | #0F1B2D background, #C5CEDB text, #8391A7 section labels, #213552 active, #60A5FA active marker | Sidebar |

Font: **Inter** (variable, bundled with the app, no external CDN), numeric/technical values in **IBM Plex Mono**. 14px body, 13px dense table, 11.5px uppercase table headers, 12px metadata, 22px page title, 15px section. Icons: **Lucide** only (one family), 16–18px, 1.75 stroke, always next to a text label in navigation.

Spacing scale 4/8/12/16/24/32 px. Standard control 36px, dense table row 40–44px, sidebar 232–248px, top bar 56px. Border radius 6px for controls, 8px for panels and drawers, 10px for dialogs, pill for status badges; no 20px rounded giant cards. Shadows subtle only for popovers/dialogs.

## Layout

Desktop >=1280px: persistent dark navy left navigation grouped into Inventory, Sources, Administration and System sections with icons; minimal 56px top bar with section / page context, asset search and the user menu (initials avatar, roles); jobs and notifications join it when those features exist, content max-width adaptable, section header with title + metadata + primary action, filter toolbar followed by table/content. Use 12-column grid internally where needed, but do not make everything a card grid.

At 768–1279px collapse optional panels; at <=767px use overlay nav and responsive stacked detail sections. Read-only inventory table may horizontally scroll on small screens with first column pinned. No essential content hidden behind hover alone.

## Components

Owner requested a broader visual refresh on 2026-11-05 while preserving the navy sidebar.
Shared headers use a fine divider and wrap actions responsively; filters/saved views sit
in compact white bordered toolbars; tables have consistent surface boundaries, restrained
header bands and a pale-blue selected row. Tabs use compact segmented surfaces with a
blue-tinted active state. Feedback has a clear bordered surface, small monochrome icon for
empty states, and a left status rule for errors/warnings. No new font/icon dependency,
gradients, oversized cards or decorative data. Existing 36px controls/40px rows remain.

- AssetTable: sticky header, column chooser, inline status chips, last-seen tooltip, keyboard focus, row selection, bulk toolbar, column widths remembered, saved views.
- AssetIdentityHeader: hostname + asset ID + category + 3 status dimensions, source freshness and verified/manual badges; not a banner.
- SourceEvidenceDrawer: observed value, normalized value, integration name, timestamp, confidence, conflict, override action.
- EOLFindingRow: explicit dimension, date type, evidence link, days left, exception badge, owner.
- IntegrationCard: small rectangular list/card with actual state Available/Configured/Degraded/Planned; no fake 'Connect' on Planned.
- GroupRuleBuilder: typed rows, AND/OR nesting, preview count, validation, explain why membership changed.
- ImportWizard: 4-step deterministic flow (file, mapping, validation, confirm) with detailed error table; do not disguise errors.
- ExportDialog: scope, format, related data, column selection, privacy note and queued progress.
- SettingsForm: grouped labels/help text, test connection button, save confirmation, saved status and audit link.

## Status color discipline

Supported=muted green, Near EOS=amber, End of Support=red, Unknown=gray, Stale=muted gray, Unmanaged=amber outline. Always show status text in addition to color; do not conflate device availability with EOL.

## Microinteractions

Fast subtle 100–160ms hover/focus; no bouncy animation, confetti, shimmer-heavy skeletons or meaningless motion. Navigation state must survive reload, table filter state may be encoded in URL. Toast only for completed actions; long jobs have durable progress panel. Confirm irreversible operations by naming affected record count.

## Accessibility

WCAG AA aim; visible keyboard focus, meaningful labels, tab order, contrast >=4.5:1 for normal text, screen-reader announcements for async job status, escape closes drawers, descriptive empty states and no color-only meaning.

## UI quality gate

Compare 1440x900 screenshot to this document. Check 25+ table rows with sensible density, text clipping, filter alignment, dialog consistency, long serial/hostname values and error states. Reject UI with big gradient title, every metric as giant rounded card, random icon colors, decorative graph with dummy data or inconsistent typography.
