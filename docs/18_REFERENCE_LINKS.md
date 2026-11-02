# 18 | Source References and Revalidation Policy

This pack contains implementation requirements, not copies of vendor source code. Before writing a new connector or pinning a library version, check the current official docs for the installed release. Never assume a referenced API is licensed/available in this environment.

## Product pattern sources

- GLPI source repository: https://github.com/glpi-project/glpi
- GLPI assets: https://help.glpi-project.org/documentation/modules/assets
- GLPI custom asset definitions: https://help.glpi-project.org/documentation/modules/configuration/asset-definitions
- GLPI GPL v3: https://github.com/glpi-project/glpi/blob/12.0/bugfixes/LICENSE
- Network Glue: https://www.itglue.com/networkglue/
- IT Glue flexible assets: https://www.itglue.com/features/flexible-assets/

## Read-only discovery APIs

- LibreNMS auto-discovery: https://docs.librenms.org/Extensions/Auto-Discovery/
- LibreNMS devices API: https://docs.librenms.org/API/Devices/
- LibreNMS inventory API: https://docs.librenms.org/API/Inventory/
- LibreNMS ports API: https://docs.librenms.org/API/Ports/
- Endpoint Central on-prem API index: https://www.manageengine.com/products/desktop-central/help/api/onpremise/api-index.html
- Endpoint Central on-prem hardware: https://www.manageengine.com/products/desktop-central/help/api/onpremise/inventory-get-all-hardware-details.html
- Intune managed devices API: https://learn.microsoft.com/en-us/graph/api/intune-devices-manageddevice-list?view=graph-rest-1.0
- Microsoft Graph subscribed SKUs: https://learn.microsoft.com/en-us/graph/api/subscribedsku-list?view=graph-rest-1.0
- Graph user license details and app-only limits: https://learn.microsoft.com/en-us/graph/api/user-list-licensedetails?view=graph-rest-1.0
- Defender machines API: https://learn.microsoft.com/en-us/defender-endpoint/api/get-machines

## Lifecycle sources

- Cisco EoX: https://developer.cisco.com/docs/support-apis/eox/
- Fortinet lifecycle: https://docs.fortinet.com/document/forticloud/26.2.0/forticare/419858/product-life-cycle
- Huawei info finder: https://info.support.huawei.com/info-finder/
- Check Point lifecycle: https://www.checkpoint.com/support-services/support-life-cycle-policy/
- endoflife.date API (supplementary, not sole official authority): https://endoflife.date/docs/api/v1/

## Deployment/operations

- AlmaLinux release notes and GA state (10.2 latest stable as of 2026-11-02; 10.3 beta): https://wiki.almalinux.org/release-notes/
- AlmaLinux 10.2 release notes: https://wiki.almalinux.org/release-notes/10.2
- Docker Engine RHEL 10 reference (AlmaLinux derivative requires compatibility test; Docker does not verify derivatives): https://docs.docker.com/engine/install/rhel/
- Docker supported platforms and derivative caveat: https://docs.docker.com/engine/install/
- Docker Compose plugin: https://docs.docker.com/compose/install/linux/
- Docker Compose production: https://docs.docker.com/compose/how-tos/production/
- Docker volumes: https://docs.docker.com/engine/storage/volumes/
- Docker Compose SELinux mount flags: https://docs.docker.com/reference/compose-file/services/
- Django deployment checklist: https://docs.djangoproject.com/en/stable/howto/deployment/checklist/
- PostgreSQL backup/restore: https://www.postgresql.org/docs/current/backup.html

## Source quality rules

1. Manufacturer support milestones: verified authoritative source first, preserve raw artifact/checksum.
2. API capabilities: use installed build/version behavior, record test fixture and timestamp.
3. Infrastructure: security defaults from current official Docker/Django/PostgreSQL documentation; pin tested versions.
4. All third-party code/license: review SPDX/license and dependency policy before copying.
5. Reject invented source citations, fake hardware serials and assumed lifecycle data.
