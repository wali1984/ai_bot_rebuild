from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
    CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
    CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
    CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
    CAUSAL_COST_ORDERED_FEATURE_NAMES,
    CausalCostEvidenceV1IntegrityError,
    CausalCostEvidenceV1ValidationError,
    build_causal_cost_evidence_v1,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.orderbook_recorder import features as orderbook_features

_SYMBOL = "BTCUSDT"
_SNAPSHOT_IDENTITY = "profiled-feature-snapshot-fixture-v1"
_DECISION_TIME = "2026-07-21T12:00:01.000000Z"
_SERVER_TIME = datetime(2026, 7, 21, 12, 0, 0, 500_000, tzinfo=UTC)
_RAW_FEE_RESPONSE = (
    b'{"symbol":"BTCUSDT","makerCommissionRate":"0.00020000",'
    b'"takerCommissionRate":"0.00040000","rpiCommissionRate":"0.00010000"}'
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _self_hash(value: dict[str, Any]) -> dict[str, Any]:
    return {**value, "receipt_sha256": _sha256(value)}


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


class _Pipeline:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        pttl_ms: int,
        server_time: datetime,
    ) -> None:
        self.payloads = payloads
        self.pttl_ms = pttl_ms
        self.server_time = server_time
        self.commands: list[tuple[str, str | None]] = []

    def type(self, key: str) -> _Pipeline:
        self.commands.append(("type", key))
        return self

    def getrange(self, key: str, _start: int, _end: int) -> _Pipeline:
        self.commands.append(("getrange", key))
        return self

    def pttl(self, key: str) -> _Pipeline:
        self.commands.append(("pttl", key))
        return self

    def time(self) -> _Pipeline:
        self.commands.append(("time", None))
        return self

    def execute(self) -> list[object]:
        out: list[object] = []
        for command, key in self.commands:
            if command == "type":
                out.append(b"string" if key in self.payloads else b"none")
            elif command == "getrange":
                out.append(self.payloads.get(str(key), b""))
            elif command == "pttl":
                out.append(self.pttl_ms if key in self.payloads else -2)
            else:
                seconds = int(self.server_time.timestamp())
                out.append((seconds, self.server_time.microsecond))
        return out

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Redis:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        pttl_ms: int = 60_000,
        server_time: datetime = _SERVER_TIME,
    ) -> None:
        self.payloads = payloads
        self.pttl_ms = pttl_ms
        self.server_time = server_time

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        assert transaction is True
        return _Pipeline(
            self.payloads,
            pttl_ms=self.pttl_ms,
            server_time=self.server_time,
        )


def _market_payloads(
    monkeypatch: pytest.MonkeyPatch,
    *,
    funding_rate: float = 0.0001,
    next_funding_time_ms: int = 1_784_635_801_000,
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
            [100.00, 50.0],
            [99.90, 50.0],
            [99.80, 50.0],
            [99.70, 50.0],
            [99.60, 50.0],
        ],
        asks=[
            [100.10, 50.0],
            [100.20, 50.0],
            [100.30, 50.0],
            [100.40, 50.0],
            [100.50, 50.0],
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
        "last_funding_rate": funding_rate,
        "next_funding_time_ms": next_funding_time_ms,
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


def _atomic_capture(
    payloads: dict[str, dict[str, Any]],
    *,
    pttl_ms: int = 60_000,
    feature_key: str | None = None,
):
    depth_key = f"v2:orderbook:depth:binance:{_SYMBOL}"
    features_key = feature_key or f"v2:orderbook:features:binance:{_SYMBOL}"
    mark_key = f"v2:market:mark_price:{_SYMBOL}"
    exact = {
        depth_key: _canonical_bytes(payloads["depth"]),
        features_key: _canonical_bytes(payloads["features"]),
        mark_key: _canonical_bytes(payloads["mark"]),
    }
    return read_atomic_redis_sources(
        _Redis(exact, pttl_ms=pttl_ms),
        (depth_key, features_key, mark_key),
    )


def _fee_inputs(
    store: ImmutableSourcePayloadStore,
    *,
    fee_bps: float = 4.0,
    effective_at: str = "2026-07-21T11:59:59.900000Z",
    available_at: str = "2026-07-21T11:59:59.900000Z",
    raw_response: bytes = _RAW_FEE_RESPONSE,
    artifact_rpi_rate_decimal: str | None = None,
) -> tuple[bytes, bytes, dict[str, Any]]:
    raw_address = store.put(raw_response)
    raw_sha = hashlib.sha256(raw_response).hexdigest()
    decoded_response = json.loads(raw_response)
    source_rpi_rate = decoded_response.get("rpiCommissionRate")
    bound_rpi_rate = artifact_rpi_rate_decimal or source_rpi_rate or "0.00010000"
    bound_rpi_bps = float(bound_rpi_rate) * 10_000.0
    artifact = {
        "schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "capture_classification": (
            "STRUCTURALLY_VALIDATED_DETACHED_SIGNED_COMMISSION_RESPONSE_UNWIRED"
        ),
        "venue": "BINANCE",
        "market": "USD_M_PERPETUAL",
        "symbol": _SYMBOL,
        "liquidity_role": "TAKER",
        "fee_semantics": "PER_SIDE_EXECUTION_FEE_NOT_ROUND_TRIP",
        "fee_unit": "BASIS_POINTS",
        "taker_fee_bps_per_side": fee_bps,
        "effective_at": effective_at,
        "available_at": available_at,
        "expires_at": "2026-07-21T13:00:00.000000Z",
        "source_key": f"v2:account:fee_schedule:{_SYMBOL}",
        "authority_scope": "BINANCE_USDM_ACCOUNT_COMMISSION_RATE",
        "source_revision": raw_sha,
        "raw_response_sha256": raw_sha,
        "raw_response_byte_count": len(raw_response),
        "raw_response_cas_address": _address_mapping(raw_address),
        "sanitized_request_identity_sha256": "1" * 64,
        "credential_binding_fingerprint_sha256": "2" * 64,
        "http_status": 200,
        "request_method": "GET",
        "request_path": "/fapi/v1/commissionRate",
        "response_observed_at": "2026-07-21T11:59:59.800000Z",
        "rpi_commission_rate_decimal": bound_rpi_rate,
        "rpi_commission_bps": bound_rpi_bps,
    }
    artifact_bytes = _canonical_bytes(artifact)
    receipt = _self_hash(
        {
            "schema_version": CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
            "receipt_kind": "DIRECT_READ",
            "artifact_payload_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "artifact_payload_byte_count": len(artifact_bytes),
            "source_key": artifact["source_key"],
            "source_schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
            "source_transport": "DETACHED_SIGNED_BINANCE_USDM_COMMISSION_RESPONSE_UNWIRED",
            "symbol": _SYMBOL,
            "effective_at": effective_at,
            "available_at": available_at,
            "expires_at": artifact["expires_at"],
            "authority_scope": artifact["authority_scope"],
            "capture_classification": artifact["capture_classification"],
            "raw_response_sha256": raw_sha,
            "raw_response_byte_count": len(raw_response),
            "raw_response_cas_address": _address_mapping(raw_address),
            "sanitized_request_identity_sha256": artifact[
                "sanitized_request_identity_sha256"
            ],
            "credential_binding_fingerprint_sha256": artifact[
                "credential_binding_fingerprint_sha256"
            ],
            "http_status": 200,
            "request_method": "GET",
            "request_path": "/fapi/v1/commissionRate",
            "response_observed_at": artifact["response_observed_at"],
            "rpi_commission_rate_decimal": bound_rpi_rate,
            "rpi_commission_bps": bound_rpi_bps,
        }
    )
    return artifact_bytes, raw_response, receipt


def _notional_inputs(
    *,
    notional: float = 1_000.0,
    receipt_source_key: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    artifact = {
        "schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
        "symbol": _SYMBOL,
        "feature_snapshot_identity": _SNAPSHOT_IDENTITY,
        "value_unit": "USD",
        "expected_notional_usd": notional,
        "policy_id": "adaptive-notional-policy-v1",
        "policy_version": "sha256:" + "3" * 64,
        "policy_source_key": "v2:allocator:expected_notional:BTCUSDT",
        "effective_at": "2026-07-21T11:59:59.700000Z",
        "available_at": "2026-07-21T11:59:59.800000Z",
        "expires_at": "2026-07-21T12:01:00.000000Z",
        "causality_scope": "FEATURE_SNAPSHOT_DECISION_EXPECTED_EXECUTION_NOTIONAL",
        "fallback_used": False,
        "static_default_used": False,
    }
    artifact_bytes = _canonical_bytes(artifact)
    receipt = _self_hash(
        {
            "schema_version": CAUSAL_COST_NOTIONAL_RECEIPT_V1_SCHEMA_VERSION,
            "receipt_kind": "DIRECT_READ",
            "artifact_payload_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "artifact_payload_byte_count": len(artifact_bytes),
            "policy_source_key": receipt_source_key or artifact["policy_source_key"],
            "source_schema_version": CAUSAL_COST_NOTIONAL_ARTIFACT_V1_SCHEMA_VERSION,
            "source_transport": "DURABLE_CAUSAL_POLICY_LEDGER",
            "symbol": _SYMBOL,
            "feature_snapshot_identity": _SNAPSHOT_IDENTITY,
            "effective_at": artifact["effective_at"],
            "available_at": artifact["available_at"],
            "expires_at": artifact["expires_at"],
            "authority_scope": "FEATURE_SNAPSHOT_CAUSAL_EXPECTED_NOTIONAL",
        }
    )
    return artifact_bytes, receipt


def _inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    payloads: dict[str, dict[str, Any]] | None = None,
    pttl_ms: int = 60_000,
    fee_bps: float = 4.0,
    notional_artifact_value: float = 1_000.0,
) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    store = ImmutableSourcePayloadStore(tmp_path / "cas")
    market = payloads or _market_payloads(monkeypatch)
    fee_artifact, fee_raw, fee_receipt = _fee_inputs(store, fee_bps=fee_bps)
    notional_artifact, notional_receipt = _notional_inputs(
        notional=notional_artifact_value
    )
    return {
        "atomic_capture": _atomic_capture(market, pttl_ms=pttl_ms),
        "source_payload_store": store,
        "fee_schedule_artifact_bytes": fee_artifact,
        "fee_schedule_raw_response_bytes": fee_raw,
        "fee_schedule_receipt": fee_receipt,
        "expected_notional_usd": 1_000.0,
        "expected_notional_policy_artifact_bytes": notional_artifact,
        "expected_notional_policy_receipt": notional_receipt,
        "symbol": _SYMBOL,
        "feature_snapshot_identity": _SNAPSHOT_IDENTITY,
        "decision_time": _DECISION_TIME,
        "counterfactual_holding_horizon_seconds": 900,
    }


def test_builds_four_exact_receipts_without_downstream_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))

    contract = result.contract
    assert contract["ordered_feature_names"] == list(CAUSAL_COST_ORDERED_FEATURE_NAMES)
    assert result.ordered_values[0] == pytest.approx(4.0)
    assert result.ordered_values[1] > 0.0
    assert result.ordered_values[2] > 0.0
    assert result.ordered_values[3] == pytest.approx(1.0)
    assert contract["fee_source"]["rpi_commission_rate_decimal"] == "0.00010000"
    assert contract["fee_source"]["rpi_commission_bps"] == pytest.approx(1.0)
    assert contract["fee_source"]["rpi_rate_used_for_cost_scalar"] is False
    assert [receipt["receipt_kind"] for receipt in result.ordered_receipts] == [
        "COMPOSITE_DERIVATION"
    ] * 4
    assert all(
        receipt["feature_role"] == "LABEL_ONLY_AUXILIARY_NOT_MODEL_INPUT"
        for receipt in result.ordered_receipts
    )
    assert contract["authorization"] == {
        "feature_snapshot_published": False,
        "live_execution_authorized": False,
        "paper_execution_authorized": False,
        "prediction_authorized": False,
        "profiled_39_record_built": False,
        "trainer_admission_authorized": False,
    }
    assert contract["optional_provider_dependencies"] == []


def test_rejects_caller_spread_and_impact_scalar_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _market_payloads(monkeypatch)
    payloads["features"]["spread_bps"] += 0.25
    with pytest.raises(
        CausalCostEvidenceV1ValidationError,
        match="FEATURE_SPREAD_BPS_SUBSTITUTION",
    ):
        build_causal_cost_evidence_v1(
            **_inputs(tmp_path / "spread", monkeypatch, payloads=payloads)
        )

    payloads = _market_payloads(monkeypatch)
    payloads["features"]["estimated_price_impact_bps"] += 0.25
    with pytest.raises(
        CausalCostEvidenceV1ValidationError,
        match="FEATURE_IMPACT_SUBSTITUTION",
    ):
        build_causal_cost_evidence_v1(
            **_inputs(tmp_path / "impact", monkeypatch, payloads=payloads)
        )


def test_rejects_source_key_sequence_and_expiry_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _inputs(tmp_path / "key", monkeypatch)
    payloads = _market_payloads(monkeypatch)
    values["atomic_capture"] = _atomic_capture(
        payloads,
        feature_key=f"v2:orderbook:features:kucoin:{_SYMBOL}",
    )
    with pytest.raises(CausalCostEvidenceV1IntegrityError, match="SOURCE_KEY"):
        build_causal_cost_evidence_v1(**values)

    payloads = _market_payloads(monkeypatch)
    payloads["depth"]["sequence_gap"] = True
    payloads["depth"]["sequence_gap_flag"] = 1
    payloads["features"]["sequence_gap"] = True
    payloads["features"]["sequence_gap_flag"] = 1
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="SEQUENCE_GAP"):
        build_causal_cost_evidence_v1(
            **_inputs(tmp_path / "gap", monkeypatch, payloads=payloads)
        )

    with pytest.raises(CausalCostEvidenceV1ValidationError, match="PERSISTED_EXPIRY"):
        build_causal_cost_evidence_v1(
            **_inputs(tmp_path / "expiry", monkeypatch, pttl_ms=0)
        )


def test_rejects_fee_value_clock_and_response_binding_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="FEE_CALLER_SCALAR"):
        build_causal_cost_evidence_v1(
            **_inputs(tmp_path / "fee", monkeypatch, fee_bps=5.0)
        )

    values = _inputs(tmp_path / "clock", monkeypatch)
    store = values["source_payload_store"]
    artifact, raw, receipt = _fee_inputs(
        store,
        effective_at="2026-07-21T11:59:59.700000Z",
        available_at="2026-07-21T11:59:59.900000Z",
    )
    values.update(
        fee_schedule_artifact_bytes=artifact,
        fee_schedule_raw_response_bytes=raw,
        fee_schedule_receipt=receipt,
    )
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="FEE_CLOCK"):
        build_causal_cost_evidence_v1(**values)

    values = _inputs(tmp_path / "response", monkeypatch)
    values["fee_schedule_raw_response_bytes"] = _RAW_FEE_RESPONSE.replace(
        b"0.00040000", b"0.00050000"
    )
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="RAW_RESPONSE_BINDING"):
        build_causal_cost_evidence_v1(**values)


def test_requires_and_binds_official_rpi_commission_rate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _inputs(tmp_path / "missing", monkeypatch)
    store = values["source_payload_store"]
    missing_rpi = (
        b'{"symbol":"BTCUSDT","makerCommissionRate":"0.00020000",'
        b'"takerCommissionRate":"0.00040000"}'
    )
    artifact, raw, receipt = _fee_inputs(store, raw_response=missing_rpi)
    values.update(
        fee_schedule_artifact_bytes=artifact,
        fee_schedule_raw_response_bytes=raw,
        fee_schedule_receipt=receipt,
    )
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="RAW_RESPONSE_FIELDS"):
        build_causal_cost_evidence_v1(**values)

    values = _inputs(tmp_path / "tampered", monkeypatch)
    store = values["source_payload_store"]
    artifact, raw, receipt = _fee_inputs(
        store,
        artifact_rpi_rate_decimal="0.00030000",
    )
    values.update(
        fee_schedule_artifact_bytes=artifact,
        fee_schedule_raw_response_bytes=raw,
        fee_schedule_receipt=receipt,
    )
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="RPI_RATE_SUBSTITUTION"):
        build_causal_cost_evidence_v1(**values)


def test_rejects_notional_value_and_receipt_source_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="NOTIONAL_CALLER_VALUE"):
        build_causal_cost_evidence_v1(
            **_inputs(
                tmp_path / "value",
                monkeypatch,
                notional_artifact_value=1_001.0,
            )
        )

    values = _inputs(tmp_path / "receipt", monkeypatch)
    artifact, receipt = _notional_inputs(receipt_source_key="v2:forged:notional")
    values.update(
        expected_notional_policy_artifact_bytes=artifact,
        expected_notional_policy_receipt=receipt,
    )
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="RECEIPT_ARTIFACT"):
        build_causal_cost_evidence_v1(**values)


def test_funding_sign_and_settlement_window_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    negative = _market_payloads(monkeypatch, funding_rate=-0.00015)
    result = build_causal_cost_evidence_v1(
        **_inputs(tmp_path / "negative", monkeypatch, payloads=negative)
    )
    assert result.ordered_values[3] == pytest.approx(-1.5)
    assert (
        result.contract["funding_settlement_contract"]["sign_semantics"]
        == "VENUE_RATE_SIGN_PRESERVED_NOT_POSITION_PNL_SIGN"
    )

    outside = _market_payloads(
        monkeypatch,
        funding_rate=0.00015,
        next_funding_time_ms=1_784_636_200_000,
    )
    result = build_causal_cost_evidence_v1(
        **_inputs(tmp_path / "outside", monkeypatch, payloads=outside)
    )
    assert result.ordered_values[3] == 0.0
    assert (
        result.contract["funding_settlement_contract"]["zero_semantics"]
        == "NEXT_SETTLEMENT_PROVEN_OUTSIDE_PINNED_HORIZON"
    )


@pytest.mark.parametrize("next_funding", [None, 1_784_635_200_000])
def test_rejects_missing_or_nonprospective_funding_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    next_funding: int | None,
) -> None:
    payloads = _market_payloads(monkeypatch)
    payloads["mark"]["next_funding_time_ms"] = next_funding
    with pytest.raises(
        CausalCostEvidenceV1ValidationError,
        match="FUNDING_NEXT_SETTLEMENT",
    ):
        build_causal_cost_evidence_v1(
            **_inputs(tmp_path / str(next_funding), monkeypatch, payloads=payloads)
        )


def test_rejects_future_mark_clock_and_non_pinned_horizon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _market_payloads(monkeypatch)
    payloads["mark"]["available_at"] = "2026-07-21T12:00:02.000Z"
    payloads["mark"]["generated_at"] = "2026-07-21T12:00:02.000Z"
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="CLOCK_ORDER"):
        build_causal_cost_evidence_v1(
            **_inputs(tmp_path / "future", monkeypatch, payloads=payloads)
        )

    values = _inputs(tmp_path / "horizon", monkeypatch)
    values["counterfactual_holding_horizon_seconds"] = 901
    with pytest.raises(CausalCostEvidenceV1ValidationError, match="PINNED_900"):
        build_causal_cost_evidence_v1(**values)


def test_fresh_property_readback_detects_cas_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))
    address, payload = result._exact_objects[0]  # noqa: SLF001 - adversarial integrity test
    path = result._store.root_path / address.relative_path  # noqa: SLF001
    os.chmod(path, 0o600)
    path.write_bytes(b"x" * len(payload))

    with pytest.raises(CausalCostEvidenceV1IntegrityError, match="CAS_READBACK"):
        _ = result.contract


def test_result_scalar_substitution_cannot_validate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = build_causal_cost_evidence_v1(**_inputs(tmp_path, monkeypatch))
    forged = replace(
        result,
        ordered_values=(result.ordered_values[0] + 1.0, *result.ordered_values[1:]),
    )
    with pytest.raises(CausalCostEvidenceV1IntegrityError, match="CONTRACT_BINDING"):
        _ = forged.contract
