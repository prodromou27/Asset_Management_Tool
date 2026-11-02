# Current Task: 002 | Named Admin Bootstrap, Local Auth/RBAC + Audit

Status: **Provisionally Complete / Pending Docker and PostgreSQL Verification.**

Started on 2026-11-02 at the owner's explicit request while Task 001 was still pending
Docker verification. Neither task may be marked Complete until the "Pending
verification" items below have been run on a Docker host and the real output recorded.

**Read:** AGENTS.md, docs/00, 03, 04, 09, 14 (backlog list) plus 07, 08 for the UI.

## Outcome (2026-11-02)

Backend (`apps/accounts`, `apps/audit`, `config/api.py`, `config/request_context.py`):

- Custom UUID `User` (lowercase unique username, case-insensitive unique email,
  version, lockout fields, `session_epoch`), `Role`, `Permission`, `SecuritySettings`.
- Seed migration: 7 documented roles; 6 permission codes; System Admin holds all,
  Auditor holds users.view/roles.view/audit.view/settings.security.view; others none yet.
- `manage.py bootstrap_admin` — named System Admin, password via TTY prompt or
  `--password-stdin` only, audited as `cli:<os user>`; supports second emergency admin.
- Auth API: `/auth/csrf`, `/auth/providers`, `/auth/local/login` (CSRF-protected,
  10/min/IP throttle, generic failure, per-account lockout, session rotation),
  `/auth/logout`, `/auth/me`, `/auth/password/change`.
- Sessions: HttpOnly SameSite=Lax cookies; admin-configurable idle and absolute
  timeouts enforced per request; disable/reset bumps `session_epoch` → all sessions
  revoked; password change revokes other sessions; inactive users rejected.
- Argon2 primary hasher; configurable minimum length + Django similarity/common/numeric.
- Temporary passwords: `must_change_password` blocks every endpoint except me,
  logout and password change.
- Users API: list (cursor, q/status/role filters), create, get, PATCH (If-Match →
  428/409), disable (reason required), enable, unlock, reset-password. Guards:
  no self-disable, no self-demotion, last active System Admin cannot be removed.
- `GET /roles`, `GET /permissions`, `GET/PATCH /settings/security` (If-Match, bounds,
  idle ≤ absolute).
- Audit: append-only model + PostgreSQL trigger (UPDATE/DELETE/TRUNCATE blocked),
  secret-key redaction, request ID, actor, IP, before/after; `GET /audit/events`
  with filters. Logged: login success/failure, lockout, logout, session expiry,
  password change/reset, user create/update/disable/enable/unlock, bootstrap,
  security-settings change.
- Error envelope `{error: {code, message, request_id, field_errors}}`; 401 vs 403;
  422 for validation; `X-Request-ID` on every response.
- Task 001 fixes found on the way: readiness no longer leaks driver/host errors to
  anonymous callers; frontend now shows a degraded (503) readiness body instead of
  a generic failure.
- Proxy-aware client IP (`ITAM_TRUSTED_PROXY_COUNT`, 1 in prod): login throttling and
  audit IPs use the nginx-appended hop; client-supplied X-Forwarded-For is ignored.

Frontend:

- Typed client generated from OpenAPI (`openapi.yaml` → `schema.d.ts`); CSRF header,
  If-Match, error envelope parsing; global 401 → back to sign-in.
- Screens: Sign in, Change password (forced for temporary passwords), Users & roles
  list/detail/create, Audit log, Security policy. Permission-filtered navigation;
  routes also guarded; API remains the authority.
- Shared accessible UI: labelled fields with aria-describedby errors, focused error
  summary, `<dialog>` confirmations naming the affected count, text+colour status
  badges, loading/empty/error/denied states, URL-encoded filters, cursor "Load more".

## Verification run on this workstation (no Docker; SQLite test-only per ASM-02)

- Backend: `pytest` **104 passed, 3 skipped** (the 3 need PostgreSQL/Redis);
  ruff check + format clean; `makemigrations --check` clean; `migrate`,
  `migrate --check`, reverse to zero and re-apply clean; `spectacular --validate
  --fail-on-warn` clean (18 paths); committed schema in sync.
- Frontend: vitest **38 passed** (no act/console warnings); oxlint clean; `tsc -b`
  clean; production build OK.
- Not run: Playwright e2e (no browser/stack), PostgreSQL trigger test, CI.

## Pending verification (requires Docker host) — covers Tasks 001 and 002

1. `scripts/compose.sh dev config --quiet` and `scripts/compose.sh prod config --quiet`.
2. `scripts/compose.sh dev up -d --build`; postgres, redis, api, worker healthy in `ps`.
3. `scripts/migrate.sh dev` succeeds against PostgreSQL (includes audit trigger).
4. `/api/v1/health/ready/` 200 with database/redis `up`; 503 with database `down`
   after `scripts/compose.sh dev stop postgres`.
5. Worker answers `celery -A config inspect ping`; scheduler starts beat cleanly.
6. `scripts/bootstrap_admin.sh dev <user> "<name>"` creates admin; second admin too.
7. Sign in at http://localhost:5173 through the Vite proxy (CSRF origin check),
   create a user, sign in as that user, forced password change, disable from admin
   and confirm the user's session ends.
8. `scripts/compose.sh dev run --rm -e DJANGO_SETTINGS_MODULE=config.settings.test api
   python -m pytest -q -rs` — **107 passed, 0 skipped**.
9. Production images build; `compose.prod.yaml` published ports are 443 only.
10. First CI run green once the repository is pushed.

## Known gaps / blockers (recorded in docs/17_ADR_OPEN_DECISIONS.md)

- ASM-03: no MFA/OIDC yet; DEC-11 must be decided before production.
- ASM-04: no site/department scoping until sites exist (Task 003).
- ASM-05: role→permission grants are seeded, not editable in the UI yet.
- Admin-only "session list" and account-access-review export are not implemented.

Proposed next task: **003 | Asset/category/site schema + CRUD** (tasks/BACKLOG.md),
only after the pending verification above. Do not start it automatically.

---

## Task 001 | Bootstrap Secure Local Stack — status

**Provisionally Complete / Pending Docker and PostgreSQL Verification** (same list
above). Django 5.2.18 LTS; DRF 3.18.3; drf-spectacular 0.30.0; Celery 5.6.3;
redis-py 6.4.0; psycopg 3.3.6; gunicorn 26.2.0. Compose and CI YAML have only been
syntax-checked; that is not runtime validation.
