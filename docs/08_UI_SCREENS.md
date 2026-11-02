# 08 | Screen-by-Screen UI Specification

Use 07_UI_DESIGN_SYSTEM.md for tokens and visual rules. Build real workflows with mock typed data first, then connect API. All screens must have loading, empty, error, denied and stale-source states.

## Information architecture

Sidebar: Overview; Assets; Discovery; Lifecycle; Software & Licenses; Domains & Certificates; Groups; Reports; Documents; Integrations; Administration. Put Settings/Account in top-bar user menu. Admin menus shown by role, but API permissions always enforced.

## 1. Overview

- Header: organization scope/site filter, 'Inventory overview', last synchronized time.
- Compact KPI strip: Total Assets, Unknown/Unclassified, EOL/EOS, Certificates Expiring, Stale Sources. Each navigates to filtered underlying list.
- Main two-column zone: lifecycle actions table (not a pie chart) and data-quality/action queue.
- Below: source health table and category/site distribution simple bars when meaningful.
- Never display demo percentages as real metrics.

## 2. Assets list

- Top: title + count, category tabs/breadcrumb, Add Asset, Import, Export.
- Toolbar: global search, filter chips (site/type/manufacturer/status/owner/source), Save View, Columns.
- Table: Name/Hostname, Category, Manufacturer/Model, Serial, Primary IP, Site, Owner, Support, Last Seen, Sources. Multi-select bulk Group/Owner/Category, archive only with separate approval.
- Row click opens full detail, no surprise inline modifications.

## 3. Asset detail

- Identity header with editable display name, asset tag, category (Change Category action), source badges.
- Metadata grid: manufacturer/model/part/serial/asset state/owner/location.
- Tabs: Overview, Hardware, Interfaces/IPs, OS/Firmware, Software, Lifecycle, Groups, Relationships, Documents, History, Observations.
- Each field displays source timestamp/lock/conflict. Changing category shows migration/field retention preview.

## 4. Discovery

- Source selector (LibreNMS primary), last successful job, total devices, new/unknown candidates, source errors.
- Tabs: Discovered Devices, Reconciliation Queue, Network Evidence, Source Coverage, Job Runs.
- Discovery table includes hostname, IPs, MACs, model, category suggestion/confidence, managed/unknown, last seen and source.
- Network Evidence view lists verified interface/FDB connections with timestamp/confidence. Never fabricate unavailable LLDP topology.
- Provide link to open the relevant device in LibreNMS (approved, fixed base URL).

## 5. Lifecycle

- Tabs: Hardware, Operating Systems, Firmware, Installed Software, Exceptions, Sources.
- Filters: dimension, verified status, vendor, site, severity, milestone type, date window.
- Table: Asset, Product/version, Milestone, Date, Days Left, Evidence, Owner, Approval/Exception.
- Details drawer compares raw/normalized identifiers and shows exact source. Unknown evidence gets explicit resolution CTA.

## 6. Software & Licenses

- Products/Versions, Installations, Entitlements, Allocations, M365 Subscriptions.
- Different totals clearly labeled: observed installations, purchased quantity, assigned users and available seats.
- One SKU drilldown shows source tenant, consumed units, assignment method, snapshot timestamp.

## 7. Domains & Certificates

- Domains table: FQDN, Owner, Registrar, Registration Expiry or Unknown, Renewal Status.
- Certificates table: SAN summary, Issuer, Fingerprint, NotAfter, Days Left, Linked Deployments/Services.
- Detail: timeline of observations and rotation; show endpoint host:port and last observed.
- New TLS endpoint requires approved hostname and port, no arbitrary URL.

## 8. Groups

- Groups list: name, Static/Dynamic, description, member count, owner, last evaluated.
- Create/Edit group: choose kind, enter name/ownership; static member selector OR dynamic filter builder with live preview; save and audit.
- Group detail: members table, lifecycle stats, source coverage, export, rule version/history, notification policy.

## 9. Integrations

- Catalogue by Available/Configured/Planned, search by provider.
- Detail/wizard: URL/tenant, required permissions, token/vault reference, test, schema preview, site mapping, schedule, activate.
- Instance page: last sync, records fetched/created/linked/review, failures, API throttling, capability gaps; no sensitive token display.

## 10. Import / Export Center

- Recent jobs table with initiator, data family, type, status, counts, downloadable result.
- Import: template -> upload -> map -> preview creates/updates/skips/errors -> confirm -> background processing.
- Export: choose data family, selection/filter, columns, format, related tables, execute -> download with expiry.

## 11. Administration

Sections: General/Organization, Sites & Locations, Users & Roles, Identity Providers, SMTP & Notifications, Integrations, Lifecycle Sources, Jobs/Schedules, Storage, Backups & Restore, Audit, Health & Diagnostics.
- Use clear Setup incomplete badges and test buttons for SMTP, SSO, API connectivity, storage and backups.
- Admin forms must say where credentials are stored and show redacted values only.
- Backup screen shows last successful backup, latest test restore date, RPO/RTO objective, encryption/off-host status and failure alerts. It does **not** execute destructive restore in the ordinary admin page.

## Required interaction consistency

All destructive or high-impact bulk actions show affected count + required reason + confirmation. No client-side-only authorization. All long jobs survive refresh. Unavailable data is shown as 'Unknown' or 'Not reported', not a blank misleading dash when interpretation matters.
