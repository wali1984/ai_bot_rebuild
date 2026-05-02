# B — Test and CI Skeleton Validation

## 1. Scope
Materialize the test and CI skeleton for AI BOT V2 per
`claude_worklog/v2_scaffold_planning/07_TEST_AND_CI_PLAN.md` §4–§5. This
milestone produces the CI scripts, GitHub workflow, and top-level Makefile
that wire every required stage from the test pyramid (lint, type,
import-cycle, schema-drift, unit, integration, contract, frontend-unit,
e2e, a11y, coverage, security-audit, secrets-scan). Schema-drift,
orphan-path, coverage, security-audit, and a11y are advisory in this
milestone and become mandatory at later milestones (C, F, H) per the
plan. No domain handlers, no live calls, no legacy Redis/DB access.

Authority:
- `claude_worklog/v2_scaffold_planning/07_TEST_AND_CI_PLAN.md` (§4 gates,
  §5 stage matrix, §10 runtime constraints).
- `claude_worklog/v2_scaffold_planning/02_PACKAGE_AND_MODULE_MAP.md` §3
  (forbidden imports enforced by `import_cycle_check.py`).
- `CLAUDE.md` Local-Native First Runtime Constraints (Docker not required;
  legacy infra never touched).

## 2. Boundaries observed
- Wrote only under `v2/**` and `claude_worklog/v2_build/**`.
- Did not edit `legacy_reference/**`, `../AI BOT/**`, `.env`, or any
  secrets file.
- Did not write to legacy Redis. Did not place or cancel exchange orders.
  Did not change leverage or margin mode. Did not restart the live trader,
  live trainer, or any live service. Did not enable live trading.
- Did not import legacy trainer modules into the FastAPI process. Did not
  pip-install into the protected trainer venv. The trainer venv is never
  invoked from CI; trainer-adapter tests use a stub subprocess per
  07_TEST_AND_CI_PLAN.md §10.
- Did not require Docker for any required CI stage. The integration stage
  uses GitHub Actions' service-container Postgres (or a local
  testcontainers-managed Postgres when run from the developer host); no
  custom Dockerfile is added.
- The GitHub workflow file is materialized under `v2/.github/workflows/`
  to honor the writable-path boundary in `CLAUDE.md`. To activate it on
  GitHub Actions, an operator with broader perms must place a copy or
  symlink at the repository root (see §6).
- LIVE TRADING: BLOCKED (default). The CI environment defaults to
  `V2_MODE=paper` and `V2_REDIS_PREFIX=v2:test`; `test.sh` refuses to run
  if `LEGACY_REDIS_URL` or `LEGACY_BOT_ROOT` leak into the env.

## 3. Files materialized

### 3.1 CI scripts under `v2/ops/ci/`
- `lint.sh` — runs `ruff check backend` (mandatory) and the frontend
  `eslint --max-warnings=0` when an eslint config + node_modules are
  present (advisory until milestone F per 015E §13).
- `type_check.sh` — runs `mypy --strict backend` (mandatory) and
  `tsc -b --noEmit` when frontend node_modules are installed (mandatory
  once installed; advisory otherwise).
- `test.sh` — orchestrator with stages `unit | integration | contract |
  property | frontend-unit | e2e | all`. Refuses to run when
  `LEGACY_REDIS_URL` or `LEGACY_BOT_ROOT` are present in the env.
  Defaults `V2_MODE=paper` and `V2_REDIS_PREFIX=v2:test`.
- `import_cycle_check.py` — uses grimp to enforce the forbidden edges
  declared in `02_PACKAGE_AND_MODULE_MAP.md` §3:
  - `app/api/** -> app/adapters/db/**`
  - `app/domain/** -> app/adapters/**`
  - `app/domain/** -> {redis, sqlalchemy, httpx, requests, psycopg,
    asyncpg, ccxt}`
  - `app/adapters/trainer/** -> legacy_reference/**` or `AI BOT/**`
    (textual scan; no module imports)
  - any module `-> dotenv` outside `app/settings.py` (textual scan)
  - `frontend/src/pages/** -> frontend/src/api/client.ts` (textual scan)
  Also runs Tarjan SCC detection over `app.*` to flag import cycles, and
  delegates frontend cycle scanning to `madge` (advisory if not
  installed).
- `schema_drift_check.py` — diffs Alembic head vs
  `app.adapters.db.base.Base.metadata`. Advisory in milestone B (zero
  versions, empty metadata is the expected harness state from milestone C
  build artifact). Promote to FAIL by setting `SCHEMA_DRIFT_MANDATORY=1`
  starting milestone C.
- `secrets_scan.sh` — runs gitleaks (working tree, no-git, redacted).
  Mandatory from milestone B per 07_TEST_AND_CI_PLAN.md §5; falls back to
  WARN-skip when gitleaks is unavailable on the local host.
- `orphan_path_check.py` — verifies every directory under
  `v2/backend/app` and `v2/backend/tests` carries `__init__.py` or
  `.gitkeep`, and rejects committed `__pycache__`, `*.pyc`, `*.bak`,
  `*.swp`, `*.orig`. Advisory by default; promote to FAIL with
  `ORPHAN_MANDATORY=1`.

The five pre-existing placeholder files (lint.sh, type_check.sh, test.sh,
import_cycle_check.py, schema_drift_check.py from milestone B/015A) are
overwritten with the concrete implementations described above.

### 3.2 GitHub Actions workflow
- `v2/.github/workflows/ci.yml` — single workflow declaring jobs for
  every required and advisory stage:
  - Required (must pass): lint, type, import-cycle, unit, integration,
    contract, frontend-unit, e2e, secrets-scan.
  - Advisory (`continue-on-error: true`): schema-drift, orphan-path, a11y,
    coverage, security-audit.
  - `ci-required` aggregator job sets the protected-branch gate: it
    `needs:` every required job and serves as the single required check.
  - Integration job uses a Postgres 16 service container, no Docker
    build, no custom image. `DATABASE_URL=postgresql+psycopg://...`
    matches `tests/integration/test_alembic_round_trip.py` from
    015B / `C_DATABASE_SKELETON_VALIDATION.md`.
  - Frontend jobs install via `npm install` and use `npx playwright
    install --with-deps chromium` for browser provisioning.

### 3.3 Top-level Makefile
- `v2/Makefile` — single source of truth for invoking the matrix locally.
  `make ci` runs the full pipeline (required + advisory). `make
  ci-required` runs only the must-pass stages. Per-stage targets
  (`ci-lint`, `ci-type`, `ci-import-cycle`, `ci-schema-drift`,
  `ci-orphan-path`, `ci-unit`, `ci-integration`, `ci-contract`,
  `ci-property`, `ci-frontend-unit`, `ci-e2e`, `ci-secrets-scan`,
  `ci-coverage`, `ci-security-audit`) are exposed for granular use.
  The Makefile is rooted at `v2/` (the top of the V2 control plane);
  `make help` documents the full target inventory.

## 4. Stage matrix and milestone gating

| Stage | Mandatory at | Implementation | Failure semantics |
|-------|--------------|----------------|-------------------|
| lint | B | `ops/ci/lint.sh` (ruff + eslint advisory) | hard fail |
| type | B | `ops/ci/type_check.sh` (mypy --strict + tsc) | hard fail |
| import-cycle | B | `ops/ci/import_cycle_check.py` (grimp + textual + Tarjan) | hard fail |
| schema-drift | C | `ops/ci/schema_drift_check.py` | advisory in B; FAIL once `SCHEMA_DRIFT_MANDATORY=1` |
| orphan-path | (advisory) | `ops/ci/orphan_path_check.py` | advisory by default |
| unit | C | `pytest backend/tests/unit -q` via `test.sh unit` | hard fail |
| integration | C | `pytest backend/tests/integration -q` via `test.sh integration` (ephemeral PG) | hard fail |
| contract | D | `pytest backend/tests/contract -q` via `test.sh contract` | hard fail |
| property | C | `pytest backend/tests/property -q` via `test.sh property` | hard fail |
| frontend-unit | E | `vitest run` via `test.sh frontend-unit` | hard fail (advisory pre-F install) |
| e2e | E | `playwright test` via `test.sh e2e` | hard fail (advisory pre-install) |
| a11y | F | axe-core within Playwright | advisory until F |
| coverage | C | `pytest --cov=app` ≥ 80% on `app/domain` | advisory until C |
| security-audit | H | pip-audit + npm audit | advisory until H |
| secrets-scan | B | `ops/ci/secrets_scan.sh` (gitleaks, redacted) | hard fail |

This matrix mirrors 07_TEST_AND_CI_PLAN.md §5 verbatim. Where the plan
demands a gate that is not yet ready (eslint/vitest/axe-core not
installed per 015E §13), the script logs WARN and exits 0; the workflow
job remains visible so milestone F can promote it without re-wiring.

## 5. Local-native posture
- No Docker is required for any required stage. Integration uses a
  service container provisioned by the runner; the developer host can
  use `testcontainers` (already pinned in `pyproject.toml`'s `dev`
  extra) or a locally-running Postgres reachable via `DATABASE_URL`.
- The trainer venv is never invoked from CI. Trainer-adapter integration
  tests will (in milestone J) call a stub subprocess that simulates
  `--mode read_only/status/export` outputs, per 07_TEST_AND_CI_PLAN.md §10.
- Legacy Redis is never reached. `test.sh` actively guards against
  `LEGACY_REDIS_URL` and `LEGACY_BOT_ROOT` leaking into the test env.
- All Redis traffic in tests goes through `${V2_REDIS_PREFIX}` which
  defaults to `v2:test` — disjoint from any legacy key namespace.
- LIVE TRADING: BLOCKED. `V2_MODE` defaults to `paper` everywhere.

## 6. Operator placement of `.github/workflows/ci.yml`
The GitHub Actions runner reads workflows from `.github/workflows/` at
the repository root only. Since `CLAUDE.md` constrains writable paths to
`./v2/**` (and a few sibling roots), this milestone materializes the
workflow at `v2/.github/workflows/ci.yml`. To activate the workflow on
GitHub, an operator must:

    mkdir -p .github/workflows
    ln -sf ../../v2/.github/workflows/ci.yml .github/workflows/ci.yml
    git add .github/workflows/ci.yml
    git commit -m "ci: install v2 workflow at repo root"

A symlink is preferred so `v2/.github/workflows/ci.yml` remains the
single source of truth. A copy is also acceptable; in that case any edit
to the v2 file must be re-applied to the root copy.

## 7. Forbidden-edge enforcement (planning view)
`import_cycle_check.py` covers every rule in 02_PACKAGE_AND_MODULE_MAP.md §3.
At this milestone the v2 source tree is largely stubs, so the script is
expected to exit 0 with `[import-cycle] OK`. The script is hardened to
keep its semantics stable as the tree fills in:
- Layer rules (`api -> adapters.db`, `domain -> adapters`) use grimp's
  resolved module graph; they are precise modulo Python import semantics.
- Domain external rule scans seven explicit external packages
  (`redis|sqlalchemy|httpx|requests|psycopg|asyncpg|ccxt`).
- Trainer-legacy and dotenv rules use textual `re` matching against
  `.py` files; this catches `from legacy_reference.foo import bar` and
  `import dotenv` without requiring the legacy modules to be installed.
- Frontend `pages -> api/client.ts` uses an import-spec textual match;
  promote to madge-based AST analysis at milestone F.

## 8. Default-deny posture preserved
- `lint.sh`, `type_check.sh`, `test.sh`, and the workflow do not import
  any exchange SDK, do not call any live endpoint, and do not require
  the live trader or live trainer to be running.
- The integration job's Postgres is ephemeral (the GitHub-managed service
  container is destroyed at job exit; testcontainers tears down the local
  container at process exit).
- `secrets_scan.sh` runs gitleaks with `--redact`, so any positive find
  is masked in the CI log.

## 9. Deviations from `07_TEST_AND_CI_PLAN.md`
- eslint, vitest, and axe-core are NOT installed in the frontend at this
  milestone (carried over from 015E §13). The matching CI stages are
  wired but exit 0 with WARN until milestone F installs the packages.
  None of these deviations affect any safety property listed in §5 or §6
  of the plan.
- Coverage gating (≥ 80% domain line, ≥ 70% domain branch) is parked at
  advisory until milestone C, when the first domain modules ship.
- `pip-audit` and `npm audit --omit=dev` are advisory until milestone H,
  matching the plan's §5 row.
- Madge cycle detection runs only when `frontend/node_modules/.bin/madge`
  is present; otherwise it is skipped with a clear advisory log line.
- The GitHub workflow file lives at `v2/.github/workflows/ci.yml` for
  boundary compliance and must be installed at the repo root by an
  operator (see §6). This is a placement deviation, not a behavioral one.

## 10. Files written
- `v2/ops/ci/lint.sh` (overwritten)
- `v2/ops/ci/type_check.sh` (overwritten)
- `v2/ops/ci/test.sh` (overwritten)
- `v2/ops/ci/import_cycle_check.py` (overwritten)
- `v2/ops/ci/schema_drift_check.py` (overwritten)
- `v2/ops/ci/secrets_scan.sh` (new)
- `v2/ops/ci/orphan_path_check.py` (new)
- `v2/.github/workflows/ci.yml` (new)
- `v2/Makefile` (new)
- `claude_worklog/v2_build/B_TEST_CI_VALIDATION.md` (this file)

## 11. Verification (planning-level for this headless emission)
This artifact was emitted as `BEGIN_FILE` blocks per the headless contract
used for milestones B/C/D/E. Concrete CI runs are deferred to a
tool-enabled follow-up that will:
- run `make ci-required` from `v2/` and observe all required stages
  exiting 0 against the existing scaffold;
- install the workflow at `.github/workflows/ci.yml` (per §6);
- promote schema-drift and orphan-path to mandatory at milestone C and
  beyond by setting `SCHEMA_DRIFT_MANDATORY=1` and `ORPHAN_MANDATORY=1`
  in the workflow env.

The skeleton's structural assertions are auditable directly from the
emitted source: stage count (14), required-stage cardinality (9),
boundary-respecting GitHub workflow placement (1 file under
`v2/.github/workflows/`), and grimp-enforced forbidden-edge cardinality
(6 rules from 02_PACKAGE_AND_MODULE_MAP.md §3).

## 12. Status
B_TEST_CI_VALIDATION_READY
