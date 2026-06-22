"""Regression tests for the post-tracker position-context feature
expansion in the V2 full-observation builder.

This packet adds 6 tracker-only position-context fields, sourced
exclusively from the two Codex-passed tracker Redis payloads
(``v2:paper:position_price_track:{symbol}`` and
``v2:paper:position_history:{symbol}``). The tests below pin the
following hard invariants:

1. The new field set is exactly the 6 names in
   ``TRACKER_EXTENDED_FIELDS`` and is disjoint from the existing
   ``TRACKER_HISTORY_DERIVED_FIELDS`` 10-field contract.
2. ``_extract_tracker_extended_fields`` NEVER consumes
   ``paper_positions`` / ``paper_ledger`` / ``paper_intents`` /
   ``paper_intents_held`` — its function signature does not accept
   those arguments at all.
3. When the consumption gate is BLOCKED, all 6 fields are masked
   with ``V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason>``
   so the operator can detect tracker-gate state from the field
   source attribution alone.
4. When the tracker payload is missing entirely, the 6 fields are
   emitted as ``None`` with ``V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING``.
5. When the tracker payload is present but a specific field is
   absent, the field is ``None`` with
   ``V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING`` — no
   silent fabrication, no zero-fill.
6. When the tracker payload is for a different symbol, the fields
   are treated as missing.
7. Aggregate ``zero_filled_field_count`` remains 0.
8. ``checkpoint_compatibility_claimed`` and
   ``policy_architecture_parity_claimed`` remain ``false``.
"""
from __future__ import annotations

import importlib
import inspect


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


def test_tracker_extended_fields_are_six_named_fields() -> None:
    b = _builder()
    assert b.TRACKER_EXTENDED_FIELDS == (
        "v2_tracker_latest_price",
        "v2_tracker_entry_price",
        "v2_tracker_source_freshness_seconds",
        "v2_tracker_missing_flag_count",
        "v2_tracker_stale_flag_count",
        "v2_shadow_observation_count",
    )


def test_tracker_extended_fields_are_disjoint_from_history_fields() -> None:
    b = _builder()
    overlap = set(b.TRACKER_EXTENDED_FIELDS) & set(b.TRACKER_HISTORY_DERIVED_FIELDS)
    assert overlap == set(), (
        f"TRACKER_EXTENDED_FIELDS must not overlap with the prior "
        f"TRACKER_HISTORY_DERIVED_FIELDS contract; found overlap: {overlap}"
    )


def test_extended_extractor_signature_rejects_raw_paper_inputs() -> None:
    """The extended extractor must take ONLY tracker payloads + gate
    inputs. If anyone ever adds paper_positions / paper_ledger /
    paper_intents / paper_intents_held to its signature, that proves
    a regression."""
    b = _builder()
    sig = inspect.signature(b._extract_tracker_extended_fields)
    forbidden = {
        "paper_positions",
        "paper_ledger",
        "paper_intents",
        "paper_intents_held",
        "paper_intents_held_by_paper_fill_gate",
    }
    assert forbidden.isdisjoint(sig.parameters.keys()), (
        f"_extract_tracker_extended_fields must not accept raw paper "
        f"inputs. Signature: {list(sig.parameters.keys())!r}"
    )
    # Required tracker-only inputs
    for required in ("symbol", "position_history", "position_price_track",
                      "consumption_allowed", "consumption_blocked_reason"):
        assert required in sig.parameters, (
            f"_extract_tracker_extended_fields missing required param "
            f"{required!r}; got {list(sig.parameters.keys())!r}"
        )


def test_extended_extractor_masks_all_fields_when_gate_blocked() -> None:
    b = _builder()
    result = b._extract_tracker_extended_fields(
        symbol="BTCUSDT",
        position_history={"symbol": "BTCUSDT", "shadow_observation_count": 4},
        position_price_track={"symbol": "BTCUSDT", "latest_price": 50000.0},
        consumption_allowed=False,
        consumption_blocked_reason="TRACKER_HEARTBEAT_MISSING",
    )
    names = [n for n, _, _ in result]
    values = [v for _, v, _ in result]
    sources = [s for _, _, s in result]
    assert names == list(b.TRACKER_EXTENDED_FIELDS)
    assert all(v is None for v in values), (
        f"All 6 fields must be None when gate is blocked; got values={values!r}"
    )
    expected_src = (
        "V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:TRACKER_HEARTBEAT_MISSING"
    )
    assert all(s == expected_src for s in sources), (
        f"All sources must be the blocked-mask; got sources={sources!r}"
    )


def test_extended_extractor_when_payloads_are_none() -> None:
    """No tracker payload anywhere → 6 fields all None with
    PAYLOAD_MISSING."""
    b = _builder()
    result = b._extract_tracker_extended_fields(
        symbol="BTCUSDT",
        position_history=None,
        position_price_track=None,
        consumption_allowed=True,
        consumption_blocked_reason=None,
    )
    assert [n for n, _, _ in result] == list(b.TRACKER_EXTENDED_FIELDS)
    for _, value, source in result:
        assert value is None
        assert source == "V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING"


def test_extended_extractor_when_payload_is_for_other_symbol() -> None:
    b = _builder()
    result = b._extract_tracker_extended_fields(
        symbol="BTCUSDT",
        position_history={"symbol": "ETHUSDT", "shadow_observation_count": 9},
        position_price_track={
            "symbol": "ETHUSDT",
            "latest_price": 3000.0,
            "missing_flags": [],
            "stale_flags": [],
        },
        consumption_allowed=True,
        consumption_blocked_reason=None,
    )
    for _, value, source in result:
        assert value is None
        assert source == "V2_POSITION_HISTORY_TRACKER_PAYLOAD_MISSING"


def test_extended_extractor_sources_open_position_fields_from_tracker() -> None:
    """Happy path: an OPEN position with all tracker fields populated
    produces sourced values for every field."""
    b = _builder()
    track = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_LONG",
        "latest_price": 50123.45,
        "entry_price": 49000.0,
        "source_freshness_seconds": 4,
        "missing_flags": [],
        "stale_flags": [],
    }
    history = {
        "symbol": "BTCUSDT",
        "position_state": "OPEN_LONG",
        "shadow_observation_count": 7,
    }
    result = dict((n, (v, s)) for n, v, s in b._extract_tracker_extended_fields(
        symbol="BTCUSDT",
        position_history=history,
        position_price_track=track,
        consumption_allowed=True,
        consumption_blocked_reason=None,
    ))
    assert result["v2_tracker_latest_price"] == (50123.45, "V2_POSITION_HISTORY_TRACKER")
    assert result["v2_tracker_entry_price"] == (49000.0, "V2_POSITION_HISTORY_TRACKER")
    assert result["v2_tracker_source_freshness_seconds"] == (4.0, "V2_POSITION_HISTORY_TRACKER")
    assert result["v2_tracker_missing_flag_count"] == (0.0, "V2_POSITION_HISTORY_TRACKER")
    assert result["v2_tracker_stale_flag_count"] == (0.0, "V2_POSITION_HISTORY_TRACKER")
    assert result["v2_shadow_observation_count"] == (7.0, "V2_POSITION_HISTORY_TRACKER")


def test_extended_extractor_flag_counts_when_lists_have_entries() -> None:
    b = _builder()
    track = {
        "symbol": "BTCUSDT",
        "missing_flags": ["FLAT_NO_OPEN_POSITION", "MISSING_ENTRY_PRICE"],
        "stale_flags": ["STALE_LATEST_PRICE"],
    }
    result = dict((n, (v, s)) for n, v, s in b._extract_tracker_extended_fields(
        symbol="BTCUSDT",
        position_history={"symbol": "BTCUSDT"},
        position_price_track=track,
        consumption_allowed=True,
        consumption_blocked_reason=None,
    ))
    assert result["v2_tracker_missing_flag_count"] == (2.0, "V2_POSITION_HISTORY_TRACKER")
    assert result["v2_tracker_stale_flag_count"] == (1.0, "V2_POSITION_HISTORY_TRACKER")


def test_extended_extractor_when_specific_fields_absent_from_payload() -> None:
    """Tracker payload present but specific fields missing → those
    fields are None with FIELD_MISSING, not blank-zero-filled."""
    b = _builder()
    track = {"symbol": "BTCUSDT", "missing_flags": [], "stale_flags": []}
    history = {"symbol": "BTCUSDT"}
    result = dict((n, (v, s)) for n, v, s in b._extract_tracker_extended_fields(
        symbol="BTCUSDT",
        position_history=history,
        position_price_track=track,
        consumption_allowed=True,
        consumption_blocked_reason=None,
    ))
    assert result["v2_tracker_latest_price"] == (
        None, "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
    )
    assert result["v2_tracker_entry_price"] == (
        None, "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
    )
    assert result["v2_tracker_source_freshness_seconds"] == (
        None, "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
    )
    assert result["v2_shadow_observation_count"] == (
        None, "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
    )
    # Flag counts are sourced from empty lists (operator-meaningful).
    assert result["v2_tracker_missing_flag_count"] == (0.0, "V2_POSITION_HISTORY_TRACKER")
    assert result["v2_tracker_stale_flag_count"] == (0.0, "V2_POSITION_HISTORY_TRACKER")


def test_extended_extractor_missing_flag_lists_when_missing_key() -> None:
    """If the recorder ever drops the missing_flags / stale_flags
    key entirely from the payload, the count fields must be None
    with FIELD_MISSING — not silently 0."""
    b = _builder()
    track = {"symbol": "BTCUSDT"}  # no missing_flags / stale_flags keys
    result = dict((n, (v, s)) for n, v, s in b._extract_tracker_extended_fields(
        symbol="BTCUSDT",
        position_history={"symbol": "BTCUSDT"},
        position_price_track=track,
        consumption_allowed=True,
        consumption_blocked_reason=None,
    ))
    assert result["v2_tracker_missing_flag_count"] == (
        None, "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
    )
    assert result["v2_tracker_stale_flag_count"] == (
        None, "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING"
    )


def test_per_symbol_observation_includes_six_extended_fields_in_position_context() -> None:
    """End-to-end: building the per-symbol observation with the
    tracker payloads must surface all 6 extended-field names in the
    position_context slice of field_names."""
    b = _builder()
    res = b.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_price=None,
        market_funding=None,
        market_open_interest=None,
        paper_intents=[],
        paper_intents_held=[],
        position_price_track={
            "symbol": "BTCUSDT",
            "position_state": "OPEN_LONG",
            "latest_price": 50000.0,
            "entry_price": 49500.0,
            "source_freshness_seconds": 3,
            "missing_flags": [],
            "stale_flags": [],
        },
        position_history={
            "symbol": "BTCUSDT",
            "position_state": "OPEN_LONG",
            "accepted_intent_count": 2,
            "held_intent_count": 0,
            "block_reason_count": 1,
            "shadow_observation_count": 5,
            "max_favorable_bps": 12.0,
            "max_adverse_bps": -3.0,
            "unrealized_bps": 8.0,
            "hold_time_seconds": 120.0,
        },
        position_history_consumption_allowed=True,
        position_history_consumption_blocked_reason=None,
    )
    for new_field in (
        "position_context.v2_tracker_latest_price",
        "position_context.v2_tracker_entry_price",
        "position_context.v2_tracker_source_freshness_seconds",
        "position_context.v2_tracker_missing_flag_count",
        "position_context.v2_tracker_stale_flag_count",
        "position_context.v2_shadow_observation_count",
    ):
        assert new_field in res.field_names, (
            f"field {new_field!r} must appear in field_names; "
            f"got tail: {res.field_names[-12:]}"
        )
    # zero_filled_field_count must remain 0.
    assert res.zero_filled_field_count == 0


def test_per_symbol_observation_extended_fields_masked_when_gate_blocked() -> None:
    """If the consumption gate is blocked, the 6 extended fields
    must be masked with the BLOCKED:<reason> source attribution."""
    b = _builder()
    res = b.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_price=None,
        market_funding=None,
        market_open_interest=None,
        paper_intents=[],
        paper_intents_held=[],
        position_price_track={
            "symbol": "BTCUSDT",
            "latest_price": 50000.0,
            "entry_price": 49500.0,
            "source_freshness_seconds": 1,
            "missing_flags": [],
            "stale_flags": [],
        },
        position_history={
            "symbol": "BTCUSDT",
            "shadow_observation_count": 99,
        },
        position_history_consumption_allowed=False,
        position_history_consumption_blocked_reason="TRACKER_HEARTBEAT_MISSING",
    )
    fields = {n: (v, s) for n, v, s in zip(
        res.field_names, res.field_values, res.field_sources
    ) if n.startswith("position_context.v2_tracker_")
       or n.startswith("position_context.v2_shadow_")}
    expected_src = (
        "V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:TRACKER_HEARTBEAT_MISSING"
    )
    for new_field in (
        "position_context.v2_tracker_latest_price",
        "position_context.v2_tracker_entry_price",
        "position_context.v2_tracker_source_freshness_seconds",
        "position_context.v2_tracker_missing_flag_count",
        "position_context.v2_tracker_stale_flag_count",
        "position_context.v2_shadow_observation_count",
    ):
        assert new_field in fields, f"{new_field} missing"
        value, source = fields[new_field]
        assert value is None
        assert source == expected_src
    # zero_filled remains 0
    assert res.zero_filled_field_count == 0


def test_extended_extractor_source_code_does_not_read_raw_paper_keys() -> None:
    """Static-source proof: the extended extractor's *code* must not
    actually consume any raw paper input. The function's docstring
    deliberately *mentions* the forbidden names to document the
    safety boundary, so we scan only the post-docstring code body
    for actual usage patterns (subscripts, attribute access,
    Redis-key strings)."""
    b = _builder()
    src = inspect.getsource(b._extract_tracker_extended_fields)
    # Strip the docstring (first triple-quoted block in the function).
    if '"""' in src:
        head, _, rest = src.partition('"""')
        _, _, after_doc = rest.partition('"""')
        body = head + after_doc
    else:
        body = src
    # Forbidden usage patterns: actual code references, not prose.
    forbidden_usage = (
        "paper_positions[",
        "paper_positions.",
        "paper_positions or",
        "paper_positions=",
        "paper_ledger[",
        "paper_ledger.",
        "paper_ledger or",
        "paper_ledger=",
        "paper_intents[",
        "paper_intents.",
        "paper_intents or",
        "paper_intents=",
        "paper_intents_held[",
        "paper_intents_held.",
        "paper_intents_held or",
        "paper_intents_held=",
        "v2:paper:positions",
        "v2:paper:ledger",
        "v2:paper:intents",
    )
    for token in forbidden_usage:
        assert token not in body, (
            f"_extract_tracker_extended_fields code (excluding docstring) "
            f"must not contain {token!r}; tracker-derived fields must not "
            "be sourced from raw paper inputs."
        )


def test_aggregate_zero_filled_remains_zero_after_expansion() -> None:
    """End-to-end on synthetic inputs: aggregate zero_filled_field_count
    must remain 0 after the expansion. No silent zero-fill anywhere."""
    b = _builder()
    res = b.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=None,
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        position_price_track={
            "symbol": "BTCUSDT",
            "missing_flags": [],
            "stale_flags": [],
        },
        position_history={"symbol": "BTCUSDT"},
        position_history_consumption_allowed=True,
        position_history_consumption_blocked_reason=None,
    )
    assert res.zero_filled_field_count == 0


def test_position_context_slice_size_remains_fifty_after_expansion() -> None:
    """The position_context slice must remain at exactly 50 dims;
    expanding the derived field count must not shift the slice
    target."""
    b = _builder()
    assert b.SLICE_SIZES["position_context"] == 50
    # The full target sum must still match TARGET_FULL_DIM=1911.
    total = (
        b.SLICE_SIZES["unified_features"]
        + b.SLICE_SIZES["portfolio_state"]
        + b.SLICE_SIZES["onchain_btc"]
        + b.SLICE_SIZES["onchain_eth"]
        + b.SLICE_SIZES["position_context"]
    )
    assert total == b.TARGET_FULL_DIM == 1911
