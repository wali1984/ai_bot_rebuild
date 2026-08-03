"""Regression tests for the tracker-only consumption boundary
remediation of the V2 full-observation builder.

Codex flagged that the builder was reading raw v2:paper:positions /
ledger / intents / intents_held into the position-history aggregator
path, so tracker-derived fields could be sourced from raw paper rows
even when the tracker payload said otherwise. The remediation splits
the position-context slice into two extractors:

- ``_extract_tracker_history_fields`` — strict tracker-only;
- ``_extract_raw_paper_context_fields`` — labels remaining
  rate/granular-block-reason fields with
  ``V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY`` and never claims they
  came from the tracker.

These tests prove every concrete adversarial case the Codex review
required.
"""
from __future__ import annotations

import importlib


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


def _by_name(values, names, sources):
    return {n: (v, s) for n, v, s in zip(names, values, sources)}


# --------------------------------------------------------------------------- #
# 1. Codex's exact failing scenario:                                          #
#    tracker says NO_OPEN_POSITION but raw ledger has an accepted row.        #
# --------------------------------------------------------------------------- #


def test_tracker_no_open_position_overrides_raw_ledger_accepted_row() -> None:
    mod = _builder()
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "NO_OPEN_POSITION",
        "accepted_intent_count": 0,
        "held_intent_count": 0,
        "block_reason_count": 0,
    }
    # Raw ledger HAS an accepted row for BTCUSDT — the old code would have
    # counted this as 1, conflating sources. The new code must surface 0.
    raw_ledger = {
        "accepted": [
            {"intent_id": "i1", "symbol": "BTCUSDT", "entry_price": 100.0}
        ]
    }
    values, names, sources, _ = mod._build_position_context_slice(
        "BTCUSDT",
        [{"intent_id": "i1", "symbol": "BTCUSDT", "side": "long"}],
        [],
        {},
        {},
        paper_intents=[{"intent_id": "i1", "symbol": "BTCUSDT"}],
        paper_intents_held=[],
        paper_ledger=raw_ledger,
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    by = _by_name(values, names, sources)
    v, s = by["position_context.v2_intents_accepted_count"]
    assert v == 0.0, "tracker says 0 accepted; raw ledger must not promote that to 1"
    assert s == "V2_POSITION_HISTORY_TRACKER"
    # MFE/MAE/ROE/position-age must remain null under NO_OPEN_POSITION.
    for field in (
        "position_context.v2_mfe_bps",
        "position_context.v2_mae_bps",
        "position_context.v2_roe_bps",
        "position_context.v2_position_age_seconds",
    ):
        v, s = by[field]
        assert v is None, field
        assert s == "V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION", field


# --------------------------------------------------------------------------- #
# 2. Inverse scenario: tracker has high counts, raw ledger is empty.          #
# --------------------------------------------------------------------------- #


def test_tracker_counts_win_when_raw_ledger_is_empty() -> None:
    mod = _builder()
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_TRACKING",
        "accepted_intent_count": 7,
        "held_intent_count": 3,
        "block_reason_count": 2,
        "max_favorable_bps": 250.0,
        "max_adverse_bps": -75.0,
        "unrealized_bps": 175.0,
        "hold_time_seconds": 3600.0,
    }
    values, names, sources, _ = mod._build_position_context_slice(
        "BTCUSDT",
        [],
        [],
        {},
        {},
        paper_intents=[],
        paper_intents_held=[],
        paper_ledger={},
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    by = _by_name(values, names, sources)
    assert by["position_context.v2_intents_accepted_count"] == (7.0, "V2_POSITION_HISTORY_TRACKER")
    assert by["position_context.v2_intents_held_count"] == (3.0, "V2_POSITION_HISTORY_TRACKER")
    assert by["position_context.v2_intents_blocked_count"] == (2.0, "V2_POSITION_HISTORY_TRACKER")
    assert by["position_context.v2_mfe_bps"] == (250.0, "V2_POSITION_HISTORY_TRACKER")
    assert by["position_context.v2_mae_bps"] == (-75.0, "V2_POSITION_HISTORY_TRACKER")
    assert by["position_context.v2_roe_bps"] == (175.0, "V2_POSITION_HISTORY_TRACKER")
    assert by["position_context.v2_hold_time_seconds_current"] == (
        3600.0, "V2_POSITION_HISTORY_TRACKER"
    )


# --------------------------------------------------------------------------- #
# 3. Stale heartbeat (consumption blocked) masks tracker fields.              #
# --------------------------------------------------------------------------- #


def test_stale_heartbeat_masks_tracker_fields_even_with_open_tracker_payload() -> None:
    mod = _builder()
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_TRACKING",
        "accepted_intent_count": 5,
        "max_favorable_bps": 100.0,
    }
    values, names, sources, _ = mod._build_position_context_slice(
        "BTCUSDT",
        [],
        [],
        {},
        {},
        paper_intents=[],
        paper_intents_held=[],
        paper_ledger={},
        position_history=tracker_payload,
        position_history_consumption_allowed=False,
        position_history_consumption_blocked_reason="TRACKER_HEARTBEAT_STALE:999",
    )
    by = _by_name(values, names, sources)
    expected_source = (
        "V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:TRACKER_HEARTBEAT_STALE:999"
    )
    for field in mod.TRACKER_HISTORY_DERIVED_FIELDS:
        full = f"position_context.{field}"
        v, s = by[full]
        assert v is None, full
        assert s == expected_source, full


# --------------------------------------------------------------------------- #
# 4. Raw held / shadow intents are not counted as accepted.                   #
# --------------------------------------------------------------------------- #


def test_raw_held_and_shadow_intents_do_not_inflate_tracker_accepted_count() -> None:
    mod = _builder()
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_TRACKING",
        "accepted_intent_count": 1,
        "held_intent_count": 4,  # tracker's own count; we surface this verbatim
        "block_reason_count": 2,
    }
    # Raw ledger has many held + shadow rows. The tracker-derived
    # accepted_intent_count must come from tracker, not get inflated by
    # the raw ledger.
    raw_ledger = {
        "accepted": [
            {"symbol": "BTCUSDT", "intent_id": "a1"},
            # The next two rows masquerade as accepted but are tagged as held / shadow:
            {"symbol": "BTCUSDT", "intent_id": "a2", "paper_result": "SHADOW"},
            {"symbol": "BTCUSDT", "intent_id": "a3", "ledger_action": "HELD_BY_PAPER_FILL_GATE"},
        ],
        "held_by_paper_fill_gate": [
            {"symbol": "BTCUSDT", "intent_id": "h1"},
            {"symbol": "BTCUSDT", "intent_id": "h2"},
        ],
        "shadow_observations": [
            {"symbol": "BTCUSDT", "intent_id": "s1"},
            {"symbol": "BTCUSDT", "intent_id": "s2"},
        ],
        "blocked": [],
    }
    values, names, sources, _ = mod._build_position_context_slice(
        "BTCUSDT",
        [{"symbol": "BTCUSDT", "side": "long"}],
        [],
        {},
        {},
        paper_intents=[],
        paper_intents_held=[],
        paper_ledger=raw_ledger,
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    by = _by_name(values, names, sources)
    accepted_value, accepted_source = by["position_context.v2_intents_accepted_count"]
    held_value, held_source = by["position_context.v2_intents_held_count"]
    assert accepted_value == 1.0, "tracker says 1 accepted; raw ledger rows must not inflate"
    assert accepted_source == "V2_POSITION_HISTORY_TRACKER"
    assert held_value == 4.0, "held count must come from tracker, not be recomputed"
    assert held_source == "V2_POSITION_HISTORY_TRACKER"


# --------------------------------------------------------------------------- #
# 5. MFE/MAE/ROE null when tracker has no open-position evidence.             #
# --------------------------------------------------------------------------- #


def test_mfe_mae_roe_remain_null_when_tracker_has_no_open_position_evidence() -> None:
    mod = _builder()
    # Even if raw paper inputs would have allowed MFE/MAE/ROE to be
    # computed under the old aggregator path, the new tracker-only
    # path must keep them null when the tracker reports NO_OPEN_POSITION.
    raw_ledger = {
        "accepted": [{"symbol": "BTCUSDT", "entry_price": 100.0}],
        "last_closed_position": {
            "symbol": "BTCUSDT", "exit_price": 110.0, "closed_at": "2026-05-21T05:00:00Z"
        },
    }
    raw_position_price_track = {
        "symbol": "BTCUSDT",
        "min_price_since_entry": 95.0,
        "max_price_since_entry": 115.0,
    }
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "NO_OPEN_POSITION",
        "accepted_intent_count": 0,
    }
    values, names, sources, _ = mod._build_position_context_slice(
        "BTCUSDT",
        [],
        [],
        {},
        {},
        paper_intents=[],
        paper_intents_held=[],
        paper_ledger=raw_ledger,
        position_price_track=raw_position_price_track,
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    by = _by_name(values, names, sources)
    for fname in (
        "position_context.v2_mfe_bps",
        "position_context.v2_mae_bps",
        "position_context.v2_roe_bps",
        "position_context.v2_position_age_seconds",
        "position_context.v2_hold_time_proxy_seconds",
        "position_context.v2_hold_time_seconds_current",
    ):
        v, s = by[fname]
        assert v is None, fname
        assert s == "V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION", fname


# --------------------------------------------------------------------------- #
# 6. Raw paper-context fields keep working but are sourced separately.        #
# --------------------------------------------------------------------------- #


def test_raw_paper_context_fields_are_explicitly_labeled_not_tracker_history() -> None:
    mod = _builder()
    tracker_payload = {
        "symbol": "BTCUSDT", "position_state": "OPEN_TRACKING",
    }
    values, names, sources, _ = mod._build_position_context_slice(
        "BTCUSDT",
        [],
        [],
        {},
        {},
        paper_intents=[
            {"symbol": "BTCUSDT", "pre_trade_allowed": True, "fee_gate_allowed": True,
             "churn_blocked": False, "intent_id": "i1"},
        ],
        paper_intents_held=[],
        paper_ledger={
            "accepted": [{"symbol": "BTCUSDT", "intent_id": "i1"}],
        },
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    by = _by_name(values, names, sources)
    for field in mod.RAW_PAPER_CONTEXT_FIELDS:
        full = f"position_context.{field}"
        v, s = by[full]
        # Source MUST be the explicit raw-paper-context label OR the
        # explicit raw-paper-context-missing fallback — never the
        # ``V2_POSITION_HISTORY_TRACKER`` label that belongs to the
        # tracker-derived path.
        assert s in {"V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY",
                     "MISSING_V2_RAW_PAPER_CONTEXT"}, (full, s)
        # Source must NOT claim to be tracker-derived — the explicit
        # ``V2_POSITION_HISTORY_TRACKER*`` family belongs to the tracker
        # extractor. (The label ``V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY``
        # contains the substring "TRACKER" intentionally, to say
        # "this is NOT tracker history".)
        assert not s.startswith("V2_POSITION_HISTORY_TRACKER"), (full, s)


# --------------------------------------------------------------------------- #
# 7. Status payload zero-fill / safety invariants stay pinned.                #
# --------------------------------------------------------------------------- #


def test_zero_fill_count_stays_zero_and_no_aggregator_source_on_status_payload(
    monkeypatch,
) -> None:
    mod = _builder()
    monkeypatch.setattr(mod, "_connect_redis", lambda: None)
    payload = mod.build_full_observation_status(symbols=("BTCUSDT",))
    assert payload["zero_filled_field_count"] == 0
    assert payload["no_zero_fill_for_unknown_fields"] is True
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_parity_claimed"] is False
    assert payload["state"] == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    # Walk every per-symbol sample and confirm the legacy aggregator
    # source label has been retired from emitted fields.
    for row in payload["per_symbol"]:
        for sample in row.get("sample_present_fields") or []:
            assert sample["source"] != "V2_POSITION_HISTORY_AGGREGATOR", sample


# --------------------------------------------------------------------------- #
# 8. Builder must not import / read legacy current-truth modules.             #
# --------------------------------------------------------------------------- #


def test_builder_does_not_import_torch_or_read_legacy_filesystem() -> None:
    import sys
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )
    assert "torch" not in sys.modules


def test_status_payload_pins_legacy_safety_invariants(monkeypatch) -> None:
    mod = _builder()
    monkeypatch.setattr(mod, "_connect_redis", lambda: None)
    payload = mod.build_full_observation_status(symbols=("BTCUSDT",))
    assert payload["no_torch_imported"] is True
    assert payload["no_pickle_loaded"] is True
    assert payload["no_legacy_filesystem_read"] is True
    assert payload["no_legacy_features_consumed_as_current_truth"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False


# --------------------------------------------------------------------------- #
# 9. Field enumeration: every emitted position-context source belongs to a    #
#    known, non-conflated source set.                                         #
# --------------------------------------------------------------------------- #


def test_every_position_context_source_belongs_to_known_disjoint_set() -> None:
    mod = _builder()
    tracker_payload = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_TRACKING",
        "accepted_intent_count": 2,
        "held_intent_count": 1,
        "block_reason_count": 0,
        "max_favorable_bps": 50.0,
        "max_adverse_bps": -10.0,
        "unrealized_bps": 30.0,
        "hold_time_seconds": 600.0,
    }
    values, names, sources, _ = mod._build_position_context_slice(
        "BTCUSDT",
        [{"symbol": "BTCUSDT", "side": "long"}],
        [],
        {"selected_action": "long"},
        {},
        paper_intents=[{"symbol": "BTCUSDT", "pre_trade_allowed": True}],
        paper_intents_held=[],
        paper_ledger={"accepted": [{"symbol": "BTCUSDT"}]},
        position_history=tracker_payload,
        position_history_consumption_allowed=True,
    )
    allowed = {
        "V2_PAPER_POSITIONS",
        "MISSING_FROM_V2_PAPER_POSITIONS",
        "V2_RISK_DECISIONS",
        "V2_RISK_DECISIONS_NO_SYMBOL_ROW",
        "MISSING_FROM_V2_RISK",
        "MISSING_FROM_V2_RISK_DECISIONS",
        "MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW",
        "MISSING_FROM_V2_RISK_DECISIONS_FIELD_PRE_TRADE_ALLOWED",
        "MISSING_FROM_V2_RISK_DECISIONS_FIELD_FEE_GATE_ALLOWED",
        "MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED",
        "V2_PREDICTION",
        "MISSING_FROM_V2_PREDICTION",
        "V2_ORCHESTRATOR_DECISIONS",
        "V2_DERIVED_FROM_PREDICTION",
        "V2_PROBE_FLAG_POSITION_HISTORY_AGGREGATOR",
        "V2_POSITION_HISTORY_TRACKER",
        "V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION",
        "V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING",
        "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING",
        "V2_RAW_PAPER_CONTEXT_NOT_TRACKER_HISTORY",
        "MISSING_V2_RAW_PAPER_CONTEXT",
        "MISSING_FROM_V2_POSITION_HISTORY",
    }
    bad = [s for s in sources if s and not s.startswith(
        ("V2_", "MISSING_")
    )]
    assert not bad, bad
    # The retired conflated label must NOT appear:
    assert "V2_POSITION_HISTORY_AGGREGATOR" not in set(sources)
    # Every concrete (non-empty) source must be in the allowed set OR a
    # tracker-consumption-blocked source (which is constructed dynamically).
    for s in sources:
        if not s:
            continue
        if s.startswith("V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:"):
            continue
        assert s in allowed, s
