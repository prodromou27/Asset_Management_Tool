# 03 | Relational Data Model and Identity

Use PostgreSQL UUID primary keys for canonical objects, timestamps with timezone, and controlled enums/lookup tables. Implement migrations per bounded feature. Index normalized search keys and active statuses. Avoid a single enormous JSON-only assets table.

## Canonical tables

| Group | Core tables and fields |
|---|---|
| Organization | organizations (single row), sites (parent/site code), departments, locations, teams |
| Identity | users, identity_links (OIDC/LDAP/local), roles, permissions, user_scope_grants, service_accounts, api_tokens (hashed) |
| Assets | assets (UUID, category, asset_tag, manufacturer/model, serial, business/observation/support states, site, owner, archived_at); asset_categories (parent/template); custom_field_definitions/values; asset_history |
| Hardware | manufacturers, product_models (canonical part), asset_components, interfaces, network_address_observations (inet, VRF/site), network_identifiers (MAC/serial/chassis), network_neighbor_evidence |
| Discovery | discovery_sources, integration_instances, integration_runs, source_asset_links (unique source+external ID), raw_observations (raw JSONB and checksum), reconciliation_candidates, field_authority/locks |
| Groups | asset_groups (static/dynamic, parent, owner), asset_group_rules (versioned typed AST), asset_group_memberships (explicit/evaluated, source, dates) |
| Software | software_products, software_versions, software_installations (asset/version/source/first/last observed) |
| Licensing | license_products, license_entitlements, license_allocations (user/asset), subscription_snapshots (tenant/SKU/quantities/timestamp), directory_objects and relationships |
| Lifecycle | lifecycle_products, lifecycle_milestones (type/date/evidence), lifecycle_sources (publisher/document/checksum/date), asset_lifecycle_matches (dimension/method/confidence/approval), assessments, exceptions |
| Domains | domain_registrations (FQDN/registrar/owner/expiry), dns_observations, tls_certificates (SHA256 fingerprint, issuer, SANs, notBefore/after), tls_deployments (host:port, cert, asset/service, last seen) |
| Relationships | asset_relationships (typed, confidence, evidence ref, approved by, valid_from/to), documents, attachments |
| Operations | import_jobs/rows, export_jobs, notification_templates, notification_rules, notification_outbox, notification_deliveries, smtp_profiles, backup_jobs/backup_artifacts, settings, audit_events |

## Critical constraints

- assets.asset_tag unique when non-null within organization; **do not** require an IP/hostname/serial.
- source_asset_links unique (source_id, external_id). A source ID is stable **within that source instance**, not across products.
- No globally unique constraint on IP, hostname, model, ifIndex or raw MAC. Addresses are time-varying and scoped by site/VRF/observed_at.
- Unique certificate identity by SHA-256 fingerprint; deployments separate because one certificate can serve many endpoints.
- EOL milestone belongs to a normalized lifecycle product/release with a verifiable source; asset assessment references approved exact match.
- Source payloads append or version; canonical fields are updated by reconciliation policy with audit and prior values.
- Archived assets retain IDs, history and references. No mass deletion when source stops reporting.
- Relationships have typed endpoints and provenance. A MAC seen on an uplink is not proof of physical cable.
- Groups are not user access grants; RBAC always evaluated independently.

## Matching precedence

1. Existing source+external stable ID match: resolve existing asset.
2. Verified exact manufacturer+serial+chassis/VM UUID and corroborating class: candidate strong match.
3. Multiple corroborating non-exclusive identifiers (MAC, device UUID, source IDs) with same site/class: manual or policy-controlled high-confidence candidate.
4. IP/hostname/model/port alone: weak; never auto-merge.
5. Conflicting strong IDs: quarantine candidate for human review.

Store which rule matched, score, source keys, alternatives, reviewer and reversible merge transaction. Manual locked values (owner, site, asset tag, category, EOL override) win over technical discovery and generate conflict notices.

## Group rule representation

Store validated JSON AST with known fields and operators eq, in, contains, before, after, and/or/not. Server compiles AST into safe parameterized ORM conditions. No raw SQL/JS/Python from browser. Evaluate in queued jobs for large groups, store rule version/evaluation time and membership snapshots; nested group parents must be acyclic.

## Suggested indexes

- assets: site/category/status; normalized asset tag; manufacturer/model/serial; archived_at.
- observation links: source_id+external_id; asset_id+observed_at; source+last_seen.
- network observations: site/VRF+inet+time, normalized MAC+time.
- lifecycle: product/milestone_type/date; assessment status/deadline; evidence ID.
- installations: asset/version; licensing: tenant/SKU and allocation target.
- jobs: state/created_at, source/date; audit: object+timestamp and actor+timestamp.

## Migration policy

Every schema change has migration and rollback guidance; test with representative 10k assets and >=1m software installations. Use immutable identity columns, FK constraints, soft-archive, optimistic record version for concurrent edits and background materialized reporting views where measured. Never drop business fields when asset category changes; keep values in versioned typed extensions.
