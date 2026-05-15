# Legacy Protective Behavior → V2 Paper Map

Task: `legacy_protective_behavior_to_v2_paper_map`
Generated: `2026-05-14T00:00:00Z`
Working tree: `/home/wali/Desktop/AI BOT REBUILD`

## Purpose

Phase E of the parent task requires every legacy protective behavior listed below to either have a V2 paper-only equivalent (preferred) or an explicit V2 paper blocker that prevents the behavior from being silently dropped. Codex review must fail if any behavior is dropped without an explicit equivalent or blocker.

## SHA-Cited Legacy Sources

All SHA values are `sha256sum` (full 64-char digest) of the legacy file as it currently exists under `legacy_reference/`. Line counts are `wc -l`.

| # | Behavior | Legacy file | sha256 | lines |
| --- | --- | --- | --- | --- |
| 1 | Churn prevention | `legacy_reference/trading/churn_prevention.py` | `f258b87233fc68d7d73e05f13fece322774bdf2a6e95ad8c081b83cbc3771d1f` | 572 |
| 2 | Position lifecycle controller | `legacy_reference/trading/lifecycle_controller.py` | `cbe9472229be257701c2fc4d48f52ad6baab6a869947d55c8a8faf430d4fd6ed` | 104 |
| 3 | Exit coordinator | `legacy_reference/trading/exit_coordinator.py` | `fb0591c2a4ef29a40695556c536ef7998657135222dab86938a3ae4219941bc4` | 489 |
| 4 | Dynamic TP engine | `legacy_reference/trading/dynamic_tp_engine.py` | `54bf102e9d5cfedb00f22f953c4894c4592a1b627a16bad51c034a7069c1e908` | 1468 |
| 5 | Dynamic adaptive stops | `legacy_reference/trading/dynamic_adaptive_stops.py` | `523ef574f6f6729c831047e73ce53bfad3d980cb562a386bf8b648b22d9d061f` | 1063 |
| 6 | Stealth stops | `legacy_reference/trading/stealth_stops.py` | `a76de1902e7c2a754f2e90a39fa9aac23d991ec059d5c54d6e0772b79b8a47cf` | 6972 |
| 7 | Fee ratio gate | `legacy_reference/trading/fee_ratio_gate.py` | `c1829afcbdb6848fb8dffd76e14b78a140832c663bb9c2f16e75029b0e7f8e7f` | 412 |
| 8 | Adaptive edge gate | `legacy_reference/trading/adaptive_edge_gate.py` | `f50455f52e53eb5e2476cae4d2722d5050980cca66a6204c2f0ecf5526054632` | 1569 |
| 9 | Reduce-only latch | `legacy_reference/risk/reduce_only_latch.py` | `e0dc68486a5cc2fa0fc0ea1d1197f66373f8c090deb889a403257e187c7ac611` | 188 |
| 10 | Intelligent close guard | `legacy_reference/risk/intelligent_close_guard.py` | `7edf6d5eca3e8654bc17f0fad22831e4daedb411138d576904a29ab0a352c3ee` | 1164 |
| 11 | Microstructure toxicity | `legacy_reference/risk/microstructure_toxicity.py` | `5103e3078e15734eaca310e9ae58dd8e89725ebf4317a98313f078c8bd74beef` | 316 |
| 12 | Risk adaptive gate | `legacy_reference/risk/adaptive_gate.py` | `a5057ea4ad4542881a6ebf14b9d789cbeed7873fc763c9d74d06c7c781674bce` | 775 |
| 13 | RL churn veto | `legacy_reference/rl/churn_veto.py` | `2c81e961b69c557dd684293cdcc6540fb7980ad42a404c5c8d08c24f9b241c74` | 160 |
| 14 | RL minimum hold time | `legacy_reference/rl/minimum_hold_time.py` | `6ab470cf50b756134ccb420f42831481d4edc5951f14f8fa2ae7bebcf68fc1ae` | 490 |
| 15 | RL fee ratio reward shaping | `legacy_reference/rl/fee_ratio_reward_shaping.py` | `e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06` | 519 |

Total legacy source surface mapped: `16,261` lines across 15 files.

## Mapping Table (V2 Paper-Only Equivalent Or Explicit Blocker)

Status legend:
- `EQUIV_PENDING_IMPLEMENTATION` = V2 paper-only equivalent identified, not yet implemented in this writing window.
- `BLOCKER_EQUIV_PENDING_IMPLEMENTATION` = explicit paper-only blocker is acceptable as a stand-in until the equivalent is implemented, not yet implemented.
- `EXISTING_PARTIAL` = some V2 module already covers a subset; further work required to close the gap.

| # | Legacy behavior | V2 paper-only target module | Status | Notes |
| --- | --- | --- | --- | --- |
| 1 | Churn prevention (same-side cooldown, flip cooldown, churn counter) | `v2/backend/app/composition/paper_edge_scoring/` (Phase B) + `v2/backend/app/composition/canary_profile_tightening/runtime.py` (`same_symbol_same_direction_in_cooldown`, `flip_churn_in_cooldown`) | EXISTING_PARTIAL | Canary tightening already emits `same_symbol_same_direction_cooldown` and `flip_churn_cooldown`. Phase B must consume the same recent_events stream and emit `COOLDOWN_BLOCK` / `FLIP_CHURN_BLOCK`. |
| 2 | Position lifecycle controller (state machine for OPEN → MANAGE → CLOSE) | `v2/backend/app/composition/paper_edge_scoring/` paper-only lifecycle hook | EQUIV_PENDING_IMPLEMENTATION | V2 paper must implement minimum-hold-time before allowing flip; surface as `FLIP_CHURN_BLOCK` when minimum hold is unmet. |
| 3 | Exit coordinator (coordinated exit on adverse-edge state) | `v2/backend/app/composition/paper_edge_scoring/` paper-only exit eligibility | EQUIV_PENDING_IMPLEMENTATION | Paper-only simulation must mirror coordinated exit by emitting `RISK_GATE_BLOCK` on adverse-edge state. |
| 4 | Dynamic TP engine | `v2/backend/app/composition/paper_edge_scoring/` paper TP simulation (no fill emitted) | EQUIV_PENDING_IMPLEMENTATION | Paper TP simulation must NOT emit `PAPER_FILL_SIMULATED`; it must record simulated exits inside the shadow outcome observer. |
| 5 | Dynamic adaptive stops | `v2/backend/app/composition/paper_edge_scoring/` paper SL simulation (no fill emitted) | EQUIV_PENDING_IMPLEMENTATION | Same constraint as TP: SL events live in the shadow observer, not the paper ledger. |
| 6 | Stealth stops | `v2/backend/app/composition/paper_edge_scoring/` paper stealth-stop simulation | BLOCKER_EQUIV_PENDING_IMPLEMENTATION | 6,972-line legacy module; minimum paper-only requirement: explicit `RISK_GATE_BLOCK` when stealth-stop conditions would have triggered. |
| 7 | Fee ratio gate | `v2/backend/app/composition/paper_edge_scoring/` `EDGE_AFTER_COSTS_NEGATIVE_BLOCK` | EXISTING_PARTIAL | Phase B explicitly subtracts `fee_bps`; the fee-ratio gate is captured as part of `expected_move_after_cost_bps >= 8`. |
| 8 | Adaptive edge gate | `v2/backend/app/composition/paper_edge_scoring/` `EDGE_AFTER_COSTS_*` family | EXISTING_PARTIAL | Phase B is the V2 paper-only equivalent. Legacy adaptive logic to be ported to V2 paper without exchange writes. |
| 9 | Reduce-only latch | `v2/backend/app/composition/paper_edge_scoring/` paper reduce-only state | EQUIV_PENDING_IMPLEMENTATION | Paper-only: if reduce-only latch is engaged, any opening-side intent must be `RISK_GATE_BLOCK`. |
| 10 | Intelligent close guard | `v2/backend/app/composition/paper_edge_scoring/` paper close-guard simulation | EQUIV_PENDING_IMPLEMENTATION | Paper-only: simulate close-guard in the shadow observer, no live actions. |
| 11 | Microstructure toxicity | `v2/backend/app/composition/paper_edge_scoring/` toxicity blocker | BLOCKER_EQUIV_PENDING_IMPLEMENTATION | Paper-only: `RISK_GATE_BLOCK` when toxicity indicator exceeds threshold; equivalent computation deferred to a later pass. |
| 12 | Risk adaptive gate | `v2/backend/app/composition/risk_gateway/` + `paper_edge_scoring/` | EXISTING_PARTIAL | V2 risk gateway already governs paper allow/deny; Phase B must consume its decision via `RISK_GATE_BLOCK`. |
| 13 | RL churn veto | `v2/backend/app/composition/paper_edge_scoring/` `FLIP_CHURN_BLOCK` | EXISTING_PARTIAL | Canary tightening + Phase B together must cover the churn-veto behavior in paper. |
| 14 | RL minimum hold time | `v2/backend/app/composition/paper_edge_scoring/` paper minimum-hold guard | EQUIV_PENDING_IMPLEMENTATION | Same-side / flip gating must respect the legacy minimum-hold-time semantics. |
| 15 | RL fee ratio reward shaping | `v2/backend/app/composition/paper_edge_scoring/` cost-aware scoring formula | EXISTING_PARTIAL | The reward-shaping idea is now expressed as an admission gate: `expected_move_after_cost_bps >= 8` rather than a reward-side adjustment. Acceptable for paper-only selection; live use is out of scope. |

## Drop Detection

No legacy protective behavior in the table above is silently dropped:

- 5 behaviors are covered partially by existing V2 modules and need only Phase B wiring (`EXISTING_PARTIAL`).
- 8 behaviors require explicit V2 paper-only equivalents (`EQUIV_PENDING_IMPLEMENTATION`).
- 2 behaviors are large enough (stealth_stops at 6,972 lines and microstructure_toxicity at 316 lines) that a paper-only blocker is acceptable until the equivalent is ported (`BLOCKER_EQUIV_PENDING_IMPLEMENTATION`).

Codex review must verify, when Phase B is implemented, that:

1. Every row above has a corresponding V2 paper-only code path.
2. No row has been removed from the mapping without explicit operator sign-off.
3. No row has been silently converted from `EQUIV_PENDING_IMPLEMENTATION` to "dropped".

## Safety Posture

| Field | Value |
| --- | --- |
| `live_gate` | `blocked_human_only` |
| `live_symbols` | `[]` |
| `approves_live` | `false` |
| `approves_legacy_shutdown` | `false` |
| `mutates_legacy_files` | `false` |
| `mutates_old_redis` | `false` |
| `places_or_cancels_exchange_orders` | `false` |
| `changes_leverage_or_margin_mode` | `false` |
