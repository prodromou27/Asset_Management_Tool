# Defender for Endpoint API fixtures (sanitized)

`responses.json` holds invented machine objects for
`GET https://api.security.microsoft.com/api/machines`. The test fake pages them with
`$top`/`$skip` and, on request, with `@odata.nextLink`. The tenant matches the Intune
fixture tenant, so Entra device IDs can be compared across the two sources. The
application ID is made up.

All data is invented: RFC 5737 addresses, `02:` locally administered MACs, `.example`
names and made-up IDs. Times are UTC (around 2026-11-02 08:00).

| Machine (…d01–d10) | Scenario |
|---|---|
| d01 lt-0042 | Same Entra device ID as Intune …0001 (cross-source); tags; link-local and loopback addresses ignored; 7-digit fractional seconds |
| d02 dt-0107 | Impaired communication, high risk and exposure; Entra ID of Intune …0002 |
| d03 srv-file-01 | Windows Server without an Entra device ID (missing ID, server hint) |
| d04 / d05 kiosk-01 | Same DNS name on two machines; only d04 has an Entra ID (duplicate names; never merged) |
| d06 vdi-0003 | Azure VM (`vmMetadata`): virtual machine hint |
| d07 lnx-build-02 | Linux, no sensor data, last seen two weeks ago |
| d08 unmanaged-host-12 | Discovered, not onboarded (`CanBeOnboarded`), short name |
| d09 mbp-0012 | macOS, no `lastSeen` (falls back to `firstSeen` with a warning) |
| d10 lab-pc-07 | Zero Entra ID (treated as missing) and an unknown extra property (schema drift) |

**Property names and enum values come from the Defender for Endpoint API documentation,
not a real tenant.** Before live use, compare them with a sanitized response from the
approved tenant (docs/17 DEC-16, ASM-37).
