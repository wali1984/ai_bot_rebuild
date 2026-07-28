"""Integration tests for the V2 post-hoc replay outcome miner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.edge_proof import replay_miner
from v2.backend.app.services.edge_proof.replay_miner import (
    _compute_window,
    _find_window_slice,
    _label_from_outcome,
    fill_outcomes,
)
from v2.backend.app.services.edge_proof.replay_schema import (
    OUTCOME_WINDOWS_SECONDS,
    ReplayLabel,
)


def _baseline_bundle(*, decision: str, paper_fill_allowed: bool, side: str = "long",
                     block_reasons: list[str] | None = None,
                     entry_price: float = 100.0) -> dict[str, Any]:
    return {
        "schema_version": "v2_native_edge_proof_replay_bundle_v1",
        "feature_snapshot_id": "BTCUSDT:1m:test",
        "prediction_id": "test-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "generated_at": "2026-05-23T04:00:00Z",
        "anchor_ts": 1_779_500_000.0,
        "features_hash": None,
        "market_snapshot": {
            "fee_bps": 5.0,
            "slippage_estimate_bps": 2.0,
        },
        "altdata_snapshot": None,
        "risk_decision": None,
        "trainer_output": {"selected_action": side},
        "paper_gate_decision": {
            "paper_fill_allowed": paper_fill_allowed,
            "paper_fill_gate_block_reasons": block_reasons or [],
        },
        "orchestrator_decision": None,
        "paper_intent": {"intent_id": "test-1", "symbol": "BTCUSDT", "side": side, "decision": decision},
        "legacy_reference_action": None,
        "entry_price": entry_price,
        "side": side,
        "future_outcomes": {
            wid: {
                "window_id": wid,
                "window_seconds": secs,
                "return_bps": None,
                "after_cost_return_bps": None,
                "drawdown_bps": None,
                "stop_hit": False,
                "samples": 0,
                "source": "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE",
            }
            for wid, secs in OUTCOME_WINDOWS_SECONDS
        },
        "outcome_after_cost": None,
        "label": ReplayLabel.INSUFFICIENT_EVIDENCE.value,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def _timeline(anchor: float, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(anchor + dt, price) for dt, price in points]


# ── price timeline slicing ──────────────────────────────────────────────

def test_find_window_slice_returns_none_when_no_endpoint() -> None:
    anchor = 1_000.0
    # Timeline goes up to anchor + 4s; window is 60s -> no endpoint.
    tl = _timeline(anchor, [(0, 100.0), (1, 100.5), (2, 101.0), (3, 100.8), (4, 101.1)])
    assert _find_window_slice(tl, anchor, 60) is None


def test_find_window_slice_returns_slice_when_endpoint_present() -> None:
    anchor = 1_000.0
    tl = _timeline(anchor, [(0, 100.0), (30, 101.0), (60, 102.0), (61, 102.5)])
    sl = _find_window_slice(tl, anchor, 60)
    assert sl is not None
    # Must include the endpoint
    assert any(ts >= anchor + 60 for ts, _ in sl)


# ── outcome math ────────────────────────────────────────────────────────

def test_compute_window_long_positive_after_cost() -> None:
    anchor = 1_000.0
    tl = _timeline(anchor, [(0, 100.0), (60, 101.5)])  # +150 bps raw
    w = _compute_window(
        timeline=tl, anchor_ts=anchor, entry_price=100.0, side="long",
        window_id="1m", window_seconds=60, fee_bps=5.0, slippage_bps=2.0,
    )
    assert w["return_bps"] == pytest.approx(150.0, rel=1e-6)
    assert w["after_cost_return_bps"] == pytest.approx(143.0, rel=1e-6)
    assert w["fee_drag_bps"] == 5.0
    assert w["slippage_estimate_bps"] == 2.0
    assert w["samples"] >= 2


def test_compute_window_short_inverts_sign() -> None:
    anchor = 1_000.0
    tl = _timeline(anchor, [(0, 100.0), (60, 101.5)])  # raw +150, short -> signed -150
    w = _compute_window(
        timeline=tl, anchor_ts=anchor, entry_price=100.0, side="short",
        window_id="1m", window_seconds=60, fee_bps=5.0, slippage_bps=2.0,
    )
    # raw_return_bps is unsigned in the output; after_cost is signed by side.
    assert w["return_bps"] == pytest.approx(150.0, rel=1e-6)
    assert w["after_cost_return_bps"] == pytest.approx(-157.0, rel=1e-6)


def test_compute_window_insufficient_when_no_anchor_or_entry() -> None:
    w1 = _compute_window(
        timeline=[], anchor_ts=None, entry_price=100.0, side="long",
        window_id="1m", window_seconds=60, fee_bps=5.0, slippage_bps=2.0,
    )
    assert w1["after_cost_return_bps"] is None
    assert w1["source"].startswith("INSUFFICIENT_EVIDENCE")
    w2 = _compute_window(
        timeline=_timeline(1000.0, [(0, 100.0)]), anchor_ts=1000.0, entry_price=None,
        side="long", window_id="1m", window_seconds=60, fee_bps=5.0, slippage_bps=2.0,
    )
    assert w2["after_cost_return_bps"] is None


def test_compute_window_insufficient_when_window_not_yet_elapsed() -> None:
    anchor = 1_000.0
    # No point at or beyond anchor + 60.
    tl = _timeline(anchor, [(0, 100.0), (30, 100.5)])
    w = _compute_window(
        timeline=tl, anchor_ts=anchor, entry_price=100.0, side="long",
        window_id="1m", window_seconds=60, fee_bps=5.0, slippage_bps=2.0,
    )
    assert w["after_cost_return_bps"] is None
    assert w["source"] == "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE"


def test_compute_window_max_favorable_and_adverse() -> None:
    anchor = 1_000.0
    tl = _timeline(anchor, [(0, 100.0), (10, 102.0), (30, 99.0), (60, 100.5)])
    w = _compute_window(
        timeline=tl, anchor_ts=anchor, entry_price=100.0, side="long",
        window_id="1m", window_seconds=60, fee_bps=0.0, slippage_bps=0.0,
    )
    # Path bps: 0, +200, -100, +50 -> mfe 200, mae -100.
    assert w["max_favorable_bps"] == pytest.approx(200.0, rel=1e-6)
    assert w["max_adverse_bps"] == pytest.approx(-100.0, rel=1e-6)
    assert w["drawdown_bps"] == pytest.approx(100.0, rel=1e-6)


# ── label assignment ────────────────────────────────────────────────────

def test_label_correct_trade_when_traded_and_profitable() -> None:
    b = _baseline_bundle(decision="ACCEPTED_PAPER_FILL", paper_fill_allowed=True)
    b["future_outcomes"]["5m"] = {"after_cost_return_bps": 25.0, "samples": 5}
    assert _label_from_outcome(bundle=b) == ReplayLabel.CORRECT_TRADE.value


def test_label_false_positive_when_traded_and_unprofitable() -> None:
    b = _baseline_bundle(decision="ACCEPTED_PAPER_FILL", paper_fill_allowed=True)
    b["future_outcomes"]["5m"] = {"after_cost_return_bps": -10.0, "samples": 5}
    assert _label_from_outcome(bundle=b) == ReplayLabel.FALSE_POSITIVE.value


def test_label_false_block_when_blocked_but_outcome_would_have_been_profitable() -> None:
    b = _baseline_bundle(
        decision="HELD_BY_PAPER_FILL_GATE", paper_fill_allowed=False,
        block_reasons=["FEE_GATE_BLOCKED"],
    )
    b["future_outcomes"]["5m"] = {"after_cost_return_bps": 18.0, "samples": 5}
    assert _label_from_outcome(bundle=b) == ReplayLabel.FALSE_BLOCK.value


def test_label_correct_no_trade_when_blocked_and_outcome_was_negative() -> None:
    b = _baseline_bundle(
        decision="HELD_BY_PAPER_FILL_GATE", paper_fill_allowed=False,
        block_reasons=["FEE_GATE_BLOCKED"],
    )
    b["future_outcomes"]["5m"] = {"after_cost_return_bps": -20.0, "samples": 5}
    assert _label_from_outcome(bundle=b) == ReplayLabel.CORRECT_NO_TRADE.value


def test_label_false_negative_when_model_held_but_outcome_was_profitable() -> None:
    b = _baseline_bundle(decision="PAPER_INTENT_OBSERVED", paper_fill_allowed=False)
    b["future_outcomes"]["5m"] = {"after_cost_return_bps": 12.0, "samples": 5}
    assert _label_from_outcome(bundle=b) == ReplayLabel.FALSE_NEGATIVE.value


def test_label_insufficient_when_primary_window_missing() -> None:
    b = _baseline_bundle(decision="ACCEPTED_PAPER_FILL", paper_fill_allowed=True)
    # 5m window has no after_cost
    b["future_outcomes"]["5m"] = {"after_cost_return_bps": None, "samples": 0}
    assert _label_from_outcome(bundle=b) == ReplayLabel.INSUFFICIENT_EVIDENCE.value


# ── fill_outcomes integration ───────────────────────────────────────────

def test_fill_outcomes_keeps_already_filled_windows_and_emits_insufficient_when_no_timeline() -> None:
    b = _baseline_bundle(decision="ACCEPTED_PAPER_FILL", paper_fill_allowed=True)
    # 1m already filled
    b["future_outcomes"]["1m"] = {
        "window_id": "1m", "window_seconds": 60,
        "return_bps": 50.0, "after_cost_return_bps": 43.0,
        "drawdown_bps": 0.0, "samples": 2, "stop_hit": False,
        "source": "V2_MINER_PRICE_TIMELINE",
    }
    out = fill_outcomes(b, timeline_by_symbol={"BTCUSDT": []})
    # 1m stays filled
    assert out["future_outcomes"]["1m"]["after_cost_return_bps"] == 43.0
    # 5m / 15m / 1h remain INSUFFICIENT_EVIDENCE (no timeline)
    for wid in ("5m", "15m", "1h"):
        row = out["future_outcomes"][wid]
        assert row.get("after_cost_return_bps") is None
        assert (row.get("source") or "").startswith("INSUFFICIENT_EVIDENCE")
    # Primary label: INSUFFICIENT because 5m is still missing
    assert out["label"] == ReplayLabel.INSUFFICIENT_EVIDENCE.value


def test_fill_outcomes_assigns_correct_trade_label_from_realized_outcome() -> None:
    anchor = 1_779_500_000.0
    timeline = [
        (anchor, 100.0),
        (anchor + 30, 100.5),
        (anchor + 60, 100.7),
        (anchor + 5 * 60, 101.5),  # 5m endpoint: long +150 bps raw, after_cost = 150 - 7 = 143
        (anchor + 15 * 60, 102.0),
        (anchor + 60 * 60, 103.0),
    ]
    b = _baseline_bundle(decision="ACCEPTED_PAPER_FILL", paper_fill_allowed=True)
    b["anchor_ts"] = anchor
    out = fill_outcomes(b, timeline_by_symbol={"BTCUSDT": timeline})
    assert out["future_outcomes"]["5m"]["after_cost_return_bps"] == pytest.approx(143.0, abs=0.1)
    assert out["label"] == ReplayLabel.CORRECT_TRADE.value
    assert out["outcome_after_cost"] == pytest.approx(143.0, abs=0.1)


def test_fill_outcomes_never_fabricates_outcomes_without_timeline_data(tmp_path: Path) -> None:
    b = _baseline_bundle(decision="ACCEPTED_PAPER_FILL", paper_fill_allowed=True)
    out = fill_outcomes(b, timeline_by_symbol={})
    for wid in ("1m", "5m", "15m", "1h"):
        assert out["future_outcomes"][wid]["after_cost_return_bps"] is None
    assert out["label"] == ReplayLabel.INSUFFICIENT_EVIDENCE.value


# ── safety pins ─────────────────────────────────────────────────────────

def test_default_paper_cost_model_contains_operator_decision_required_literal() -> None:
    """The literal ``OPERATOR_DECISION_REQUIRED`` must appear in the cost
    model marker so every default-cost-model bundle/summary is
    unambiguously flagged as not-yet-approved by the operator (Codex
    fail blocker #2)."""
    assert "OPERATOR_DECISION_REQUIRED" in replay_miner.COST_MODEL_NOTE
    assert replay_miner.COST_MODEL_OPERATOR_OVERRIDE_REQUIRED is True
    assert replay_miner.DEFAULT_FEE_BPS > 0
    assert replay_miner.DEFAULT_SLIPPAGE_BPS >= 0
    # The new-bundle market_snapshot must propagate the literal and
    # surface explicit defaults.
    row = {
        "intent_id": "x", "symbol": "BTCUSDT", "side": "long",
        "ts": 1_000.0, "generated_utc": "2026-05-23T00:00:00Z",
        "entry_price": 100.0, "raw_row": {},
        "expected_move_after_cost_bps": None,
        "confidence_calibrated": None,
        "entry_feature_decision_time": "2026-05-23T00:00:00Z",
        "entry_feature_available_at": "2026-05-22T23:59:59Z",
        "entry_feature_generated_at": "2026-05-22T23:59:58Z",
        "entry_feature_cutoff": "2026-05-22T23:59:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "pre_trade_allowed": None, "fee_gate_allowed": None,
        "churn_blocked": None, "paper_fill_allowed": None,
        "decision": "PAPER_INTENT_OBSERVED",
        "risk_decision": None, "orchestrator_decision": None,
    }
    new_bundle = replay_miner._new_bundle_from_row(row)
    market = new_bundle["market_snapshot"]
    assert "OPERATOR_DECISION_REQUIRED" in market["cost_model_source"]
    assert market["operator_override_required"] is True
    assert market["operator_decision_required"] is True
    assert market["default_fee_bps_visible"] == replay_miner.DEFAULT_FEE_BPS
    assert market["default_slippage_estimate_bps_visible"] == replay_miner.DEFAULT_SLIPPAGE_BPS
    assert new_bundle["bundle_generated_at"] == "2026-05-23T00:00:00Z"
    assert new_bundle["decision_time"] == "2026-05-23T00:00:00Z"
    assert new_bundle["available_at"] == "2026-05-22T23:59:59Z"
    assert new_bundle["feature_cutoff"] == "2026-05-22T23:59:00Z"
    assert new_bundle["entry_feature_generated_at"] == "2026-05-22T23:59:58Z"
    assert new_bundle["entry_feature_candle_closed_confirmed"] is True


# ─────────────────────────────────────────────────────────────────────
# Cost-model backfill remediation (Codex re-review fail blocker).
# ─────────────────────────────────────────────────────────────────────

from v2.backend.app.services.edge_proof.replay_miner import (
    LEGACY_COST_MODEL_MARKER,
    REQUIRED_COST_MODEL_LITERAL,
    REQUIRED_COST_MODEL_MARKER,
    REQUIRED_MARKET_SNAPSHOT_KEYS,
    PUBLIC_DIR as MINER_PUBLIC_DIR,
    REPLAY_BUNDLES_PATH,
    WORKLOG_DIR as MINER_WORKLOG_DIR,
    backfill_bundle_cost_model,
    backfill_bundle_replay_context,
    backfill_jsonl_store,
    build_altdata_snapshot,
    validate_bundle_row,
)


def _stale_legacy_row() -> dict[str, object]:
    return {
        "intent_id": "stale-1",
        "prediction_id": "stale-1",
        "symbol": "BTCUSDT",
        "generated_at": "2026-05-23T05:00:00Z",
        "anchor_ts": 1_779_500_000.0,
        "side": "long",
        "entry_price": 100.0,
        "market_snapshot": {
            "fee_bps": 5.0,
            "slippage_estimate_bps": 2.0,
            "cost_model_source": LEGACY_COST_MODEL_MARKER,
        },
        "future_outcomes": {
            "1m": {"window_id": "1m", "window_seconds": 60, "after_cost_return_bps": None,
                   "samples": 0, "source": "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE"},
            "5m": {"window_id": "5m", "window_seconds": 300, "after_cost_return_bps": None,
                   "samples": 0, "source": "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE"},
            "15m": {"window_id": "15m", "window_seconds": 900, "after_cost_return_bps": None,
                    "samples": 0, "source": "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE"},
            "1h": {"window_id": "1h", "window_seconds": 3600, "after_cost_return_bps": None,
                   "samples": 0, "source": "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE"},
        },
        "outcome_after_cost": None,
        "label": "insufficient_evidence",
        "altdata_snapshot": {
            "symbol": "BTCUSDT",
            "status": "MISSING_SOURCE",
            "source_label": "MISSING_SOURCE",
            "source_key": "v2:altdata:symbol_score:BTCUSDT",
            "missing_reason": "v2_altdata_symbol_score_key_missing",
            "payload": None,
        },
        "paper_fill_allowed": False,
        "paper_fill_gate_status": "MISSING_SOURCE",
        "paper_fill_gate_block_reasons": [],
        "paper_fill_gate_block_reasons_lineage": {
            "state": "MISSING_SOURCE",
            "missing_reason": "paper_fill_gate_block_reason_missing_from_v2_sources",
            "evidence_sources_considered": list(replay_miner.PAPER_FILL_GATE_EVIDENCE_SOURCES),
            "evidence_sources": [],
        },
        "paper_gate_decision": {
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": [],
            "paper_fill_gate_block_reasons_lineage": {
                "state": "MISSING_SOURCE",
                "missing_reason": "paper_fill_gate_block_reason_missing_from_v2_sources",
                "evidence_sources_considered": list(replay_miner.PAPER_FILL_GATE_EVIDENCE_SOURCES),
                "evidence_sources": [],
            },
        },
        "trainer_output": {
            "paper_fill_gate_block_reasons": [],
            "paper_fill_gate_block_reasons_lineage": {
                "state": "MISSING_SOURCE",
                "missing_reason": "paper_fill_gate_block_reason_missing_from_v2_sources",
                "evidence_sources_considered": list(replay_miner.PAPER_FILL_GATE_EVIDENCE_SOURCES),
                "evidence_sources": [],
            },
        },
        "paper_intent": {"intent_id": "stale-1", "symbol": "BTCUSDT", "side": "long", "decision": "SHADOW_OBSERVATION_ONLY"},
    }


def _clean_row() -> dict[str, object]:
    row = _stale_legacy_row()
    row["intent_id"] = "clean-1"
    row["prediction_id"] = "clean-1"
    row["paper_intent"] = dict(row["paper_intent"])
    row["paper_intent"]["intent_id"] = "clean-1"
    row["market_snapshot"] = dict(row["market_snapshot"])
    row["market_snapshot"].update({
        "cost_model_source": REQUIRED_COST_MODEL_MARKER,
        "operator_decision_required": True,
        "operator_override_required": True,
        "default_fee_bps_visible": 5.0,
        "default_slippage_estimate_bps_visible": 2.0,
    })
    return row


def test_backfill_stale_row_retags_cost_model_and_adds_visible_fields() -> None:
    row = _stale_legacy_row()
    out, changed = backfill_bundle_cost_model(row)
    assert changed is True
    assert REQUIRED_COST_MODEL_LITERAL in out["market_snapshot"]["cost_model_source"]
    assert out["market_snapshot"]["operator_decision_required"] is True
    assert out["market_snapshot"]["operator_override_required"] is True
    assert out["market_snapshot"]["default_fee_bps_visible"] == 5.0
    assert out["market_snapshot"]["default_slippage_estimate_bps_visible"] == 2.0
    # Protected fields unchanged.
    for k in ("intent_id", "prediction_id", "symbol", "generated_at", "anchor_ts",
              "future_outcomes", "label", "paper_gate_decision", "paper_intent"):
        assert out[k] == row[k], k


def test_backfill_clean_row_is_idempotent_and_unchanged() -> None:
    row = _clean_row()
    out, changed = backfill_bundle_cost_model(row)
    assert changed is False
    assert out == row


def test_new_bundle_records_missing_paper_gate_reason_without_fabricating_reason(monkeypatch) -> None:
    monkeypatch.setattr(replay_miner, "_safe_redis_read", lambda key: None)
    row = {
        "intent_id": "missing-reason-1",
        "symbol": "BTCUSDT",
        "side": "long",
        "ts": 1_000.0,
        "generated_utc": "2026-05-23T00:00:00Z",
        "entry_price": 100.0,
        "paper_fill_allowed": False,
        "decision": "PAPER_INTENT_OBSERVED",
        "raw_row": {},
    }
    bundle = replay_miner._new_bundle_from_row(row)
    gate = bundle["paper_gate_decision"]
    assert gate["paper_fill_gate_block_reasons"] == []
    assert gate["paper_fill_gate_block_reasons_lineage"]["state"] == "MISSING_SOURCE"
    assert bundle["paper_fill_gate_status"] == "MISSING_SOURCE"
    assert bundle["label"] == ReplayLabel.INSUFFICIENT_EVIDENCE.value


def test_new_bundle_records_explicit_paper_gate_reason_lineage(monkeypatch) -> None:
    monkeypatch.setattr(replay_miner, "_safe_redis_read", lambda key: None)
    row = {
        "intent_id": "reason-1",
        "symbol": "BTCUSDT",
        "side": "long",
        "ts": 1_000.0,
        "generated_utc": "2026-05-23T00:00:00Z",
        "entry_price": 100.0,
        "paper_fill_allowed": False,
        "decision": "HELD_BY_PAPER_FILL_GATE",
        "raw_row": {"paper_fill_gate_block_reasons": ["BLOCK_FEATURE_FRESHNESS_NOT_CURRENT"]},
    }
    bundle = replay_miner._new_bundle_from_row(row)
    gate = bundle["paper_gate_decision"]
    assert gate["paper_fill_gate_block_reasons"] == ["BLOCK_FEATURE_FRESHNESS_NOT_CURRENT"]
    assert gate["paper_fill_gate_block_reasons_lineage"]["state"] == "RECORDED"
    assert bundle["paper_fill_gate_status"] == "BLOCK_REASON_RECORDED"


def test_altdata_snapshot_uses_v2_key_or_explicit_missing_source(monkeypatch) -> None:
    seen: list[str] = []

    def fake_read(key: str):
        seen.append(key)
        return {"symbol": "BTCUSDT", "score": 0.42}

    monkeypatch.setattr(replay_miner, "_safe_redis_read", fake_read)
    snapshot = build_altdata_snapshot("BTCUSDT")
    assert snapshot["status"] == "ATTACHED"
    assert snapshot["source_label"] == "V2_NATIVE_PUBLIC_PAYLOAD"
    assert snapshot["source_key"] == "v2:altdata:symbol_score:BTCUSDT"
    assert seen == ["v2:altdata:symbol_score:BTCUSDT"]

    monkeypatch.setattr(replay_miner, "_safe_redis_read", lambda key: None)
    missing = build_altdata_snapshot("ETHUSDT")
    assert missing["status"] == "MISSING_SOURCE"
    assert missing["source_label"] == "MISSING_SOURCE"
    assert missing["source_key"] == "v2:altdata:symbol_score:ETHUSDT"


def test_backfill_bundle_replay_context_adds_altdata_and_lineage(monkeypatch) -> None:
    monkeypatch.setattr(replay_miner, "_safe_redis_read", lambda key: None)
    row = _clean_row()
    row.pop("altdata_snapshot")
    row["paper_gate_decision"] = {"paper_fill_allowed": False, "paper_fill_gate_block_reasons": []}
    out, changed = backfill_bundle_replay_context(row)
    assert changed is True
    assert out["altdata_snapshot"]["status"] == "MISSING_SOURCE"
    assert (
        out["paper_gate_decision"]["paper_fill_gate_block_reasons_lineage"]["state"]
        == "MISSING_SOURCE"
    )
    assert validate_bundle_row(out) == []


def test_validate_bundle_row_passes_on_clean_row() -> None:
    assert validate_bundle_row(_clean_row()) == []


def test_validate_bundle_row_fails_on_stale_row() -> None:
    errs = validate_bundle_row(_stale_legacy_row())
    assert "cost_model_source_missing_required_literal" in errs
    assert "missing_or_falsy_operator_decision_required" in errs
    assert "missing_or_falsy_operator_override_required" in errs
    assert "missing_default_fee_bps_visible" in errs
    assert "missing_default_slippage_estimate_bps_visible" in errs


def test_validate_bundle_row_flags_fabricated_outcome_in_insufficient_window() -> None:
    row = _clean_row()
    row["future_outcomes"] = dict(row["future_outcomes"])
    row["future_outcomes"]["5m"] = dict(row["future_outcomes"]["5m"])
    # Fabricate an after_cost value but keep the INSUFFICIENT source.
    row["future_outcomes"]["5m"]["after_cost_return_bps"] = 25.0
    errs = validate_bundle_row(row)
    assert any(e.startswith("insufficient_window_with_fabricated_outcome") for e in errs)


def test_backfill_jsonl_store_retags_stale_rows_and_preserves_others(tmp_path) -> None:
    p = tmp_path / "bundles.jsonl"
    rows = [_stale_legacy_row(), _clean_row()]
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, default=str) + "\n")
    status = backfill_jsonl_store(p)
    assert status["validation_passed"] is True
    assert status["changed"] == 1
    assert status["protected_field_drift"] == []
    # After backfill: both rows pass validation.
    with p.open("r", encoding="utf-8") as f:
        backfilled = [json.loads(line) for line in f]
    for r in backfilled:
        assert REQUIRED_COST_MODEL_LITERAL in r["market_snapshot"]["cost_model_source"]
        for k in REQUIRED_MARKET_SNAPSHOT_KEYS:
            assert k in r["market_snapshot"], k


def test_persisted_replay_bundle_stores_pass_validation_after_backfill() -> None:
    """The three persisted JSONL stores (worklog, public mirror,
    miner state) must all carry the literal and visible override fields
    on every row. This regression locks in the backfill so a future
    miner run cannot regress them."""
    targets = [
        MINER_WORKLOG_DIR / "replay_outcome_bundles.jsonl",
        MINER_PUBLIC_DIR / "replay_outcome_bundles.jsonl",
        REPLAY_BUNDLES_PATH,
    ]
    for path in targets:
        assert path.exists(), str(path)
        with path.open("r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        for i, row in enumerate(rows):
            errs = validate_bundle_row(row)
            assert errs == [], (str(path), i, errs)


def test_backfill_never_modifies_future_outcomes_or_labels() -> None:
    row = _stale_legacy_row()
    original_outcomes = json.loads(json.dumps(row["future_outcomes"], default=str))
    original_label = row["label"]
    out, _ = backfill_bundle_cost_model(row)
    assert out["future_outcomes"] == original_outcomes
    assert out["label"] == original_label
    assert out["outcome_after_cost"] == row["outcome_after_cost"]


def test_backfill_artifacts_emit_no_live_canary_shutdown_approvals() -> None:
    targets = [
        MINER_WORKLOG_DIR / "replay_outcome_bundles.jsonl",
        MINER_PUBLIC_DIR / "replay_outcome_bundles.jsonl",
        REPLAY_BUNDLES_PATH,
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for forbidden in (
            '"approves_live": true',
            '"approves_canary": true',
            '"approves_legacy_shutdown": true',
            '"approves_redis_trim": true',
        ):
            assert forbidden not in text, (str(path), forbidden)


def test_pending_retention_prunes_multirow_store_streaming_and_preserves_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pending.jsonl"
    now_ts = 20_000.0
    stale = {"prediction_id": "stale", "anchor_ts": 1_000.0, "payload": "x" * 4096}
    fresh = {"prediction_id": "fresh", "anchor_ts": 19_000.0, "payload": "y" * 4096}
    fresh_line = json.dumps(fresh, sort_keys=True).encode() + b"\n"
    path.write_bytes(json.dumps(stale, sort_keys=True).encode() + b"\n" + fresh_line)

    status = replay_miner._prune_stale_pending_streaming(  # noqa: SLF001
        path,
        now_ts=now_ts,
        maximum_age_seconds=4_000,
    )

    assert status["status"] == "PASS"
    assert status["rows_seen"] == 2
    assert status["rows_stale_pruned"] == 1
    assert status["rows_retained"] == 1
    assert path.read_bytes() == fresh_line
    assert status["output_sha256"] == hashlib.sha256(fresh_line).hexdigest()


def test_pending_stream_validation_failure_keeps_original_store(tmp_path: Path) -> None:
    path = tmp_path / "pending.jsonl"
    original = b'{"anchor_ts":19000,"prediction_id":"valid"}\nnot-json\n'
    path.write_bytes(original)

    with pytest.raises(ValueError, match="PENDING_STREAM_ROW_INVALID_JSON:2"):
        replay_miner._prune_stale_pending_streaming(  # noqa: SLF001
            path,
            now_ts=20_000.0,
            maximum_age_seconds=4_000,
        )

    assert path.read_bytes() == original
    assert not path.with_suffix(path.suffix + ".prune.tmp").exists()


def test_replay_bundle_binds_large_authorities_by_hash_not_payload(
    monkeypatch,
) -> None:
    monkeypatch.setattr(replay_miner, "build_altdata_snapshot", lambda symbol: {
        "symbol": symbol,
        "status": "MISSING_SOURCE",
        "source_label": "MISSING_SOURCE",
        "source_key": f"v2:altdata:symbol_score:{symbol}",
        "missing_reason": "test",
        "payload": None,
    })
    monkeypatch.setattr(replay_miner, "_legacy_reference_action_for", lambda symbol: None)
    large_risk = {
        "risk_decision_id": "risk-1",
        "symbol": "BTCUSDT",
        "strategy_decision_time": "2026-07-28T20:00:00Z",
        "strategy_feature_cutoff": "2026-07-28T19:59:00Z",
        "paper_only": True,
        "matrix": "r" * 1_000_000,
    }
    large_orchestrator = {
        "orchestrator_decision_id": "orch-1",
        "paper_only": True,
        "matrix": "o" * 1_000_000,
    }
    row = {
        "intent_id": "intent-1",
        "symbol": "BTCUSDT",
        "side": "long",
        "generated_utc": "2026-07-28T20:00:00Z",
        "ts": 1_785_268_800.0,
        "entry_price": 100.0,
        "risk_decision": large_risk,
        "orchestrator_decision": large_orchestrator,
        "paper_fill_allowed": False,
        "decision": "PAPER_INTENT_OBSERVED",
        "raw_row": {"paper_fill_gate_block_reasons": []},
    }

    bundle = replay_miner._new_bundle_from_row(row)  # noqa: SLF001

    assert bundle["risk_decision"]["source_record_sha256"] == (
        replay_miner._canonical_sha256(large_risk)  # noqa: SLF001
    )
    assert bundle["orchestrator_decision"]["source_record_sha256"] == (
        replay_miner._canonical_sha256(large_orchestrator)  # noqa: SLF001
    )
    assert "matrix" not in bundle["risk_decision"]
    assert "matrix" not in bundle["orchestrator_decision"]
    assert len(json.dumps(bundle, sort_keys=True)) < 20_000


def test_large_artifact_copy_is_streaming_and_atomic(tmp_path: Path) -> None:
    from v2.backend.app.cli.v2_post_hoc_replay_outcome_miner import (
        _copy_file_atomic,
    )

    source = tmp_path / "source.jsonl"
    target = tmp_path / "mirror" / "target.jsonl"
    payload = (b'{"row":1}\n' * 200_000)
    source.write_bytes(payload)

    _copy_file_atomic(source, target)

    assert target.read_bytes() == payload
    assert not target.with_suffix(target.suffix + ".tmp").exists()
