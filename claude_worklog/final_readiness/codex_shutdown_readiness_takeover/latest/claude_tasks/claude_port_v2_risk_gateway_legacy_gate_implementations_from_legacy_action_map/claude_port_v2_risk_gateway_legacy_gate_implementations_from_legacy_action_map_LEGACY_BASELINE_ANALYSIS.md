# Legacy Baseline Analysis — V2 risk-gateway legacy gate callables

Date: 2026-05-14. All citations point at preserved copies under `v2/legacy_preserved/full_runtime_closure/risk/` whose SHA256 are recorded in `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json`.

## 1. risk/kill_switch.py (SHA256 bf730c6fa425097aa0c246dfbab88e4f8d158afdd606a905c8f9e3c7695df59e, 192 lines)

- Redis key: `KILL_SWITCH_KEY = "wma:kill_switch"` (line 10). Scoped keys: `wma:kill_switch:{account}`, `wma:kill_switch:{symbol}`.
- GLOBAL allowlist (line 13–24): `{"ORCH_STALLED","SYSTEMIC_EMERGENCY","REDIS_DOWN","MARKET_DATA_DOWN","INFRA_EMERGENCY"}` — non-allowlisted GLOBAL codes are downgraded to ACCOUNT when an account is provided.
- `kill_switch_blocks(data, account=, symbol=)` (line 173–192) is the decision predicate:
  - `not data.active` → returns False (allow).
  - scope == `GLOBAL` → True (deny).
  - scope == `ACCOUNT` → True if no account query, else True iff account matches.
  - scope == `SYMBOL` → True if no symbol query, else True iff symbol matches.
  - corrupt JSON → returns `{"active":True,"code":"KILL_SWITCH_CORRUPT","scope":"GLOBAL"}` → True (deny). Lines 162–168.
- V2 callable parity: `evaluate_kill_switch_state` mirrors `kill_switch_blocks` scope-resolution semantics and corrupt-payload deny. Provenance capture, TTL clamp, and telegram dedupe are out of scope for the gate verdict — they are observability concerns.

## 2. risk/halt_manager.py (SHA256 49504d73a9fef319eb0ac6282d571492714a62526bc1c9849148685ad7eac314, 614 lines)

- `class HaltManager` (line 20). Key state: `account_id`, `kill_key`, redis, telegram.
- `is_halted()` (line 94–98) wraps `get_kill_switch(account=self.account_id)` and returns `(halted, data)`.
- `_fail_storm_triggered(window_sec=120, threshold=10)` (line 48–61) — Redis `zadd / zremrangebyscore / zcard` over `wma:exec_fail:{account_id}`. If count ≥ 10 within 120s → halt.
- `_mu_breach_sustained(mu_after, max_mu, breach_delta=0.03, sustain_sec=15)` (line 63–86) — sustained MU breach detection over 15 s.
- V2 callable parity: `evaluate_halt_state` accepts `halted: bool` plus `halt_code ∈ {"", "kill_switch_active", "fail_storm", "mu_breach_sustained"}`. Time-window state-machine math (zadd / zcard) is delegated to the caller's snapshot.

## 3. risk/reduce_only_latch.py (SHA256 e0dc68486a5cc2fa0fc0ea1d1197f66373f8c090deb889a403257e187c7ac611, 188 lines)

- Module docstring (lines 1–14): post-deleverage Redis latch at `risk:reduce_only_until:{account_id}` for N seconds, value `"{until_epoch_ms}|{reason}"`, TTL = N + 10. Only CLOSE / TP / SL pass through.
- `set_latch / get_latch / clear_latch / set_latch_per_symbol / get_latch_per_symbol` (lines 37–188).
- `get_latch` returns `(active: bool, until_ms: int, reason: str)`.
- V2 callable parity: `evaluate_latch_state` accepts `latch_active: bool` and `is_risk_add: bool`. When `latch_active and is_risk_add` → `close_only` (mirrors "only CLOSE / TP / SL pass"). When `latch_active and not is_risk_add` → `allow` (reduce always passes). When not latched → `allow`. Per-symbol latch parity is documented as a remaining gap and would be a separate state field.

## 4. risk/intelligent_close_guard.py (SHA256 7edf6d5eca3e8654bc17f0fad22831e4daedb411138d576904a29ab0a352c3ee, 1,164 lines)

- Docstring lines 1–27: weights `regime > unified_features > coinapi_wsds > trainer:intent > prediction:*`. `CloseGuardVerdict` actions `"ALLOW_CLOSE"` / `"DEFER_CLOSE"` (lines 66–78).
- Hard emergency rule (docstring line 22–24): MU>85% or IM>85% → bypass guard entirely (close anyway).
- V2 callable parity: `evaluate_close_guard` accepts `guard_action ∈ {"allow_close","defer_close","emergency_bypass"}`. `allow_close` → `allow`, `defer_close` → `deny` (prevent auto-close), `emergency_bypass` → `close_only` (force reduce-only flow even though the guard would otherwise defer). The 2000+-feature hold-score computation is delegated to the caller's pre-step.

## 5. risk/auto_deleverager.py (SHA256 76652e99ec0b0717a3bfea887c25f78746df7765ba3f5e4eff6a21d0e820a377, 1,745 lines)

- Layer-2 deleverager (docstring lines 1–45). Triggers (line 10):
  1. account IM/equity > cap OR MU > mu_cap → reduce worst-margin symbol largest leg.
  2. any symbol IM/equity > sym_cap → reduce that symbol's largest leg.
  3. hedge-aware PAIR_REDUCE (60/40) when both legs present.
- Always `reduce_only=True`; never opens, never flips.
- `class AutoDeleverager` (line 171). `DeleverageOrder` (line 127). `DeleverageCheckResult.needed: bool` (line 158).
- V2 callable parity: `evaluate_adl_state` accepts `cap_breach ∈ {"", "account", "mu", "symbol"}`. Any non-empty → `close_only` with the matching reason. Hedge-pair sizing math is a remaining gap.

## 6. risk/shared_risk_gate.py (SHA256 62c2403f2cf2ce5dec71522b919f1db6a2f6908e338903e359e021c75c59dd7f, 404 lines)

- `check_risk_gate(...)` (line 59). Checks in order (lines 116–298):
  - 0. emergency margin gate (`mr_pct ≥ 20%` / `mu_pct > 75%`, protective hedges 50% / 85%) → `EMERGENCY_MARGIN_BLOCK`.
  - 1. reversal gate (`reversal:global.active == True`) → `SHARED_REVERSAL_BLOCK` unless hedge_intent.
  - 2. RBA cadence (`risk_budget:state:{account_id}.cadence_min_sec`) → `SHARED_CADENCE_BLOCK`.
  - 3. RBA max symbols → `SHARED_MAX_SYMBOLS_BLOCK`.
  - 4. toxicity extreme → `SHARED_TOXICITY_EXTREME_BLOCK` (handled separately in our gate #9).
- Reduces always pass: `if is_reduce and not is_risk_add: return passed=True` (line 108).
- V2 callable parity: `evaluate_budget_state` accepts `block_code ∈ {"", "cadence","max_symbols","reversal","emergency_margin"}` plus `is_risk_add`/`is_reduce`. Reduce-only branch returns `allow`. Non-empty block code on risk-add → `deny` with matching reason. Toxicity check is intentionally moved to gate #9 for compositional clarity (legacy bundles them; the V2 mapping documents this split).

## 7. risk/margin_governor.py (SHA256 e8448d2ee70697a97fbb4af27555adabe2af590d8185ebfc644b965070376eee, 876 lines)

- `class GovernorVerdict` (line 67–100): actions `ALLOW`, `BLOCK`, `DELEVERAGE`; codes include `GOV_ACCOUNT_MARGIN_BREACH` etc.
- Action classifiers `is_risk_add / is_risk_reduce / is_hedge_action` (lines 118–142).
- V2 callable parity: `evaluate_margin_state` accepts `verdict_action ∈ {"allow","block_account","block_symbol","deleverage"}`. `allow` → `allow_margin_within_caps`. `block_account` → `deny_margin_account_breach`. `block_symbol` → `deny_margin_symbol_breach`. `deleverage` → `close_only_margin_deleverage_required`.

## 8. risk/phase_controller.py (SHA256 ecd566ca7537551a9e6e267da4880a41764d346a1d43137d4088003951211ee1, 397 lines)

- `check_ramp_limits(phase, portfolio, signal)` (line 297). Hard checks: equity NaN/≤0, `mu_after > max_mu`, `free_margin_ratio < min_fmr`, new symbol when `open_positions ≥ max_positions`, per-symbol margin > per-pos cap. Returns `{"ok": bool, "reason": "RAMP_LIMIT"|"OK", "meta": {...}}`.
- Reduce / non-OPEN action category short-circuits to `ok=True` (lines 312–320).
- V2 callable parity: `evaluate_phase_gate` accepts `ramp_limit_breach ∈ {"", "max_mu","min_free_margin_ratio","max_positions","per_symbol_margin","equity_missing_or_nan"}`. Empty → allow. Non-empty → deny with matching reason. Dynamic max-positions adjusters are a remaining gap.

## 9. risk/microstructure_toxicity.py (SHA256 5103e3078e15734eaca310e9ae58dd8e89725ebf4317a98313f078c8bd74beef, 316 lines)

- Defaults (lines 41–43): `HIGH_THRESHOLD=0.65`, `EXTREME_THRESHOLD=0.85`. Component weights sum to 1.0 (lines 46–52).
- `ToxicityResult.is_extreme = score ≥ EXTREME_THRESHOLD` (line 83).
- Legacy use: `shared_risk_gate` blocks risk-adds when `score ≥ extreme_threshold`.
- V2 callable parity: `evaluate_toxicity_block` accepts `score`, `extreme_threshold`, `is_risk_add`. Risk-add with `score ≥ extreme_threshold` → `deny_toxicity_extreme_block`. Anything else → `allow_toxicity_within_threshold`. Score recomputation from 7 components is a remaining gap and lives in the per-snapshot caller.

## Companion: risk/adaptive_gate.py (SHA256 a5057ea4ad4542881a6ebf14b9d789cbeed7873fc763c9d74d06c7c781674bce, 775 lines)

- Real-time market-condition gate (lines 1–22). Returns `GateVerdict(allow, code, reason, sizing_mult, delay_seconds, meta)` (lines 35–43).
- Not exposed as one of the nine task-required callables. Documented here so the closure is complete. Adaptive-gate parity is a candidate follow-on task (`claude_port_v2_adaptive_gate_callable_from_legacy_action_map`).

## Fail-closed invariants enforced in V2

1. Every evaluator carries `live_blocked=True` and rejects construction with `live_blocked=False`.
2. Every evaluator has a `deny_<gate>_evidence_missing` path triggered when the caller's snapshot is incomplete (e.g., `evidence_present=False`).
3. Every evaluator validates `now_ms_clock()` result is `int` and `>= 0`; otherwise raises `RiskLegacyGatesServiceError`.
4. Every evaluator emits `legacy_source_path` + `legacy_source_sha256` so audit trails can pin the legacy baseline.
