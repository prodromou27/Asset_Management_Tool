# ITAM Platform | Development Handoff

Status: implementation specification, not an already-built application.
Target: **one organization**, multiple sites; **2,000–10,000 IP-connected devices** plus hardware, software, licenses, domains and non-network assets.
Hosting: **AlmaLinux OS 10.2 (latest stable as of 2 November 2026) + Docker Engine + Docker Compose v2**, single deployment. Revalidate stable release before final host installation.
Business objective: trustworthy asset inventory, discovery reconciliation, ownership, hardware/OS/firmware EOL/EOS, certificates and licenses.

## Read this first

1. Read [AGENTS.md](AGENTS.md) or [CLAUDE.md](CLAUDE.md), depending on your coding agent.
2. Read [00_MASTER_DECISIONS.md](docs/00_MASTER_DECISIONS.md).
3. Read [ACTIVE_TASK.md](tasks/ACTIVE_TASK.md), which selects one bounded implementation task and lists only the required reference docs.
4. Work on that task, run tests, record progress, stop. Do not ingest every document into context every session.

## Documents by responsibility

| Question | Document |
|---|---|
| What are we building and not building? | [00 Master decisions](docs/00_MASTER_DECISIONS.md), [01 Product and workflows](docs/01_PRODUCT_AND_WORKFLOWS.md) |
| How should services be structured? | [02 Architecture](docs/02_SYSTEM_ARCHITECTURE.md) |
| What data must persist? | [03 Data model](docs/03_DATA_MODEL.md) |
| Which HTTP API and error conventions? | [04 API](docs/04_API_CONTRACT.md) |
| How to integrate LibreNMS, Endpoint Central and Microsoft? | [05 Integrations](docs/05_INTEGRATIONS_DISCOVERY.md) |
| How do hardware and OS EOL or licenses work? | [06 Lifecycle](docs/06_LIFECYCLE_AND_LICENSES.md) |
| How should the interface look and behave? | [07 UI style](docs/07_UI_DESIGN_SYSTEM.md), [08 Screens](docs/08_UI_SCREENS.md) |
| How to configure user accounts and roles? | [09 Authentication and admin](docs/09_AUTH_AND_ADMIN.md) |
| How to configure outgoing mail? | [10 SMTP](docs/10_SMTP_NOTIFICATIONS.md) |
| How to import/export/report? | [11 Bulk data](docs/11_BULK_IO_AND_REPORTING.md) |
| How to deploy on AlmaLinux using Docker? | [12 Deployment](docs/12_DEPLOY_DOCKER_ALMALINUX.md) |
| How to back up and recover? | [13 Backups](docs/13_BACKUP_RECOVERY.md) |
| How to secure and validate? | [14 Security](docs/14_SECURITY_NFR.md), [15 Acceptance](docs/15_TESTING_ACCEPTANCE.md) |
| What order should Codex/Claude build? | [16 Roadmap](docs/16_ROADMAP_TASKS.md), [tasks](tasks/BACKLOG.md) |
| What remains undecided? | [17 Decisions](docs/17_ADR_OPEN_DECISIONS.md) |
| Which docs and vendor APIs are authoritative? | [18 References](docs/18_REFERENCE_LINKS.md) |
| How should code, tests and folders be organized? | [19 Repository conventions](docs/19_REPOSITORY_CONVENTIONS.md) |
| Which admin settings and first-run checks are required? | [20 Admin configuration](docs/20_ADMIN_CONFIGURATION_CATALOG.md) |

For practical copy/paste agent commands, see [Prompt templates](tasks/PROMPT_TEMPLATES.md). Follow the numbered dependencies in the [task backlog](tasks/BACKLOG.md); do not attempt all modules in a single generation.

## Start commands for the agent

First task: read AGENTS.md + docs/00_MASTER_DECISIONS.md + tasks/ACTIVE_TASK.md; implement only the active task. Show changed files and test results. Ask about a blocking decision; otherwise use documented defaults. Do not claim the app is deployed before it has passed the runbook.

This pack is self-contained for local development. Sensitive production values, real network scopes, tenant IDs, API credentials and SMTP passwords are intentionally **not included**.

## Local development (Task 001 bootstrap)

Prerequisites: Docker Engine + Docker Compose v2. No real integration credentials are needed or used in dev.

All Compose commands go through `scripts/compose.sh <dev|prod> ...`, which always loads the repository-root `.env` and pairs `infra/compose.yaml` with exactly one override.

```bash
cp .env.example .env
# Edit .env: set DJANGO_SECRET_KEY and POSTGRES_PASSWORD to local-only values.

scripts/compose.sh dev config --quiet          # validate merged config
scripts/compose.sh dev up -d --build
scripts/compose.sh dev ps                       # wait for postgres/redis/api healthy
scripts/migrate.sh dev                          # one-off; containers never auto-migrate
scripts/bootstrap_admin.sh dev jane.admin "Jane Admin" jane@example.test   # prompts for password
```

Sign in at http://localhost:5173 with that account. Create a second named admin the same way (emergency access, docs/09). Other users are created under **Administration → Users & roles** with a temporary password they must change at first sign-in.

- Liveness: http://localhost:8000/api/v1/health/live/
- Readiness (PostgreSQL + Redis): http://localhost:8000/api/v1/health/ready/ — returns 503 with `"database": {"status": "down"}` when PostgreSQL is stopped (`scripts/compose.sh dev stop postgres`)
- OpenAPI docs: http://localhost:8000/api/v1/docs/
- Frontend shell: http://localhost:5173
- Captured local email (Mailpit): http://localhost:8025

### Accounts, roles and audit (Task 002)

- Roles: System Admin, ITAM Manager, Infrastructure Engineer, Security Analyst, Asset Operator, Auditor, Read Only. Today only System Admin (everything) and Auditor (read users/roles/audit/security policy) hold permissions; the others gain theirs as their features land.
- Security policy (idle/absolute session timeouts, lockout threshold/duration, minimum password length) is edited under **Administration → Security policy**. Every change is audited.
- Login: Argon2 hashing, generic failure message, per-account lockout, 10 attempts/minute per client, CSRF-protected, session key rotated on sign-in. Disabling a user or resetting their password signs out all their sessions.
- Audit log: **Administration → Audit log**. Append-only; PostgreSQL rejects UPDATE/DELETE/TRUNCATE on the table.
- Not yet available: SSO/OIDC and MFA (see ASM-03 in docs/17_ADR_OPEN_DECISIONS.md), site-scoped permissions (Task 003).

### Assets, categories and sites (Task 003)

- **Assets** (`/assets`): inventory list with search (name, tag, serial, model, hostname, exact IP or MAC), filters kept in the URL, detail with Overview / Network / History tabs, create/edit forms, category change with impact preview and required reason, archive/restore (no hard delete).
- **Sites & locations** and **Categories & fields** under Administration (System Admin). Default category taxonomy is seeded; fields are typed (text, long text, integer, decimal, yes/no, date, choice) and inherited by subcategories.
- **Site access**: on each user's page under Users & roles. Users see only assets in granted sites (and their child sites) unless "All sites" is set. `bootstrap_admin` creates admins with all sites.
- Every create, edit, reassignment, reclassification, archive and restore is recorded in the asset's history (append-only) and the audit log. Edits require the current version (If-Match); stale edits are rejected.

### Discovery and reconciliation (Task 004)

- **Discovery** (`/discovery`): reconciliation queue (new devices and uncertain matches with confidence and matching identifiers), field conflicts, and sources with freshness and sync history. Candidate pages show normalised values, warnings, the raw payload, matches and a decision panel (link, create, hold, reject; reason required).
- **Source evidence** tab on each asset: current value, who/what set it and when, lock state, every source's reported value (flagged when it differs), linked sources (unlink) and merges (merge/revert).
- **Administration → Integrations**: integration instances (vendor sources are Planned until their adapters exist; LibreNMS is Beta since Task 006), default site/VRF, stale threshold, optional automatic linking of strong matches, and per-field source precedence.
- No vendor APIs are called and nothing scans the network. Sanitised records can be loaded for pilots and testing:

```bash
scripts/compose.sh dev cp fixtures/discovery/network_devices.json api:/tmp/network_devices.json
scripts/compose.sh dev exec api python manage.py load_observations \
  --instance "<integration name>" --file /tmp/network_devices.json --mode full
```

### Inventory views (Task 005)

- **Saved views** on the Assets page: save the current filters, sort order and columns; apply them from the "Saved view" selector (the view id is kept in the URL). Users with asset edit rights can share views; shared views show each person only assets in their own sites.
- **Columns**: choose visible columns (Name is always shown). Includes Last seen (relative time, exact time on hover and for screen readers), Sources and Observation.
- **Evidence drawer**: on an asset's Overview, "Evidence" next to each technical field shows its value, source, time, lock and every linked source's report.
- New filters: Observation status and Source (integration).

### LibreNMS connector (Task 006, Beta — live access off)

- **Administration → Integrations → (integration)**: configuration (HTTPS base URL, API token *reference*, auth header, private CA bundle reference, timeout, retries, rate limit, sync/evidence intervals, enrichment age, LibreNMS time zone, enabled), live-access approval with a reason, **Test connection**, **Sync now**, health (last success, next run, devices discovered, assets matched, new candidates, errors/warnings, failures, version, capabilities) and sync history with progress.
- Asset **Network** tab: "Observed network evidence" (MAC table and LLDP/CDP neighbours). Observed, not a confirmed cable.
- The connector only sends GET requests to `/api/v0`, never changes LibreNMS, never scans networks and never auto-merges devices. Unmatched devices go to the Discovery queue.
- **Live access is disabled.** It requires both `ITAM_ALLOW_LIVE_INTEGRATIONS=true` on the host *and* an approval recorded on the integration. Do not enable either until the Docker-host verification has passed and a read-only LibreNMS API account is approved (DEC-05). Then put the token in `.env` as `ITAM_INTEGRATION_LIBRENMS_TOKEN` (or a file in `ITAM_SECRETS_DIR`) and reference it as `env:ITAM_INTEGRATION_LIBRENMS_TOKEN`; the token is never entered in, stored by, or shown in the application.
- Scheduled syncs run from Celery beat (`integrations.dispatch_due_syncs`, every 5 minutes, honouring each integration's interval). Sanitized fixtures and scenarios: `fixtures/librenms/README.md`.

### Endpoint Central connector (Task 007, Beta — live access off)

- Same integration page and gates as LibreNMS. Configure the verified HTTPS listener (for example `https://endpointcentral.example:8383`), a read-only API key reference (`env:ITAM_INTEGRATION_ENDPOINT_CENTRAL_KEY`) and the header format (raw `Authorization` by default).
- The connection test detects the API generation (`/dcapi` first, then `/api/1.4`) and the build number. Syncs read the paginated computer list and, only for new or rescanned computers, hardware, OS and network adapter details. Installed software is not read yet (Task 016).
- Laptops, desktops, servers and virtual machines are proposed in the Discovery queue with category hints; nothing is merged on hostname, IP or MAC. Sanitized fixtures and scenarios: `fixtures/endpoint_central/README.md`.
- Do not enable live access until the Docker-host verification has passed and DEC-06 (read-only key, build, sample responses) is approved.

### Microsoft Intune connector (Task 008, Beta — live access off)

- Reads `GET https://graph.microsoft.com/v1.0/deviceManagement/managedDevices` only, following `@odata.nextLink` (continuation links must stay on `graph.microsoft.com`, https, under the same collection, or they are not followed and the run is treated as incomplete). Beta endpoints are not used. Devices are never modified.
- **App registration (DEC-07):** single-tenant Microsoft Entra application with the **application** permission `DeviceManagementManagedDevices.Read.All` and admin consent. Do not grant `DeviceManagementManagedDevices.ReadWrite.All`, `PrivilegedOperations` or other write permissions; the connection test and every sync warn if the token carries them.
- **Credential (certificate preferred):** upload the certificate to the app registration and give the server one PEM file holding the unencrypted RSA private key and the certificate, mounted read-only into the `api` and `worker` containers under `/run/secrets` (for example with a Compose `secrets:` entry in a host-specific override file), then reference it as `file:<name>` with the method "OAuth client certificate". A client secret (`env:ITAM_INTEGRATION_INTUNE_CLIENT_SECRET`, method "OAuth client secret") is supported as a fallback. Neither the credential nor any access token is stored, logged or returned by the API.
- On the integration page enter the **tenant ID** (directory GUID or verified domain) and **application (client) ID**. The Graph endpoint is fixed and cannot be changed. New Intune integrations default to a daily sync and report a device stale after 7 days without an Intune check-in.
- Stored per device: Intune managed device ID (external ID), Entra device ID, tenant, device name, manufacturer, model, serial, OS and version, enrollment type and time, compliance, management agent, ownership and registration state, Wi-Fi MAC. User names, e-mail addresses and phone identifiers are not requested.
- Matching follows the shared rules: Intune gives no chassis type, so only unambiguous models (for example MacBook, Latitude, EliteDesk, virtual machines) get a category hint, and devices without one are never linked automatically. A second active Intune record for an already linked asset (re-enrollment) becomes a conflict candidate. Sanitized fixtures and scenarios: `fixtures/intune/graph/README.md`.

### Microsoft Defender for Endpoint connector (Task 009, Beta — live access off)

- Reads only `GET https://api.security.microsoft.com/api/machines` with a token for the Defender for Endpoint API (`https://api.securitycenter.microsoft.com/.default`). Pages with `$top`/`$skip` or `@odata.nextLink`; incremental runs filter on `lastSeen`. Never calls device actions (isolation, scans, quarantine, live response, offboarding) or Advanced Hunting.
- **App registration (DEC-16):** single-tenant Entra application with only the WindowsDefenderATP **application** permission `Machine.Read.All` and admin consent, authenticating with a **certificate** (PEM with the private key and certificate mounted under `/run/secrets`, referenced as `file:<name>`). Client secrets are not accepted for Defender. The connection test and every sync warn about any device-action or write permission in the token.
- Throttling stays under the published limits with a per-tenant budget shared by all runs and workers through Redis (at most 90 calls a minute and 1,400 an hour; one request per 0.6 s per client) and honours Retry-After.
- Matching: the Entra device ID links a Defender machine to the asset of an Intune device from the **same tenant** when a hostname or MAC corroborates it and nothing conflicts (ADR-014); otherwise it is a review candidate. Hostname or IP alone never links.
- Security facts (onboarding, sensor health, exposure, risk, tags, first/last seen, original values) are stored apart from asset fields and shown on the asset's **Security** tab (requires `discovery.view` and site access). "Last report received" is not an online status, and a machine missing from Defender's list is flagged, never treated as deleted. Sanitized fixtures: `fixtures/defender/api/README.md`.

### Imports (Task 013)

- **Imports** (sidebar, and Import on the Assets page): choose what to import (assets, locations, groups, static group members), download the versioned CSV template, upload a CSV or XLSX file (up to 5 MB / 10,000 rows), map columns, choose create only / update matched / create and update, and run a dry run that shows Create/Update/Skip/Conflict/Error per row before anything changes.
- Assets update only by id or asset tag; a matching manufacturer + serial or name + site without them is a conflict for review, never a merge, and hostname/IP are never used. Locked fields, discovery-sourced values and site scope are respected. Missing rows never delete anything; re-importing the same file is safe.
- Importing needs a confirmation with an idempotency key; each row is re-checked and applied on its own. The receipt shows applied/not applied/failed rows with a downloadable report (formula-safe), and rollback undoes rows nobody has changed since. Original files are kept encrypted for 90 days (`ITAM_IMPORT_RETENTION_DAYS`).

### Asset groups (Task 012)

- **Groups** (sidebar): static groups (members added and removed by hand, removals with a reason) and dynamic groups (a typed AND/OR/NOT rule builder over asset fields, with a live preview of matching assets and, when editing, how many members the change would add or remove).
- Dynamic groups re-evaluate when the rule is saved, on "Re-evaluate now" and hourly; each membership shows why it exists (added by a person, or the rule version that matched) and removed memberships stay visible as history. Rule changes are versioned with a reason.
- Groups never grant access: lists, counts and members only include assets in your sites. Nested groups and "member of group" rules cannot form cycles. The asset page has a Groups tab.

### Reconciliation review, category reviews and data quality (Task 011)

- **Discovery → Reconciliation queue**: filter by assignee, waiting time and text, sort by age or confidence, select devices and assign, put on hold or reject them in bulk with a reason (each item keeps its own version check and audit entry). Linking and creating stay one device at a time.
- **Discovery → Category reviews**: when a linked source reports a device type that maps to a different category, the asset is not changed; a review lets an authorised user reclassify (template impact preview, same asset ID and history) or keep the current category. Linking a candidate can also move the asset to the suggested category in the same step.
- **Discovery → Data quality**: queues for duplicate candidates, unknown model, stale sources and missing owners, with severity, evidence, assignee and resolution state. Rechecked hourly; fixing the asset resolves the finding; dismissed findings stay dismissed while the condition holds.

### Microsoft 365 / Entra license connector (Task 010, Beta — live access off)

- Reads only Graph v1.0 `GET /subscribedSkus` and `GET /users` (selected fields: ID, UPN, display name, enabled, assigned licenses and license assignment states). App registration (DEC-17): application permissions `Organization.Read.All` and `User.Read.All` with admin consent; certificate preferred (`file:<name>`), client secret fallback (`env:ITAM_INTEGRATION_M365_CLIENT_SECRET`). Optional `GroupMember.Read.All` lets the connector show the names of license-assigning groups; without it only group IDs are shown.
- **Licenses** screen (permission `licenses.view`: System Admin, ITAM Manager, Auditor): each SKU with purchased (enabled), consumed (as the tenant reports it), assigned users (ITAM's distinct count; a user with the SKU directly and through groups counts once) and available units, with a quantity history and the list of assigned users (direct, group, both; state).
- This is tenant inventory, not a billing agreement or license compliance. Only a complete user listing ends assignments or produces counts; nothing is deleted. Sanitized fixtures: `fixtures/m365/graph/README.md`.

After changing an API serializer, regenerate the contract: `cd backend && uv run python manage.py spectacular --file ../frontend/src/shared/api/openapi.yaml`, then `cd frontend && pnpm run gen:api`. CI fails on drift.

Dev ports are bound to 127.0.0.1 only. Stop with `scripts/compose.sh dev down` (add `-v` only to discard the local PostgreSQL volume).

### Backend tests

Authoritative run, against PostgreSQL and Redis in the dev stack (same as CI):

```bash
scripts/compose.sh dev run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test api python -m pytest -q -rs
```

Workstation shortcut without Docker. SQLite is **test-only**: the two PostgreSQL/Redis integration tests are skipped, and CI refuses this mode (see ASM-02 in docs/17_ADR_OPEN_DECISIONS.md):

```bash
cd backend
uv sync --group dev
ITAM_TEST_DB_SQLITE=1 DJANGO_SECRET_KEY=test-secret uv run python -m pytest -q -rs
uv run ruff check . && uv run ruff format --check .
```

### Production configuration check

```bash
scripts/compose.sh prod config --quiet
scripts/compose.sh prod exec api python manage.py check --deploy
```

### Simple installation

On AlmaLinux: clone to `/opt/itam`, run `sudo bash scripts/install.sh` and open `http://<server-ip>/`. Add a certificate later with `sudo bash scripts/enable_https.sh`. See [docs/12 section 9](docs/12_DEPLOY_DOCKER_ALMALINUX.md#9-simple-installation-http-first-https-later).

Production settings refuse to start with `ITAM_DEBUG` enabled, a missing/short/test secret key, wildcard `ITAM_ALLOWED_HOSTS` or a missing database password. PostgreSQL and Redis publish no host ports in `compose.prod.yaml`; only the proxy publishes 80 and 443.

Frontend:

```bash
cd frontend
pnpm install
pnpm run lint
pnpm run typecheck
pnpm run test
pnpm run build
```

## Key prohibitions

- No additional endpoint agent or native SNMP scanner in V1. LibreNMS already performs network discovery.
- No automatic false EOL status from a guessed model, hostname or MAC prefix.
- No copying of GLPI GPLv3 source into the custom codebase.
- No direct modification of Endpoint Central, Intune, Defender, LibreNMS or Microsoft 365 through their APIs.
- No generated demo values in production reporting, no fabricated vendor EOL dates.
- No deployment of incomplete admin controls, SMTP or backups to production.
