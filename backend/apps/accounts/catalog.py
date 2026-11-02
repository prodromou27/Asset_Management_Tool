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

PERMISSIONS: dict[str, str] = {
    USERS_VIEW: "View user accounts, role assignments and access review data",
    USERS_MANAGE: "Create, edit, disable and enable user accounts and their roles",
    ROLES_VIEW: "View roles and the permissions each role grants",
    AUDIT_VIEW: "View the audit log",
    SECURITY_SETTINGS_VIEW: "View session, lockout and password policy settings",
    SECURITY_SETTINGS_MANAGE: "Change session, lockout and password policy settings",
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
        [],
    ),
    (
        "infrastructure_engineer",
        "Infrastructure Engineer",
        "Technical comments, match proposals and source diagnostics.",
        [],
    ),
    (
        "security_analyst",
        "Security Analyst",
        "Read and investigate assets; flag high-risk lifecycle findings.",
        [],
    ),
    (
        "asset_operator",
        "Asset Operator",
        "Maintains authorized business fields and static group membership.",
        [],
    ),
    (
        "auditor",
        "Auditor",
        "Read-only access to evidence, health and the audit log.",
        [USERS_VIEW, ROLES_VIEW, AUDIT_VIEW, SECURITY_SETTINGS_VIEW],
    ),
    (
        "read_only",
        "Read Only",
        "Site-scoped read access.",
        [],
    ),
]

# Permissions the System Admin role must always hold (cannot be removed without
# a security decision recorded in docs/17_ADR_OPEN_DECISIONS.md).
MANDATORY_ADMIN_PERMISSIONS = frozenset({USERS_MANAGE, USERS_VIEW, ROLES_VIEW, AUDIT_VIEW})
