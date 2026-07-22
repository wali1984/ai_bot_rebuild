from __future__ import annotations

import hashlib
import json
from collections import Counter, namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.cli import v2_profiled_base_feature_publisher as cli_module
from v2.backend.app.cli.v2_profiled_base_feature_publisher import (
    bounded_cycle_summary,
)
from v2.backend.app.services import (
    binance_usdm_commission_evidence_broker as commission_broker_module,
)
from v2.backend.app.services.binance_usdm_commission_evidence_broker import (
    CredentiallessCommissionEvidence,
)
from v2.backend.app.services.native_trainer import (
    binance_usdm_commission_capture_v1 as commission_capture_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_base_feature_publisher_v1 as publisher_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_ledger_loader_v1 as loader_module,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.binance_usdm_commission_capture_v1 import (
    BinanceUSDMCommissionCaptureV1ValidationError,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CanonicalOhlcvAtomicCaptureValidationError,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_multitimeframe_capture_set_v1 import (
    CanonicalOhlcvMultitimeframeCaptureSetV1Error,
    build_canonical_ohlcv_multitimeframe_capture_set_v1,
)
from v2.backend.app.services.native_trainer.causal_adaptive_cold_start_notional_policy_v1 import (
    CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID,
    CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY,
    CausalAdaptiveColdStartNotionalPolicyV1ValidationError,
    causal_adaptive_cold_start_notional_policy_source_key_v1,
)
from v2.backend.app.services.native_trainer.causal_cost_evidence_v1 import (
    CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
    CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
    CAUSAL_COST_NOTIONAL_PROVENANCE_VERIFIED_STATUS,
    CausalCostEvidenceV1ValidationError,
    build_causal_cost_evidence_v1,
)
from v2.backend.app.services.native_trainer.causal_expected_notional_policy_v1 import (
    CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
    CausalExpectedNotionalPolicyV1ValidationError,
    build_causal_expected_notional_policy_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.native_trainer.profiled_base_feature_publisher_v1 import (
    AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE,
    BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL,
    BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE,
    DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS,
    DISK_RESERVE_POLICY_V1,
    DYNAMIC_SYMBOL_SELECTION_KEY,
    MASKED_COST_OBSERVATION_MODE,
    MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS,
    ProfiledBaseFeaturePublisherV1,
    ProfiledBaseFeaturePublisherV1ConfigurationError,
    ProfiledBaseFeaturePublisherV1Error,
    ProfiledBaseFeaturePublisherV1ResourceError,
    ProfiledBaseFeaturePublisherV1StateError,
    _singleton_writer_lock,
    adaptive_resource_decision_v1,
    least_recently_covered_symbols_v1,
    prospective_decision_midpoint_v1,
    pttl_derived_cost_recapture_target_v1,
    select_source_shard_index_v1,
    wait_for_prospective_decision_v1,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
    ProfiledModelFeatureSnapshotRecordV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_enrichment_record_v1 import (
    ProfiledTrainingEnrichmentRecordV1Error,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    MAX_LEDGER_BYTES,
    TrainerSourceProvenanceLedgerV4DurabilityError,
)
from v2.backend.app.services.orderbook_recorder import features as orderbook_features
from v2.backend.tests.unit.services import (
    test_binance_usdm_commission_evidence_broker as commission_broker_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_binance_usdm_commission_capture_v1 as commission_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_multitimeframe_capture_set_v1 as capture_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_causal_adaptive_cold_start_notional_policy_v1 as cold_start_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_causal_cost_evidence_v1 as cost_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_causal_expected_notional_policy_v1 as notional_support,
)

DiskUsage = namedtuple("DiskUsage", "total used free")
FIXED_CLOCK = datetime.now(UTC) - timedelta(seconds=2)


class _Pipeline:
    def __init__(self, owner: _Redis) -> None:
        self.owner = owner
        self.keys: list[str] = []

    def type(self, key: str) -> _Pipeline:
        self.keys.append(key)
        return self

    def getrange(self, key: str, _start: int, _end: int) -> _Pipeline:
        assert self.keys[-1] == key
        return self

    def pttl(self, key: str) -> _Pipeline:
        assert self.keys[-1] == key
        return self

    def time(self) -> _Pipeline:
        return self

    def execute(self) -> list[object]:
        assert self.keys
        self.owner.atomic_batches.append(tuple(self.keys))
        result: list[object] = []
        for key in self.keys:
            self.owner.atomic_reads[key] += 1
            result.extend((b"string", self.owner.payloads[key], self.owner.pttl_ms))
        result.append(
            (
                int(self.owner.server_time.timestamp()),
                self.owner.server_time.microsecond,
            )
        )
        return result

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Redis:
    def __init__(
        self,
        payloads: dict[str, bytes],
        *,
        pttl_ms: int = 600_000,
        server_time: datetime = FIXED_CLOCK,
    ) -> None:
        self.payloads = dict(payloads)
        self.pttl_ms = pttl_ms
        self.server_time = server_time
        self.atomic_reads: Counter[str] = Counter()
        self.atomic_batches: list[tuple[str, ...]] = []
        self.scan_calls = 0

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        assert transaction is True
        return _Pipeline(self)

    def scan_iter(self, *, match: bytes, count: int):  # type: ignore[no-untyped-def]
        assert match.startswith(b"v2:market:ohlcv_closed:binance:")
        assert count > 0
        self.scan_calls += 1
        required_timeframe = match.decode("ascii").rsplit(":", 1)[1]
        yield from sorted(
            key.encode("ascii") for key in self.payloads if key.endswith(f":{required_timeframe}")
        )


class _Monotonic:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def _key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"


def _payloads(*, stale_5m: bool = False) -> dict[str, bytes]:
    latest_5m = capture_support._latest_open_ms("5m", decision=FIXED_CLOCK)
    if stale_5m:
        latest_5m -= TIMEFRAME_DURATION_MS["5m"]
    latest_1h = capture_support._latest_open_ms("1h", decision=FIXED_CLOCK)
    return {
        DYNAMIC_SYMBOL_SELECTION_KEY: json.dumps(
            {
                "generated_utc": (FIXED_CLOCK - timedelta(seconds=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "symbols": ["BTCUSDT"],
            },
            sort_keys=True,
        ).encode(),
        _key("BTCUSDT", "5m"): capture_support._payload(
            capture_support._rows("5m", latest_open_ms=latest_5m)
        ),
        _key("BTCUSDT", "1h"): capture_support._payload(
            capture_support._rows("1h", latest_open_ms=latest_1h)
        ),
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _self_hash(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "receipt_sha256": hashlib.sha256(_canonical_bytes(value)).hexdigest(),
    }


def _address_mapping(address: SourcePayloadAddress) -> dict[str, Any]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _runtime_cost_source_payloads(
    *,
    symbol: str,
    decision_at: datetime,
) -> dict[str, bytes]:
    source_at = decision_at - timedelta(seconds=1)
    source_clock = _iso(source_at)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(orderbook_features, "utc_now_iso", lambda: source_clock)
        orderbook = orderbook_features.build_orderbook_payloads(
            exchange="binance",
            symbol=symbol,
            bids=[
                [100.0, 50.0],
                [99.9, 50.0],
                [99.8, 50.0],
                [99.7, 50.0],
                [99.6, 50.0],
            ],
            asks=[
                [100.1, 50.0],
                [100.2, 50.0],
                [100.3, 50.0],
                [100.4, 50.0],
                [100.5, 50.0],
            ],
            event_time_ms=int(source_at.timestamp() * 1_000),
            transaction_time_ms=int(source_at.timestamp() * 1_000),
            received_at=source_clock,
            available_at=source_clock,
            sequence_id=701,
            previous_sequence_id=700,
            sequence_gap=False,
            update_type="diff_depth",
            feed_speed_ms=100,
            price_impact_notional_usd=1_000.0,
        )
    mark = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": symbol,
        "mark_price": 100.05,
        "markPrice": 100.05,
        "index_price": 100.04,
        "indexPrice": 100.04,
        "estimated_settle_price": None,
        "last_funding_rate": 0.0001,
        "next_funding_time_ms": int((decision_at + timedelta(seconds=600)).timestamp() * 1_000),
        "event_time": source_clock,
        "generated_at": source_clock,
        "received_at": source_clock,
        "available_at": source_clock,
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
        f"v2:orderbook:depth:binance:{symbol}": _canonical_bytes(orderbook["depth"]),
        f"v2:orderbook:features:binance:{symbol}": _canonical_bytes(orderbook["features"]),
        f"v2:market:mark_price:{symbol}": _canonical_bytes(mark),
    }


def _paper_margin_status(*, generated_at: datetime, paper_cycle_id: str) -> bytes:
    margin_base = 2_985.59472051
    used_margin = 0.0
    free_margin = margin_base - used_margin
    margin_buffer = 509.04412243
    after_buffer = free_margin - margin_buffer
    return _canonical_bytes(
        {
            "schema_version": "paper_account_margin_v1",
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
            "margin_base_usd": margin_base,
            "used_margin_usd": used_margin,
            "free_margin_usd": free_margin,
            "margin_buffer_usd": margin_buffer,
            "free_margin_after_buffer_usd": after_buffer,
            "usable_margin_after_buffer_before_reservations_usd": after_buffer,
            "generated_utc": _iso(generated_at),
            "paper_cycle_id": paper_cycle_id,
        }
    )


def _test_cost_evidence_factory(
    *,
    parent_record: dict[str, Any],
    enrichment_store: ImmutableSourcePayloadStore,
    decision_at: datetime,
    strict_notional_provenance: bool = True,
):  # type: ignore[no-untyped-def]
    envelope = parent_record["frozen_envelope"]
    symbol = envelope["symbol"]
    identity = parent_record["durable_snapshot_id"]
    source_at = decision_at - timedelta(seconds=1)
    server_at = decision_at - timedelta(milliseconds=500)
    source_clock = _iso(source_at)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(orderbook_features, "utc_now_iso", lambda: source_clock)
        orderbook = orderbook_features.build_orderbook_payloads(
            exchange="binance",
            symbol=symbol,
            bids=[[100.0, 50.0], [99.9, 50.0], [99.8, 50.0], [99.7, 50.0], [99.6, 50.0]],
            asks=[
                [100.1, 50.0],
                [100.2, 50.0],
                [100.3, 50.0],
                [100.4, 50.0],
                [100.5, 50.0],
            ],
            event_time_ms=int(source_at.timestamp() * 1_000),
            transaction_time_ms=int(source_at.timestamp() * 1_000),
            received_at=source_clock,
            available_at=source_clock,
            sequence_id=701,
            previous_sequence_id=700,
            sequence_gap=False,
            update_type="diff_depth",
            feed_speed_ms=100,
            price_impact_notional_usd=1_000.0,
        )
    mark = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": symbol,
        "mark_price": 100.05,
        "markPrice": 100.05,
        "index_price": 100.04,
        "indexPrice": 100.04,
        "estimated_settle_price": None,
        "last_funding_rate": 0.0001,
        "next_funding_time_ms": int((decision_at + timedelta(seconds=600)).timestamp() * 1_000),
        "event_time": source_clock,
        "generated_at": source_clock,
        "received_at": source_clock,
        "available_at": source_clock,
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
    depth_key = f"v2:orderbook:depth:binance:{symbol}"
    features_key = f"v2:orderbook:features:binance:{symbol}"
    mark_key = f"v2:market:mark_price:{symbol}"
    market_capture = read_atomic_redis_sources(
        cost_support._Redis(
            {
                depth_key: _canonical_bytes(orderbook["depth"]),
                features_key: _canonical_bytes(orderbook["features"]),
                mark_key: _canonical_bytes(mark),
            },
            pttl_ms=60_000,
            server_time=server_at,
        ),
        (depth_key, features_key, mark_key),
    )
    effective_at = _iso(decision_at - timedelta(seconds=2))
    expires_at = _iso(decision_at + timedelta(hours=1))
    raw_fee = _canonical_bytes(
        {
            "makerCommissionRate": "0.00020000",
            "rpiCommissionRate": "0.00010000",
            "symbol": symbol,
            "takerCommissionRate": "0.00040000",
        }
    )
    raw_address = enrichment_store.put(raw_fee)
    raw_sha = hashlib.sha256(raw_fee).hexdigest()
    fee_artifact = {
        "schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
        "capture_classification": (
            "STRUCTURALLY_VALIDATED_DETACHED_SIGNED_COMMISSION_RESPONSE_UNWIRED"
        ),
        "venue": "BINANCE",
        "market": "USD_M_PERPETUAL",
        "symbol": symbol,
        "liquidity_role": "TAKER",
        "fee_semantics": "PER_SIDE_EXECUTION_FEE_NOT_ROUND_TRIP",
        "fee_unit": "BASIS_POINTS",
        "taker_fee_bps_per_side": 4.0,
        "effective_at": effective_at,
        "available_at": effective_at,
        "expires_at": expires_at,
        "source_key": f"v2:account:fee_schedule:{symbol}",
        "authority_scope": "BINANCE_USDM_ACCOUNT_COMMISSION_RATE",
        "source_revision": raw_sha,
        "raw_response_sha256": raw_sha,
        "raw_response_byte_count": len(raw_fee),
        "raw_response_cas_address": _address_mapping(raw_address),
        "sanitized_request_identity_sha256": "1" * 64,
        "credential_binding_fingerprint_sha256": "2" * 64,
        "http_status": 200,
        "request_method": "GET",
        "request_path": "/fapi/v1/commissionRate",
        "response_observed_at": effective_at,
        "rpi_commission_rate_decimal": "0.00010000",
        "rpi_commission_bps": 1.0,
    }
    fee_artifact_bytes = _canonical_bytes(fee_artifact)
    fee_receipt = _self_hash(
        {
            "schema_version": CAUSAL_COST_FEE_RECEIPT_V1_SCHEMA_VERSION,
            "receipt_kind": "DIRECT_READ",
            "artifact_payload_sha256": hashlib.sha256(fee_artifact_bytes).hexdigest(),
            "artifact_payload_byte_count": len(fee_artifact_bytes),
            "source_key": fee_artifact["source_key"],
            "source_schema_version": CAUSAL_COST_FEE_ARTIFACT_V1_SCHEMA_VERSION,
            "source_transport": "DETACHED_SIGNED_BINANCE_USDM_COMMISSION_RESPONSE_UNWIRED",
            "symbol": symbol,
            "effective_at": effective_at,
            "available_at": effective_at,
            "expires_at": expires_at,
            "authority_scope": fee_artifact["authority_scope"],
            "capture_classification": fee_artifact["capture_classification"],
            "raw_response_sha256": raw_sha,
            "raw_response_byte_count": len(raw_fee),
            "raw_response_cas_address": _address_mapping(raw_address),
            "sanitized_request_identity_sha256": "1" * 64,
            "credential_binding_fingerprint_sha256": "2" * 64,
            "http_status": 200,
            "request_method": "GET",
            "request_path": "/fapi/v1/commissionRate",
            "response_observed_at": effective_at,
            "rpi_commission_rate_decimal": "0.00010000",
            "rpi_commission_bps": 1.0,
        }
    )
    notional_status = notional_support._status(
        count=2,
        gross_notional_usd=2_000.0,
    )
    notional_status["generated_utc"] = effective_at
    notional_token = build_causal_expected_notional_policy_v1(
        atomic_capture=read_atomic_redis_sources(
            cost_support._Redis(
                {
                    CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY: json.dumps(
                        notional_status
                    ).encode("utf-8")
                },
                pttl_ms=60_000,
                server_time=server_at,
            ),
            (CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,),
        ),
        source_payload_store=enrichment_store,
        symbol=symbol,
        feature_snapshot_identity=identity,
        feature_snapshot_decision_time=decision_at,
    )
    return build_causal_cost_evidence_v1(
        atomic_capture=market_capture,
        source_payload_store=enrichment_store,
        fee_schedule_artifact_bytes=fee_artifact_bytes,
        fee_schedule_raw_response_bytes=raw_fee,
        fee_schedule_receipt=fee_receipt,
        expected_notional_usd=notional_token.expected_notional_usd,
        expected_notional_policy_artifact_bytes=(
            notional_token.notional_artifact_bytes
        ),
        expected_notional_policy_receipt=notional_token.notional_receipt,
        **(
            {
                "expected_notional_policy_source_receipt_bytes": (
                    notional_token.source_read_receipt_bytes
                ),
                "expected_notional_policy_factory_token": notional_token,
            }
            if strict_notional_provenance
            else {}
        ),
        symbol=symbol,
        feature_snapshot_identity=identity,
        decision_time=_iso(decision_at),
        counterfactual_holding_horizon_seconds=900,
    )


def _publisher(
    tmp_path: Path,
    redis_client: _Redis,
    *,
    state_name: str = "state.json",
    capture_function=capture_canonical_closed_ohlcv_atomic_receipts,  # type: ignore[no-untyped-def]
    capture_set_builder=build_canonical_ohlcv_multitimeframe_capture_set_v1,  # type: ignore[no-untyped-def]
    cost_evidence_factory=_test_cost_evidence_factory,  # type: ignore[no-untyped-def]
    commission_fingerprint_hmac_key: bytes | None = None,
    commission_cost_mode: str = AUTHENTICATED_COST_EVIDENCE_REQUIRED_MODE,
    commission_evidence_reader=None,  # type: ignore[no-untyped-def]
) -> ProfiledBaseFeaturePublisherV1:
    return ProfiledBaseFeaturePublisherV1(
        redis_client=redis_client,
        data_root=(tmp_path / "publisher").absolute(),
        feature_ledger_path=(tmp_path / "feature-ledger.sqlite3").absolute(),
        state_path=(tmp_path / state_name).absolute(),
        status_path=(tmp_path / f"{state_name}.status").absolute(),
        cycle_period_seconds=300.0,
        boundary_retry_limit=2,
        clock=lambda: FIXED_CLOCK,
        monotonic=_Monotonic(),
        disk_usage=lambda _path: DiskUsage(10**12, 10**9, 10**12 - 10**9),
        decision_planner=lambda _generated_at: FIXED_CLOCK,
        decision_waiter=lambda _decision_at: FIXED_CLOCK,
        capture_function=capture_function,
        capture_set_builder=capture_set_builder,
        cost_evidence_factory=cost_evidence_factory,
        commission_fingerprint_hmac_key=commission_fingerprint_hmac_key,
        commission_cost_mode=commission_cost_mode,
        commission_evidence_reader=commission_evidence_reader,
    )


def _seed_observed_state(path: Path) -> None:
    state = {
        "schema_version": "profiled_base_feature_publisher_state_v1",
        "coverage": {},
        "rotation_last_attempted_at": {},
        "observations": {
            "cycle_count": 1,
            "materialized_publication_count": 1,
            "materialized_publication_elapsed_seconds": 1.0,
            "materialized_publication_bytes": BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL,
        },
    }
    path.write_text(
        json.dumps(state, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )


def test_policy_v1_window_fingerprint_cannot_suppress_policy_v2_build(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    source_store = ImmutableSourcePayloadStore((tmp_path / "source-cas").absolute())
    captures = tuple(
        capture_canonical_closed_ohlcv_atomic_receipts(
            redis_client,
            source_store,
            expected_symbol="BTCUSDT",
            expected_timeframe=timeframe,
            consumer_clock=lambda: FIXED_CLOCK,
        )
        for timeframe in ("5m", "1h")
    )
    legacy_fingerprint = publisher_module.stable_sha256(
        {
            "schema_version": "profiled_base_finalized_window_fingerprint_v1",
            "symbol": "BTCUSDT",
            "timeframes": [
                {
                    "timeframe": timeframe,
                    "suffix_digest_sha256": capture.suffix_digest_sha256,
                    "latest_candle_id": capture.selected_candle_ids[-1],
                }
                for timeframe, capture in zip(("5m", "1h"), captures, strict=True)
            ],
        }
    )
    builder_calls = 0

    def replay_capture(*_args: Any, expected_timeframe: str, **_kwargs: Any) -> Any:
        return captures[("5m", "1h").index(expected_timeframe)]

    def counted_builder(**kwargs: Any) -> Any:
        nonlocal builder_calls
        builder_calls += 1
        return build_canonical_ohlcv_multitimeframe_capture_set_v1(**kwargs)

    publisher = _publisher(
        tmp_path,
        redis_client,
        capture_function=replay_capture,
        capture_set_builder=counted_builder,
    )
    _, current_fingerprint, capture_set, _, _, _ = publisher._capture_and_build_set(
        symbol="BTCUSDT",
        source_store=source_store,
        capture_set_store=ImmutableSourcePayloadStore(
            (tmp_path / "capture-set-cas").absolute()
        ),
        prior_fingerprint=legacy_fingerprint,
    )

    assert current_fingerprint != legacy_fingerprint
    assert capture_set is not None
    assert builder_calls == 1


def test_prospective_decision_is_strict_midpoint_before_next_5m_boundary() -> None:
    generated = datetime(2026, 7, 21, 12, 1, 0, tzinfo=UTC)
    decision = prospective_decision_midpoint_v1(generated)

    assert decision == datetime(2026, 7, 21, 12, 3, 0, tzinfo=UTC)
    assert generated < decision < datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC)

    with pytest.raises(
        ProfiledBaseFeaturePublisherV1ConfigurationError,
        match="PROFILED_BASE_PUBLISHER_NO_PROSPECTIVE_DECISION_WINDOW",
    ):
        prospective_decision_midpoint_v1(datetime(2026, 7, 21, 12, 4, 59, 999_999, tzinfo=UTC))


def test_cost_recapture_target_is_derived_from_shortest_atomic_redis_pttl() -> None:
    server_at = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    decision_at = server_at + timedelta(seconds=120)
    notional_batch = read_atomic_redis_sources(
        cost_support._Redis(
            {"v2:paper:adaptive_sizing_runtime_status": b"{}"},
            pttl_ms=60_000,
            server_time=server_at,
        ),
        ("v2:paper:adaptive_sizing_runtime_status",),
    )
    market_keys = (
        "v2:orderbook:depth:binance:BTCUSDT",
        "v2:orderbook:features:binance:BTCUSDT",
        "v2:market:mark_price:BTCUSDT",
    )
    market_batch = read_atomic_redis_sources(
        cost_support._Redis(
            {key: b"{}" for key in market_keys},
            pttl_ms=30_000,
            server_time=server_at,
        ),
        market_keys,
    )

    target = pttl_derived_cost_recapture_target_v1(
        atomic_captures=(notional_batch, market_batch),
        decision_at=decision_at,
    )

    assert target == decision_at - timedelta(seconds=15)


def test_runtime_default_cost_chain_uses_ordered_atomic_sources_and_real_factories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _payloads()
    server_at = FIXED_CLOCK - timedelta(milliseconds=500)
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": server_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["BTCUSDT"],
        },
        sort_keys=True,
    ).encode()
    notional_status = notional_support._status()
    notional_status["generated_utc"] = _iso(server_at - timedelta(milliseconds=100))
    payloads[CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY] = json.dumps(notional_status).encode("utf-8")
    payloads.update(_runtime_cost_source_payloads(symbol="BTCUSDT", decision_at=FIXED_CLOCK))
    redis_client = _Redis(payloads, pttl_ms=1_501, server_time=server_at)
    http_calls: list[dict[str, Any]] = []
    refresh_tokens: list[Any] = []
    commission_tokens: list[Any] = []
    monkeypatch.setattr(
        commission_capture_module,
        "resolve_binance_credential_binding",
        commission_support._binding,
    )
    monkeypatch.setattr(
        commission_capture_module,
        "binance_rest_fallback_decision",
        commission_support._allowed_decision(),
    )
    monkeypatch.setattr(
        commission_capture_module,
        "report_binance_rest_response",
        lambda **_kwargs: True,
    )

    def http_get(**kwargs: Any):  # type: ignore[no-untyped-def]
        http_calls.append(dict(kwargs))
        return commission_support._Response(commission_support._RAW)

    def real_commission_capture(**kwargs: Any):  # type: ignore[no-untyped-def]
        refresh_tokens.append(kwargs["refresh_policy"])
        token = commission_capture_module.capture_binance_usdm_commission_rate_v1(
            **kwargs,
            http_get=http_get,
        )
        commission_tokens.append(token)
        return token

    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_fingerprint_hmac_key=commission_support._FINGERPRINT_KEY,
    )
    publisher.clock = lambda: FIXED_CLOCK - timedelta(microseconds=100)
    publisher.commission_capture_function = real_commission_capture
    notional_tokens: list[Any] = []
    real_notional_builder = publisher.expected_notional_builder

    def observed_notional_builder(**kwargs: Any):  # type: ignore[no-untyped-def]
        token = real_notional_builder(**kwargs)
        notional_tokens.append(token)
        return token

    publisher.expected_notional_builder = observed_notional_builder

    status = publisher.run_cycle()

    assert status["published_symbols"] == ["BTCUSDT"], status["failures"][0]["reasons"]
    assert len(http_calls) == 1
    assert redis_client.atomic_batches[-2:] == [
        (CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,),
        (
            "v2:orderbook:depth:binance:BTCUSDT",
            "v2:orderbook:features:binance:BTCUSDT",
            "v2:market:mark_price:BTCUSDT",
        ),
    ]
    assert (
        CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY,
    ) not in redis_client.atomic_batches
    assert len(refresh_tokens) == 1
    refresh = refresh_tokens[0]
    assert refresh.refresh_interval_seconds == 1
    assert refresh.artifact["policy_id"] == (
        "profiled-training-commission-notional-pttl-refresh-v1"
    )
    assert refresh.artifact["policy_version"] == ("notional-redis-pttl-server-clock-v1")
    assert refresh.adaptive_input_receipt_sha256 == (notional_tokens[0].source_read_receipt_sha256)
    publication = status["publications"][0]
    assert publication["runtime_cost_auxiliary_cas_bytes"] == (
        len(refresh.artifact_bytes)
        + len(refresh.receipt_bytes)
        + len(commission_tokens[0].sanitized_request_identity_bytes)
    )
    cost_store = ImmutableSourcePayloadStore(Path(publication["cost_store_root"]))
    cost_contract = json.loads(
        cost_store.get(publication["cost_capture_artifact_sha256"])
    )
    positive_provenance = cost_contract["notional_source"]["policy_provenance"]
    assert positive_provenance["verification_status"] == (
        CAUSAL_COST_NOTIONAL_PROVENANCE_VERIFIED_STATUS
    )
    assert positive_provenance["bound_source_object_count"] == 1
    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    assert ledger.verify_integrity_streaming().verified_records == 2

    def forbidden_unchanged_commission(**_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("unchanged finalized windows must not recapture commission")

    publisher.commission_capture_function = forbidden_unchanged_commission
    unchanged = publisher.run_cycle()
    assert unchanged["unchanged_symbols"] == ["BTCUSDT"]
    assert len(http_calls) == 1


def _credentialless_fee_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> CredentiallessCommissionEvidence:
    _result, broker_redis, store, context, calls, clock = (
        commission_broker_support._publish(  # noqa: SLF001 - cross-boundary E2E fixture
            tmp_path,
            monkeypatch,
            start_at=FIXED_CLOCK - timedelta(seconds=2),
        )
    )
    selected = commission_broker_module.read_authenticated_commission_evidence(
        broker_redis,
        store=store,
        security_context=context,
        symbol="BTCUSDT",
        decision_time=FIXED_CLOCK,
        now_fn=clock,
    )
    assert len(calls) == 1
    assert selected["status"] == "READY"
    evidence = selected["evidence"]
    assert type(evidence) is CredentiallessCommissionEvidence
    return evidence


def test_broker_reader_builds_strict_pair_without_exchange_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _payloads()
    server_at = FIXED_CLOCK - timedelta(milliseconds=500)
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": server_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["BTCUSDT"],
        },
        sort_keys=True,
    ).encode()
    notional_status = notional_support._status()
    notional_status["generated_utc"] = _iso(
        server_at - timedelta(milliseconds=100)
    )
    payloads[CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY] = json.dumps(
        notional_status
    ).encode("utf-8")
    payloads.update(
        _runtime_cost_source_payloads(symbol="BTCUSDT", decision_at=FIXED_CLOCK)
    )
    redis_client = _Redis(payloads, pttl_ms=1_501, server_time=server_at)
    evidence = _credentialless_fee_evidence(tmp_path, monkeypatch)
    reads: list[dict[str, Any]] = []

    def reader(**kwargs: Any) -> dict[str, Any]:
        reads.append(dict(kwargs))
        return {"status": "READY", "evidence": evidence}

    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_cost_mode=(
            BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
        ),
        commission_evidence_reader=reader,
    )
    publisher.clock = lambda: FIXED_CLOCK - timedelta(microseconds=100)

    def forbidden_direct_capture(**_kwargs: Any) -> Any:
        raise AssertionError(
            "credentialless broker mode must not load or call exchange credentials"
        )

    publisher.commission_capture_function = forbidden_direct_capture

    status = publisher.run_cycle()

    assert status["published_symbols"] == ["BTCUSDT"], status["failures"]
    assert status["masked_cost_observation_symbol_count"] == 0
    assert status["commission_broker_reader_available"] is True
    assert status["commission_credentials_available"] is False
    assert status["exchange_credentials_loaded_by_publisher"] is False
    assert len(reads) == 1
    assert reads[0]["symbol"] == "BTCUSDT"
    assert reads[0]["decision_time"] == _iso(FIXED_CLOCK)
    publication = status["publications"][0]
    assert publication["commission_evidence_read_attempted"] is True
    assert publication["commission_evidence_status"] == "READY"
    assert publication["commission_evidence_authenticated"] is True
    assert publication["runtime_cost_auxiliary_cas_bytes"] == 0
    cost_store = ImmutableSourcePayloadStore(Path(publication["cost_store_root"]))
    cost_artifact_bytes = cost_store.get(publication["cost_capture_artifact_sha256"])
    cost_contract = json.loads(cost_artifact_bytes)
    transport = cost_contract["fee_transport_provenance"]
    assert transport["broker_envelope_sha256"] == evidence.broker_envelope_sha256
    assert (
        transport["consumer_receipt_payload_sha256"]
        == evidence.broker_consumer_receipt_sha256
    )
    assert transport["exchange_credentials_read"] is False
    assert cost_contract["fee_source_authenticity_status"] == (
        "BROKER_READER_HMAC_CAS_AND_PIT_VERIFIED_WITH_SIGNED_RECEIPT_PERSISTED"
    )
    assert cost_store.get(evidence.broker_envelope_sha256) == evidence.broker_envelope_bytes
    assert cost_store.get(evidence.broker_consumer_receipt_sha256) == (
        evidence.broker_consumer_receipt_bytes
    )
    ledger = DurableFeatureSnapshotLedger(
        (tmp_path / "feature-ledger.sqlite3").absolute()
    )
    assert ledger.verify_integrity_streaming().verified_records == 2

    batch = loader_module.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=Path(publication["cost_store_root"]),
        training_observed_at=_iso(datetime.now(UTC) + timedelta(seconds=1)),
    )
    assert len(batch.samples) == 1
    assert batch.exclusions == ()


def test_broker_temporal_miss_retries_whole_window_instead_of_masking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _payloads()
    server_at = FIXED_CLOCK - timedelta(milliseconds=500)
    notional_status = notional_support._status()
    notional_status["generated_utc"] = _iso(
        server_at - timedelta(milliseconds=100)
    )
    payloads[CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY] = json.dumps(
        notional_status
    ).encode("utf-8")
    payloads.update(
        _runtime_cost_source_payloads(symbol="BTCUSDT", decision_at=FIXED_CLOCK)
    )
    redis_client = _Redis(payloads, pttl_ms=1_501, server_time=server_at)
    evidence = _credentialless_fee_evidence(tmp_path, monkeypatch)
    reads = 0

    def reader(**_kwargs: Any) -> dict[str, Any]:
        nonlocal reads
        reads += 1
        if reads == 1:
            return {
                "status": "COMMISSION_BROKER_DECISION_TEMPORAL_ADMISSION_FAILED",
                "evidence": None,
            }
        return {"status": "READY", "evidence": evidence}

    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_cost_mode=(
            BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
        ),
        commission_evidence_reader=reader,
    )

    status = publisher.run_cycle()

    assert reads == 2
    assert status["published_symbols"] == ["BTCUSDT"], status["failures"]
    assert status["masked_cost_observation_symbol_count"] == 0
    assert status["publications"][0]["publication_attempts"] == 2
    ledger = DurableFeatureSnapshotLedger(
        (tmp_path / "feature-ledger.sqlite3").absolute()
    )
    assert ledger.verify_integrity_streaming().verified_records == 2


def test_zero_candidate_cold_start_builds_strict_pair_from_adaptive_paper_margin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _payloads()
    server_at = FIXED_CLOCK - timedelta(milliseconds=500)
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": server_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["BTCUSDT"],
        },
        sort_keys=True,
    ).encode()
    notional_status = cold_start_support._zero_candidate_payload()
    notional_status["generated_utc"] = _iso(
        server_at - timedelta(milliseconds=100)
    )
    payloads[CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY] = json.dumps(
        notional_status
    ).encode("utf-8")
    payloads[CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY] = (
        _paper_margin_status(
            generated_at=server_at - timedelta(milliseconds=100),
            paper_cycle_id=notional_status["paper_cycle_id"],
        )
    )
    payloads.update(
        _runtime_cost_source_payloads(symbol="BTCUSDT", decision_at=FIXED_CLOCK)
    )
    redis_client = _Redis(payloads, pttl_ms=1_501, server_time=server_at)
    evidence = _credentialless_fee_evidence(tmp_path, monkeypatch)

    def reader(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "READY", "evidence": evidence}

    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_cost_mode=(
            BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
        ),
        commission_evidence_reader=reader,
    )
    publisher.clock = lambda: FIXED_CLOCK - timedelta(microseconds=100)

    def forbidden_direct_capture(**_kwargs: Any) -> Any:
        raise AssertionError("cold-start broker mode must remain credentialless")

    publisher.commission_capture_function = forbidden_direct_capture

    status = publisher.run_cycle()

    assert status["published_symbols"] == ["BTCUSDT"], status["failures"]
    assert status["masked_cost_observation_symbol_count"] == 0
    assert redis_client.atomic_batches.count(
        (CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,)
    ) == 1
    assert redis_client.atomic_batches.count(
        (
            CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
            CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_PORTFOLIO_SOURCE_KEY,
        )
    ) == 1
    publication = status["publications"][0]
    assert publication["expected_notional_usd"] == 2_476.55059808
    assert publication["expected_notional_policy_id"] == (
        CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID
    )
    assert publication["expected_notional_policy_source_key"] == (
        causal_adaptive_cold_start_notional_policy_source_key_v1("BTCUSDT")
    )
    assert publication["commission_evidence_authenticated"] is True
    cost_store = ImmutableSourcePayloadStore(Path(publication["cost_store_root"]))
    cost_contract = json.loads(
        cost_store.get(publication["cost_capture_artifact_sha256"])
    )
    notional_source = cost_contract["notional_source"]
    assert notional_source["expected_notional_usd"] == 2_476.55059808
    assert notional_source["policy_id"] == (
        CAUSAL_ADAPTIVE_COLD_START_NOTIONAL_POLICY_ID
    )
    assert notional_source["fallback_used"] is False
    assert notional_source["static_default_used"] is False
    cold_provenance = notional_source["policy_provenance"]
    assert cold_provenance["verification_status"] == (
        CAUSAL_COST_NOTIONAL_PROVENANCE_VERIFIED_STATUS
    )
    assert cold_provenance["bound_source_object_count"] == 5
    assert cold_provenance["strict_publisher_eligible"] is True
    ledger = DurableFeatureSnapshotLedger(
        (tmp_path / "feature-ledger.sqlite3").absolute()
    )
    assert ledger.verify_integrity_streaming().verified_records == 2

    batch = loader_module.load_profiled_training_ledger_v1(
        ledger=ledger,
        trusted_immutable_cost_store_root=Path(publication["cost_store_root"]),
        training_observed_at=_iso(datetime.now(UTC) + timedelta(seconds=1)),
    )
    assert len(batch.samples) == 1
    assert batch.exclusions == ()


def test_broker_missing_or_stale_evidence_masks_without_bad_training_row(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    reads: list[dict[str, Any]] = []

    def reader(**kwargs: Any) -> dict[str, Any]:
        reads.append(dict(kwargs))
        return {"status": "COMMISSION_EVIDENCE_MISSING", "evidence": None}

    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_cost_mode=(
            BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
        ),
        commission_evidence_reader=reader,
    )

    def forbidden_cost_dependency(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("missing broker evidence must mask before reading cost sources")

    publisher.commission_capture_function = forbidden_cost_dependency
    publisher.expected_notional_builder = forbidden_cost_dependency
    publisher.commission_refresh_builder = forbidden_cost_dependency
    publisher.causal_cost_builder = forbidden_cost_dependency

    status = publisher.run_cycle()

    assert status["published_symbol_count"] == 0
    assert status["masked_cost_observation_symbols"] == ["BTCUSDT"]
    assert status["failed_symbols"] == []
    assert status["commission_broker_reader_available"] is True
    assert status["exchange_credentials_loaded_by_publisher"] is False
    assert len(reads) == 1
    observation = status["masked_cost_observations"][0]
    assert observation["commission_evidence_read_attempted"] is True
    assert observation["commission_evidence_status"] == "COMMISSION_EVIDENCE_MISSING"
    assert observation["commission_evidence_authenticated"] is False
    assert observation["cost_source_read_attempted"] is False
    assert observation["authority"]["child_trainer_admission_authorized"] is False
    ledger = DurableFeatureSnapshotLedger(
        (tmp_path / "feature-ledger.sqlite3").absolute()
    )
    assert ledger.verify_integrity_streaming().verified_records == 1


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        (
            "hmac",
            "COMMISSION_CAPTURE_CREDENTIAL_FINGERPRINT_HMAC_KEY_TOO_SHORT",
        ),
        (
            "credential",
            "COMMISSION_CAPTURE_ACCOUNT_SPECIFIC_CREDENTIAL_REQUIRED",
        ),
    ],
)
def test_runtime_default_hmac_and_credential_blockers_do_not_retry_or_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_reason: str,
) -> None:
    server_at = FIXED_CLOCK - timedelta(milliseconds=500)
    payloads = _payloads()
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": server_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["BTCUSDT"],
        },
        sort_keys=True,
    ).encode()
    notional_status = notional_support._status()
    notional_status["generated_utc"] = _iso(server_at - timedelta(milliseconds=100))
    payloads[CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY] = json.dumps(notional_status).encode("utf-8")
    payloads.update(_runtime_cost_source_payloads(symbol="BTCUSDT", decision_at=FIXED_CLOCK))
    redis_client = _Redis(payloads, pttl_ms=1_501, server_time=server_at)
    binding = (
        commission_support._binding()
        if case == "hmac"
        else commission_support._binding(account_specific=False)
    )
    monkeypatch.setattr(
        commission_capture_module,
        "resolve_binance_credential_binding",
        lambda: binding,
    )
    http_calls = 0

    def forbidden_http(**_kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal http_calls
        http_calls += 1
        raise AssertionError("credential blockers must precede HTTP")

    def real_commission_capture(**kwargs: Any):  # type: ignore[no-untyped-def]
        return commission_capture_module.capture_binance_usdm_commission_rate_v1(
            **kwargs,
            http_get=forbidden_http,
        )

    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_fingerprint_hmac_key=(
            None if case == "hmac" else commission_support._FINGERPRINT_KEY
        ),
    )
    publisher.clock = lambda: FIXED_CLOCK - timedelta(microseconds=100)
    publisher.commission_capture_function = real_commission_capture

    status = publisher.run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["reasons"] == [
        "COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED",
        expected_reason,
    ]
    assert status["failures"][0]["in_cycle_temporal_retryable"] is False
    assert http_calls == 0
    assert redis_client.atomic_batches.count((CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,)) == 1
    assert (
        redis_client.atomic_batches.count(
            (
                "v2:orderbook:depth:binance:BTCUSDT",
                "v2:orderbook:features:binance:BTCUSDT",
                "v2:market:mark_price:BTCUSDT",
            )
        )
        == 1
    )
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_runtime_default_missing_market_source_fails_before_commission_and_append(
    tmp_path: Path,
) -> None:
    server_at = FIXED_CLOCK - timedelta(milliseconds=500)
    payloads = _payloads()
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": server_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["BTCUSDT"],
        },
        sort_keys=True,
    ).encode()
    notional_status = notional_support._status()
    notional_status["generated_utc"] = _iso(server_at - timedelta(milliseconds=100))
    payloads[CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY] = json.dumps(notional_status).encode("utf-8")
    redis_client = _Redis(payloads, pttl_ms=1_501, server_time=server_at)
    commission_calls = 0

    def forbidden_commission(**_kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal commission_calls
        commission_calls += 1
        raise AssertionError("missing atomic market evidence must precede commission")

    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_fingerprint_hmac_key=commission_support._FINGERPRINT_KEY,
    )
    publisher.clock = lambda: FIXED_CLOCK - timedelta(microseconds=100)
    publisher.commission_capture_function = forbidden_commission

    status = publisher.run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["reasons"] == [
        "COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED",
        "atomic_redis_source_read_transport_failed",
    ]
    assert status["failures"][0]["in_cycle_temporal_retryable"] is False
    assert commission_calls == 0
    assert redis_client.atomic_batches.count((CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,)) == 1
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_decision_wait_is_bounded_and_wall_clock_rollback_fails_closed() -> None:
    base = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
    decision = base + timedelta(seconds=2)
    clocks = iter((base, base + timedelta(milliseconds=500), decision))
    sleeps: list[float] = []

    observed = wait_for_prospective_decision_v1(
        decision,
        clock=lambda: next(clocks),
        sleeper=sleeps.append,
    )

    assert observed == decision
    assert sleeps == [1.0, 1.0]

    rollback_clocks = iter((base, base - timedelta(microseconds=1)))
    with pytest.raises(
        ProfiledBaseFeaturePublisherV1ConfigurationError,
        match="PROFILED_BASE_PUBLISHER_DECISION_WAIT_CLOCK_MOVED_BACKWARDS",
    ):
        wait_for_prospective_decision_v1(
            base + timedelta(seconds=1),
            clock=lambda: next(rollback_clocks),
            sleeper=lambda _seconds: None,
        )


def test_feature_append_occurs_only_after_decision_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    wait_completed = False

    def waiter(decision_at: datetime) -> datetime:
        nonlocal wait_completed
        wait_completed = True
        return decision_at

    publisher.decision_waiter = waiter
    original_append = DurableFeatureSnapshotLedger.append_snapshots

    def guarded_append(self, records, *, writer_lease=None):  # type: ignore[no-untyped-def]
        assert wait_completed is True
        assert len(records) == 2
        return original_append(self, records, writer_lease=writer_lease)

    monkeypatch.setattr(DurableFeatureSnapshotLedger, "append_snapshots", guarded_append)
    status = publisher.run_cycle()

    assert status["published_symbol_count"] == 1
    assert status["publications"][0]["prospective_decision_wait_verified"] is True
    assert (
        status["publications"][0]["decision_wait_completed_at"]
        >= status["publications"][0]["decision_time"]
    )


def test_waiter_cannot_authorize_append_before_decision(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    publisher.decision_waiter = lambda decision_at: decision_at - timedelta(microseconds=1)

    status = publisher.run_cycle()

    assert status["published_symbol_count"] == 0
    assert status["failed_symbol_count"] == 1
    assert status["failures"][0]["reasons"] == [
        "PROFILED_BASE_PUBLISHER_APPEND_BEFORE_PROSPECTIVE_DECISION"
    ]


def test_missed_prospective_decision_recaptures_whole_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = _Redis(_payloads())
    publisher = _publisher(tmp_path, redis_client)
    original_builder = publisher_module.build_profiled_model_feature_snapshot_record_v1
    calls = 0

    def fail_first_record_build(**kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProfiledModelFeatureSnapshotRecordV1Error(
                "PROFILED_MODEL_RECORD_PUBLICATION_CLOCK_ORDER_INVALID"
            )
        return original_builder(**kwargs)

    monkeypatch.setattr(
        publisher_module,
        "build_profiled_model_feature_snapshot_record_v1",
        fail_first_record_build,
    )
    status = publisher.run_cycle()

    assert status["published_symbol_count"] == 1
    assert status["publications"][0]["publication_attempts"] == 2
    assert redis_client.atomic_reads[_key("BTCUSDT", "5m")] == 2
    assert redis_client.atomic_reads[_key("BTCUSDT", "1h")] == 2


def test_post_decision_cost_capture_retries_whole_prospective_record(
    tmp_path: Path,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    calls = 0

    def temporal_cost_failure(**kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CausalCostEvidenceV1ValidationError("CAUSAL_COST_ATOMIC_CAPTURE_AFTER_DECISION")
        return _test_cost_evidence_factory(**kwargs)

    publisher.cost_evidence_factory = temporal_cost_failure

    status = publisher.run_cycle()

    assert calls == 2
    assert status["published_symbols"] == ["BTCUSDT"]
    assert status["publications"][0]["publication_attempts"] == 2
    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    assert ledger.verify_integrity_streaming().verified_records == 2


def test_injected_cost_factory_cannot_bypass_strict_notional_provenance(
    tmp_path: Path,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))

    def unverified_factory(**kwargs: Any):  # type: ignore[no-untyped-def]
        return _test_cost_evidence_factory(
            **kwargs,
            strict_notional_provenance=False,
        )

    publisher.cost_evidence_factory = unverified_factory

    status = publisher.run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert "PROFILED_BASE_PUBLISHER_NOTIONAL_POLICY_PROVENANCE_UNVERIFIED" in (
        status["failures"][0]["reasons"]
    )
    assert status["failures"][0]["coverage_advanced"] is False
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


@pytest.mark.parametrize(
    ("failure", "expected_calls", "temporal_retryable"),
    [
        (
            BinanceUSDMCommissionCaptureV1ValidationError(
                "COMMISSION_CAPTURE_ACCOUNT_SPECIFIC_CREDENTIAL_REQUIRED"
            ),
            1,
            False,
        ),
        (
            BinanceUSDMCommissionCaptureV1ValidationError(
                "COMMISSION_CAPTURE_CREDENTIAL_FINGERPRINT_HMAC_KEY_INVALID"
            ),
            1,
            False,
        ),
        (
            BinanceUSDMCommissionCaptureV1ValidationError(
                "COMMISSION_CAPTURE_REST_FALLBACK_OR_SHARED_BUDGET_BLOCKED"
            ),
            1,
            False,
        ),
        (
            CausalExpectedNotionalPolicyV1ValidationError(
                "EXPECTED_NOTIONAL_ZERO_CANDIDATE_SUPPLY"
            ),
            1,
            False,
        ),
        (
            CausalCostEvidenceV1ValidationError("CAUSAL_COST_ORDERBOOK_DEPTH_SOURCE_MISSING"),
            1,
            False,
        ),
        (
            CausalCostEvidenceV1ValidationError(
                "CAUSAL_COST_ORDERBOOK_DEPTH_SOURCE_EXPIRED_AT_DECISION"
            ),
            2,
            True,
        ),
        (
            CausalAdaptiveColdStartNotionalPolicyV1ValidationError(
                "COLD_START_NOTIONAL_MARKET_CAPTURE_AFTER_DECISION"
            ),
            2,
            True,
        ),
        (
            CausalAdaptiveColdStartNotionalPolicyV1ValidationError(
                "COLD_START_NOTIONAL_MARKET_EXPIRED_AT_DECISION"
            ),
            2,
            True,
        ),
        (
            CausalCostEvidenceV1ValidationError("CAUSAL_COST_ORDERBOOK_CROSSED_OR_ZERO_SPREAD"),
            1,
            False,
        ),
    ],
)
def test_cost_blockers_never_append_parent_or_advance_coverage(
    tmp_path: Path,
    failure: Exception,
    expected_calls: int,
    temporal_retryable: bool,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    calls = 0

    def fail_cost(**_kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise failure

    publisher.cost_evidence_factory = fail_cost

    status = publisher.run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert "COST_EVIDENCE_UNAVAILABLE_PARENT_NOT_APPENDED" in status["failures"][0]["reasons"]
    assert status["failures"][0]["coverage_advanced"] is False
    assert status["coverage"]["BTCUSDT"]["durable_snapshot_id"] is None
    assert calls == expected_calls
    assert status["failures"][0]["in_cycle_temporal_retryable"] is temporal_retryable
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_masked_cost_mode_appends_only_quarantined_parent_without_cost_values(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_cost_mode=MASKED_COST_OBSERVATION_MODE,
    )

    def forbidden_cost_dependency(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("masked mode must not read or construct cost evidence")

    publisher.commission_capture_function = forbidden_cost_dependency
    publisher.expected_notional_builder = forbidden_cost_dependency
    publisher.commission_refresh_builder = forbidden_cost_dependency
    publisher.causal_cost_builder = forbidden_cost_dependency

    status = publisher.run_cycle()

    assert status["classification"] == "CYCLE_COMPLETE_MASKED_COST_OBSERVATIONS", status[
        "failures"
    ][0]["reasons"]
    assert status["commission_cost_mode"] == MASKED_COST_OBSERVATION_MODE
    assert status["commission_credentials_available"] is False
    assert status["published_symbol_count"] == 0
    assert status["exact_replay_symbol_count"] == 0
    assert status["masked_cost_observation_symbol_count"] == 1
    assert status["masked_cost_observation_symbols"] == ["BTCUSDT"]
    assert status["failed_symbols"] == []
    assert (
        status["authority_semantics"][
            "published_child_trainer_admission_authorized"
        ]
        is False
    )
    observation = status["masked_cost_observations"][0]
    mask = observation["cost_observation"]
    assert mask["ordered_feature_names"] == [
        "fee_bps",
        "spread_bps",
        "expected_slippage_bps",
        "expected_funding_bps",
    ]
    assert mask["missing_mask"] == [1, 1, 1, 1]
    assert mask["stale_mask"] == [0, 0, 0, 0]
    assert mask["source_availability_mask"] == [0, 0, 0, 0]
    assert mask["feature_values_emitted"] is False
    assert mask["feature_source_receipts_emitted"] is False
    assert "feature_values" not in mask
    assert "feature_source_receipt_sha256s" not in mask
    assert observation["cost_values_or_receipts_fabricated"] is False
    assert observation["commission_capture_attempted"] is False
    assert observation["cost_source_read_attempted"] is False
    assert observation["feature_cutoff"] <= observation["decision_time"]
    assert observation["prospective_decision_wait_verified"] is True
    assert observation["authority"]["parent_trainer_admission_authorized"] is False
    assert observation["authority"]["child_trainer_admission_authorized"] is False
    assert not any(
        key.startswith("v2:orderbook:")
        or key.startswith("v2:market:mark_price:")
        or key == CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY
        for batch in redis_client.atomic_batches
        for key in batch
    )

    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    integrity = ledger.verify_integrity_streaming()
    assert integrity.verified_records == 1
    committed = ledger.get_snapshot(observation["durable_snapshot_id"])
    assert committed is not None
    envelope = committed.record["frozen_envelope"]
    assert len(envelope["ordered_feature_names"]) == 35
    assert not {
        "fee_bps",
        "spread_bps",
        "expected_slippage_bps",
        "expected_funding_bps",
    }.intersection(envelope["ordered_feature_names"])
    assert envelope["strict_training_eligible"] is False
    assert envelope["temporal_rejection_reasons"] == [
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON
    ]


def test_masked_parent_replays_after_state_loss_and_is_never_retro_enriched(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    first = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_cost_mode=MASKED_COST_OBSERVATION_MODE,
    ).run_cycle()
    assert first["masked_cost_observation_symbol_count"] == 1, first["failures"][0][
        "reasons"
    ]
    (tmp_path / "state.json").unlink()

    replay_publisher = _publisher(
        tmp_path,
        redis_client,
        cost_evidence_factory=None,
        commission_cost_mode=MASKED_COST_OBSERVATION_MODE,
    )
    replay_publisher.clock = lambda: FIXED_CLOCK + timedelta(minutes=10)
    prior_atomic_batches = len(redis_client.atomic_batches)
    replay = replay_publisher.run_cycle()

    assert replay["masked_cost_observation_symbol_count"] == 0
    assert replay["masked_cost_observation_replay_symbol_count"] == 1, replay[
        "failures"
    ][0]["reasons"]
    assert len(redis_client.atomic_batches) == prior_atomic_batches + 1
    assert redis_client.atomic_batches[-1] == (DYNAMIC_SYMBOL_SELECTION_KEY,)
    detail = replay["masked_cost_observations"][0]
    assert detail["classification"] == "MASKED_COST_OBSERVATION_PARENT_EXACT_REPLAY"
    assert detail["append_after_prospective_decision_reverified"] is True
    assert detail["feature_append"]["new_rows_inserted_this_cycle"] is False
    assert (
        detail["recovery"]["classification"]
        == "STATE_LOSS_MASKED_PARENT_LEDGER_READBACK_VERIFIED"
    )
    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    assert ledger.verify_integrity_streaming().verified_records == 1

    def forbidden_retro_cost(**_kwargs: Any) -> Any:
        raise AssertionError("an unchanged masked decision must not be retro-enriched")

    (tmp_path / "state.json").unlink()
    authenticated = _publisher(tmp_path, redis_client)
    authenticated.clock = lambda: FIXED_CLOCK + timedelta(minutes=20)
    authenticated.cost_evidence_factory = forbidden_retro_cost
    recovered = authenticated.run_cycle()
    assert recovered["masked_cost_observation_replay_symbols"] == ["BTCUSDT"]
    assert recovered["published_symbols"] == []
    assert ledger.verify_integrity_streaming().verified_records == 1


def test_masked_cost_mode_rejects_loaded_cost_credentials_or_factory(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())

    with pytest.raises(
        ProfiledBaseFeaturePublisherV1ConfigurationError,
        match="PROFILED_BASE_PUBLISHER_CONFIGURATION_INVALID",
    ):
        _publisher(
            tmp_path,
            redis_client,
            commission_cost_mode=MASKED_COST_OBSERVATION_MODE,
        )
    with pytest.raises(
        ProfiledBaseFeaturePublisherV1ConfigurationError,
        match="PROFILED_BASE_PUBLISHER_CONFIGURATION_INVALID",
    ):
        _publisher(
            tmp_path,
            redis_client,
            cost_evidence_factory=None,
            commission_fingerprint_hmac_key=b"x" * 32,
            commission_cost_mode=MASKED_COST_OBSERVATION_MODE,
        )


@pytest.mark.parametrize("failure_stage", ["pair_build", "pair_append"])
def test_pair_failure_stages_never_leave_an_orphan_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    function_name = (
        "build_profiled_training_enrichment_pair_v1"
        if failure_stage == "pair_build"
        else "append_profiled_training_enrichment_pair_v1"
    )

    def fail_pair(**_kwargs: Any):  # type: ignore[no-untyped-def]
        raise ProfiledTrainingEnrichmentRecordV1Error(
            f"PROFILED_TRAINING_INJECTED_{failure_stage.upper()}_FAILURE"
        )

    monkeypatch.setattr(publisher_module, function_name, fail_pair)

    status = _publisher(tmp_path, _Redis(_payloads())).run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["orphan_feature_ledger_record_appended"] is False
    assert status["coverage"]["BTCUSDT"]["durable_snapshot_id"] is None
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_happy_path_publishes_exact_adjacent_authenticated_training_pair(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    publisher = _publisher(tmp_path, redis_client)

    status = publisher.run_cycle()

    assert status["classification"] == "CYCLE_COMPLETE_ALL_SELECTED_AUTHENTICATED_OR_UNCHANGED"
    assert status["discovered_symbols"] == ["BTCUSDT"]
    assert status["eligible_symbols"] == ["BTCUSDT"]
    assert status["selected_symbols"] == ["BTCUSDT"]
    assert status["published_symbols"] == ["BTCUSDT"]
    assert status["failed_symbols"] == []
    assert status["legacy_feature_redis_write_performed"] is False
    assert status["market_performance_thresholds_applied"] is False
    assert status["disk_resource_safety"]["policy"] == DISK_RESERVE_POLICY_V1
    assert status["disk_resource_safety"]["reserve_bytes"] == 200_000_000_000
    assert status["disk_resource_safety"]["operational_invariant_not_market_selection"] is True
    publication = status["publications"][0]
    assert publication["execution_time"] is None
    assert publication["available_at"] <= publication["decision_time"]
    assert publication["source_appends"][0]["durable_postcommit_readback_verified"] is True
    assert publication["source_appends"][1]["durable_postcommit_readback_verified"] is True
    assert publication["feature_append"]["transaction_committed"] is True
    assert publication["feature_append"]["transaction_readback_verified"] is True
    assert publication["authority"] == {
        "child_trainer_admission_authorized": True,
        "live_execution_authorized": False,
        "paper_trading_authorized": False,
        "parent_trainer_admission_authorized": False,
        "prediction_authorized": False,
        "publisher_runtime_authority_granted": False,
        "runtime_wired": False,
        "trainer_candidate_in_lineage": True,
    }

    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    child = ledger.get_snapshot(publication["durable_snapshot_id"])
    parent = ledger.get_snapshot(publication["parent_durable_snapshot_id"])
    assert child is not None
    assert parent is not None
    assert parent.sequence + 1 == child.sequence
    assert parent.append_transaction_id == child.append_transaction_id
    assert parent.append_receipt_sha256 == child.append_receipt_sha256
    assert parent.postcommit_receipt_sha256 == child.postcommit_receipt_sha256
    parent_envelope = parent.record["frozen_envelope"]
    child_envelope = child.record["frozen_envelope"]
    assert len(parent_envelope["ordered_feature_names"]) == 35
    assert len(child_envelope["ordered_feature_names"]) == 39
    assert child_envelope["feature_values"][:35] == parent_envelope["feature_values"]
    assert (
        child_envelope["feature_source_receipt_sha256s"][:35]
        == parent_envelope["feature_source_receipt_sha256s"]
    )
    assert parent_envelope["temporal_rejection_reasons"] == [
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON
    ]
    assert parent_envelope["strict_training_eligible"] is False
    assert child_envelope["strict_training_eligible"] is True
    lineage = child_envelope["source_lineage_material"][
        "authenticated_profiled_training_enrichment_v1"
    ]
    assert lineage["physical_feature_count"] == 39
    assert lineage["authorization"] == {
        "live_execution_authorized": False,
        "paper_trading_authorized": False,
        "prediction_authorized": False,
        "runtime_wired": False,
        "trainer_admission_authorized": True,
    }
    assert publication["cost_store_root"] == str(
        (tmp_path / "publisher/profiled-training-enrichment-cas").absolute()
    )


def test_missing_timeframe_is_ineligible_without_source_read(tmp_path: Path) -> None:
    payloads = _payloads()
    payloads.pop(_key("BTCUSDT", "1h"))
    redis_client = _Redis(payloads)

    status = _publisher(tmp_path, redis_client).run_cycle()

    assert status["classification"] == "NO_ELIGIBLE_SYMBOLS"
    assert status["eligible_symbols"] == []
    assert status["selected_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["missing_timeframes"] == ["1h"]
    assert redis_client.atomic_reads == Counter({DYNAMIC_SYMBOL_SELECTION_KEY: 1})


def test_dynamic_universe_intersection_excludes_stale_and_invalid_symbols(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    for symbol in ("GUSDT", "YBUSDT"):
        payloads[_key(symbol, "5m")] = payloads[_key("BTCUSDT", "5m")]
        payloads[_key(symbol, "1h")] = payloads[_key("BTCUSDT", "1h")]
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": (FIXED_CLOCK - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["BTCUSDT", "币安人生USDT"],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")

    status = _publisher(tmp_path, _Redis(payloads)).run_cycle()

    assert status["discovered_symbols"] == ["BTCUSDT", "GUSDT", "YBUSDT"]
    assert status["eligible_symbols"] == ["BTCUSDT"]
    assert status["published_symbols"] == ["BTCUSDT"]
    universe = status["dynamic_selection_universe"]
    assert universe["ohlcv_discovered_excluded_symbols"] == ["GUSDT", "YBUSDT"]
    assert universe["rejected_symbols"] == ["币安人生USDT"]
    assert universe["rejected_symbol_reason"] == (
        "SYMBOL_FORMAT_NOT_CANONICAL_ASCII_RUNTIME_SYMBOL"
    )
    assert universe["trainer_evidence_or_authority_conferred"] is False


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        (
            {
                "generated_utc": (FIXED_CLOCK - timedelta(seconds=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "symbols": ["BTCUSDT"],
                "unbound_extra_field": True,
            },
            "MALFORMED_HOLD",
        ),
        (
            {
                "generated_utc": (FIXED_CLOCK - timedelta(seconds=1)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "symbols": [],
            },
            "VALID_EMPTY_HOLD",
        ),
    ],
)
def test_malformed_or_empty_dynamic_universe_holds_without_global_crash(
    tmp_path: Path,
    payload: dict[str, Any],
    expected_status: str,
) -> None:
    payloads = _payloads()
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(payload, sort_keys=True).encode()

    status = _publisher(tmp_path, _Redis(payloads)).run_cycle()

    assert status["classification"] == f"DYNAMIC_SELECTION_UNIVERSE_{expected_status}"
    assert status["selected_symbols"] == []
    assert status["published_symbols"] == []
    assert status["dynamic_selection_universe"]["status"] == expected_status
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_dynamic_universe_uses_positive_source_owned_pttl_until_expiry(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            # Older than the remaining PTTL on purpose: remaining lifetime is
            # not the original TTL and cannot be used as a payload-age limit.
            "generated_utc": (FIXED_CLOCK - timedelta(seconds=601)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["BTCUSDT"],
        },
        sort_keys=True,
    ).encode()

    status = _publisher(tmp_path, _Redis(payloads, pttl_ms=600_000)).run_cycle()

    assert status["dynamic_selection_universe"]["status"] == "VALID"
    assert status["dynamic_selection_universe"]["availability_contract"] == (
        "POSITIVE_SOURCE_OWNED_REDIS_PTTL"
    )
    assert status["published_symbols"] == ["BTCUSDT"]


def test_dynamic_universe_without_source_owned_expiry_holds_fail_closed(
    tmp_path: Path,
) -> None:
    status = _publisher(tmp_path, _Redis(_payloads(), pttl_ms=-1)).run_cycle()

    universe = status["dynamic_selection_universe"]
    assert status["classification"] == "DYNAMIC_SELECTION_UNIVERSE_UNAVAILABLE_HOLD"
    assert universe["status"] == "UNAVAILABLE_HOLD"
    assert universe["reason"] == "DYNAMIC_SELECTION_UNIVERSE_SOURCE_MISSING_OR_UNPERSISTED"
    assert status["published_symbols"] == []
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_stale_final_candle_retries_then_skips_without_feature_record(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads(stale_5m=True))

    status = _publisher(tmp_path, redis_client).run_cycle()

    assert status["classification"] == "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED"
    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["boundary_or_finality_related"] is True
    assert redis_client.atomic_reads[_key("BTCUSDT", "5m")] == 2
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_required_window_rest_provenance_rejection_appends_no_ledgers(
    tmp_path: Path,
) -> None:
    payloads = _payloads()
    rows = json.loads(payloads[_key("BTCUSDT", "1h")])
    required_rows = dict(capture_support.CAPTURE_SET_REQUIRED_LOOKBACKS)["1h"]
    first_required = -required_rows
    rows[first_required] = capture_support._canonical_rest(  # noqa: SLF001
        int(rows[first_required]["candle_open_time"]),
        timeframe="1h",
    )
    payloads[_key("BTCUSDT", "1h")] = capture_support._payload(rows)

    status = _publisher(tmp_path, _Redis(payloads)).run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["reasons"] == [
        "canonical_ohlcv_multitimeframe_required_window_rest_provenance_unavailable"
    ]
    assert not (tmp_path / "feature-ledger.sqlite3").exists()
    assert not (tmp_path / "publisher" / "source-provenance-shards").exists()


def test_boundary_race_recaptures_whole_pair_before_any_provenance_append(
    tmp_path: Path,
) -> None:
    calls = 0

    def boundary_once(**kwargs: Any):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CanonicalOhlcvMultitimeframeCaptureSetV1Error(
                "canonical_ohlcv_multitimeframe_stale_or_unfinished_latest_candle"
            )
        return build_canonical_ohlcv_multitimeframe_capture_set_v1(**kwargs)

    redis_client = _Redis(_payloads())
    status = _publisher(
        tmp_path,
        redis_client,
        capture_set_builder=boundary_once,
    ).run_cycle()

    assert calls == 2
    assert redis_client.atomic_reads[_key("BTCUSDT", "5m")] == 2
    assert redis_client.atomic_reads[_key("BTCUSDT", "1h")] == 2
    assert status["published_symbols"] == ["BTCUSDT"]
    assert status["publications"][0]["boundary_attempts"] == 2
    assert len(status["publications"][0]["source_appends"]) == 2


def test_source_ledger_append_failure_prevents_transform_record_and_feature_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_append(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise TrainerSourceProvenanceLedgerV4DurabilityError(
            "source_provenance_v4_injected_append_failure"
        )

    monkeypatch.setattr(
        publisher_module.TrainerSourceProvenanceLedgerV4,
        "append_atomic_capture",
        fail_append,
    )
    status = _publisher(tmp_path, _Redis(_payloads())).run_cycle()

    assert status["published_symbols"] == []
    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["reasons"] == ["source_provenance_v4_injected_append_failure"]
    assert not (tmp_path / "feature-ledger.sqlite3").exists()


def test_one_symbol_failure_does_not_block_another_eligible_symbol(tmp_path: Path) -> None:
    payloads = _payloads()
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": (FIXED_CLOCK - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["AAAUSDT", "BTCUSDT"],
        },
        sort_keys=True,
    ).encode()
    payloads[_key("AAAUSDT", "5m")] = payloads[_key("BTCUSDT", "5m")]
    payloads[_key("AAAUSDT", "1h")] = payloads[_key("BTCUSDT", "1h")]
    redis_client = _Redis(payloads)

    def selective_capture(*args: Any, expected_symbol: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        if expected_symbol == "AAAUSDT":
            raise CanonicalOhlcvAtomicCaptureValidationError(
                "canonical_ohlcv_injected_symbol_failure"
            )
        return capture_canonical_closed_ohlcv_atomic_receipts(
            *args,
            expected_symbol=expected_symbol,
            **kwargs,
        )

    _seed_observed_state(tmp_path / "state.json")
    status = _publisher(
        tmp_path,
        redis_client,
        capture_function=selective_capture,
    ).run_cycle()

    assert status["selected_symbols"] == ["AAAUSDT", "BTCUSDT"]
    assert status["failed_symbols"] == ["AAAUSDT"]
    assert status["published_symbols"] == ["BTCUSDT"]
    assert status["classification"] == "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED"


def test_state_loss_recovers_authenticated_pair_without_recapture_or_reappend(
    tmp_path: Path,
) -> None:
    redis_client = _Redis(_payloads())
    first = _publisher(tmp_path, redis_client, state_name="state-one.json").run_cycle()
    _seed_observed_state(tmp_path / "state-two.json")

    def forbidden_capture(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("OHLCV capture must not run during pair recovery")

    def forbidden_cost(**_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("cost/commission capture must not run during pair recovery")

    recovering = _publisher(
        tmp_path,
        redis_client,
        state_name="state-two.json",
        capture_function=forbidden_capture,
    )
    recovering.cost_evidence_factory = forbidden_cost
    second = recovering.run_cycle()

    assert first["published_symbols"] == ["BTCUSDT"]
    assert second["published_symbols"] == []
    assert second["exact_replay_symbols"] == ["BTCUSDT"]
    assert second["failed_symbols"] == []
    assert (
        second["coverage"]["BTCUSDT"]["durable_snapshot_id"]
        == first["coverage"]["BTCUSDT"]["durable_snapshot_id"]
    )
    recovery = second["publications"][0]["recovery"]
    assert recovery == {
        "classification": "STATE_LOSS_COMMITTED_PAIR_INDEPENDENTLY_AUTHENTICATED",
        "recovery_receipt_sha256": recovery["recovery_receipt_sha256"],
        "ledger_and_trusted_cost_cas_reopened": True,
        "cost_or_commission_recapture_performed": False,
        "feature_ledger_append_performed": False,
        "coverage_recovered_from_commit_receipt": True,
    }
    assert second["cycle_materialized_publication_count"] == 1
    assert second["cycle_evidence_accounted_bytes"] > 0
    recovered_state = json.loads((tmp_path / "state-two.json").read_text(encoding="ascii"))
    assert recovered_state["observations"]["materialized_publication_count"] == 2
    assert recovered_state["observations"]["materialized_publication_elapsed_seconds"] == 2.0
    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    assert ledger.verify_integrity_streaming().verified_records == 2

    settled = _publisher(
        tmp_path,
        redis_client,
        state_name="state-two.json",
    )
    settled.cost_evidence_factory = forbidden_cost
    third = settled.run_cycle()
    assert third["exact_replay_symbols"] == []
    assert third["unchanged_symbols"] == ["BTCUSDT"]


def test_legacy_recovery_receipt_is_preserved_while_v2_pair_is_published(
    tmp_path: Path,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    publisher.data_root.mkdir(mode=0o700)
    legacy_path = (
        tmp_path
        / "publisher/profiled-training-pair-recovery-receipts/BTCUSDT.json"
    )
    legacy_path.parent.mkdir(mode=0o700)
    unsigned = {
        "schema_version": "profiled_training_pair_recovery_receipt_v1",
        "symbol": "BTCUSDT",
        "window_fingerprint_sha256": "1" * 64,
        "parent_durable_snapshot_id": "legacy-parent",
        "parent_record_sha256": "2" * 64,
        "child_durable_snapshot_id": "legacy-child",
        "child_record_sha256": "3" * 64,
        "cost_capture_artifact_sha256": "4" * 64,
        "cost_store_root": str(
            (tmp_path / "publisher/profiled-training-enrichment-cas").absolute()
        ),
        "prepared_at": FIXED_CLOCK.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "append_disposition": (
            "PREPARED_BEFORE_ATOMIC_PAIR_APPEND_REQUIRES_LEDGER_READBACK"
        ),
        "materialized_evidence_bytes": 1,
        "evidence_accounting_method": (
            "CONSERVATIVE_EXACT_CAS_PLUS_LEDGER_RECORD_MULTIPLIER_"
            "AND_AUXILIARY_SQLITE_OVERHEAD"
        ),
    }
    receipt = {
        **unsigned,
        "recovery_receipt_sha256": publisher_module.stable_sha256(unsigned),
    }
    publisher_module._atomic_write_json(
        legacy_path,
        receipt,
        failure_reason="TEST_LEGACY_RECEIPT_WRITE_FAILED",
    )
    legacy_bytes = legacy_path.read_bytes()

    status = publisher.run_cycle()

    v2_path = (
        tmp_path
        / "publisher/profiled-training-pair-recovery-receipts-v2/BTCUSDT.json"
    )
    assert status["published_symbols"] == ["BTCUSDT"]
    assert legacy_path.read_bytes() == legacy_bytes
    assert status["publications"][0]["legacy_recovery_receipt_observation"] == {
        "classification": "LEGACY_V1_RECOVERY_RECEIPT_PRESERVED_UNCONSUMED",
        "present": True,
        "regular_file": True,
        "owned_by_runtime_uid": True,
        "private_mode": True,
        "content_consumed": False,
        "authority_granted": False,
    }
    assert json.loads(v2_path.read_text(encoding="ascii"))["schema_version"] == (
        "profiled_training_pair_recovery_receipt_v2"
    )


def test_malformed_legacy_recovery_receipt_cannot_block_v2_publication(
    tmp_path: Path,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    publisher.data_root.mkdir(mode=0o700)
    legacy_path = (
        tmp_path
        / "publisher/profiled-training-pair-recovery-receipts/BTCUSDT.json"
    )
    legacy_path.parent.mkdir(mode=0o700)
    legacy_path.write_bytes(b"{malformed-legacy-receipt\n")
    legacy_path.chmod(0o600)
    legacy_bytes = legacy_path.read_bytes()

    status = publisher.run_cycle()

    assert status["published_symbols"] == ["BTCUSDT"]
    assert legacy_path.read_bytes() == legacy_bytes
    observation = status["publications"][0]["legacy_recovery_receipt_observation"]
    assert observation["classification"] == (
        "LEGACY_V1_RECOVERY_RECEIPT_PRESERVED_UNCONSUMED"
    )
    assert observation["content_consumed"] is False
    assert observation["authority_granted"] is False
    assert (
        tmp_path
        / "publisher/profiled-training-pair-recovery-receipts-v2/BTCUSDT.json"
    ).is_file()


def test_state_write_crash_after_pair_commit_recovers_once_without_work_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = _Redis(_payloads())
    publisher = _publisher(tmp_path, redis_client)
    original_atomic_write = publisher_module._atomic_write_json
    failed_state_write = False

    def crash_state_write(path: Path, value: object, *, failure_reason: str) -> None:
        nonlocal failed_state_write
        if path == publisher.state_path and not failed_state_write:
            failed_state_write = True
            raise ProfiledBaseFeaturePublisherV1StateError(
                "PROFILED_BASE_PUBLISHER_INJECTED_STATE_WRITE_CRASH"
            )
        original_atomic_write(path, value, failure_reason=failure_reason)

    monkeypatch.setattr(publisher_module, "_atomic_write_json", crash_state_write)
    with pytest.raises(
        ProfiledBaseFeaturePublisherV1StateError,
        match="PROFILED_BASE_PUBLISHER_INJECTED_STATE_WRITE_CRASH",
    ):
        publisher.run_cycle()

    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    assert ledger.verify_integrity_streaming().verified_records == 2
    assert not publisher.state_path.exists()
    receipt_path = (
        tmp_path
        / "publisher/profiled-training-pair-recovery-receipts-v2/BTCUSDT.json"
    )
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="ascii"))
    assert receipt["schema_version"] == "profiled_training_pair_recovery_receipt_v2"
    assert receipt["capture_policy_id"] == (
        publisher_module.CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID
    )
    assert receipt["capture_policy_sha256"] == (
        publisher_module.CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256
    )
    assert receipt["transform_configuration_sha256"] == (
        publisher_module.AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
    )

    monkeypatch.setattr(publisher_module, "_atomic_write_json", original_atomic_write)

    def forbidden_capture(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("recovery must precede OHLCV recapture")

    def forbidden_cost(**_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("recovery must precede cost/commission HTTP")

    recovering = _publisher(
        tmp_path,
        redis_client,
        capture_function=forbidden_capture,
    )
    recovering.clock = lambda: FIXED_CLOCK + timedelta(seconds=1)
    recovering.cost_evidence_factory = forbidden_cost
    recovered = recovering.run_cycle()

    assert recovered["exact_replay_symbols"] == ["BTCUSDT"]
    assert recovered["failed_symbols"] == []
    assert recovered["cycle_materialized_publication_count"] == 1
    assert recovered["cycle_evidence_accounted_bytes"] > 0
    assert ledger.verify_integrity_streaming().verified_records == 2

    settled = _publisher(tmp_path, redis_client)
    settled.cost_evidence_factory = forbidden_cost
    third = settled.run_cycle()
    assert third["exact_replay_symbols"] == []
    assert third["unchanged_symbols"] == ["BTCUSDT"]


def test_recovery_receipt_with_only_parent_is_quarantined_without_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_pairs: list[Any] = []

    def intercept_pair_append(*, ledger: Any, pair: Any):  # type: ignore[no-untyped-def]
        del ledger
        captured_pairs.append(pair)
        raise ProfiledTrainingEnrichmentRecordV1Error("PROFILED_TRAINING_INJECTED_PRECOMMIT_STOP")

    monkeypatch.setattr(
        publisher_module,
        "append_profiled_training_enrichment_pair_v1",
        intercept_pair_append,
    )
    redis_client = _Redis(_payloads())
    first = _publisher(tmp_path, redis_client).run_cycle()
    assert first["failed_symbols"] == ["BTCUSDT"]
    assert len(captured_pairs) == 1

    ledger = DurableFeatureSnapshotLedger((tmp_path / "feature-ledger.sqlite3").absolute())
    append = ledger.append_snapshots([captured_pairs[0].parent_record])
    assert append.inserted_rows == 1

    def forbidden_capture(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("partial-pair recovery must fail before capture")

    recovering = _publisher(
        tmp_path,
        redis_client,
        capture_function=forbidden_capture,
    )
    second = recovering.run_cycle()

    assert second["published_symbols"] == []
    assert second["failed_symbols"] == ["BTCUSDT"]
    assert second["failures"][0]["reasons"] == [
        "PROFILED_BASE_PUBLISHER_PAIR_RECOVERY_PARTIAL_PAIR_QUARANTINED"
    ]
    assert second["coverage"]["BTCUSDT"]["durable_snapshot_id"] is None
    assert ledger.verify_integrity_streaming().verified_records == 1


def test_unchanged_window_does_not_dilute_materialized_publication_observations(
    tmp_path: Path,
) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    first = publisher.run_cycle()
    state_after_insert = json.loads((tmp_path / "state.json").read_text("ascii"))
    second = publisher.run_cycle()
    state_after_unchanged = json.loads((tmp_path / "state.json").read_text("ascii"))

    assert first["published_symbols"] == ["BTCUSDT"]
    assert second["unchanged_symbols"] == ["BTCUSDT"]
    assert state_after_unchanged["observations"] == state_after_insert["observations"] | {
        "cycle_count": state_after_insert["observations"]["cycle_count"] + 1
    }


def test_second_writer_fails_before_state_or_shard_selection(tmp_path: Path) -> None:
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    data_root = (tmp_path / "publisher").absolute()
    data_root.mkdir(mode=0o700, parents=True)

    with _singleton_writer_lock(data_root):
        with pytest.raises(ProfiledBaseFeaturePublisherV1ResourceError) as exc_info:
            publisher.run_cycle()

    assert exc_info.value.reasons == ("PROFILED_BASE_PUBLISHER_SINGLETON_WRITER_LOCK_CONTENDED",)
    assert not (tmp_path / "state.json").exists()
    assert not (data_root / "source-provenance-shards").exists()


def test_resource_rotation_and_source_sharding_are_evidence_derived() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=200,
        observations={
            "cycle_count": 4,
            "materialized_publication_count": 4,
            "materialized_publication_elapsed_seconds": 40.0,
            "materialized_publication_bytes": 20_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=316_000_000_000,
        disk_free_bytes=684_000_000_000,
    )
    assert decision.estimated_evidence_bytes_per_symbol == 5_000_000
    assert decision.estimated_seconds_per_symbol == 10.0
    assert decision.disk_reserve_policy == DISK_RESERVE_POLICY_V1
    assert decision.disk_reserve_bytes == 200_000_000_000
    assert decision.safe_disk_headroom_bytes == 484_000_000_000
    assert decision.selected_count == 3
    assert decision.bootstrap_observation_required is False
    assert least_recently_covered_symbols_v1(
        ("SOLUSDT", "BTCUSDT", "ETHUSDT"),
        {
            "BTCUSDT": {"last_published_at": "2026-07-21T12:00:00.000000Z"},
            "ETHUSDT": {"last_published_at": "2026-07-21T11:00:00.000000Z"},
        },
    ) == ("SOLUSDT", "ETHUSDT", "BTCUSDT")
    assert select_source_shard_index_v1(
        active_index=7,
        active_ledger_bytes=MAX_LEDGER_BYTES - 10,
        active_ledger_entries=20,
        projected_pair_bytes=11,
    ) == (8, True)


def test_large_universe_is_bounded_by_sustainable_cadence_disk_budget() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=160,
        observations={
            "cycle_count": 10,
            "materialized_publication_count": 10,
            "materialized_publication_elapsed_seconds": 10.0,
            "materialized_publication_bytes": 49_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=316_000_000_000,
        disk_free_bytes=684_000_000_000,
    )
    assert decision.selected_count < 160
    assert decision.disk_reserve_bytes == 200_000_000_000
    assert decision.selected_count == 3
    assert (
        decision.selected_count * decision.estimated_evidence_bytes_per_symbol
        <= decision.available_write_credit_bytes
    )


def test_indivisible_evidence_unit_accrues_bounded_cross_cycle_credit() -> None:
    base_observations = {
        "materialized_publication_count": 1,
        "materialized_publication_elapsed_seconds": 1.0,
        "materialized_publication_bytes": 10_000_000,
    }
    resource_inputs = {
        "eligible_count": 75,
        "cycle_period_seconds": 300.0,
        "resource_sustainability_horizon_seconds": (
            MINIMUM_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS
        ),
        "disk_total_bytes": 500_000_000_000,
        "disk_used_bytes": 296_320_000_000,
        "disk_free_bytes": 203_680_000_000,
    }

    before_credit = adaptive_resource_decision_v1(
        observations={**base_observations, "cycle_count": 2},
        **resource_inputs,
    )
    funded = adaptive_resource_decision_v1(
        observations={**base_observations, "cycle_count": 4},
        **resource_inputs,
    )

    assert before_credit.sustainable_cycle_write_budget_bytes == 4_000_000
    assert before_credit.estimated_evidence_bytes_per_symbol == 10_000_000
    assert before_credit.available_write_credit_bytes == 2_000_000
    assert before_credit.selected_count == 0
    assert "BOUNDED_WRITE_CREDIT_ACCRUAL_PENDING" in before_credit.reasons
    assert "RESOURCE_HEADROOM_NO_SAFE_PUBLICATION_UNIT" not in before_credit.reasons
    assert funded.cumulative_sustainable_write_budget_bytes == 20_000_000
    assert funded.write_credit_capacity_bytes == 10_000_000
    assert funded.available_write_credit_bytes == 10_000_000
    assert funded.selected_count == 1
    assert "BOUNDED_CROSS_CYCLE_WRITE_CREDIT_ACCRUAL" in funded.reasons


def test_shared_filesystem_reserve_holds_when_free_space_is_at_reserve() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=160,
        observations={
            "cycle_count": 10,
            "materialized_publication_count": 10,
            "materialized_publication_elapsed_seconds": 10.0,
            "materialized_publication_bytes": 49_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=800_000_000_000,
        disk_free_bytes=200_000_000_000,
    )

    assert decision.disk_reserve_policy == DISK_RESERVE_POLICY_V1
    assert decision.disk_reserve_bytes == 200_000_000_000
    assert decision.safe_disk_headroom_bytes == 0
    assert decision.sustainable_cycle_write_budget_bytes == 0
    assert decision.disk_capacity_symbols == 0
    assert decision.selected_count == 0
    assert "RESOURCE_HEADROOM_NO_SAFE_PUBLICATION_UNIT" in decision.reasons


def test_two_observed_units_can_bind_shared_filesystem_reserve() -> None:
    decision = adaptive_resource_decision_v1(
        eligible_count=1,
        observations={
            "cycle_count": 1,
            "materialized_publication_count": 1,
            "materialized_publication_elapsed_seconds": 1.0,
            "materialized_publication_bytes": 150_000_000_000,
        },
        cycle_period_seconds=300.0,
        resource_sustainability_horizon_seconds=(DEFAULT_RESOURCE_SUSTAINABILITY_HORIZON_SECONDS),
        disk_total_bytes=1_000_000_000_000,
        disk_used_bytes=600_000_000_000,
        disk_free_bytes=400_000_000_000,
    )

    assert decision.estimated_evidence_bytes_per_symbol == 150_000_000_000
    assert decision.disk_reserve_bytes == 300_000_000_000
    assert decision.safe_disk_headroom_bytes == 100_000_000_000
    assert decision.selected_count == 0


def test_intra_cycle_backpressure_stops_after_observed_write_cost_jump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = {
        _key(symbol, timeframe): b"unused-by-controller-test"
        for symbol in ("AAAUSDT", "BTCUSDT")
        for timeframe in ("5m", "1h")
    }
    payloads[DYNAMIC_SYMBOL_SELECTION_KEY] = json.dumps(
        {
            "generated_utc": (FIXED_CLOCK - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "symbols": ["AAAUSDT", "BTCUSDT"],
        },
        sort_keys=True,
    ).encode()
    _seed_observed_state(tmp_path / "state.json")
    publisher = _publisher(tmp_path, _Redis(payloads))
    disk_usage_calls = 0
    disk_total_bytes = 10**12
    cycle_start_free_bytes = disk_total_bytes - 10**9
    free_bytes_by_call = (
        cycle_start_free_bytes,
        cycle_start_free_bytes,
        cycle_start_free_bytes,
        cycle_start_free_bytes - 250_000_000,
    )

    def counted_disk_usage(_path: Path) -> DiskUsage:
        nonlocal disk_usage_calls
        free_bytes = free_bytes_by_call[disk_usage_calls]
        disk_usage_calls += 1
        return DiskUsage(
            disk_total_bytes,
            disk_total_bytes - free_bytes,
            free_bytes,
        )

    publisher.disk_usage = counted_disk_usage

    def materialize_first_only(**kwargs: Any):  # type: ignore[no-untyped-def]
        symbol = kwargs["symbol"]
        coverage = {
            "last_published_at": FIXED_CLOCK.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "feature_cutoff": FIXED_CLOCK.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "decision_time": FIXED_CLOCK.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "window_fingerprint_sha256": "a" * 64,
            "durable_snapshot_id": f"durable-{symbol}",
            "record_sha256": "b" * 64,
        }
        return publisher_module._SymbolOutcome(
            symbol=symbol,
            classification="AUTHENTICATED_PROFILED_TRAINING_PAIR_INSERTED",
            window_fingerprint_sha256="a" * 64,
            materialized_evidence_bytes=50_000_000,
            detail={"symbol": symbol},
            coverage=coverage,
        )

    monkeypatch.setattr(publisher, "_publish_symbol", materialize_first_only)
    status = publisher.run_cycle()

    assert status["selected_symbols"] == ["AAAUSDT"]
    assert status["resource_deferred_symbols"] == ["BTCUSDT"]
    assert status["classification"] == "CYCLE_COMPLETE_RESOURCE_BACKPRESSURE_DEFERRED"
    assert disk_usage_calls == 4
    assert not hasattr(publisher, "_evidence_allocated_bytes")
    assert status["cycle_materialized_artifact_bytes"] == 50_000_000
    assert status["cycle_disk_consumption_high_water_bytes"] == 250_000_000
    assert status["cycle_owned_durable_growth_bytes"] == 0
    assert status["cycle_evidence_accounted_bytes"] == 50_000_000
    assert (
        status["cycle_evidence_accounted_bytes"]
        > status["resource_decision"]["sustainable_cycle_write_budget_bytes"]
    )
    assert (
        status["cycle_evidence_accounted_bytes"]
        > status["resource_decision"]["available_write_credit_bytes"]
    )
    persisted_state = json.loads((tmp_path / "state.json").read_text(encoding="ascii"))
    assert persisted_state["observations"]["materialized_publication_bytes"] == (
        BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL + 50_000_000
    )


def test_failed_attempt_filesystem_cost_is_charged_to_adaptive_observations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_observed_state(tmp_path / "state.json")
    publisher = _publisher(tmp_path, _Redis(_payloads()))
    disk_total = 10**12
    free_start = disk_total - 10**9
    free_values = iter(
        (
            free_start,
            free_start,
            free_start - 70_000_000,
            free_start - 70_000_000,
        )
    )

    def disk_usage(_path: Path) -> DiskUsage:
        free = next(free_values)
        return DiskUsage(disk_total, disk_total - free, free)

    def fail_after_materialization(**_kwargs: Any):  # type: ignore[no-untyped-def]
        publisher.data_root.mkdir(parents=True, exist_ok=True)
        (publisher.data_root / "failed-owned-artifact.bin").write_bytes(
            b"x" * 7_000_000
        )
        raise ProfiledTrainingEnrichmentRecordV1Error(
            "PROFILED_TRAINING_INJECTED_FAILURE_AFTER_AUXILIARY_CAS"
        )

    publisher.disk_usage = disk_usage
    monkeypatch.setattr(publisher, "_publish_symbol", fail_after_materialization)

    status = publisher.run_cycle()

    assert status["failed_symbols"] == ["BTCUSDT"]
    assert status["failures"][0]["materialized_evidence_bytes"] == 7_000_000
    assert status["cycle_evidence_accounted_bytes"] == 7_000_000
    assert status["cycle_disk_consumption_high_water_bytes"] == 70_000_000
    assert status["cycle_owned_durable_growth_bytes"] == 7_000_000
    persisted = json.loads((tmp_path / "state.json").read_text("ascii"))
    assert persisted["observations"]["materialized_publication_count"] == 2
    assert persisted["observations"]["materialized_publication_bytes"] == (
        BOOTSTRAP_EVIDENCE_BYTES_PER_SYMBOL + 7_000_000
    )


def test_short_resource_horizon_cannot_defeat_ninety_day_sustainability(
    tmp_path: Path,
) -> None:
    with pytest.raises(ProfiledBaseFeaturePublisherV1ConfigurationError):
        adaptive_resource_decision_v1(
            eligible_count=160,
            observations={
                "cycle_count": 0,
                "materialized_publication_count": 0,
                "materialized_publication_elapsed_seconds": 0.0,
                "materialized_publication_bytes": 0,
            },
            cycle_period_seconds=300.0,
            resource_sustainability_horizon_seconds=1.0,
            disk_total_bytes=1_000_000_000_000,
            disk_used_bytes=316_000_000_000,
            disk_free_bytes=684_000_000_000,
        )
    with pytest.raises(ProfiledBaseFeaturePublisherV1ConfigurationError):
        ProfiledBaseFeaturePublisherV1(
            redis_client=_Redis(_payloads()),
            data_root=tmp_path / "data",
            feature_ledger_path=tmp_path / "feature-ledger.sqlite3",
            cycle_period_seconds=300.0,
            resource_sustainability_horizon_seconds=1.0,
        )


def test_cli_cycle_summary_stays_bounded_when_full_status_has_large_inventories(
    tmp_path: Path,
) -> None:
    status = {
        "classification": "CYCLE_COMPLETE_PARTIAL_SYMBOL_FAILURES_ISOLATED",
        "cycle_started_at": "2026-07-21T12:00:00.000000Z",
        "cycle_completed_at": "2026-07-21T12:00:10.000000Z",
        "cycle_elapsed_seconds": 10.0,
        "discovered_symbol_count": 10_000,
        "eligible_symbol_count": 10_000,
        "selected_symbol_count": 5,
        "published_symbol_count": 4,
        "exact_replay_symbol_count": 0,
        "masked_cost_observation_symbol_count": 1,
        "masked_cost_observation_replay_symbol_count": 0,
        "unchanged_symbol_count": 0,
        "failed_symbol_count": 1,
        "cycle_evidence_accounted_bytes": 20_000_000,
        "status_sha256": "a" * 64,
        "commission_cost_mode": MASKED_COST_OBSERVATION_MODE,
        "commission_credentials_available": False,
        "authority_semantics": {
            "publisher_runtime_authority_granted": False,
            "published_child_trainer_admission_authorized": True,
            "prediction_paper_live_authority_granted": False,
            "automatic_trainer_transition_authorized": False,
        },
        "resource_decision": {
            "estimated_evidence_bytes_per_symbol": 5_000_000,
            "estimated_seconds_per_symbol": 2.0,
            "sustainable_cycle_write_budget_bytes": 25_000_000,
            "observed_cycle_count": 10,
            "consumed_materialized_evidence_bytes": 100_000_000,
            "write_credit_capacity_bytes": 25_000_000,
            "available_write_credit_bytes": 25_000_000,
            "disk_reserve_policy": DISK_RESERVE_POLICY_V1,
            "disk_reserve_bytes": 200_000_000_000,
            "safe_disk_headroom_bytes": 484_000_000_000,
            "disk_capacity_symbols": 5,
            "publication_latency_capacity_symbols": 150,
            "bootstrap_observation_required": False,
        },
        "discovered_symbols": [f"SYMBOL{index}" for index in range(10_000)],
        "publications": [{"large": "x" * 10_000} for _ in range(100)],
        "failures": [{"large": "y" * 10_000} for _ in range(100)],
    }
    summary = bounded_cycle_summary(
        status,
        status_path=tmp_path / "full-status.json",
    )
    encoded = json.dumps(summary, separators=(",", ":"), sort_keys=True)
    assert len(encoded) < 2_048
    assert "discovered_symbols" not in summary
    assert "publications" not in summary
    assert "failures" not in summary
    assert summary["publisher_runtime_authority_granted"] is False
    assert summary["published_child_trainer_admission_authorized"] is True
    assert summary["automatic_trainer_transition_authorized"] is False
    assert summary["masked_cost_observation_symbol_count"] == 1
    assert summary["commission_cost_mode"] == MASKED_COST_OBSERVATION_MODE
    assert summary["commission_credentials_available"] is False
    assert summary["resource_decision"]["observed_cycle_count"] == 10
    assert (
        summary["resource_decision"]["available_write_credit_bytes"]
        == 25_000_000
    )
    assert summary["credential_ref_read_only_assertion"] is True
    assert (
        summary["credential_ref_read_only_assertion_semantics"]
        == "OPERATOR_PROVISIONING_LABEL_NOT_BINANCE_PERMISSION_PROOF"
    )
    assert summary["exchange_key_permissions_proven_by_connector"] is False
    assert summary["live_execution_authorized"] is False


def test_cli_protected_commission_hmac_is_never_rendered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "publisher-test-separate-hmac-secret-never-render"  # noqa: S105
    monkeypatch.setattr(
        cli_module,
        "load_profiled_base_publisher_runtime_credentials_if_available",
        lambda: SimpleNamespace(
            commission_binding=SimpleNamespace(),
            fingerprint_hmac_key=secret.encode(),
        ),
    )

    def fail_redis(_redis_url: str) -> object:
        raise ProfiledBaseFeaturePublisherV1Error("PROFILED_BASE_PUBLISHER_INJECTED_REDIS_FAILURE")

    monkeypatch.setattr(cli_module, "_raw_redis_client", fail_redis)

    assert cli_module.main(["--once"]) == 1
    captured = capsys.readouterr()
    rendered = captured.out + captured.err
    assert secret not in rendered
    assert "PROFILED_BASE_PUBLISHER_INJECTED_REDIS_FAILURE" in rendered
    option_strings = {
        option
        for action in cli_module.build_parser()._actions  # noqa: SLF001
        for option in action.option_strings
    }
    assert not any(
        "hmac" in option.lower() or "secret" in option.lower() for option in option_strings
    )


def test_cli_missing_protected_credentials_fail_before_redis(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli_module,
        "load_profiled_base_publisher_runtime_credentials_if_available",
        lambda: (_ for _ in ()).throw(
            cli_module.ProfiledBasePublisherCredentialError(
                "PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID"
            )
        ),
    )
    redis_called = False

    def forbidden_redis(_redis_url: str) -> object:
        nonlocal redis_called
        redis_called = True
        raise AssertionError("Redis must not be contacted without the HMAC secret")

    monkeypatch.setattr(cli_module, "_raw_redis_client", forbidden_redis)

    assert cli_module.main(["--once"]) == 78
    captured = capsys.readouterr()
    assert redis_called is False
    assert "PROFILED_BASE_PUBLISHER_SYSTEMD_CREDENTIALS_DIRECTORY_INVALID" in captured.err


def test_cli_broker_mode_loads_only_verifier_context_and_no_exchange_bundle(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    client = object()
    security_context = object()
    broker_store = object()
    captured_arguments: dict[str, Any] = {}

    def forbidden_exchange_bundle() -> Any:
        raise AssertionError("broker-reader publisher must not load exchange credentials")

    monkeypatch.setattr(
        cli_module,
        "load_profiled_base_publisher_runtime_credentials_if_available",
        forbidden_exchange_bundle,
    )
    monkeypatch.setattr(
        cli_module,
        "consumer_security_context_from_systemd_credentials",
        lambda: security_context,
    )
    monkeypatch.setattr(cli_module, "_raw_redis_client", lambda _url: client)
    monkeypatch.setattr(
        cli_module,
        "default_commission_broker_store",
        lambda _path: broker_store,
    )

    class FakePublisher:
        status_path = (tmp_path / "status.json").absolute()

        def run_cycle(self) -> dict[str, Any]:
            return {
                "classification": "CYCLE_COMPLETE_MASKED_COST_OBSERVATIONS",
                "commission_cost_mode": (
                    BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
                ),
                "commission_credentials_available": False,
                "commission_broker_reader_available": True,
                "exchange_credentials_loaded_by_publisher": False,
                "authority_semantics": {
                    "published_child_trainer_admission_authorized": False,
                },
            }

    def fake_publisher(**kwargs: Any) -> FakePublisher:
        captured_arguments.update(kwargs)
        return FakePublisher()

    monkeypatch.setattr(cli_module, "ProfiledBaseFeaturePublisherV1", fake_publisher)
    cli_module._STOP = False  # noqa: SLF001
    broker_root = (tmp_path / "broker").absolute()

    exit_code = cli_module.main(
        ["--once", "--commission-broker-data-root", str(broker_root)]
    )

    assert exit_code == 0
    assert captured_arguments["redis_client"] is client
    assert captured_arguments["commission_cost_mode"] == (
        BROKER_AUTHENTICATED_COST_EVIDENCE_WITH_MASKED_FALLBACK_MODE
    )
    reader = captured_arguments["commission_evidence_reader"]
    assert callable(reader)
    assert reader.keywords["store"] is broker_store
    assert reader.keywords["security_context"] is security_context
    rendered = capsys.readouterr().out
    assert '"commission_broker_reader_available":true' in rendered
    assert '"exchange_credentials_loaded_by_publisher":false' in rendered
