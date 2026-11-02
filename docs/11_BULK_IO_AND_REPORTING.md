# 11 | Imports, Exports, Reporting and Groups

## Import

Every writable business entity family has a versioned template with required columns and sample-safe documentation. V1 CSV/XLSX: assets, locations, categories, groups/static memberships, manufacturers/models, manually maintained software entitlements, domains, approved TLS endpoints and relationship metadata. Do not allow users to fabricate LibreNMS observations or Graph license counts via import.

Wizard steps:

1. Select family/template, upload, detect encoding and columns.
2. Map column names, FK/reference keys, category templates and types.
3. Dry-run with totals Create/Update/Skip/Conflict/Error; downloadable row errors.
4. Choose Create Only / Update Matched / Upsert, conflict policies, approve, enqueue, show progress/receipt.

For update matching prefer immutable asset UUID or approved asset tag/serial+manufacturer as defined by family; **never IP/hostname-only**. Re-import has idempotency key, checksum, row-level results. Manual field locks and source authority must be honored. Missing rows never delete/retire assets. Bulk rollback only for changes with no subsequent edits; else supervised correction report. Bound file size and row counts, parse as stream, reject malicious formulas/paths, preserve originals encrypted for retention period.

## Export

Every supported data family, list and report exposes permitted export. Formats: UTF-8 CSV, XLSX and versioned JSON. Filtered current view, selected rows or all authorized records. Include provenance, category/group/owner, source freshness, EOL evidence IDs and export timestamp. 1:N related data (MAC/IP/software/group memberships) uses separate sheets/files or structured JSON, never one flattened lossy field.

Large export runs as async job, stores private encrypted artifact, short-lived authenticated download, deletion policy, count and audit. CSV formula injection protection on all text cells; XLSX sheet limits handled by segmentation. Field/site masking applies at server export query, not after file creation.

Import template names / stable keys:

| Family | Required match key | Typical columns |
|---|---|---|
| Asset | id, or approved asset_tag; serial+vendor review-only | name, category, manufacturer, model, serial, site, owner |
| Group | group external key or approved name+scope | name, kind, parent, owner, validated filters |
| Group membership | group key + asset ID/tag | membership source, effective date |
| License | vendor SKU + entitlement ID | product, quantity, term, assigned resource |
| Domain | normalized owned FQDN | owner, registrar, verified expiry |
| TLS endpoint | approved host+port+SNI | asset/service, owner, enabled |
| Relationship | type + two stable IDs + time validity | endpoints, evidence, notes |

## Reports

- Inventory by category/site/vendor/owner and stale status.
- EOL/EOS by dimension/milestone/priority/evidence.
- Unknown/Unmanaged and missing Defender/Endpoint Central coverage.
- Software installations vs license subscriptions/allocations, no invented compliance.
- Domains/certificates by expiration.
- Group-based replacement and ownership reports.
- Integration health and last successful sync.
- Import/export logs and audit events for authorized auditors.

Saved views: filter AST, sort, columns and owner/site scope. Scheduled report delivery via SMTP outbox with minimal sensitive attachment by default. Option to link to authenticated private export rather than attaching full inventory in email.

## Groups

Static: manual members, bulk membership import, audited removals.
Dynamic: typed AND/OR field operators, evaluation preview and versioned membership; rerun when key facts change.
Nested group references must reject cycles; group membership cannot confer access. Group export is site/RBAC filtered and includes timestamp and source membership semantics.

## Performance

Target at least 10k devices, 20k other records and 1m software installations; paginate tables, server-side filter/search, background large exports, index group criteria. Tune concurrency based on tests, not a fictional throughput guarantee.
