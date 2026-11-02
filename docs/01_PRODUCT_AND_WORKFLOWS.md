# 01 | Functional Modules and User Workflows

## Personas and scope

System Administrator (deployment, integrations, credentials, users), ITAM Manager (ownership/corrections/EOL decisions), Infrastructure Engineer (device facts/discovery), Security Analyst (unsupported equipment/security integration), Procurement Operator (cost/license entries), Auditor (approved read-only).

## Asset taxonomy

Hierarchical categories, editable by admins: Workstations (desktop/laptop/thin client); Servers (physical/VM/hypervisor); Networking (switch/router/AP/controller/load balancer); Security (firewall/VPN/WAF); Printers/Scanners; Voice & AV (IP phone/TV/conference); Storage/Backup; Power (UPS/PDU); Peripherals (monitor/dock); Software; Licenses/Subscriptions; Domain; Certificate; Other/Unknown. Custom types and structured fields are allowed.

An asset may have no IP, serial or agent. Asset status has **three dimensions**:

- Business: Ordered, In Stock, Deployed, Assigned, In Repair, Retired, Disposed, Lost.
- Observation: Recently Seen, Stale, Unreachable, Never Scanned, Manual Only.
- Support: Supported, EOL Announced, Expiring, Security Maintenance Ended, EOS, Unknown, Not Announced.

## Core user journeys

| Journey | Required behavior |
|---|---|
| View inventory | Search all authorized assets; filter category, vendor, site, owner, support, source, last seen; save view and export |
| Register asset | Select template/category; enter identifiers, location, owner, notes, attachments; save with audit |
| Reclassify | Change category, preview template impact, require reason, keep source history, record actor |
| Reconcile discovery | Show new observation, possible existing assets, strong/weak matching keys; approve link/create/hold/reject |
| View evidence | Every discovered field shows source, timestamp, confidence, locked/manual state and conflicts |
| Make asset group | Static members or typed dynamic AND/OR conditions; preview, save, export, set report recipients |
| Review EOL | Select exact manufacturer/model/OS version; show official milestone/evidence, assessed status, days remaining, exception |
| Manage license | Distinguish product/SKU, entitlement, allocation, observed installation, subscription snapshot |
| Track domain/certificate | Owner, registrar when known, domain expiry, TLS certificate/endpoint, alert thresholds, replacement history |
| Bulk import | Upload CSV/XLSX, map columns, validate, dry-run, preview match actions, commit, download row errors |
| Export | Current filtered view, selection or all authorized records; CSV/XLSX/JSON, async large jobs, audit |
| Administer | Users/roles/sites, integration instances, EOL imports, email, alerts, jobs, backups and restore diagnostics |

## Relationship rules

Use typed time-bounded relationships: attached-to, assigned-to, located-in, installed-on, hosted-on, member-of, connected-to (observed vs confirmed), protects, depends-on, managed-by, subscribed-by.
Examples: monitor attached to workstation; UPS protects rack; license allocated to user; certificate deployed at service host:port; switch port sees MAC. Preserve history on reassignment.

## Data quality workflows

Dedicated queues: New/Unmanaged, Duplicate Candidates, Model Unknown, EOL Evidence Missing, Source Stale, Owner Missing, Certificate Expiring, Import Errors. Each finding has assignee, severity, evidence and resolution state; no silent normalization of uncertain values.

## Success metrics

- No known false auto-merges in curated pilot.
- Repeated sync/import is idempotent.
- All discovered assets show source and freshness.
- EOL findings cite source, exact product match and policy/date type.
- Admin config for email, accounts and backups is tested before production.
- Every authorized list has export, and all writable business entities have an import template or documented API path.
