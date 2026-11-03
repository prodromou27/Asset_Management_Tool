# Current Task: 011 | Reconciliation review and category reclassification

Status: **Complete (CI run 41739915106 green)**
(2026-11-04, branch DEV).

**Read:** AGENTS.md, docs/00, 01 (Reclassify, Reconcile discovery, dedicated queues), 03, 07,
08, 15 (A06), 17.

**Previous:**
- 010 Microsoft 365 licenses (CI run 41672076454 green).
- Follow-up fixes for Tasks 008–010 (`5afb2a1`, CI run 41736399569 green: backend 542
  passed, frontend 100):
  - a per-tenant Defender rate budget shared through Redis;
  - optional M365 group names (`GroupMember.Read.All`);
  - licensed-users wording on the M365 integration page;
  - a prefetch for the subscriptions list.

**Scope (operator choice, 2026-11-04):**
- Category mismatch review.
- Queue triage.
- Data-quality queues.

Already present from earlier tasks and reused: asset reclassification with impact preview
and reason (Task 003), and the candidate link/create/hold/reject decisions (Tasks 004–005).

Out of scope: review metrics (not chosen); the docs/01 queues "EOL evidence missing",
"certificate expiring" and "import errors" (Tasks 015, 017 and 013).

## Outcome

**Category review (ADR-015, ASM-44):**
- Sources never change an asset's category.
- After each applied observation, a source type that maps to a different category opens
  one `CategoryReview` per asset and source, of kind `more_specific`, `different_type` or
  `different_class`.
- A reviewer with `assets.reclassify` either reclassifies through the existing audited
  service or keeps the current category with a reason. A kept category is not
  re-proposed for the same suggestion.
- Any reclassification (review, asset page or link-time) settles open reviews through a
  new `asset_reclassified` signal. Reviews also resolve when the source agrees again.
- Linking a candidate can reclassify in the same transaction (`reclassify=true`); a
  missing required template field rolls back both.

**Queue triage (ASM-45):**
- Candidates have an `assignee` (validated: may decide, has site access).
- New filters: site, assignee (me / none / user), `older_than_days`, `q`; ordering by
  newest, oldest or score.
- Bulk hold, reject or assign: at most 200 items, each with its viewed version, its own
  transaction, audit entry and result. Linking and creating stay one at a time.
- The assignee picker is backed by `GET /reconciliation/assignees/`.

**Data-quality queues (`apps.quality`, ASM-46):**
- `DataQualityFinding` per asset and kind:
  - duplicate candidate: same manufacturer + serial (high) or same MAC (medium);
  - model unknown (medium; VMs exempt);
  - source stale (medium);
  - owner missing (low when deployed, medium when assigned).
- Each finding has severity, summary, evidence, assignee and status (open, dismissed,
  resolved).
- Findings are recomputed hourly (Celery beat `quality.refresh_findings`) or on demand.
  They auto-resolve when the condition clears; dismissed findings stay dismissed while it
  holds. Assets are never changed.

**Migrations (all reversible; CI reverses `quality` too):**
- `reconciliation.0002_category_review_and_triage`
- `quality.0001_data_quality_findings`

**APIs (new):**

| Area | Endpoints |
|---|---|
| Category reviews | `GET /discovery/category-reviews/`; `POST .../{id}/reclassify/` and `.../{id}/dismiss/` (If-Match) |
| Triage | `POST /reconciliation/{id}/assign/` (If-Match), `POST /reconciliation/bulk/`, `GET /reconciliation/assignees/` |
| Data quality | `GET /quality/findings/`, `GET /quality/summary/`; `POST /quality/findings/{id}/assign/`, `.../dismiss/`, `.../reopen/` (If-Match); `POST /quality/refresh/` |

Changed:
- Candidates add `assignee` and `assigned_at`.
- The candidate list adds the new filters.
- Approve-link accepts `reclassify`, `category` and `custom_fields`.

**UI:**
- Discovery reconciliation queue: assignee, waiting-time and sort filters, search, row
  selection with a bulk bar (assign to me, unassign, hold, reject) and a reason dialog
  that reports per-item results, plus assignee and waiting-since columns.
- New **Category reviews** tab: current versus suggested path, kind, source, a reclassify
  dialog with template impact (it links to the asset's Change category form when
  required fields are missing), and keep-current.
- New **Data quality** tab: queue selector with counts, status, severity and assignee
  filters, evidence links to the other duplicate assets, assign to me, dismiss, reopen,
  and re-check now.
- Candidate page: an "Also change the asset's category" option when linking.
- Shared `ReasonDialog`; new `.segmented` and `.bulk-bar` styles.

**Docs:** docs/17 ADR-015 and ASM-44 to ASM-46; README section.

## Verification (workstation; SQLite test-only fallback, no Docker/PostgreSQL here)

- **Backend: 560 passed, 6 skipped** (the 6 skips are PostgreSQL/Redis-only). 24 new
  tests:
  - `test_category_review.py` (11): open, kinds, class versus agreement, reclassify with
    audit and same UUID, required fields, dismiss not re-proposed, reopen on a new
    suggestion, asset-page reclassify settles, agree again resolves, link + reclassify,
    all-or-nothing rollback, scope and permissions;
  - `test_triage.py` (6): assign with 428 without If-Match, assignee validation and
    picker, filters and ordering, bulk with stale versions and invisible IDs, bulk
    assign and validation, permissions and site scope;
  - `apps/quality/tests` (7): every rule including VM exemption and severities, stale
    links, auto-resolve and reopen history, dismissed stays dismissed, assign, filters
    and summary, scope and permissions, refresh with archived assets.
- Ruff check and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and matches the committed file.
- Frontend: typecheck, oxlint, **109 tests** (9 new) and the build all pass.
- GitHub CI run 41739915106 on `7698c5c` (PostgreSQL 16 + Redis 7): backend **566 passed,
  0 skipped**; migrations applied and reversed (including `quality` and `reconciliation`);
  OpenAPI drift check; frontend 109 tests; Compose config and production image builds
  pass.
- Not run: Docker stack, Playwright, browser review at 1440×900 and 390×844.

**Still open from earlier tasks (need decisions or outside input):**
- Regional Defender hosts.
- Whether excess roles should block syncs.
- Phone and tablet categories.
- DEC-15, DEC-16 and DEC-17.

**Open in this task:**
- Severity thresholds and the exemption list are initial (ASM-46).
- Review metrics were not built.
- Bulk link/create is intentionally absent.

Proposed next task: **012 | Static/dynamic groups + editor** (tasks/BACKLOG.md). Do not start
automatically.
