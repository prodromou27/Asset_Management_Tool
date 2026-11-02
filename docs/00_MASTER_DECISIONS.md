# 00 | Product Constitution and Scope Lock

Document status: v1 implementation baseline, 2 November 2026. This document is **normative**; if another document conflicts with it, this document wins and the agent must flag the conflict.

## Product and deployment

- Product: custom IT Asset Management and EOL/EOS platform, **single organization** with multiple locations, teams and sites.
- Scale: 2,000–10,000 network-connected devices and at least 20,000 other asset/entitlement records, with growing history.
- Deployment: one **AlmaLinux OS 10.2** host/VM initially (latest stable verified 2 November 2026), Docker Engine + Docker Compose v2, internal HTTPS FQDN, PostgreSQL persistent storage. Recheck the latest stable GA release before deployment; never use beta or AlmaLinux Kitten as a production default.
- Language and UI: English, desktop-first, accessible, dense and professional.
- Runtime: free/open-source core; commercial data feeds are optional external entitlements.
- No mandatory LibreNMS agent installation: the organization **already has LibreNMS**, and its API is V1's primary network source.
- Endpoint Central is **on-premises**, not cloud.
- Microsoft sources: Intune, Defender for Endpoint and Microsoft 365/Entra. The client grants application permissions as available.
- Use GLPI, IT Glue and Network Glue **as product/design benchmarks**; build original code, schema and UI.

## Required V1 modules

1. Asset register: physical, virtual and logical records, custom category templates, hostname, many IPs/MACs, vendor/model/serial/OS/firmware, ownership, location, history.
2. Manual and dynamic asset groups; category and group membership are different concerns.
3. External source connectors, sync jobs, observations, identity reconciliation and source-field authority.
4. Native **discovery UI**, backed by LibreNMS API; no duplicate active scanner in V1.
5. Hardware, OS and firmware EOL/EOS with versioned evidence and Unknown/Unverified states.
6. Installed software, Microsoft 365 SKU inventory/assignments, manual licenses and subscriptions.
7. Monitors, IP phones, TVs, printers, UPS, network appliances and assets with no IP.
8. Domains, TLS certificates, observed deployments and expiration notifications.
9. Vendor/model catalogues, sites, departments, owners, notes, documents, typed relationships.
10. Import/export service, dashboards, saved filters, CSV/XLSX/JSON reporting and scheduled email.
11. User management, authentication, RBAC, audit, SMTP, integration credentials, administration, backup/restore, diagnostics and health.

## Out of scope for V1

- Full ITSM incident/change/ticketing engine and password vault.
- Agent deployment or remote endpoint actions.
- Vulnerability scanning, penetration testing or arbitrary network scanning.
- Comprehensive all-vendor SAM license compliance/optimization.
- Automated physical cabling certainty; topology is evidence-based and may be partial.
- Full procurement/depreciation/payables, advanced rack/DCIM or application dependency mapping.
- Multi-tenant/MSP isolation, high-availability clustering, multi-node database at initial release.
- Automatic source write-back (reconfigure, block, retire or patch remote assets).

## Canonical behavior rules

- One canonical asset can have many source observations, source IDs, interfaces, IPs, MACs, software installations and related assets.
- IP address, hostname, MAC OUI and model name alone are not safe merge keys.
- Source refresh never removes an asset or overrides a manually locked field; it can flag conflict/staleness.
- EOL = evidence-backed date/status for an **exact** matched hardware model/part or software release. No match means Unknown.
- Business status, observation status and support status are independent.
- User may change an asset's category; record before/after and preserve all raw observations and relationships.
- Static groups persist, dynamic groups evaluate typed filters; neither is an RBAC authorization grant.
- All exports obey user/site/field permissions; imported source evidence is immutable.
- Any vendor API can appear in the catalogue as Planned, but cannot be called Available until its tested adapter works.
- Users and SMTP/backup services must be configurable through secure admin settings and deployment secrets.

## Delivery priorities

P0: secure platform foundation + core assets/groups + read-only connectors + EOL + administration/SMTP/backups + import/export + tests.
P1: richer device/vendor coverage, advanced contracts, vendor warranty APIs, direct OS enrichment and deeper topology.
P2: forecasting, full SAM optimization, deeper CMDB/ITSM.

## Source of truth

The ITAM PostgreSQL schema is authoritative for curated asset identity, site, owner, category, groups and manual fields.
External systems are authoritative **only for the facts they observe**: LibreNMS network inventory; Endpoint Central managed OS/hardware/software; Intune enrollment; Defender security posture; Microsoft 365 SKU/assignment; manufacturer EOL source.

## Blockers that require human approval

Production FQDN/TLS issuance, host CPU architecture and Docker compatibility with AlmaLinux OS 10.2, actual site CIDRs, live API token/tenant consent, identity provider, SMTP relay/credentials, backup destination/key, restore objectives, real EOL vendor entitlements. See docs/17_ADR_OPEN_DECISIONS.md. Use fixtures and configuration placeholders until approved.
