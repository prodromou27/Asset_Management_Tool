# Discovery fixtures (sanitized)

Fictitious data only: RFC 5737 documentation IPs (192.0.2.0/24, 198.51.100.0/24),
locally administered MACs (02:…), `.example` domains and made-up serials. Never add
production exports here (docs/05 "Test fixtures").

Files are JSON arrays of **source records**, the adapter-neutral shape every future
connector (LibreNMS, Endpoint Central, Intune, Defender) will emit after mapping its
own API payload. Fields:

| Field | Required | Notes |
|---|---|---|
| `external_id` | yes | Stable ID within the integration instance |
| `observed_at` | yes | RFC 3339 with offset |
| `manufacturer`, `model`, `serial` | no | Placeholder serials become unknown |
| `hostname` / `hostnames` / `fqdn` | no | Lower-cased, trailing dot removed |
| `interfaces[]` | no | `{name, mac, ips[]}` |
| `ip_addresses[]` | no | `{address, vrf, interface}`; site comes from the instance |
| `os_name`, `os_version`, `firmware_version` | no | |
| `hardware_uuid` | no | BIOS/VM UUID; strong identifier across sources |
| `device_type` | no | Category hint, e.g. `switch`, `laptop`, `ups` |
| `source_version` | no | Source software version, recorded on the observation |

`network_devices.json` covers: normal switch, firewall with two interfaces, printer
with a placeholder serial, UPS without any IP, and a second switch reusing the first
switch's hostname (must not merge on hostname alone).

Load into an instance created under Administration → Integrations (source "Sanitized
fixture import"):

```bash
scripts/compose.sh dev cp fixtures/discovery/network_devices.json api:/tmp/network_devices.json
scripts/compose.sh dev exec api python manage.py load_observations \
  --instance "Fixture network" --file /tmp/network_devices.json --mode full
```
