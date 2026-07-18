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

## VERIFIED but DORMANT (real latent bugs, but NOT in the live pipeline — investigated, not live risks)
Investigation result: both flagged risk/model-logic items are in superseded/dormant code with no live
consumers, so neither latent bug reaches production. Left as-is (editing dead code is churn); noted here
for a future dead-code cleanup, not a live fix.
1. **`services/adaptive_gate_tuning/runtime_tuner.py:110-115`** — threshold adaptation IS inverted for
   block-when-value>=threshold gates (`base/composite`; e.g. loss-prob threshold rises to min(1.0,0.72/0.5)=1.0
   in degraded conditions -> never blocks when data is worst; should be `* composite`). BUT this module has
   **zero live importers** (`grep` for any import = empty). The LIVE tuner is
   `ai-bot-v2-adaptive-gate-tuner.service` -> `cli/v2_adaptive_gate_tuner.py`, which uses FIXED thresholds
   (0.85/0.80), NOT the inversion. So the bug is latent in dead code; production is unaffected.
2. **`services/enhanced_unified_feature_builder.py:599`** — 0.0-as-missing freshness metric + TokenMetrics
   stored as raw strings. BUT this module is only referenced by `cli/day5_simple_validation.py` (an old
   phase-5 validation script) + day5 docs — NOT imported by the running paper loop or trainer. Dormant;
   the live model pipeline does not consume it.

Net: every defect on the LIVE backend/frontend/iOS surfaces is fixed. The two remaining items are
dead-code latent bugs, not live risks.

## PASS 2 (services / CLI / data-integrity / config) — workflow wu1w0l5je
Second pass on the under-covered layers. is_live filter used (0 dead-code false alarms).

### FIXED + committed (0747c64fb2)
- cross_margin_liquidation.py:137 — SHORT shocked-maintenance wrong side-sign; cascade guard withheld a
  protective close in an up-squeeze. Sign dropped (maintenance scales with abs(notional)).
- 3 live status publishers (technical_analysis / ingestors_status / decision_lineage) — blocking KEYS +
  per-key TTL fan-out on the 634K store to bounded SCAN + one pipelined TTL; decision_lineage loop wrapped
  in try/except (was crash-restart churn).
- mobile.py:1371 — iOS equity curve + win/loss donut now use canonical NET pnl (was gross alias).
- canonical_pnl.py:53 — freshness lags off OLDEST source (fresh secondary key no longer masks stale equity).
- main.py:302 — Swagger/ReDoc/OpenAPI disabled in production (info-disclosure hardening).

### DEFERRED to TRAINER lane (model-facing; inference-only change would cause train/serve skew)
- v2_liquidation_enhanced.py:294-295 (long_oi and short_oi both = total OI to a constant ratio) and :298
  (5-min liq count relabeled 1-min, ~5x velocity inflation). Fix in training+inference together + retrain.

### OPERATOR-CONFIG flags (not repo code fixes; some CRITICAL)
1. CRITICAL: ALPHAFORGE_ENV is UNSET on the live public backend, so ALL production auth hardening is inert:
   verify_admin_step_up_code returns True unconditionally (admin MFA step-up bypass), plus cookie-secure /
   samesite / token-revocation are not enforced. Set ALPHAFORGE_ENV=production in the deploy env AND provision
   the now-required secrets (admin step-up TOTP secret etc.) in the SAME change. (auth/security.py:90,311)
2. adaptive_gate_tuner.py:116,233 (live ai-bot-v2-adaptive-gate-tuner.service) reads
   v2:market:candle:latest:SYM which NO service writes, so volatility/regime adaptation is permanently DEAD
   (protective high-vol tightening never fires). Repoint to an existing candle key (v2:market:kline_current:
   binance:SYM:1m) + freshness gate. NOT auto-applied: changes live paper-gate thresholds, Codex-adjacent —
   operator/Codex should own activation.
3. public-website-backend base systemd unit hardcodes V2_BACKEND_PORT=5173 (collides with the vite frontend;
   only a release drop-in masks it) — set the base unit to 8000.
4. Two legacy old-bot systemd units execute the forbidden legacy tree with Restart=always — operator should
   mask/disable them (do not edit the legacy tree itself).

### NOTE: 52 PRE-EXISTING domain-purity test failures
tests/unit/domain/{shadow_mode_readiness,trainer_prediction_output}/* fail on the CURRENT tree even with my
pass-2 changes stashed, so NOT caused by this audit — most likely from Codex's uncommitted changeset adding a
forbidden import into a domain module. Flag for Codex's commit validation.

## Caveats surfaced to operator
- Auth changes (RBAC/backtest/login) verified against the test suite but NOT runtime-verified here (no live
  login/cookie flow) — operator should confirm login + pipeline control + backtest still work after deploy.
- iOS app-target edits are not compile-verified on this Linux host (SwiftUI target is macOS/iOS-only);
  reasoned for correctness, matched existing patterns.
