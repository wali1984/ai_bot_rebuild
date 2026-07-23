from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import causal_cost_evidence_v1
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.causal_adaptive_cold_start_notional_policy_v1 import (
    CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID,
    CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY,
    CausalAdaptiveColdStartNotionalPolicyV1Error,
    CausalAdaptiveColdStartNotionalPolicyV1IntegrityError,
    CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
    build_causal_adaptive_cold_start_notional_policy_v1,
    causal_adaptive_cold_start_notional_policy_source_key_v1,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.orderbook_recorder import features as orderbook_features
from v2.backend.tests.unit.services.native_trainer import (
    test_causal_cost_evidence_v1 as cost_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_causal_expected_notional_policy_v1 as notional_support,
)

_SYMBOL = "BTCUSDT"
_SNAPSHOT = "profiled-feature-snapshot:BTCUSDT:2026-07-21T12:00:00Z"
_PORTFOLIO_SERVER_AT = datetime(2026, 7, 21, 12, 0, 0, 400_000, tzinfo=UTC)
_MARKET_SERVER_AT = datetime(2026, 7, 21, 12, 0, 0, 500_000, tzinfo=UTC)
_DECISION_AT = datetime(2026, 7, 21, 12, 0, 1, tzinfo=UTC)
_PAPER_CYCLE_ID = "paper_cycle:" + "a" * 64


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


class _Pipeline:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        pttl_ms: int,
        server_time: datetime,
    ) -> None:
        self._payloads = payloads
        self._pttl_ms = pttl_ms
        self._server_time = server_time
        self._commands: list[tuple[str, str | None]] = []

    def type(self, key: str) -> _Pipeline:
        self._commands.append(("type", key))
        return self

    def getrange(self, key: str, _start: int, _end: int) -> _Pipeline:
        self._commands.append(("getrange", key))
        return self

    def pttl(self, key: str) -> _Pipeline:
        self._commands.append(("pttl", key))
        return self

    def time(self) -> _Pipeline:
        self._commands.append(("time", None))
        return self

    def execute(self) -> list[object]:
        output: list[object] = []
        for command, key in self._commands:
            if command == "type":
                output.append(b"string" if key in self._payloads else b"none")
            elif command == "getrange":
                output.append(self._payloads.get(str(key), b""))
            elif command == "pttl":
                output.append(self._pttl_ms if key in self._payloads else -2)
            else:
                output.append(
                    (int(self._server_time.timestamp()), self._server_time.microsecond)
                )
        return output

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Redis:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        pttl_ms: int,
        server_time: datetime,
    ) -> None:
        self._payloads = payloads
        self._pttl_ms = pttl_ms
        self._server_time = server_time

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        assert transaction is True
        return _Pipeline(
            self._payloads,
            pttl_ms=self._pttl_ms,
            server_time=self._server_time,
        )


def _portfolio_payload(*, free_after_buffer: float = 4_000.0) -> dict[str, Any]:
    free_margin = free_after_buffer + 1_000.0
    used_margin = 10_000.0 - free_margin
    return {
        "schema_version": "paper_account_margin_v1",
        "generated_utc": "2026-07-21T12:00:00.200Z",
        "paper_cycle_id": _PAPER_CYCLE_ID,
        "status": "PASS",
        "source": "POST_LIFECYCLE_CANONICAL_OPEN_POSITIONS",
        "accounting_complete": True,
        "control_inputs_valid": True,
        "admission_inputs_valid": True,
        "margin_buffer_input_valid": True,
        "newly_reserved_margin_input_valid": True,
        "reservations_included_in_open_positions_input_valid": True,
        "margin_buffer_invariant_holds": True,
        "no_negative_free_margin": True,
        "invariant": True,
        "invariant_holds": True,
        "numeric_invariant_holds": True,
        "margin_base_available": True,
        "used_margin_aggregation_valid": True,
        "projected_used_margin_aggregation_valid": True,
        "open_position_collection_complete": True,
        "open_position_canonical_identities_unique": True,
        "newly_reserved_included_in_used_margin": True,
        "pre_lifecycle_reservation_invariant_holds": True,
        "cycle_reserved_candidate_count": 0,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "failure_reasons": [],
        "invalid_open_position_margin_rows": [],
        "invalid_open_position_margin_count": 0,
        "duplicate_open_position_identity_group_count": 0,
        "duplicate_open_position_identity_row_count": 0,
        "open_position_collection_iteration_invalid_reason": None,
        "newly_reserved_margin_usd": 0.0,
        "newly_reserved_margin_unrounded_usd": 0.0,
        "margin_base_usd": 10_000.0,
        "used_margin_usd": used_margin,
        "free_margin_usd": free_margin,
        "margin_buffer_usd": 1_000.0,
        "free_margin_after_buffer_usd": free_after_buffer,
        "usable_margin_after_buffer_before_reservations_usd": free_after_buffer,
    }


def _zero_candidate_payload() -> dict[str, Any]:
    status = notional_support._status(count=0, gross_notional_usd=0.0)
    status["generated_utc"] = "2026-07-21T12:00:00.200Z"
    status["paper_cycle_id"] = _PAPER_CYCLE_ID
    status["candidate_allocations"] = []
    contract = status["candidate_allocations_canonical_aggregate_contract"]
    contract["zero_liquidation"] = {
        "a_grade_candidate_count": 0,
        "all_a_grade_candidates_pass": False,
        "blocker_counts": {},
        "failed_a_grade_candidate_count": 0,
        "passed_a_grade_candidate_count": 0,
    }
    contract["hedge"] = {
        "active_hedge_candidate_count": 0,
        "all_active_hedge_candidates_pass": True,
        "blocker_counts": {},
        "failed_active_hedge_candidate_count": 0,
        "hedge_enabled_candidate_count": 0,
        "passed_active_hedge_candidate_count": 0,
        "positive_hedge_budget_candidate_count": 0,
    }
    contract["capital"] = {
        "a_grade_candidate_count": 0,
        "accepted_a_grade_candidate_count": 0,
        "account_context": {},
        "allocator_decision_counts": {},
        "allowed_before_non_executable_tier_block_count": 0,
        "candidate_count": 0,
        "classification_counts": {},
        "numeric_sums": {},
        "original_allocator_decision_counts": {},
        "paper_opportunity_tier_counts": {},
        "recommended_leverage_counts": {},
        "recommended_margin_mode_counts": {},
        "underfunded_a_grade_candidate_count": 0,
    }
    for field in (
        "A_grade_rows",
        "a_grade_rows",
        "accepted_allocation_count",
        "blocked_allocation_count",
        "candidate_allocations_projection_count",
        "hold_with_directional_expected_move_bps_count",
        "hold_zero_after_cost_with_directional_expected_move_bps_count",
        "missing_microstructure_trust_candidate_count",
        "near_A_grade_rows",
        "near_a_grade_rows",
        "non_executable_tier_publication_block_count",
        "rare_event_stress_complete_candidate_count",
        "rare_event_stress_partial_candidate_count",
        "sample_allocations_projection_count",
        "source_tier_a_grade_execution_rows",
        "source_tier_or_guardian_blocked_allocator_pass_rows",
        "unclassified_allocation_publication_block_count",
    ):
        status[field] = 0
    for field in (
        "allocator_decision_counts",
        "allocator_microstructure_block_reason_counts",
        "guardian_status_counts",
        "local_block_reason_counts",
        "microstructure_trust_status_counts",
        "paper_allocation_block_reason_counts",
        "paper_fill_block_reason_counts",
        "paper_opportunity_tier_counts",
        "paper_opportunity_tier_reason_counts",
        "selected_action_counts",
        "selected_action_expected_move_bps_sign_counts",
        "source_tier_counts",
        "strategy_router_block_reason_counts",
        "strategy_router_selected_mode_counts",
    ):
        status[field] = {}
    status["sample_allocations"] = []
    notional_support._rehash_contract(status)
    return status


def _control_capture(
    zero_candidate_payload: dict[str, Any],
    margin_payload: dict[str, Any],
    *,
    pttl_ms: int = 60_000,
    server_at: datetime = _PORTFOLIO_SERVER_AT,
):
    zero_key = notional_support.CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY
    margin_key = CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY
    return read_atomic_redis_sources(
        _Redis(
            {
                zero_key: _canonical_bytes(zero_candidate_payload),
                margin_key: _canonical_bytes(margin_payload),
            },
            pttl_ms=pttl_ms,
            server_time=server_at,
        ),
        [zero_key, margin_key],
    )


def _market_payloads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bid_quantity: float = 50.0,
    ask_quantity: float = 50.0,
) -> dict[str, dict[str, Any]]:
    monkeypatch.setattr(
        orderbook_features,
        "utc_now_iso",
        lambda: "2026-07-21T12:00:00.200Z",
    )
    orderbook = orderbook_features.build_orderbook_payloads(
        exchange="binance",
        symbol=_SYMBOL,
        bids=[
            [100.00, bid_quantity],
            [99.90, bid_quantity],
            [99.80, bid_quantity],
            [99.70, bid_quantity],
            [99.60, bid_quantity],
        ],
        asks=[
            [100.10, ask_quantity],
            [100.20, ask_quantity],
            [100.30, ask_quantity],
            [100.40, ask_quantity],
            [100.50, ask_quantity],
        ],
        event_time_ms=1_784_635_199_500,
        transaction_time_ms=1_784_635_199_500,
        received_at="2026-07-21T12:00:00.100Z",
        available_at="2026-07-21T12:00:00.100Z",
        sequence_id=701,
        previous_sequence_id=700,
        sequence_gap=False,
        update_type="diff_depth",
        feed_speed_ms=100,
        price_impact_notional_usd=1_000.0,
    )
    mark = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": _SYMBOL,
        "mark_price": 100.05,
        "markPrice": 100.05,
        "index_price": 100.04,
        "indexPrice": 100.04,
        "estimated_settle_price": None,
        "last_funding_rate": 0.0001,
        "next_funding_time_ms": 1_784_635_801_000,
        "event_time": "2026-07-21T12:00:00.000Z",
        "generated_at": "2026-07-21T12:00:00.100Z",
        "received_at": "2026-07-21T12:00:00.100Z",
        "available_at": "2026-07-21T12:00:00.100Z",
        "expected_update_interval_seconds": 1.0,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "transport": "websocket_primary",
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "raw_credentials_exposed": False,
    }
    return {
        "depth": orderbook["depth"],
        "features": orderbook["features"],
        "mark": mark,
    }


def _market_capture(
    payloads: dict[str, dict[str, Any]],
    *,
    pttl_ms: int = 60_000,
    server_at: datetime = _MARKET_SERVER_AT,
):
    keys = (
        f"v2:orderbook:depth:binance:{_SYMBOL}",
        f"v2:orderbook:features:binance:{_SYMBOL}",
        f"v2:market:mark_price:{_SYMBOL}",
    )
    exact = {
        keys[0]: _canonical_bytes(payloads["depth"]),
        keys[1]: _canonical_bytes(payloads["features"]),
        keys[2]: _canonical_bytes(payloads["mark"]),
    }
    return read_atomic_redis_sources(
        _Redis(exact, pttl_ms=pttl_ms, server_time=server_at),
        keys,
    )


def _build(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    free_after_buffer: float = 4_000.0,
    bid_quantity: float = 50.0,
    ask_quantity: float = 50.0,
    portfolio_payload: dict[str, Any] | None = None,
    market_payloads: dict[str, dict[str, Any]] | None = None,
    portfolio_pttl_ms: int = 60_000,
    market_pttl_ms: int = 60_000,
    portfolio_server_at: datetime = _PORTFOLIO_SERVER_AT,
    market_server_at: datetime = _MARKET_SERVER_AT,
    zero_candidate_payload: dict[str, Any] | None = None,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    resolved_portfolio = portfolio_payload or _portfolio_payload(
        free_after_buffer=free_after_buffer
    )
    resolved_market = market_payloads or _market_payloads(
        monkeypatch,
        bid_quantity=bid_quantity,
        ask_quantity=ask_quantity,
    )
    store = ImmutableSourcePayloadStore(tmp_path / "cas")
    token = build_causal_adaptive_cold_start_notional_policy_v1(
        control_atomic_capture=_control_capture(
            zero_candidate_payload or _zero_candidate_payload(),
            resolved_portfolio,
            pttl_ms=portfolio_pttl_ms,
            server_at=portfolio_server_at,
        ),
        market_atomic_capture=_market_capture(
            resolved_market,
            pttl_ms=market_pttl_ms,
            server_at=market_server_at,
        ),
        source_payload_store=store,
        symbol=_SYMBOL,
        feature_snapshot_identity=_SNAPSHOT,
        feature_snapshot_decision_time=_DECISION_AT,
    )
    return token, store, resolved_market


@pytest.mark.parametrize(
    ("free_after_buffer", "bid_quantity", "ask_quantity", "binding_source"),
    [
        (4_000.0, 50.0, 50.0, "capital"),
        (9_000.0, 8.0, 12.0, "bid"),
        (9_000.0, 12.0, 8.0, "ask"),
    ],
)
def test_adaptive_min_derivation_binds_capital_and_each_visible_book_side(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    free_after_buffer: float,
    bid_quantity: float,
    ask_quantity: float,
    binding_source: str,
) -> None:
    token, _store, market = _build(
        tmp_path,
        monkeypatch,
        free_after_buffer=free_after_buffer,
        bid_quantity=bid_quantity,
        ask_quantity=ask_quantity,
    )
    bid_total = sum(
        float(level["price"]) * float(level["quantity"])
        for level in market["depth"]["bids"]
    )
    ask_total = sum(
        float(level["price"]) * float(level["quantity"])
        for level in market["depth"]["asks"]
    )

    assert token.expected_notional_usd == min(
        free_after_buffer,
        bid_total,
        ask_total,
    )
    if binding_source == "capital":
        assert token.expected_notional_usd == free_after_buffer
    elif binding_source == "bid":
        assert token.expected_notional_usd == bid_total
    else:
        assert token.expected_notional_usd == ask_total


def test_artifact_receipts_bind_all_sources_and_grant_no_authority(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, store, _market = _build(tmp_path, monkeypatch)
    artifact = token.notional_artifact
    receipt = token.notional_receipt
    source_receipt = token.source_read_receipt

    assert artifact["policy_id"] == CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID
    assert artifact["policy_source_key"] == (
        causal_adaptive_cold_start_notional_policy_source_key_v1(_SYMBOL)
    )
    assert artifact["expected_notional_usd"] == token.expected_notional_usd
    assert artifact["fallback_used"] is False
    assert artifact["static_default_used"] is False
    assert receipt["artifact_payload_sha256"] == hashlib.sha256(
        token.notional_artifact_bytes
    ).hexdigest()
    assert receipt["artifact_payload_byte_count"] == len(
        token.notional_artifact_bytes
    )
    assert receipt["receipt_sha256"] == token.notional_receipt_sha256
    assert source_receipt["receipt_sha256"] == token.source_read_receipt_sha256
    assert len(source_receipt["source_bindings"]) == 5
    assert {row["role"] for row in source_receipt["source_bindings"]} == {
        "zero_candidate_status",
        "paper_account_margin_status",
        "orderbook_depth",
        "orderbook_features",
        "mark_price",
    }
    assert len(
        {row["atomic_batch_material_sha256"] for row in source_receipt["source_bindings"]}
    ) == 2
    assert source_receipt["candidate_rows_consumed"] == 0
    assert source_receipt["candidate_fabricated"] is False
    assert source_receipt["leverage_assumption"] is None
    for authority in (
        "trainer_authority",
        "prediction_authority",
        "paper_authority",
        "live_authority",
        "order_authority",
    ):
        assert token.contract[authority] is False
        assert source_receipt[authority] is False

    validated, validated_receipt, exact_objects = (
        causal_cost_evidence_v1._validate_notional_evidence(  # noqa: SLF001
            store=store,
            artifact_bytes=token.notional_artifact_bytes,
            receipt=token.notional_receipt,
            expected_notional_usd=token.expected_notional_usd,
            symbol=_SYMBOL,
            feature_snapshot_identity=_SNAPSHOT,
            decision_at=_DECISION_AT,
        )
    )
    assert validated["expected_notional_usd"] == token.expected_notional_usd
    assert validated_receipt["receipt_sha256"] == token.notional_receipt_sha256
    assert len(exact_objects) == 2

    fee_artifact, fee_raw, fee_receipt = cost_support._fee_inputs(store)
    result = causal_cost_evidence_v1.build_causal_cost_evidence_v1(
        atomic_capture=_market_capture(_market),
        source_payload_store=store,
        fee_schedule_artifact_bytes=fee_artifact,
        fee_schedule_raw_response_bytes=fee_raw,
        fee_schedule_receipt=fee_receipt,
        expected_notional_usd=token.expected_notional_usd,
        expected_notional_policy_artifact_bytes=token.notional_artifact_bytes,
        expected_notional_policy_receipt=token.notional_receipt,
        expected_notional_policy_source_receipt_bytes=(
            token.source_read_receipt_bytes
        ),
        expected_notional_policy_factory_token=token,
        symbol=_SYMBOL,
        feature_snapshot_identity=_SNAPSHOT,
        decision_time=_DECISION_AT.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        counterfactual_holding_horizon_seconds=900,
    )
    provenance = result.contract["notional_source"]["policy_provenance"]
    assert provenance["verification_status"] == (
        causal_cost_evidence_v1.CAUSAL_COST_NOTIONAL_PROVENANCE_VERIFIED_STATUS
    )
    assert provenance["bound_source_object_count"] == 5
    assert provenance["bound_source_payload_byte_count"] == sum(
        row["payload_byte_count"] for row in source_receipt["source_bindings"]
    )
    exact_hashes = [address.payload_sha256 for address, _ in result._exact_objects]
    assert len(exact_hashes) == len(set(exact_hashes))


def test_future_and_expired_captures_fail_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
        match="COLD_START_NOTIONAL_CONTROL_CAPTURE_AFTER_DECISION",
    ):
        _build(
            tmp_path / "future",
            monkeypatch,
            portfolio_server_at=datetime(2026, 7, 21, 12, 0, 2, tzinfo=UTC),
        )

    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1Error,
        match="EXPIRED_AT_DECISION",
    ):
        _build(
            tmp_path / "expired",
            monkeypatch,
            portfolio_pttl_ms=500,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source", "UNTRUSTED_MARGIN_SOURCE"),
        ("paper_only", False),
        ("routes_to_live", True),
        ("places_real_order", True),
        ("invariant_holds", False),
    ],
)
def test_untrusted_live_or_invalid_margin_contract_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    replacement: object,
) -> None:
    portfolio = _portfolio_payload()
    portfolio[field] = replacement

    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
        match="COLD_START_NOTIONAL_PORTFOLIO_MARGIN_CONTRACT_INVALID",
    ):
        _build(tmp_path, monkeypatch, portfolio_payload=portfolio)


def test_zero_candidate_status_authority_or_cycle_mismatch_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe = _zero_candidate_payload()
    unsafe["places_real_order"] = True
    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
        match="COLD_START_NOTIONAL_ZERO_CANDIDATE_STATUS_INVALID",
    ):
        _build(
            tmp_path / "unsafe",
            monkeypatch,
            zero_candidate_payload=unsafe,
        )


def test_rehashed_nested_positive_zero_candidate_fact_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe = _zero_candidate_payload()
    unsafe["candidate_allocations_canonical_aggregate_contract"]["capital"][
        "accepted_a_grade_candidate_count"
    ] = 1
    notional_support._rehash_contract(unsafe)

    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
        match="COLD_START_NOTIONAL_ZERO_CANDIDATE_CONTRACT_NOT_EXACT_ZERO",
    ):
        _build(
            tmp_path,
            monkeypatch,
            zero_candidate_payload=unsafe,
        )


def test_required_producer_cycle_id_is_exactly_bound_or_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle_id = _PAPER_CYCLE_ID
    zero_candidate = _zero_candidate_payload()
    zero_candidate["paper_cycle_id"] = cycle_id
    margin = _portfolio_payload()
    margin["paper_cycle_id"] = cycle_id

    token, _store, _market = _build(
        tmp_path / "matching",
        monkeypatch,
        zero_candidate_payload=zero_candidate,
        portfolio_payload=margin,
    )

    assert token.source_read_receipt["producer_cycle_id"] == cycle_id

    margin["paper_cycle_id"] = "paper_cycle:" + "b" * 64
    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
        match="COLD_START_NOTIONAL_CANDIDATE_MARGIN_CYCLE_ID_MISMATCH",
    ):
        _build(
            tmp_path / "mismatch",
            monkeypatch,
            zero_candidate_payload=zero_candidate,
            portfolio_payload=margin,
        )

    missing = _portfolio_payload()
    missing.pop("paper_cycle_id")
    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
        match="COLD_START_NOTIONAL_PRODUCER_CYCLE_ID_INVALID",
    ):
        _build(
            tmp_path / "missing",
            monkeypatch,
            zero_candidate_payload=zero_candidate,
            portfolio_payload=missing,
        )

    different_cycle = _zero_candidate_payload()
    different_cycle["generated_utc"] = "2026-07-21T12:00:00.100Z"
    with pytest.raises(
        CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
        match="COLD_START_NOTIONAL_CANDIDATE_MARGIN_CYCLE_MISMATCH",
    ):
        _build(
            tmp_path / "cycle",
            monkeypatch,
            zero_candidate_payload=different_cycle,
        )


def test_independent_eight_decimal_margin_rounding_remains_valid(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    margin = _portfolio_payload(free_after_buffer=185.68197857)
    margin.update(
        {
            "margin_base_usd": 579.98924775,
            "used_margin_usd": 294.30726917,
            "free_margin_usd": 285.68197857,
            "margin_buffer_usd": 100.0,
            "free_margin_after_buffer_usd": 185.68197857,
            "usable_margin_after_buffer_before_reservations_usd": 185.68197857,
        }
    )

    token, _store, _market = _build(
        tmp_path,
        monkeypatch,
        portfolio_payload=margin,
    )

    assert token.expected_notional_usd == 185.68197857


@pytest.mark.parametrize("defect", ["sequence_gap", "negative_quantity"])
def test_sequence_gap_or_malformed_orderbook_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    market = deepcopy(_market_payloads(monkeypatch))
    if defect == "sequence_gap":
        market["depth"]["sequence_gap"] = True
        market["features"]["sequence_gap"] = True
    else:
        market["depth"]["bids"][0]["quantity"] = -1.0

    with pytest.raises(CausalAdaptiveColdStartNotionalPolicyV1ValidationError):
        _build(tmp_path, monkeypatch, market_payloads=market)


def test_cas_bound_token_tamper_fails_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, _store, _market = _build(tmp_path, monkeypatch)
    object.__setattr__(token, "notional_artifact_bytes", b"{}")

    with pytest.raises(CausalAdaptiveColdStartNotionalPolicyV1IntegrityError):
        _ = token.contract
