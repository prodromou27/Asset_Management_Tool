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

Production settings refuse to start with `ITAM_DEBUG` enabled, a missing/short/test secret key, wildcard `ITAM_ALLOWED_HOSTS` or a missing database password. PostgreSQL and Redis publish no host ports in `compose.prod.yaml`; only the proxy publishes 443.

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
