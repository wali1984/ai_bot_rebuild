# Codex Review: codex_review_autoseed_cuda_live_gate_single_pass_stale_prediction_signal_payloads_r1

GO/NO-GO: `MIGRATED_CODEX_PASS`

## Command

```text
/home/wali/.local/bin/codex exec review ...
```

## Raw Output (tail)

```text
def test_coinank_only_symbols_are_excluded_from_runtime_training_and_paper(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        "v2_coinank",
        {
            "discovered_symbols": ["BTCUSDT", "COINANK_ONLY_USDT"],
            "paper_symbols": ["BTCUSDT", "COINANK_ONLY_USDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
        },
    )

    payload = build_payload(tmp_path)

    assert payload["discovered_symbols"] == ["BTCUSDT"]
    assert payload["paper_symbols"] == ["BTCUSDT"]
    assert payload["paper_shadow_live_symbols"] == ["BTCUSDT"]
    assert payload["live_symbols"] == []
    assert payload["execution_live_symbols"] == []
    assert payload["rejected_paper_symbols"] == []
    assert payload["coinank_symbols_directly_tradable"] is False
    assert payload["coinank_symbols_tradability"] == "market_intelligence_only_until_binance_usdm_confirmed"

exec
/bin/bash -lc "sed -n '260,520p' v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
exec
/bin/bash -lc "grep -R \"missing_symbol_selection_evidence\\|requested_scope_matches_or_contains_all_discovered_symbols\" -n v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py v2/backend/tests/unit/cli | sed -n '1,200p'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
grep: v2/backend/tests/unit/cli/__pycache__/test_symbol_universe_public_payload.cpython-312.pyc: binary file matches
grep: v2/backend/tests/unit/cli/__pycache__/test_symbol_universe_public_payload.cpython-312-pytest-8.3.3.pyc: binary file matches
v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py:81:    assert "requested_scope_matches_or_contains_all_discovered_symbols" not in payload["symbol_universe_payload_evidence_gaps"]
v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py:81:    assert "requested_scope_matches_or_contains_all_discovered_symbols" not in payload["symbol_universe_payload_evidence_gaps"]

exec
/bin/bash -lc "grep -R \"cooldown_clear\\|flip_churn_clear\\|microstructure_toxicity_clear\" -n v2/backend/app | sed -n '1,200p'" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
grep: v2/backend/app/composition/paper_edge_scoring/__pycache__/runtime.cpython-312.pyc: binary file matches
grep: v2/backend/app/cli/__pycache__/paper_online_runtime.cpython-312.pyc: binary file matches
grep: v2/backend/app/cli/__pycache__/v2_paper_execution_worker.cpython-312.pyc: binary file matches
v2/backend/app/composition/paper_edge_scoring/runtime.py:144:    if not _bool_with_default(record.get("cooldown_clear")):
v2/backend/app/composition/paper_edge_scoring/runtime.py:147:        _first(record, "flip_churn_clear", "churn_clear", "flip_clear"),
v2/backend/app/composition/paper_edge_scoring/runtime.py:157:        _first(record, "microstructure_toxicity_clear", "toxicity_clear")
v2/backend/app/composition/paper_edge_scoring/runtime.py:191:        "microstructure_toxicity_clear": microstructure_clear,
v2/backend/app/cli/paper_online_runtime.py:569:    microstructure_toxicity_clear = (
v2/backend/app/cli/paper_online_runtime.py:622:            "cooldown_clear": "same_symbol_same_direction_cooldown"
v2/backend/app/cli/paper_online_runtime.py:624:            "flip_churn_clear": "flip_churn_cooldown" not in set(gate.get("blockers") or []),
v2/backend/app/cli/paper_online_runtime.py:627:            "microstructure_toxicity_clear": microstructure_toxicity_clear,
v2/backend/app/cli/paper_online_runtime.py:650:        "microstructure_toxicity_clear": microstructure_toxicity_clear,
v2/backend/app/cli/paper_online_runtime.py:1047:        "microstructure_toxicity_clear": protective_gate.get("microstructure_toxicity_clear"),
v2/backend/app/cli/v2_paper_execution_worker.py:458:        "cooldown_clear",
v2/backend/app/cli/v2_paper_execution_worker.py:459:        "flip_churn_clear",
v2/backend/app/cli/v2_paper_execution_worker.py:871:        "cooldown_clear",
v2/backend/app/cli/v2_paper_execution_worker.py:872:        "flip_churn_clear",
v2/backend/app/cli/v2_paper_execution_worker.py:875:        "microstructure_toxicity_clear",

exec
/bin/bash -lc "sed -n '600,690p' v2/backend/app/cli/paper_online_runtime.py" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "funding_bps": 0.0,
        },
        recent_events=recent_events,
        approval_token_present=False,
    )
    paper_edge_gate = score_paper_edge(
        {
            "symbol": intent.get("symbol") or signal.get("symbol"),
            "risk_action": "allow",
            "trainer_source": prediction.get("trainer_source") or raw_output.get("trainer_source"),
            "feature_freshness_state": feature_snapshot.get("freshness_state"),
            "confidence_calibrated": signal.get("confidence_calibrated")
            or signal.get("confidence")
            or prediction.get("confidence_calibrated"),
            "expected_move_bps": coverage.get("expected_move_bps_for_fill_gate"),
            "expected_move_after_cost_bps": coverage.get("expected_move_after_cost_bps_for_fill_gate"),
            "fee_bps": 4.0,
            "spread_bps": 0.0,
            "slippage_bps": 2.0,
            "funding_risk_bps": 0.0,
            "cooldown_clear": "same_symbol_same_direction_cooldown"
            not in set(gate.get("blockers") or []),
            "flip_churn_clear": "flip_churn_cooldown" not in set(gate.get("blockers") or []),
            "reduce_only_clear": True,
            "intelligent_close_guard_clear": True,
            "microstructure_toxicity_clear": microstructure_toxicity_clear,
        },
        paper_symbols=[str(intent.get("symbol") or signal.get("symbol") or "").upper()],
        live_symbols=[],
        live_gate=LIVE_GATE_STATUS,
    )
    risk["canary_profile_tightening"] = gate
    risk["expected_move_coverage"] = coverage
    risk["expected_move_source"] = coverage.get("expected_move_source")
    risk["expected_move_coverage_status"] = coverage.get("expected_move_coverage_status")
    risk["expected_move_bps"] = coverage.get("expected_move_bps_for_fill_gate")
    risk["expected_move_after_cost_bps"] = coverage.get("expected_move_after_cost_bps_for_fill_gate")
    risk["paper_edge_gate"] = paper_edge_gate
    risk["paper_edge_gate_classification"] = paper_edge_gate.get("classification")
    risk["paper_edge_gate_blockers"] = list(paper_edge_gate.get("blockers") or [])
    risk["paper_protective_behavior_gate"] = {
        "minimum_hold_seconds": PAPER_POSITION_MIN_HOLD_SECONDS,
        "dynamic_take_profit_model": "expected_move_after_cost_bps_floor",
        "dynamic_stop_model": "paper_static_stop_floor_until_legacy_dynamic_stop_parity",
        "reduce_only_protection_clear": True,
        "intelligent_close_guard_clear": True,
        "microstructure_toxicity_score_bps": microstructure_toxicity_score_bps,
        "microstructure_toxicity_max_bps": PAPER_MICROSTRUCTURE_TOXICITY_MAX_BPS,
        "microstructure_toxicity_clear": microstructure_toxicity_clear,
        "paper_only": True,
    }
    paper_outcome_model, paper_outcome_model_blockers = _paper_outcome_model_contract()
    risk["paper_outcome_model"] = paper_outcome_model
    expected_move_model_review, expected_move_model_review_blockers = _expected_move_model_review_contract()
    risk["expected_move_model_review"] = expected_move_model_review
    if (
        gate.get("blockers")
        or paper_edge_gate.get("blockers")
        or paper_outcome_model_blockers
        or expected_move_model_review_blockers
    ):
        risk["risk_action"] = "deny"
        risk["risk_result"] = "BLOCKED"
        risk["risk_reason_code"] = (
            "deny_paper_outcome_model_missing"
            if paper_outcome_model_blockers
            and not gate.get("blockers")
            and not paper_edge_gate.get("blockers")
            and not expected_move_model_review_blockers
            else "deny_expected_move_model_review"
            if expected_move_model_review_blockers
            and not gate.get("blockers")
            and not paper_edge_gate.get("blockers")
            else "deny_canary_profile_tightening"
        )
        risk["canary_profile_tightening_blockers"] = [
            *list(gate.get("blockers") or []),
            *paper_outcome_model_blockers,
            *expected_move_model_review_blockers,
        ]
        risk["paper_outcome_model_blockers"] = paper_outcome_model_blockers
        risk["expected_move_model_review_blockers"] = expected_move_model_review_blockers
        required = list(risk.get("required_blocks_checked") or [])
        if "canary_profile_tightening" not in required:
            required.append("canary_profile_tightening")
        if "paper_edge_scoring" not in required:
            required.append("paper_edge_scoring")
        if "paper_outcome_model" not in required:
            required.append("paper_outcome_model")

exec
/bin/bash -lc "python - <<'PY'
from pathlib import Path
import json, shutil, tempfile
from v2.backend.app.cli.symbol_universe_public_payload import build_payload

tmp = Path('/tmp/su_test_case')
if tmp.exists(): shutil.rmtree(tmp)
(tmp/'v2/frontend/public/operator_runtime/v2_a/latest').mkdir(parents=True, exist_ok=True)
# write one payload with requested single symbol but no binance confirmed
payload={
 'discovered_symbols':['BTCUSDT','ETHUSDT'],
 'training_symbols':['BTCUSDT'],
 'paper_symbols':['ETHUSDT'],
}
(tmp/'v2/frontend/public/operator_runtime/v2_a/latest/test_status.json').write_text(json.dumps(payload))
print(build_payload(tmp, generated_at='2026-06-05T00:00:00Z')['training_symbols'])
print(build_payload(tmp, generated_at='2026-06-05T00:00:00Z')['paper_symbols'])
print(build_payload(tmp, generated_at='2026-06-05T00:00:00Z')['symbol_universe_payload_evidence_gaps'])
PY" in /home/wali/Desktop/AI BOT REBUILD
 succeeded in 0ms:
['BTCUSDT', 'ETHUSDT']
['BTCUSDT', 'ETHUSDT']
['missing_binance_usdm_confirmed_symbols']

codex
The patch introduces two clear safety regressions: fail-open handling of missing protective edge flags and synthesized directional market-flow values in the global CoinAnk aggregate. These weaken explicit readiness/fail-safe guarantees and can introduce non-authentic signal-like behavior. There is also a symbol-scope widening issue that can erode explicit selection boundaries.

Full review comments:

- [P1] Preserve fail-closed behavior for missing edge-protection flags — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/v2_paper_execution_worker.py:867-878
  When `evaluate_paper_edge_gate` sees missing `cooldown_clear`, `flip_churn_clear`, `reduce_only_clear`, `intelligent_close_guard_clear`, or `microstructure_toxicity_clear`, it replaces them with `True` before calling `score_paper_edge`. `score_paper_edge` defaults these protective bits to denied when absent, so this overwrite turns an unknown/no-evidence state into an explicit pass and can allow paper-edge approval when upstream payloads are incomplete (for example when stale or truncated records omit protective gate outputs). For stale-input safety this should fail closed unless those fields are explicitly present and clean.

- [P1] Avoid synthesizing directional flow from undirected volume — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/coinank_bridge/service.py:541-556
  If both buy/sell directional fields are missing, the CoinAnk aggregate now splits `quote_volume` evenly into buy/sell totals. That inserts fabricated directional components (`buy_total` and `sell_total`) even though true direction is unavailable, and downstream features like `market_sentiment` and aggregate indicators then consume this as if it were observed signal data. This is exactly a synthetic signal-path behavior and can hide data-loss conditions while still producing plausible-feeling outputs.

- [P2] Do not always expand requested symbol scope to all discovered symbols — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/symbol_universe_public_payload.py:171-180
  `_selected_subset` unconditionally merges all discovered symbols into `requested` whenever `default_to_discovered` is true, and `build_payload()` sets that flag for both training and paper selections. This means explicit requested symbol lists are widened to the full discovered set even when a narrower scope was supplied, which can silently include additional runtime symbols and reduce the clarity of scope-based safeguards. If explicit scope is intended, this should only widen when no explicit request exists.
The patch introduces two clear safety regressions: fail-open handling of missing protective edge flags and synthesized directional market-flow values in the global CoinAnk aggregate. These weaken explicit readiness/fail-safe guarantees and can introduce non-authentic signal-like behavior. There is also a symbol-scope widening issue that can erode explicit selection boundaries.

Full review comments:

- [P1] Preserve fail-closed behavior for missing edge-protection flags — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/v2_paper_execution_worker.py:867-878
  When `evaluate_paper_edge_gate` sees missing `cooldown_clear`, `flip_churn_clear`, `reduce_only_clear`, `intelligent_close_guard_clear`, or `microstructure_toxicity_clear`, it replaces them with `True` before calling `score_paper_edge`. `score_paper_edge` defaults these protective bits to denied when absent, so this overwrite turns an unknown/no-evidence state into an explicit pass and can allow paper-edge approval when upstream payloads are incomplete (for example when stale or truncated records omit protective gate outputs). For stale-input safety this should fail closed unless those fields are explicitly present and clean.

- [P1] Avoid synthesizing directional flow from undirected volume — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/services/coinank_bridge/service.py:541-556
  If both buy/sell directional fields are missing, the CoinAnk aggregate now splits `quote_volume` evenly into buy/sell totals. That inserts fabricated directional components (`buy_total` and `sell_total`) even though true direction is unavailable, and downstream features like `market_sentiment` and aggregate indicators then consume this as if it were observed signal data. This is exactly a synthetic signal-path behavior and can hide data-loss conditions while still producing plausible-feeling outputs.

- [P2] Do not always expand requested symbol scope to all discovered symbols — /home/wali/Desktop/AI BOT REBUILD/v2/backend/app/cli/symbol_universe_public_payload.py:171-180
  `_selected_subset` unconditionally merges all discovered symbols into `requested` whenever `default_to_discovered` is true, and `build_payload()` sets that flag for both training and paper selections. This means explicit requested symbol lists are widened to the full discovered set even when a narrower scope was supplied, which can silently include additional runtime symbols and reduce the clarity of scope-based safeguards. If explicit scope is intended, this should only widen when no explicit request exists.
```
