# LibreNMS API fixtures (sanitized)

`api/responses.json` maps LibreNMS API v0 paths (without `/api/v0`) to response
bodies in the LibreNMS envelope (`{"status": "ok", ...}` / `{"status": "error", ...}`).
All data is fictitious: RFC 5737/3849 addresses, `02:` locally administered MACs,
`.example` hostnames, invented serials. SNMP credential fields carry fake values so
tests prove they are stripped before storage.

| Device | Vendor | Scenario |
|---|---|---|
| 101 | Cisco Catalyst (iosxe) | Normal; stacked chassis (2 serials); IP in VRF `MGMT` |
| 102 | Fortinet FortiGate | Firewall; inventory route returns "No inventory found" |
| 103 | HPE Aruba CX | Vendor from chassis inventory |
| 104 | Huawei VRP | Empty inventory |
| 105 | Check Point Gaia | Missing serial everywhere |
| 106 | Dell OS10 | Serial only in chassis inventory; IPv6 address |
| 107 | Unknown vendor | IP-literal hostname, placeholder serial, no IPs |
| 108 | Cisco | Duplicate of 101 (same serial, new device ID, old poll) |
| 109 | Cisco ISR | Device serial and chassis serial conflict |
| 110 | APC UPS | Disabled in LibreNMS |

Evidence: `/resources/fdb` (MACs on device 101 port Gi1/0/1, one known, one unknown)
and `/resources/links` (one LLDP neighbour that is a known device, one CDP neighbour
that is not).

Tests serve these through `httpx.MockTransport`; nothing contacts a network. Before
live use, capture the installed version's real responses (sanitized) and compare field
names; adjust `mapping.py` if they differ.
