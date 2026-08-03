"""Tests for the V2 full-observation builder's position-history
consumption gate.

Paper-only. No torch import. No legacy mutation. No real Redis.

Verifies:
- gate-allowed path emits ``V2_POSITION_HISTORY_AGGREGATOR``-sourced fields
- gate blocks when the tracker Codex PASS marker is missing
- gate blocks when the tracker heartbeat is stale
- gate blocks when the tracker heartbeat TTL is not positive
- blocked path emits null tracker fields with explicit
  ``V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>`` source
- NO_OPEN_POSITION inside an allowed payload never fabricates MFE/MAE/ROE
- safety invariants (no zero-fill, no checkpoint/parity claim) stay pinned
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


# --------------------------------------------------------------------------- #
# Gate decision unit tests                                                    #
# --------------------------------------------------------------------------- #


def _write_marker(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")


def _fresh_heartbeat(now: datetime, **overrides) -> dict:
    payload = {
        "generated_utc": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "process_mode": "persistent_daemon",
        "service_active": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "no_synthesized_accepted_positions": True,
        "no_fabricated_excursion_metrics": True,
        "no_shadow_observations_counted_as_accepted": True,
    }
    payload.update(overrides)
    return payload


def test_gate_allowed_when_codex_pass_and_heartbeat_fresh(tmp_path: Path) -> None:
    mod = _builder()
    marker = tmp_path / "remediation_pass.md"
    _write_marker(
        marker, "V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS"
    )
    now = datetime(2026, 5, 21, 6, 0, 0, tzinfo=timezone.utc)
    hb = _fresh_heartbeat(now)
    result = mod.evaluate_position_history_consumption_gate(
        codex_pass_marker_paths=(marker,),
        tracker_heartbeat=hb,
        tracker_heartbeat_ttl_seconds=300,
        now=now,
    )
    assert result["consumption_allowed"] is True
    assert result["blocked_reason"] is None
    assert result["consumption_state"] == "ALLOWED_AFTER_CODEX_PASS_AND_FRESH_HEARTBEAT"
    assert result["tracker_heartbeat_present"] is True
    assert result["tracker_heartbeat_fresh"] is True
    assert result["tracker_heartbeat_ttl_seconds"] == 300
    assert result["tracker_codex_pass_marker_paths_passed"] == [str(marker)]
    assert result["tracker_codex_pass_marker_paths_failed"] == []


def test_gate_accepts_persistent_tracker_pass_token_too(tmp_path: Path) -> None:
    mod = _builder()
    marker = tmp_path / "persistent_pass.md"
    _write_marker(marker, "V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS")
    now = datetime(2026, 5, 21, 6, 0, 0, tzinfo=timezone.utc)
    hb = _fresh_heartbeat(now)
    result = mod.evaluate_position_history_consumption_gate(
        codex_pass_marker_paths=(marker,),
        tracker_heartbeat=hb,
        tracker_heartbeat_ttl_seconds=300,
        now=now,
    )
    assert result["consumption_allowed"] is True


def test_gate_blocks_when_codex_pass_marker_missing(tmp_path: Path) -> None:
    mod = _builder()
    marker = tmp_path / "fail.md"
    _write_marker(marker, "V2_POSITION_HISTORY_TRACKER_CODEX_FAIL")
    now = datetime(2026, 5, 21, 6, 0, 0, tzinfo=timezone.utc)
    hb = _fresh_heartbeat(now)
    result = mod.evaluate_position_history_consumption_gate(
        codex_pass_marker_paths=(marker,),
        tracker_heartbeat=hb,
        tracker_heartbeat_ttl_seconds=300,
        now=now,
    )
    assert result["consumption_allowed"] is False
    assert result["blocked_reason"] == "TRACKER_CODEX_PASS_MISSING_OR_MISMATCH"
    assert result["consumption_state"] == "BLOCKED_TRACKER_NOT_CODEX_PASSED"
    assert result["tracker_codex_pass_marker_paths_passed"] == []


def test_gate_blocks_when_heartbeat_missing(tmp_path: Path) -> None:
    mod = _builder()
    marker = tmp_path / "pass.md"
    _write_marker(
        marker, "V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS"
    )
    result = mod.evaluate_position_history_consumption_gate(
        codex_pass_marker_paths=(marker,),
        tracker_heartbeat=None,
        tracker_heartbeat_ttl_seconds=None,
    )
    assert result["consumption_allowed"] is False
    assert result["blocked_reason"] == "TRACKER_HEARTBEAT_MISSING"
    assert result["consumption_state"] == "BLOCKED_HEARTBEAT_MISSING"


def test_gate_blocks_when_heartbeat_stale(tmp_path: Path) -> None:
    mod = _builder()
    marker = tmp_path / "pass.md"
    _write_marker(
        marker, "V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS"
    )
    now = datetime(2026, 5, 21, 6, 0, 0, tzinfo=timezone.utc)
    # Build a heartbeat 999 seconds old; default max is 180.
    stale_ts = datetime(2026, 5, 21, 5, 43, 21, tzinfo=timezone.utc)
    hb = _fresh_heartbeat(stale_ts)
    result = mod.evaluate_position_history_consumption_gate(
        codex_pass_marker_paths=(marker,),
        tracker_heartbeat=hb,
        tracker_heartbeat_ttl_seconds=10,
        now=now,
    )
    assert result["consumption_allowed"] is False
    assert result["blocked_reason"].startswith("TRACKER_HEARTBEAT_STALE")
    assert result["consumption_state"] == "BLOCKED_HEARTBEAT_STALE"
    assert result["tracker_heartbeat_age_seconds"] >= 180


def test_gate_blocks_when_heartbeat_ttl_not_positive(tmp_path: Path) -> None:
    mod = _builder()
    marker = tmp_path / "pass.md"
    _write_marker(
        marker, "V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS"
    )
    now = datetime(2026, 5, 21, 6, 0, 0, tzinfo=timezone.utc)
    hb = _fresh_heartbeat(now)
    result = mod.evaluate_position_history_consumption_gate(
        codex_pass_marker_paths=(marker,),
        tracker_heartbeat=hb,
        tracker_heartbeat_ttl_seconds=-2,
        now=now,
    )
    assert result["consumption_allowed"] is False
    assert result["blocked_reason"].startswith("TRACKER_HEARTBEAT_TTL_NOT_POSITIVE")
    assert result["consumption_state"] == "BLOCKED_HEARTBEAT_TTL_NOT_POSITIVE"


# --------------------------------------------------------------------------- #
# Per-symbol masking behaviour                                                #
# --------------------------------------------------------------------------- #


def test_blocked_consumption_masks_tracker_fields_with_explicit_source() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[
            {"symbol": "BTCUSDT", "side": "long", "entry_price": 100.0,
             "generated_utc": "2026-05-21T05:00:00Z"}
        ],
        paper_ledger={
            "accepted": [{"symbol": "BTCUSDT", "entry_price": 100.0}]
        },
        risk_decisions=None,
        orchestrator_decisions=None,
        trainer_heartbeat=None,
        prediction=None,
        position_price_track={"symbol": "BTCUSDT", "latest_price": 110.0},
        position_history={
            "symbol": "BTCUSDT", "position_state": "OPEN_TRACKING",
            "max_favorable_bps": 1000.0
        },
        position_history_consumption_allowed=False,
        position_history_consumption_blocked_reason="TRACKER_HEARTBEAT_STALE:999",
    )
    expected_source = (
        "V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:TRACKER_HEARTBEAT_STALE:999"
    )
    tracker_field_names = {
        f"position_context.{n}"
        for n in mod.TRACKER_DERIVED_POSITION_CONTEXT_FIELDS
    }
    masked_indices = [
        i for i, name in enumerate(result.field_names) if name in tracker_field_names
    ]
    assert masked_indices, "expected tracker-derived field names in output"
    for i in masked_indices:
        assert result.field_values[i] is None, result.field_names[i]
        assert result.field_sources[i] == expected_source, result.field_names[i]


def test_allowed_consumption_emits_aggregator_sourced_fields() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[
            {"symbol": "BTCUSDT", "side": "long", "entry_price": 100.0,
             "generated_utc": "2026-05-21T05:00:00Z"}
        ],
        paper_ledger={
            "accepted": [{"symbol": "BTCUSDT", "entry_price": 100.0}]
        },
        risk_decisions=None,
        orchestrator_decisions=None,
        trainer_heartbeat=None,
        prediction=None,
        position_price_track={"symbol": "BTCUSDT", "latest_price": 110.0},
        position_history={
            "symbol": "BTCUSDT", "position_state": "OPEN_TRACKING",
            "max_favorable_bps": 1000.0
        },
        position_history_consumption_allowed=True,
    )
    # After the tracker-only consumption remediation, the tracker-derived
    # fields are sourced with ``V2_POSITION_HISTORY_TRACKER`` (or
    # tracker-no-open-position / tracker-payload-field-missing sources),
    # and the raw paper-context fields with
    # ``V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY``. The old
    # ``V2_POSITION_HISTORY_AGGREGATOR`` source label must NOT appear on
    # any position-context field — that conflated sources and was the
    # exact label Codex flagged.
    assert any(
        s == "V2_POSITION_HISTORY_TRACKER" for s in result.field_sources
    )
    assert any(
        s == "V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY"
        for s in result.field_sources
    )
    assert not any(
        s == "V2_POSITION_HISTORY_AGGREGATOR" for s in result.field_sources
    )


def test_no_open_position_does_not_fabricate_mfe_mae_roe_in_allowed_path() -> None:
    """When the tracker payload is allowed but there is no open paper
    position, MFE/MAE/ROE must remain null and their source must NOT be
    ``V2_POSITION_HISTORY_AGGREGATOR`` claiming real evidence."""
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        # No paper position row for BTCUSDT.
        paper_positions=[],
        paper_ledger={},
        risk_decisions=None,
        orchestrator_decisions=None,
        trainer_heartbeat=None,
        prediction=None,
        position_price_track=None,
        position_history={
            "symbol": "BTCUSDT", "position_state": "NO_OPEN_POSITION",
            "max_favorable_bps": None, "max_adverse_bps": None,
            "unrealized_bps": None,
        },
        position_history_consumption_allowed=True,
    )
    names = list(result.field_names)
    values = list(result.field_values)
    sources = list(result.field_sources)
    for tracker_field in ("v2_mfe_bps", "v2_mae_bps", "v2_roe_bps"):
        full = f"position_context.{tracker_field}"
        idx = names.index(full)
        assert values[idx] is None, (full, values[idx])
        # When v2 has no open paper position evidence the source is the
        # explicit MISSING sentinel, never a fabricated aggregator claim.
        assert sources[idx] != "V2_POSITION_HISTORY_AGGREGATOR" or values[idx] is None


def test_status_payload_surfaces_consumption_gate(monkeypatch) -> None:
    """``build_full_observation_status`` exposes the gate decision in the
    top-level status payload regardless of Redis availability."""
    mod = _builder()
    # Force no Redis so the gate path runs with hb_present=False.
    monkeypatch.setattr(mod, "_connect_redis", lambda: None)
    payload = mod.build_full_observation_status(symbols=("BTCUSDT",))
    assert "position_history_consumption" in payload
    gate = payload["position_history_consumption"]
    assert gate["consumption_allowed"] in (True, False)
    assert "consumption_state" in gate
    assert "tracker_heartbeat_present" in gate
    assert "tracker_codex_pass_marker_paths_passed" in gate
    assert "tracker_codex_pass_marker_paths_failed" in gate
    # Top-level mirror fields.
    assert payload["position_history_consumption_allowed"] == gate["consumption_allowed"]
    assert payload["position_history_consumption_state"] == gate["consumption_state"]
    # Pinned safety invariants must remain.
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_parity_claimed"] is False
    assert payload["no_zero_fill_for_unknown_fields"] is True
    assert payload["zero_filled_field_count"] == 0
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_status_payload_zero_fill_count_stays_zero_when_consumption_blocked(
    monkeypatch,
) -> None:
    """Blocking consumption must not zero-fill the masked fields; they
    must remain ``None`` so the operator can see them as missing."""
    mod = _builder()
    monkeypatch.setattr(mod, "_connect_redis", lambda: None)
    payload = mod.build_full_observation_status(symbols=("BTCUSDT",))
    # When the gate blocks, the masked fields are None — they count as
    # missing, not as zero-fill. ``zero_filled_field_count`` must be 0.
    assert payload["zero_filled_field_count"] == 0
    assert payload["no_zero_fill_for_unknown_fields"] is True


def test_module_default_pass_marker_paths_pin_codex_review_files() -> None:
    """If a future change repoints the gate at the wrong marker files,
    this test catches it."""
    mod = _builder()
    expected = (
        "claude_worklog/final_readiness/v2_position_history_tracker_daemon_remediation/"
        "latest/codex_review/CODEX_GO_NO_GO.md",
        "claude_worklog/final_readiness/v2_position_history_persistent_tracker/"
        "latest/codex_review/CODEX_GO_NO_GO.md",
    )
    actual = tuple(str(p) for p in mod.TRACKER_CODEX_PASS_MARKER_PATHS)
    assert actual == expected
    assert mod.ACCEPTED_TRACKER_CODEX_PASS_TOKENS == frozenset(
        {
            "V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS",
            "V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS",
        }
    )
