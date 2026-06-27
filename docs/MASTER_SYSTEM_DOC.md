# AI BOT V2 — Master System Document

**Generated:** 2026-06-23 | **Branch:** codex/pipeline-trust-refresh | **Status:** NON-LIVE. PAPER ONLY. LIVE TRADING: BLOCKED.

---

## 1. Mission

Build a GUI-first, fully auditable trading control platform (V2) that replaces the legacy bot without touching its live runtime. Target: 90%+ win-rate signal quality, zero liquidation, compounding toward 1000x equity over time. Survival and auditability come before returns.

---

## 2. Active Codex Agents (as of 2026-06-23)

| Agent | Goal | Touch zones — do NOT conflict |
|---|---|---|
| Codex Agent 1 | 90%+ win-rate / 1000x trainer quality | v2_trade_management_paper_loop.py, trainer bridge, signal publisher, goal_state/V2_CONTINUOUS_90P_* |
| Codex Agent 2 | Website + iOS redesign (NerVyx theme) | v2/frontend/, v2/mobile/, docs/nervyx-* |

Codex config (`.codex/config.toml`): `approval_policy = never`, `sandbox_mode = danger-full-access`. These agents have FULL repo access with no approval gates. Any change they make is immediate.

---

## 3. System Architecture

### 3.1 Codebase Map

```
/home/wali/Desktop/AI BOT REBUILD/
├── legacy_reference/      # READ-ONLY. The old bot. Never edit.
├── v2/
│   ├── backend/           # FastAPI backend (943 .py files)
│   │   ├── app/
│   │   │   ├── api/v1/    # V1 API routes (28/79 are stub skeletons)
│   │   │   ├── api/v2/    # V2 API routes (real implementations)
│   │   │   ├── api/middleware/ # 10-layer middleware stack
│   │   │   ├── cli/       # 226 CLI worker scripts
│   │   │   ├── adapters/  # Redis, trainer, exchange, DB adapters
│   │   │   ├── services/  # Business logic
│   │   │   └── auth/      # Auth, RBAC, session security
│   │   └── tests/         # 1419 test files
│   ├── frontend/          # React/Vite frontend (66 pages, 389 .ts/.tsx files)
│   ├── mobile/            # SwiftUI iOS/iPadOS/watchOS app (54 Swift files)
│   └── workers/           # Stub launcher dirs (actual code in cli/)
├── claude_worklog/        # Audit logs, task tracking, evidence
├── goal_state/            # Active Codex goal state directories
├── legacy_owned_runtime/  # GITIGNORED. Live bot runtime data.
└── docs/                  # Documentation (you are here)
```

### 3.2 Backend Stack

- **Framework:** FastAPI + uvicorn (py3.11+)
- **Database:** SQLite via SQLAlchemy + Alembic migrations. Path: `v2/backend/v2_paper_trading.db`
- **Redis:** Shared instance with legacy bot. V2 writes ONLY to `v2:` prefix namespace. Never writes to legacy keys.
- **Auth:** Cookie-based session tokens, RBAC with roles: viewer, admin, superadmin

### 3.3 Middleware Stack (outermost to innermost)

1. **RequestIdMiddleware** — attach X-Request-ID to every request
2. **IpAllowlistMiddleware** — IP-based gating
3. **RateLimitMiddleware** — request rate limiting
4. **StepUpMfaMiddleware** — MFA for dangerous admin actions
5. **RbacMiddleware** — role-based access control enforcement
6. **IdempotencyMiddleware** — dedup repeat requests
7. **LineageValidatorMiddleware** — signal lineage chain enforcement
8. **ApprovalMiddleware** — human approval gate for sensitive ops
9. **LiveBlockGuardMiddleware** — **blocks ALL `/api/v1/live/**` with HTTP 403 at all times**
10. **DbErrorTranslatorMiddleware** — translate DB errors to structured API errors

Source: `v2/backend/app/api/middleware/__init__.py`

### 3.4 Frontend Stack

- **Framework:** React + TypeScript + Vite
- **Pages:** 66 pages covering all CLAUDE.md required pages
- **Routing:** React Router v6 (see `v2/frontend/src/router.tsx`)
- **Theme:** NerVyx Midnight Neural (active Codex Agent 2 redesign)

### 3.5 Mobile Stack

- **Platform:** SwiftUI — iOS, iPadOS, watchOS
- **Files:** 54 Swift files in `v2/mobile/`
- **Backend endpoints:** 10 routes at `/api/v2/mobile/*`
- **Status:** TestFlight build 5 uploaded (App Store icons fixed 2026-06-22)

### 3.6 Trainer Integration Boundary

- **Rule:** V2 NEVER directly imports the legacy trainer runtime. Subprocess boundary only.
- **Adapter:** `v2/backend/app/adapters/trainer/subprocess_adapter.py`
- **Safety checks in adapter:** path validation, forbidden shell metacharacters (`;|&&$(``), env allowlist enforcement, configurable timeout, full audit event emission on every call
- **Redis writes:** adapter enforces zero writes to legacy Redis keys. Legacy reads are read-only via explicit helpers.

### 3.7 Redis Namespace Strategy

| Prefix | Owner | Mode |
|---|---|---|
| `v2:` | V2 backend | Read + Write |
| (legacy keys) | Legacy bot | Read-only from V2 |

---

## 4. API Surface

### 4.1 V1 API — /api/v1/ (Partial stub)

28 of 79 route files are `milestone_d_status = skeleton`: OPTIONS-only shims that return route metadata but no real data.

**Stub routes (no real handler bodies):**
`accounts`, `audit`, `auth`, `claude_admin`, `codex_review`, `decisions`, `discovery`, `evidence`, `exchanges`, `features`, `fleet`, `governance`, `health`, `ingestors`, `intents`, `live_mode`, `live_readiness`, `mission_control`, `monitor`, `ollama_assistant`, `paper`, `predictions`, `replay`, `risk`, `risk_decisions`, `selection`, `signals`, `universe`

**Real routes (V2 layer or auth_rbac):**
- `/api/auth/login`, `/api/auth/logout`, `/api/admin/*` — full implementation in `auth_rbac.py`
- `/api/v2/*` — market contracts, pipeline control, landing
- `/api/v2/mobile/*` — 10 mobile endpoints

### 4.2 Live Block — Permanent Default

**`/api/v1/live/**` is permanently blocked with HTTP 403** enforced in middleware layer 9. This is code-level enforcement, not config — a config change alone cannot bypass it. Response: `{"error": {"class": "live.blocked_default", "message": "Live mode is blocked by default.", "details": {"banner": "LIVE TRADING: BLOCKED"}}}`.

---

## 5. Worker Inventory (Key Workers)

All 226 CLI worker scripts live in `v2/backend/app/cli/`. Workers are started via launcher stubs in `v2/workers/` subdirectories.

| Worker | Purpose | Status |
|---|---|---|
| `v2_trade_management_paper_loop.py` | Paper trade lifecycle, B-grade quality telemetry | Active — Codex Agent 1 today |
| `v2_risk_gateway_runtime_worker.py` | Risk gate enforcement | Running |
| `v2_feature_snapshot_builder.py` | Feature pipeline assembly | Running |
| `v2_trainer_bridge.py` | Subprocess trainer adapter | Running |
| `v2_signal_publisher.py` | Signal publication to Redis | Running |
| `v2_market_ingestor.py` | Market data ingestion | Running |
| `v2_native_trainer_prediction_publisher.py` | Prediction publication | Running |
| `v2_paper_execution_worker.py` | Paper-mode execution | Running |
| `v2_script_monitor.py` | Health monitor for all other workers | Running |

---

## 6. Goal State — Current Blockers

### Primary Goal: 90%+ A-grade edge, zero liquidation, 1000x compounding release

**Status: BLOCKED** (source: `goal_state/V2_CONTINUOUS_90P_A_GRADE_EDGE_ZERO_LIQUIDATION_AND_1000X_COMPOUNDING_RELEASE/CURRENT_BLOCKERS.json`)

1. **HOLDOUT_EVIDENCE_ACQUISITION_BLOCKED** — Need ≥50,000 point-in-time-valid predictions before release. Currently: 0 countable untouched holdout rows.
2. **ALL_HOLDOUT_CANDIDATES_REJECTED** — 39,356 rows reviewed; 38,737 rejected (DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE); 39,356 rejected (NO_PRE_REGISTERED_HOLDOUT_WINDOW)
3. **INSUFFICIENT_UNTOUCHED_HOLDOUT_SYMBOL_COVERAGE** — needs ≥100 symbols; currently 0

**Codex Agent 1 work today (2026-06-23):** Added B-grade paper quality telemetry to `v2_trade_management_paper_loop.py` — directional accuracy, Brier score, ECE, MAE, precision/recall by symbol/timeframe/side/strategy/regime/confidence bucket. Explicitly marked as non-A-grade, non-promotable, not live-ready evidence. ✅

---

## 7. Safety Gates

### Hard Code-Level Safety (cannot be bypassed by config)

| Gate | Location | Enforces |
|---|---|---|
| LiveBlockGuardMiddleware | `api/middleware/live_block_guard.py` | 403 all `/api/v1/live/**` requests |
| LIVE_GATE_BLOCKED constant | `v2_trade_management_paper_loop.py:25` | Paper loop checks gate at every intent |
| SubprocessTrainerAdapter | `adapters/trainer/subprocess_adapter.py` | Subprocess boundary, no direct legacy import |
| V2_MODE default | `app/settings.py` | Defaults to `paper`, never `live` |
| LIVE_APPROVAL_TOKEN | `app/settings.py` | Required for any gate flip |

### Operations Requiring Explicit Human Approval (L4/L5 gate)

- Enable live trading
- Activate live exchange API keys
- Increase max position size or daily loss limits
- Disable kill switch or mandatory stop
- Enable hedge/DCA/ADJUST_LEVERAGE modes
- Flip V2_MODE from paper to live

---

## 8. Audit Findings — Issues & Gaps

### 8.1 CRITICAL: 3002 node_modules Files Tracked in Git

`v2/frontend/node_modules/` has 3002 files committed to git. `.gitignore` updated 2026-06-23. Git history remains bloated until operator runs cleanup:

```bash
git rm -r --cached v2/frontend/node_modules/
git commit -m "chore: remove node_modules from git tracking"
```

### 8.2 HIGH: SQLite Databases Tracked in Git

Three `.db` files are tracked (runtime artifacts, not source):
- `leases.db` at root
- `v2/backend/v2_paper_trading.db`  
- `claude_worklog/final_readiness/v2_closed_loop_spark/state/leases.db`

`.gitignore` updated with `*.db`, `*.db-wal`, `*.db-shm`. Operator cleanup:

```bash
git rm --cached leases.db v2/backend/v2_paper_trading.db
git rm --cached "claude_worklog/final_readiness/v2_closed_loop_spark/state/leases.db"
git commit -m "chore: remove sqlite databases from git tracking"
```

### 8.3 HIGH: 356 Log Files Tracked in Git

`claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/` has 356 `.log` files tracked. Largest: 48MB, 16MB, 12MB. `.gitignore` updated with `*.log`. Operator cleanup:

```bash
git ls-files "*.log" | xargs git rm --cached
git commit -m "chore: remove log files from git tracking"
```

### 8.4 MEDIUM: 28 V1 API Routes Are Stub Skeletons

All 28 V1 routes (`/api/v1/`) are OPTIONS-only scaffolds — no real data flows through them. Frontend pages backed by these routes (Monitor Center, Signal Explainability, Risk Control, Paper Trading, etc.) may be rendering mock or empty data.

**Impact on 90%+ win-rate goal:** If prediction/signal/paper-trade data doesn't reach the frontend, the monitoring loop is broken and operator cannot verify progress.

### 8.5 MEDIUM: Redis V2 Adapter Is a Stub

`v2/backend/app/adapters/redis_v2/client.py` and `streams.py` are placeholder files with no implementation. Workers likely bypass this adapter and use raw Redis — meaning the `v2:` namespace enforcement is not uniformly guaranteed.

### 8.6 MEDIUM: 423 Bare `except Exception:` in CLI Workers

123 CLI worker files have bare exception handlers (423 occurrences). Documented cases (`# noqa: BLE001`) are intentional loop-continuations. Undocumented ones silently swallow errors, making failures invisible to monitoring.

Top undocumented offenders:
- `v2_market_ingestor.py` — 5 occurrences  
- `v2_prediction_signal_natural_language_explainer.py` — 4
- `v2_dynamic_symbol_discovery_free_tier.py` — 4
- `v2_operator_review_publisher.py` — 3

### 8.7 LOW: No CORS Middleware in FastAPI Stack

The 10-layer middleware stack has no `CORSMiddleware`. Acceptable if nginx handles CORS for the production domain. Verify: nginx at `dashboard.wajidali.us` must add CORS headers for `/api/*` so the iOS app and any third-party tool can reach the API.

### 8.8 LOW: Root-Level Artifact Clutter

Many large audit JSONs, pass/evidence run directories, and runtime status files are at repo root. `.gitignore` updated 2026-06-23 to prevent new additions. Existing tracked artifacts that should be moved or removed:

- `QUARANTINE_REVIEW_20260612_*.md` and `.targets.json`
- `PASS2A_*.md`, `PASS2B_*.md`, `PASS4A_*.md`
- `PIPELINE_TRUST_AUDIT.md`, `PIPELINE_TRUST_VERIFICATION.md`
- `PUBLISHER_PROOF_BLOCKERS_*.md`, `PUBLISHER_PROOF_RESULT_*.md`
- Large legacy inventory JSONs: `legacy_hybrid_trainer_*.json`, `trainer_*.json`
- `pass2b_edge_proof/`, `pass3*_*/` directories
- `publisher_proof/` directory

---

## 9. Codex Behavior Audit — Intentional Bugs Check

**Verdict: No intentional sabotage or goal-blocking code found.**

Reviewed:
- `LiveBlockGuardMiddleware` — correctly enforces 403 on all live paths ✅
- `v2_trade_management_paper_loop.py` — LIVE_GATE_BLOCKED enforced at every intent, no live execution paths ✅  
- `subprocess_adapter.py` — properly blocks direct runtime import, shell metacharacter injection, and Redis writes ✅
- B-grade telemetry added 2026-06-23 — correctly marked non-A-grade, non-promotable, no live implications ✅

**Structural debt Codex has been building around rather than filling:**

1. V1 API stubs remain after many sprints. Codex has been building CLI workers instead of wiring the API layer. Frontend may be operating on mocked data for the dashboards it needs most.
2. Redis V2 adapter stub means namespace isolation is not uniformly enforced — a risk if workers accidentally write to legacy keys.

These are architectural debts, not intentional bugs. They block the monitoring loop needed to verify the 90%+ target.

---

## 10. Repo Cleanliness — Changes Made 2026-06-23

### .gitignore Additions

| Pattern | Reason |
|---|---|
| `node_modules/`, `**/node_modules/` | 3002 frontend files tracked |
| `*.db`, `*.db-wal`, `*.db-shm` | SQLite runtime files tracked |
| `*.log` | 356 log files tracked |
| `worker_pool_status.json` | Runtime status file |
| `operator_dashboard_payload.json` at root | Runtime artifact |
| `legacy_hybrid_trainer_*.json` | Large regeneratable audit JSONs |
| `pass2b_edge_proof/`, `pass3*_*/`, etc. | Audit run snapshots |
| `goal_state/*/operator_dashboard_payload.json` | Runtime payloads up to 35MB each |

### Pending Operator Cleanup

All three actions below affect currently tracked files — they must be confirmed by operator before execution.

1. `git rm -r --cached v2/frontend/node_modules/` (3002 files)
2. `git rm --cached leases.db v2/backend/v2_paper_trading.db` (2 db files)
3. `git ls-files "*.log" | xargs git rm --cached` (356 log files)

---

## 11. Live Readiness Gate Summary

**Status: BLOCKED — multiple gates unmet**

| Gate | Required | Current |
|---|---|---|
| Holdout predictions (A-grade) | ≥50,000 | 0 countable |
| Holdout symbol coverage | ≥100 | 0 countable |
| A-grade model quality | Required | B-grade only |
| Paper soak | In progress | Running |
| V1 API completeness | All routes real | 28 stubs |
| Redis V2 adapter | Real implementation | Stub |
| CORS verification | Confirmed | Unverified |

---

## 12. Key File Locations

| Concern | File |
|---|---|
| Live block middleware | `v2/backend/app/api/middleware/live_block_guard.py` |
| Trainer subprocess adapter | `v2/backend/app/adapters/trainer/subprocess_adapter.py` |
| V2 settings + env vars | `v2/backend/app/settings.py` |
| RBAC auth routes | `v2/backend/app/api/auth_rbac.py` |
| Paper trade loop (Codex Agent 1) | `v2/backend/app/cli/v2_trade_management_paper_loop.py` |
| Risk gateway worker | `v2/backend/app/cli/v2_risk_gateway_runtime_worker.py` |
| Frontend router | `v2/frontend/src/router.tsx` |
| iOS app | `v2/mobile/` (54 Swift files) |
| Codex config | `.codex/config.toml` |
| Agent rules | `AGENTS.md` |
| Current goal blockers | `goal_state/V2_CONTINUOUS_90P_A_GRADE_EDGE_ZERO_LIQUIDATION_AND_1000X_COMPOUNDING_RELEASE/CURRENT_BLOCKERS.json` |
| This document | `docs/MASTER_SYSTEM_DOC.md` |
