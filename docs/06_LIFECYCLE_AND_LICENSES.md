# 06 | EOL/EOS, Software and License Intelligence

## Lifecycle dimensions

Track independently: physical hardware model/part, firmware/OS release, installed software/product version, contract/warranty, domain expiry and certificate expiration. Never collapse these into one boolean.

| State | Meaning |
|---|---|
| Supported | An authoritative source confirms support within the relevant lifecycle policy |
| Announced | An official EOL/EOS date exists but has not reached threshold |
| Expiring | Verified milestone is approaching within policy threshold |
| Security Maintenance Ended | Verified security support date has passed |
| End of Support | Verified support milestone has passed |
| Not Announced | Product verified, publisher has not issued applicable date |
| Unknown | Insufficient exact product identification or lifecycle evidence |
| Unverified | Candidate lifecycle match exists but needs approval |

Use separate milestone types such as end-of-sale, end-of-maintenance, end-of-security-support and end-of-support. Each has source ID, date, retrieved date, publisher, original file/URL and interpretation notes. The status is calculated, not manually guessed.

## Source strategy

Preference: official manufacturer API or authenticated export, official bulletin/support lifecycle page, verified vendor record, then community endoflife.date as supplementary indication with explicit lower-confidence label. Cisco EoX, Fortinet product lifecycle, Check Point support policy, HPE/Aruba, Huawei Info-Finder, Dell warranties and Microsoft Windows releases have different semantics. Implement **adapters**, not a universal parser that assumes one date type. Access to paid support portals is not assumed.

## Processing workflow

1. Collect vendor, exact part/model, OS/version/build and source evidence.
2. Normalize publisher aliases and model SKUs; preserve original string.
3. Match to lifecycle catalogue with confidence and exact dimension.
4. Queue uncertain matches for reviewer; avoid declaring Supported/Unsupported automatically.
5. Apply timezone-safe date thresholds; calculate 365/180/90/30 days.
6. Persist assessment snapshots and previous values when vendor updates dates.
7. Notify owner/group by policy; exceptions have reviewer, reason, compensating controls and expiry.

## EOL reporting

Columns: Asset, Site, Category, Vendor, Model/Part, OS/Firmware, Dimension, Status, Milestone Type, Date, Days Remaining, Criticality, Owner, Evidence Source, Verification Timestamp, Exception. Export all permitted rows, including Unknown as a separate population.

## Software and license model

- Software product: publisher and canonical name.
- Software version: edition/build and release.
- Installation: asset, version, discovered source, first/last seen.
- License product: vendor SKU and metric (user/device/core/subscription).
- Entitlement: purchased units, agreement, term and owner, manual or trusted source.
- Allocation: user/asset/group relation, effective period, method.
- Microsoft 365 subscription snapshot: tenant+SKU, purchased/consumed/available as of timestamp.

One user with a group-assigned M365 SKU must not be double-counted as another direct license. Graph tenant inventory is not a billing agreement. V1 reports inventory/allocation, **not** comprehensive license compliance for complex products.

## Domain and TLS

Domain registration: normalized name, owner, registrar when known, domain renewal date and evidence. Unknown registrar expiration remains Unknown.
TLS certificate: fingerprint, subject, SANs, issuer, notBefore/notAfter, metadata (no private keys).
Deployment: host/IP, SNI, port, certificate and observation date. One certificate can serve multiple host:port endpoints. Alert thresholds: 90/60/30/14/7 days and expired.

Only explicitly approved domains and TLS endpoints may be checked. Never allow arbitrary URL requests, redirects to internal metadata services or unchecked host/port values.

## Review and test

Fixture cases: hardware supported while firmware EOS, duplicate aliases, no serial, unknown vendor date, updated bulletin, certificate rotation, domain expiry unknown, multiple TLS deployments, expired exception, changed M365 purchased units. All findings must show evidence.
