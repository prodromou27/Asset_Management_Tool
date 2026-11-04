# Microsoft Graph (Intune) fixtures (sanitized)

`responses.json` holds invented Graph v1.0 `managedDevice` objects for
`GET /v1.0/deviceManagement/managedDevices`. The test fake serves them four per page and
links the pages with `@odata.nextLink` (`$skiptoken`). The tenant and application IDs
are made up.

All data is invented: `02:` locally administered MACs, made-up serials and GUIDs, and no
user names, e-mail addresses or phone numbers. Times are UTC (around 2026-11-02 08:00).

| Device | Scenario |
|---|---|
| …0001 LT-0042 | Dell Latitude laptop. Same manufacturer and serial as Endpoint Central fixture 301 (cross-source) |
| …0002 DT-0107 | HP EliteDesk desktop, co-managed (Configuration Manager + MDM), noncompliant, no Wi-Fi MAC |
| …0003 LT-0077 | Microsoft Surface Laptop (laptop by product line), MAC with separators |
| …0004 MBP-0012 | Apple MacBook Pro, macOS |
| …0005 | iPhone named "Alex's iPhone": not a valid hostname, so it is not used as one; no category |
| …0006 | Personal Android device with an empty serial (missing serial) |
| …0007 VDI-0003 | Hyper-V virtual machine ("Virtual Machine" model) |
| …0008 / …0009 KIOSK-01 | Two different devices with the same name (duplicate names; must never merge) |
| …0010 | Missing properties: no manufacturer, model or serial; "never" (`0001-01-01`) times; zero Entra ID |
| …0011 DT-0107 | Older, stale record of …0002 (same serial and Entra device ID: re-enrollment, shared identifiers) |
| …0012 LAB-PC-07 | OEM placeholders for manufacturer, model and serial, plus an unknown extra property (schema drift) |

**Property names come from the Graph v1.0 `managedDevice` documentation; the values are
not captures from a real tenant.** Before live use, compare them with a sanitized
response from the approved tenant (docs/17 DEC-07, ASM-33).

## Detected apps (Task 016a)

`detectedApps` lists four invented apps (one with `deviceCount` 0, one reported only on a
device that is not in the managed-device list); `detectedAppDevices` maps each app ID to the
managed device IDs the test fake returns from
`/deviceManagement/detectedApps/{id}/managedDevices`. Property names follow the Graph v1.0
`detectedApp` resource; verify against a sanitized tenant capture (DEC-07, ASM-54).
