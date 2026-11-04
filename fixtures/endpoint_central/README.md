# Endpoint Central API fixtures (sanitized)

`api/responses.json` holds fictitious responses for both on-premises API generations:

- `api_1_4`: `serverproperties`, a 10-computer `scancomputers` list (served page by page by
  the test fake) and one `compdetailssummary` per computer.
- `dcapi`: three computers in a camelCase list envelope, each with `summary`, `hardware`,
  `osInformation` and `network` documents.

All data is invented: RFC 5737 addresses, `02:` locally administered MACs, `.example`
names and made-up serials. Times are epoch milliseconds (2026-11-02 08:00 UTC).

| Resource | Scenario |
|---|---|
| 301 | Dell laptop: serial, SMBIOS UUID, two adapters (one without an IP) |
| 302 | HP desktop ("Small Form Factor" chassis) |
| 303 | Dell server: Windows Server, two IPs on one adapter |
| 304 | VMware virtual machine |
| 305 | "To be filled by O.E.M." manufacturer, model and serial |
| 306 | Same hostname as 301 in another domain (must never merge) |
| 307 | Apple MacBook (macOS, build number) |
| 308 | No successful scan time (falls back to agent contact time) |
| 309 | Schema drift: other key names, nested under `data`, unknown extra fields |
| 310 | Linux server with an unrecognised chassis (no category is guessed) |

**The envelopes and field names are assumptions** taken from public documentation
examples, not captures from a live server. In particular, the `dcapi` envelope is
unconfirmed. Before live use, capture sanitized responses from the installed build and
compare them (docs/17 DEC-06, ASM-29). Regenerate the file with care: tests depend on
these values.

## Installed software (Task 016a)

`dcapi.details.<id>.softwareInfo` holds fictitious `softwareInfo` documents for 301 (five
rows: an office suite, 7-Zip, a browser listed twice, and a row without a name) and 302
(two rows). 303 has none (the route answers 404). The envelope and key names
(`softwareName`, `softwareVersion`, `manufacturerName`, `installedDate`, `softwareId`) are
assumptions to verify with a sanitized capture (DEC-06, ASM-54).
