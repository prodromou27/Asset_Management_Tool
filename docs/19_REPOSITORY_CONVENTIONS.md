# 19 | Repository Structure and Engineering Rules

The initial handoff contains documentation only. The coding agent creates this target tree during Phase 1, without destroying these docs:

~~~text
itam/
  AGENTS.md
  CLAUDE.md
  README.md
  docs/
  tasks/
  backend/
    pyproject.toml
    uv.lock
    config/
    apps/
      accounts/ assets/ catalogs/ observations/
      reconciliation/ groups/ lifecycles/ software/
      licenses/ integrations/ domains/ certificates/
      imports/ exports/ notifications/ audit/ health/
    tests/
  frontend/
    package.json
    pnpm-lock.yaml
    src/
      app/
      features/
      shared/ui/
      shared/api/
      styles/
    e2e/
  infra/
    compose.yaml
    compose.dev.yaml
    compose.prod.yaml
    nginx/
  ops/
    backup/
    restore/
    deployment/
  fixtures/
    librenms/
    endpoint-central/
    graph/
    defender/
    lifecycle/
  .github/workflows/
  .env.example
~~~

## Development conventions

- Python: supported version selected/pinned during bootstrap; manage dependencies with uv + uv.lock; Django/DRF, pytest-django, ruff, static typing where beneficial.
- TypeScript: strict mode, Vite, pnpm lockfile, React Router, TanStack Query or equivalent data cache, Vitest and Playwright.
- UI: design tokens and reusable accessible components built in shared/ui, no one-off duplicate card/table implementations.
- REST: Django services/serializers for input validation, business logic in domain services, clear transaction boundaries, OpenAPI schema and generated frontend client.
- DB: Django migrations; avoid cross-module circular imports; use explicit service interfaces and foreign-key constraints.
- Jobs: Celery task files per module, retry policy, idempotent job keys, source checkpoint, logged outcome; never send email synchronously inside API request.
- Tests: isolated fixture data, no live external API calls by default, deterministic time via clock abstraction, live integration smoke in explicit operator-approved job only.
- Security: never commit .env, real tokens, keys, plaintext SMTP credentials or private inventory; scrub fixtures.

## Local developer behavior

- On bootstrap, implement one command that starts the dev Compose stack and provides health/testing instructions.
- No real external integrations are configured in dev by default. Use sanitized fixtures and captured mail sink.
- Every DB model change requires a migration and test.
- Every permission-sensitive mutation requires a 403 test and audit test.
- Every UI feature must have empty/loading/error/success states and be accessible via keyboard.
- Large tables use backend pagination, not rendering 10,000 rows in browser at once.

## CI quality gates

Backend format/lint/type validation, unit+integration tests, migration check, OpenAPI schema check; frontend lint/type/unit/e2e smoke; container build and dependency/image checks. Reject commits with secrets, broken migration/test or unhandled permission failure. Stage first before production image promotion.

## ADR mechanism

Add docs/adr/NNN-title.md only if changing locked stack, auth, data identity, infrastructure or security. Format: Context / Options / Decision / Consequences / Rollback. Prefer a small PR over wholesale regeneration.
