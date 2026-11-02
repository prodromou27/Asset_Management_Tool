"""Permission and role catalogue (docs/09_AUTH_AND_ADMIN.md).

Only permissions for implemented features are listed. Later tasks add codes
(assets.*, exports.*, ...) through migrations; roles gain them explicitly.
"""

USERS_VIEW = "users.view"
USERS_MANAGE = "users.manage"
ROLES_VIEW = "roles.view"
AUDIT_VIEW = "audit.view"
SECURITY_SETTINGS_VIEW = "settings.security.view"
SECURITY_SETTINGS_MANAGE = "settings.security.manage"
ASSETS_VIEW = "assets.view"
ASSETS_CREATE = "assets.create"
ASSETS_EDIT = "assets.edit"
ASSETS_RECLASSIFY = "assets.reclassify"
ASSETS_ARCHIVE = "assets.archive"
CATEGORIES_MANAGE = "categories.manage"
SITES_MANAGE = "sites.manage"
ASSETS_EDIT_TECHNICAL = "assets.edit_technical"
ASSETS_MERGE = "assets.merge"
DISCOVERY_VIEW = "discovery.view"
RECONCILIATION_DECIDE = "reconciliation.decide"
INTEGRATIONS_MANAGE = "integrations.manage"

PERMISSIONS: dict[str, str] = {
    USERS_VIEW: "View user accounts, role assignments and access review data",
    USERS_MANAGE: "Create, edit, disable and enable user accounts and their roles",
    ROLES_VIEW: "View roles and the permissions each role grants",
    AUDIT_VIEW: "View the audit log",
    SECURITY_SETTINGS_VIEW: "View session, lockout and password policy settings",
    SECURITY_SETTINGS_MANAGE: "Change session, lockout and password policy settings",
    ASSETS_VIEW: "View assets in permitted sites",
    ASSETS_CREATE: "Register assets in permitted sites",
    ASSETS_EDIT: "Edit and reassign assets in permitted sites",
    ASSETS_RECLASSIFY: "Change an asset's category",
    ASSETS_ARCHIVE: "Archive and restore assets",
    CATEGORIES_MANAGE: "Manage asset categories and custom field definitions",
    SITES_MANAGE: "Manage sites, locations and departments",
    ASSETS_EDIT_TECHNICAL: (
        "Edit discovered technical fields, lock/unlock fields, resolve field conflicts"
    ),
    ASSETS_MERGE: "Merge duplicate assets and revert merges",
    DISCOVERY_VIEW: "View discovery sources, observations, candidates and source evidence",
    RECONCILIATION_DECIDE: "Approve, reject or hold reconciliation candidates; unlink sources",
    INTEGRATIONS_MANAGE: "Configure integration instances and field authority",
}

SYSTEM_ADMIN = "system_admin"

# (code, name, description, permissions)
ROLES: list[tuple[str, str, str, list[str]]] = [
    (
        SYSTEM_ADMIN,
        "System Admin",
        "Full administration of users, settings, integrations and backups.",
        list(PERMISSIONS),
    ),
    (
        "itam_manager",
        "ITAM Manager",
        "Curates asset data, approves lifecycle matches and exceptions.",
        [
            ASSETS_VIEW,
            ASSETS_CREATE,
            ASSETS_EDIT,
            ASSETS_RECLASSIFY,
            ASSETS_ARCHIVE,
            ASSETS_EDIT_TECHNICAL,
            ASSETS_MERGE,
            DISCOVERY_VIEW,
            RECONCILIATION_DECIDE,
        ],
    ),
    (
        "infrastructure_engineer",
        "Infrastructure Engineer",
        "Technical comments, match proposals and source diagnostics.",
        [ASSETS_VIEW, ASSETS_EDIT_TECHNICAL, DISCOVERY_VIEW],
    ),
    (
        "security_analyst",
        "Security Analyst",
        "Read and investigate assets; flag high-risk lifecycle findings.",
        [ASSETS_VIEW, DISCOVERY_VIEW],
    ),
    (
        "asset_operator",
        "Asset Operator",
        "Maintains authorized business fields and static group membership.",
        [ASSETS_VIEW, ASSETS_CREATE, ASSETS_EDIT],
    ),
    (
        "auditor",
        "Auditor",
        "Read-only access to evidence, health and the audit log.",
        [
            USERS_VIEW,
            ROLES_VIEW,
            AUDIT_VIEW,
            SECURITY_SETTINGS_VIEW,
            ASSETS_VIEW,
            DISCOVERY_VIEW,
        ],
    ),
    (
        "read_only",
        "Read Only",
        "Site-scoped read access.",
        [ASSETS_VIEW],
    ),
]

# Permissions the System Admin role must always hold (cannot be removed without
# a security decision recorded in docs/17_ADR_OPEN_DECISIONS.md).
MANDATORY_ADMIN_PERMISSIONS = frozenset({USERS_MANAGE, USERS_VIEW, ROLES_VIEW, AUDIT_VIEW})
