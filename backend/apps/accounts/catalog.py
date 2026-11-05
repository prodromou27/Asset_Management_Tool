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
LICENSES_VIEW = "licenses.view"
LICENSES_MANAGE = "licenses.manage"
GROUPS_VIEW = "groups.view"
GROUPS_MANAGE = "groups.manage"
GROUPS_MEMBERS = "groups.members"
IMPORTS_RUN = "imports.run"
EXPORTS_RUN = "exports.run"
EXPORTS_PERSONAL = "exports.personal"
LIFECYCLE_VIEW = "lifecycle.view"
LIFECYCLE_MANAGE = "lifecycle.manage"
LIFECYCLE_APPROVE = "lifecycle.approve"
CERTIFICATES_VIEW = "certificates.view"
CERTIFICATES_MANAGE = "certificates.manage"
NOTIFICATIONS_VIEW = "notifications.view"
NOTIFICATIONS_MANAGE = "notifications.manage"
BACKUPS_VIEW = "backups.view"
BACKUPS_MANAGE = "backups.manage"

PERMISSIONS: dict[str, str] = {
    BACKUPS_VIEW: "View backup operations and recovery reports (never backup files or secrets)",
    BACKUPS_MANAGE: (
        "Configure backup policy, request backups and verification, record restore drills"
    ),
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
    LICENSES_VIEW: "View license subscriptions, quantities and user license assignments",
    LICENSES_MANAGE: "Maintain license products, entitlements and allocations",
    GROUPS_VIEW: "View asset groups and their members in permitted sites",
    GROUPS_MANAGE: "Create, edit and archive asset groups and dynamic group rules",
    GROUPS_MEMBERS: "Add and remove static group members in permitted sites",
    IMPORTS_RUN: "Upload, preview and commit CSV/XLSX imports (plus the family's own permission)",
    EXPORTS_RUN: "Export data you can view (site-scoped) to CSV, XLSX or JSON",
    EXPORTS_PERSONAL: "Include personal data (owner and user names) in exports",
    LIFECYCLE_VIEW: "View lifecycle catalogue, evidence and asset lifecycle assessments",
    LIFECYCLE_MANAGE: "Add and edit lifecycle products, aliases, sources and dates (unverified)",
    LIFECYCLE_APPROVE: "Verify lifecycle evidence, approve or reject matches and grant exceptions",
    CERTIFICATES_VIEW: "View domains, TLS certificates and approved TLS endpoints",
    CERTIFICATES_MANAGE: (
        "Maintain domains, upload certificates and approve, check or retire TLS endpoints"
    ),
    NOTIFICATIONS_VIEW: "View SMTP settings (without credentials), templates and the mail queue",
    NOTIFICATIONS_MANAGE: (
        "Change SMTP settings and templates, test mail and retry or cancel queued messages"
    ),
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
            LICENSES_VIEW,
            LICENSES_MANAGE,
            GROUPS_VIEW,
            GROUPS_MANAGE,
            GROUPS_MEMBERS,
            IMPORTS_RUN,
            EXPORTS_RUN,
            EXPORTS_PERSONAL,
            LIFECYCLE_VIEW,
            LIFECYCLE_MANAGE,
            LIFECYCLE_APPROVE,
            CERTIFICATES_VIEW,
            CERTIFICATES_MANAGE,
        ],
    ),
    (
        "infrastructure_engineer",
        "Infrastructure Engineer",
        "Technical comments, match proposals and source diagnostics.",
        [
            ASSETS_VIEW,
            ASSETS_EDIT_TECHNICAL,
            DISCOVERY_VIEW,
            GROUPS_VIEW,
            GROUPS_MEMBERS,
            EXPORTS_RUN,
            LIFECYCLE_VIEW,
            LIFECYCLE_MANAGE,
            CERTIFICATES_VIEW,
            CERTIFICATES_MANAGE,
        ],
    ),
    (
        "security_analyst",
        "Security Analyst",
        "Read and investigate assets; flag high-risk lifecycle findings.",
        [
            ASSETS_VIEW,
            DISCOVERY_VIEW,
            GROUPS_VIEW,
            EXPORTS_RUN,
            LIFECYCLE_VIEW,
            CERTIFICATES_VIEW,
        ],
    ),
    (
        "asset_operator",
        "Asset Operator",
        "Maintains authorized business fields and static group membership.",
        [
            ASSETS_VIEW,
            ASSETS_CREATE,
            ASSETS_EDIT,
            GROUPS_VIEW,
            GROUPS_MEMBERS,
            IMPORTS_RUN,
            EXPORTS_RUN,
            EXPORTS_PERSONAL,
            LIFECYCLE_VIEW,
            CERTIFICATES_VIEW,
        ],
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
            LICENSES_VIEW,
            GROUPS_VIEW,
            EXPORTS_RUN,
            LIFECYCLE_VIEW,
            CERTIFICATES_VIEW,
            NOTIFICATIONS_VIEW,
            BACKUPS_VIEW,
        ],
    ),
    (
        "read_only",
        "Read Only",
        "Site-scoped read access.",
        [ASSETS_VIEW, GROUPS_VIEW, EXPORTS_RUN, LIFECYCLE_VIEW, CERTIFICATES_VIEW],
    ),
]

# Permissions the System Admin role must always hold (cannot be removed without
# a security decision recorded in docs/17_ADR_OPEN_DECISIONS.md).
MANDATORY_ADMIN_PERMISSIONS = frozenset({USERS_MANAGE, USERS_VIEW, ROLES_VIEW, AUDIT_VIEW})
