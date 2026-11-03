# Microsoft 365 / Entra license fixtures (sanitized)

`responses.json` holds invented Microsoft Graph v1.0 responses for `GET /subscribedSkus`
and `GET /users?$select=id,userPrincipalName,displayName,accountEnabled,assignedLicenses,
licenseAssignmentStates`. The test fake serves the users four per page, linked with
`@odata.nextLink`. The tenant matches the Intune and Defender fixtures. SKU, group, user and
application IDs are made up (they are **not** Microsoft's real SKU GUIDs), and users have
`.example` addresses.

**SKUs**

| Part number | Scenario |
|---|---|
| SPE_E3 | 50 enabled, 6 consumed; assigned directly, by group, both, and with an error |
| EMSPREMIUM | Direct and group assignments |
| POWER_BI_PRO | `Warning` capability status (all 10 units in warning) |
| FLOW_FREE | Free SKU with a large prepaid quantity |
| VISIOCLIENT | `Suspended`: 0 enabled, 5 suspended, nobody assigned |

**Users**

| User | Scenario |
|---|---|
| Ada | SPE_E3 and EMSPREMIUM direct |
| Ben | SPE_E3 through group "sales"; FLOW_FREE direct |
| Cleo | SPE_E3 **direct and** through "sales" (counted once); EMSPREMIUM through group "sec" |
| Dev | SPE_E3 group assignment in `Error` (`CountViolation`, not assigned); POWER_BI_PRO direct |
| Eve | Disabled account with SPE_E3 direct |
| Finn | No licenses (not stored) |
| Gia | A SKU that is no longer in subscribedSkus |
| Hal | `assignedLicenses` without `licenseAssignmentStates` (unknown path, counted) |
| Ivy | SPE_E3 through two groups (counted once) |
| Jo | POWER_BI_PRO `ActiveWithError` (`MutuallyExclusiveViolation`, counted) |

ITAM's distinct assigned-user count for SPE_E3 is 6 (Ada, Ben, Cleo, Eve, Hal and Ivy): 4
direct and 3 through groups, with Cleo in both.

**Property names come from the Graph v1.0 documentation; the values are not captures from a
real tenant.** Before live use, compare them with a sanitized response from the approved
tenant (docs/17 DEC-17, ASM-41).
