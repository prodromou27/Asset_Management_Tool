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

## Proposed design tokens (adjust only via design review)

| Token | Light | Dark (optional later) |
|---|---|---|
| Page background | #F6F8FA | #101923 |
| Main surface | #FFFFFF | #18232E |
| Primary text | #17212B | #ECF1F5 |
| Secondary text | #5F6C79 | #A5B2BF |
| Hairline border | #E0E6EB | #33414D |
| Brand/action | #175E70 (deep teal) | #59A9B9 |
| Link | #175E70 | #79C1CE |
| Success | #16734A | #56BA8A |
| Warning | #A45A0C | #E7B35B |
| Danger | #B63636 | #E27D7D |
| Neutral/unknown | #65717D | #A8B3BB |
| Focus ring | #2F7F94 | #64BBD0 |

Font: IBM Plex Sans (or system sans fallback), numeric/technical values in IBM Plex Mono when helpful. 14px body, 13px dense table, 12px metadata, 20–24px page title, 16–18px section. Avoid mixing 3+ font families.

Spacing scale 4/8/12/16/24/32 px. Standard control 36px, dense table row 40–44px, sidebar 232–248px, top bar 56px. Border radius 4–6px in most surfaces, 8px for drawers; no 20px rounded giant cards. Shadows subtle only for popovers/dialogs.

## Layout

Desktop >=1280px: persistent dark-ish or neutral narrow left navigation, minimal 56px top bar (search, jobs, notifications, user), content max-width adaptable, section header with title + metadata + primary action, filter toolbar followed by table/content. Use 12-column grid internally where needed, but do not make everything a card grid.

At 768–1279px collapse optional panels; at <=767px use overlay nav and responsive stacked detail sections. Read-only inventory table may horizontally scroll on small screens with first column pinned. No essential content hidden behind hover alone.

## Components

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
