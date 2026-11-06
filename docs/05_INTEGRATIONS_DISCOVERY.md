# 05 | API Integrations and Discovery

**V1 sources are existing systems. Do not deploy another endpoint agent or network scanner.** Every connector is read-only by default, creates timestamped observations, records source version, uses checkpoints, and never directly edits manually approved asset fields.

Task 022d pins inventory HTTPS and fixed Entra authentication connections to validated
DNS addresses per request while retaining the original Host/SNI and certificate checks.
Mixed/empty/metadata answers are refused. Ambient proxy/CA environment overrides are
ignored; approved hosts need direct HTTPS egress and internal trust uses the explicit
CA file reference. Inventory remains GET-only; the existing Entra token POST is an
authentication exchange. See ASM-66 and `tasks/TASK022D_REPORT.md` for proof and limits.

## 1. LibreNMS (primary network discovery)

Connection: administrator-configured internal HTTPS base URL, a dedicated token and read-only GET requests. Validate TLS. Instance ID namespaces its device IDs.

| Documented route | Purpose |
|---|---|
| GET /api/v0/devices | List source devices, identifiers, hostname, OS/model and availability |
| GET /api/v0/devices/{id} | Full device metadata |
| GET /api/v0/devices/{id}/ports | Interface names/IDs and optional VLAN data |
| GET /api/v0/devices/{id}/ip | IP addresses per device |
| GET /api/v0/devices/{id}/fdb | MAC/port/VLAN learned evidence |
| GET /api/v0/devices/{id}/nac | Optional NAC associations when populated |
| GET /api/v0/inventory/{id}/all | Chassis/modules/physical parts, model/serial/firmware when exposed |

Do not assume LLDP/CDP topology has a stable public REST route. First test installed version and available data. If the API lacks an adjacency route, show verified interface/FDB evidence and defer richer topology. A MAC on a trunk is not an endpoint cable fact.

LibreNMS auto-discovery supports SNMP scanning and LLDP/CDP neighbors; ARP addition is optional/disabled by default and must be changed only by existing LibreNMS administrators. ITAM must never trigger network scanning or alter LibreNMS devices.

Test: at least switch, firewall, router, printer/UPS where available; compare API response fields and timestamps with UI. Rate-limit per-device enrichment and avoid pulling all switch FDB entries every minute.

## 2. ManageEngine Endpoint Central (on premises)

Connect over organization's verified HTTPS listener (documentation examples use 8383, but actual port may differ). Verify installed build and supported on-prem API generation. Current on-prem docs describe routes such as:

- GET /dcapi/inventory/viewData/scanComputers
- GET /dcapi/inventory/computers/{resourceID}/summary
- GET /dcapi/inventory/computers/{resourceID}/hardware
- GET /dcapi/inventory/computers/{resourceID}/osInformation
- GET /dcapi/inventory/computers/{resourceID}/softwareInfo
- GET /dcapi/inventory/computers/{resourceID}/network

Older installations may use /api/1.4/inventory routes. Select API route family only after a real version/test handshake. Request Inventory.READ-like least-privilege scope; no patch/device actions. Data: endpoint IDs, hostname/domain, OS/build, manufacturer/model/serial/BIOS, interface MAC/IP, installed apps, possibly monitor/peripheral info (must verify actual payload).

## 3. Microsoft Intune

Microsoft Graph managedDevices and detectedApps. Prefer application-only read permissions if supported for a given endpoint and consented. Preserve Entra device ID, Intune managedDevice ID, enrolled/lastSync timestamps, platform/OS, detected software and managed state. No policy modification, device wipe or enrollment action.

## 4. Microsoft Defender for Endpoint

Use Defender Machines API and appropriately licensed discovery data, optionally Advanced Hunting DeviceInfo if granted. Keep Defender machine ID, onboarding state, risk/last seen, discovered/unmanaged sightings, source age and tenant context. Security facts are enrichment, not asset purchase/license truth.

## 5. Microsoft 365 / Entra

Graph /subscribedSkus, user assignedLicenses and licenseAssignmentStates; directory identity relationships. Distinguish purchased/consumed/available SKU quantities from entitlements, billing and true license compliance. **Do not use user licenseDetails for unattended application-only sync** where the API does not support it.

## 6. Future connector catalogue

V1 UI can list Planned integrations: vCenter, Hyper-V/SCVMM, Dell/HPE management, Cisco/Fortinet/Check Point/Aruba/Huawei APIs, Azure/AWS, IT Glue, Autotask PSA, GLPI, ServiceNow, registrar/CA APIs. A Planned tile cannot be configured as Available. Generic REST importer is future work behind allowlists and schema validation, not arbitrary server-side URL fetching.

## Shared normalization

All sources implement test_connection, capabilities, fetch, normalize, map_external_id, sync_checkpoint, health. Store raw snapshot checksum and normalized fields. Stable matching hierarchy:

1. Instance+external device ID already linked.
2. Verified manufacturer+serial/chassis/VM UUID plus category corroboration.
3. Strong multiple corroborating keys under human review.
4. Hostname/IP/MAC/OUI/port alone = not safe for auto merge.

Show source per field and freshness. If a source stops reporting, mark source stale/missing, never delete the asset. Manually approved owner/site/category/asset tag stay locked until an authorized change.

## Sync defaults for initial pilot

Start full import, record baseline and checkpoint. Suggested schedules pending measurement: LibreNMS device metadata every 6–12h and expensive per-device FDB daily; Endpoint Central every 12–24h; Intune/Defender daily; M365 license quantities daily. Expose per-connector schedule in Admin; apply retries and official API throttling. No vendor API call during user-facing asset GET.

## Failure behavior

Expired token: integration Degraded, job failed with actionable error, asset history kept. Missing field: Unknown plus source freshness. Partial paginated response: retain checkpoint, no mass removal. User disables integration: stop jobs, keep links/history. Source IDs must be scoped to instance/tenant.

## Test fixtures

Commit sanitized JSON fixtures for each connector: normal, empty, missing serial, duplicate hostname, changed IP, pagination, unauthorized, rate limit, incomplete date, schema drift. Never check in production API data with personal/secret fields.
