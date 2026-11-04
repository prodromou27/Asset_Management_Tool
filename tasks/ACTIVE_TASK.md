# Current Task: 012 | Static/dynamic groups + editor

Status: **Complete (workstation-verified; CI pending at the time of writing)**
(2026-11-04, branch DEV).

**Read:** AGENTS.md, docs/00, 01 (Make asset group), 03 (Groups, group rule representation),
04 (Groups endpoints), 07 (GroupRuleBuilder), 08 (§8 Groups), 09 (role matrix), 11 (Groups),
15 (A07), 17.

**Previous:** 011 reconciliation review, category reviews and data-quality queues (CI run
41739915106 green: backend 566 passed, frontend 109).

## Scope

- Static and dynamic asset groups with a typed rule builder, live preview, versioned rules,
  explained and historical membership, nesting without cycles, and site-scoped visibility
  (groups never grant access).

Out of scope:
- Group export and import (Tasks 014 and 013).
- Report recipients and notification policy (Task 018).
- Lifecycle stats and source coverage on the group page (Tasks 015 and 022).
- Bulk "add to group" from the asset list.

## Outcome

**Backend (`apps.groups`):**
- Models:
  - `AssetGroup`: static or dynamic, parent, owner, current rule and version, last
    evaluated, archived, version.
  - `AssetGroupRuleVersion`: number, rule, reason, author.
  - `AssetGroupMembership`: explicit or evaluated, rule version, who and why added or
    removed. Never deleted; one active row per group and asset.
- `rules.py`:
  - a validated JSON tree (`and`/`or`/`not`; `eq`, `in`, `contains`, `before`, `after`)
    over an allowlist of 21 asset fields;
  - limits: depth 5, 50 nodes, 100 values per list, 200 characters per value;
  - compiled to parameterised ORM `Q`/`Exists`, with category and site subtrees,
    "not set" values, source links, last seen and `member_of`;
  - archived assets never match.
- `services.py`:
  - create and update (rule changes need a reason, create a new version and re-evaluate);
  - parent and reference cycle checks;
  - archive, refused while the group has children or is referenced; frees the name;
  - evaluate (adds and removes with rule-version reasons), and `evaluate_all` (referenced
    groups first; hourly Celery beat);
  - static member add/remove (removals need a reason; dynamic groups refuse explicit
    members);
  - preview (visible assets only; for an existing group, would add/remove).
- Audit entries: `groups.create`, `groups.update`, `groups.archive`, `groups.evaluate`,
  `groups.members`.
- Permissions (docs/09):
  - `groups.view`: all roles;
  - `groups.manage`: System Admin, ITAM Manager;
  - `groups.members`: System Admin, ITAM Manager, Infrastructure Engineer, Asset Operator.

**Migrations (all reversible; CI reverses `groups`):**
- `groups.0001_asset_groups`
- `accounts.0006_group_permissions`

**APIs (new):**

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/groups/` | List with visible member counts; create |
| GET, PATCH | `/groups/{id}/` | PATCH needs If-Match |
| POST | `/groups/{id}/archive/` | Needs If-Match and a reason |
| POST | `/groups/preview/`, `/groups/{id}/preview/` | Rule preview |
| GET | `/groups/{id}/assets/` | `history`, `q` |
| POST | `/groups/{id}/members/` | Static add/remove |
| POST | `/groups/{id}/evaluate/` | Re-evaluate now |
| GET | `/groups/{id}/rule-versions/` | Rule history |
| GET | `/groups/fields/` | Rule-builder field catalogue |
| GET | `/assets/{id}/groups/` | Groups an asset belongs to |

**UI:**
- **Groups** in the sidebar.
- List: kind, rule summary, members in your sites, owner, last evaluated.
- "New group" dialog: kind, name, description, parent, owner, and for dynamic groups the
  rule builder (typed rows, field-specific operators, enum, reference and date pickers,
  multi-select for `in`, Exclude, nested AND/OR groups) with a live preview of the
  matching count and sample.
- Group page:
  - details, re-evaluate, edit details, archive with a reason;
  - rule panel: edit with a preview of the membership difference, plus a reason;
  - rule history;
  - members table: why (manual or rule version), since, removed history, search;
  - static: add assets by search, remove selected with a reason.
- Asset page: **Groups** tab.
- Shared helpers in `ruleUtils.ts`; builder styles.

**Docs:** docs/17 ASM-47 and ASM-48; README section.

## Verification (workstation; SQLite test-only fallback, no Docker/PostgreSQL here)

- **Backend: 582 passed, 6 skipped** (the 6 skips are PostgreSQL/Redis-only). 22 new tests
  in `apps/groups/tests/test_groups.py`:
  - 9 invalid-rule cases; size and depth limits;
  - rule semantics: subtrees, text, empty, enum, owner, hostname, and/or/not, archived;
  - dates, source links, last seen and `member_of`;
  - dynamic lifecycle via the API: preview, create, evaluate, audit, diff preview, rule
    change with reason, history reasons, versions;
  - re-evaluation follows asset changes;
  - dependency-ordered evaluation; circular references and parents rejected;
  - archive blocked while referenced, and the name is reusable;
  - static members: idempotent adds, removal reasons, audit, asset groups endpoint,
    dynamic refuses explicit members;
  - **no access widening** (docs/15 A07);
  - role permissions and site scope for members;
  - kind immutable, static has no rule, unique names;
  - field catalogue.
- Ruff check and format are clean; no migration drift; the OpenAPI schema validates with
  `--fail-on-warn` and matches the committed file.
- Frontend: typecheck, oxlint, **116 tests** (7 new) and the build all pass.
- Not run: Docker stack, Playwright, browser review at 1440×900 and 390×844.

**Open:**
- Evaluation runs on save, on demand and hourly, not on every asset change (ASM-48).
- Group export, import and notifications come with Tasks 013, 014 and 018.
- Earlier open items: DEC-15, DEC-16 and DEC-17; regional Defender hosts; whether excess
  roles should block syncs; phone and tablet categories; ASM-46 severities.

Proposed next task: **013 | CSV/XLSX imports with preview/guarded upsert**
(tasks/BACKLOG.md). Do not start automatically.
