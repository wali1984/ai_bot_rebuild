# Full-Stack Audit + Remediation (backend / frontend / iOS)

Date: 2026-07-18 | Workflow: wgfvpxx61 (18 agents, adversarially verified)
Scope: operator directive "review and audit full backend front end and ios app and fix all issues"
Constraints honored: Codex's 57 in-flight backend files untouched; live gate stays BLOCKED.

## Baseline (before): all green
frontend typecheck + build pass; iOS core `swift build` (Linux) passes. No build/type defects —
everything below is a SEMANTIC defect.

## FIXED + committed
### Commit 285c7a6071 (11 confirmed high/medium)
- **RBAC X-Role bypass** (`api/v2/_common.py`): role now from JWT session (optional_auth), not the
  spoofable `X-Role` header. Frontend PipelineControlPanel sends credentials. RBAC integration tests
  converted from X-Role to real JWT login.
- **/api/v2/backtest/run** now `require_auth` (was anon subprocess-spawn DoS); frontend sends credentials.
- **Login brute-force limiter** (`auth_rbac.py`): per-(ip,email) fail counter, fail-OPEN on Redis error.
- **6 blocking Redis KEYS -> bounded SCAN**: chart.py (11x/req), derivatives.py (+ reused client),
  market_contracts.py (`_redis_keys` + coinapi-status), status_contracts.py (public endpoints), mobile.py.
- **iOS RiskControlView**: guarded force-unwrapped admin URL (crashed on malformed baseURL).
- **iOS AuthManager**: `@MainActor` (drove SwiftUI state off-main = data race).
- **Frontend**: funding rate 100x understatement; ingestors `0` rendered as missing; dashboard
  fabricated `$3000` equity baseline removed.

### Commit cbd6f90492 (3 low)
- **Mobile push-token IDOR**: unregister now owner-only; register stores real id ("id" not "user_id").
- **Binance paper-order fetch**: dropped dead `Bearer <never-set>` header, uses credentials:'include'.
- **loss_probability**: reuse a module-level Redis client (was a new pool per pre-trade eval).

Verification: 146 unit + 208 integration API tests pass; frontend typecheck+build green; iOS core builds;
26 mobile/loss_probability tests pass.

## VERIFIED but DEFERRED (risk/model logic on the LIVE pipeline; Codex-adjacent — flag, don't change mid-flight)
1. **`services/adaptive_gate_tuning/runtime_tuner.py:110-115`** — threshold adaptation is INVERTED for
   block-when-value>=threshold gates. `base / composite` means in degraded conditions (low composite,
   clamped 0.5) the loss-probability threshold rises to min(1.0, 0.72/0.5=1.44)=1.0 -> the loss-prob gate
   effectively never blocks exactly when data is worst. MIN-threshold gates (min_confidence, min_market_state)
   use `/composite` correctly; the MAX/block-when->= gates (loss_probability, confidence_risk, maybe
   exit_feasibility) should use `* composite`. NOT auto-fixed: the correct per-gate direction depends on each
   consumer's block semantics in the paper-loop code Codex is actively editing; changing risk-gate direction
   mid-flight could interact badly. Recommend Codex fix with the gate-consumer semantics confirmed.
2. **`services/enhanced_unified_feature_builder.py:599`** — feature-freshness metric counts a legitimate 0.0
   value as "missing"; TokenMetrics fields stored as raw strings (other fetchers float-coerce). The string
   values feed the model, so a fix touches model inputs — defer to the trainer/feature lane rather than change
   model-facing data unilaterally.

## Caveats surfaced to operator
- Auth changes (RBAC/backtest/login) verified against the test suite but NOT runtime-verified here (no live
  login/cookie flow) — operator should confirm login + pipeline control + backtest still work after deploy.
- iOS app-target edits are not compile-verified on this Linux host (SwiftUI target is macOS/iOS-only);
  reasoned for correctness, matched existing patterns.
