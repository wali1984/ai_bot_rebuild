from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import causal_cost_evidence_v1
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.causal_expected_notional_policy_v1 import (
    CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256,
    CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256,
    CAUSAL_EXPECTED_NOTIONAL_POLICY_ID,
    CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY,
    CausalExpectedNotionalPolicyV1IntegrityError,
    CausalExpectedNotionalPolicyV1ValidationError,
    build_causal_expected_notional_policy_v1,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)

_SYMBOL = "BTCUSDT"
_SNAPSHOT = "profiled-feature-snapshot:BTCUSDT:2026-07-21T12:00:00Z"
_SERVER_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
_DECISION_AT = datetime(2026, 7, 21, 12, 0, 0, 500_000, tzinfo=UTC)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _status(*, count: int = 2, gross_notional_usd: float = 3_000.0) -> dict[str, Any]:
    source_hashes = [
        hashlib.sha256(f"source-{index}".encode()).hexdigest() for index in range(count)
    ]
    fact_hashes = [hashlib.sha256(f"fact-{index}".encode()).hexdigest() for index in range(count)]
    contract_material = {
        "schema_version": "paper_candidate_canonical_aggregate_contract_v1",
        "producer": "v2_trade_management_paper_loop",
        "paper_only": True,
        "contract_hash_algorithm": "sha256(canonical-json-v1)",
        "operator_projection_is_canonical_evidence": False,
        "source_row_count": count,
        "source_rows_all_hashable": True,
        "source_rows_aggregate_sha256": _canonical_sha256(source_hashes),
        "contract_evaluated_row_count": count,
        "contract_fact_hashes": fact_hashes,
        "contract_fact_hashes_all_hashable": True,
        "contract_fact_hashes_aggregate_sha256": _canonical_sha256(fact_hashes),
        "zero_liquidation": {},
        "hedge": {},
        "capital": {
            "candidate_count": count,
            "numeric_sums": {
                "allocated_margin_usd": 1_500.0,
                "gross_notional_usd": gross_notional_usd,
                "risk_budget_usd": 30.0,
            },
        },
    }
    contract = {
        **contract_material,
        "contract_hash": _canonical_sha256(contract_material),
    }
    return {
        "allocator": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        "fixed_runtime_notional_removed": True,
        "paper_candidates_with_allocation": count,
        "candidate_allocation_count": count,
        # Deliberately misleading projection: it must never drive the policy.
        "candidate_allocations": [
            {"gross_notional_usd": 99_999.0, "operator_projection_only": True}
        ],
        "candidate_allocations_complete": False,
        "candidate_allocations_projection_only": True,
        "candidate_allocations_source_row_count": count,
        "candidate_allocations_source_hashes": [
            {
                "source_row_index": index,
                "source_row_canonical_sha256": source_hash,
            }
            for index, source_hash in enumerate(source_hashes)
        ],
        "candidate_allocations_all_source_rows_hashable": True,
        "candidate_allocations_unhashable_source_row_count": 0,
        "candidate_allocations_aggregate_sha256": _canonical_sha256(source_hashes),
        "candidate_allocations_canonical_aggregate_contract": contract,
        "candidate_allocations_selected_before_outcome": True,
        "candidate_allocations_future_labels_used_as_features": False,
        "generated_utc": "2026-07-21T11:59:59.500Z",
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "old_redis_writes": False,
    }


class _Pipeline:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def type(self, _key: str) -> _Pipeline:
        return self

    def getrange(self, _key: str, _start: int, _end: int) -> _Pipeline:
        return self

    def pttl(self, _key: str) -> _Pipeline:
        return self

    def time(self) -> _Pipeline:
        return self

    def execute(self) -> list[object]:
        return list(self.responses)

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Client:
    def __init__(self, responses: list[object]) -> None:
        self._pipeline = _Pipeline(responses)

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _Pipeline:
        assert transaction is True
        return self._pipeline


def _raw_status(status: dict[str, Any]) -> bytes:
    # This is the live producer's current serialization dialect.
    return json.dumps(status).encode("utf-8")


def _batch(
    raw: bytes,
    *,
    pttl_ms: int = 60_000,
    server_at: datetime = _SERVER_AT,
):
    seconds = int(server_at.timestamp())
    return read_atomic_redis_sources(
        _Client([b"string", raw, pttl_ms, (seconds, server_at.microsecond)]),
        [CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY],
    )


def _build(
    tmp_path,
    *,
    status: dict[str, Any] | None = None,
    raw: bytes | None = None,
    pttl_ms: int = 60_000,
    server_at: datetime = _SERVER_AT,
    decision_at: datetime = _DECISION_AT,
    symbol: str = _SYMBOL,
    snapshot: str = _SNAPSHOT,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = raw if raw is not None else _raw_status(status or _status())
    store = ImmutableSourcePayloadStore(tmp_path / "cas")
    token = build_causal_expected_notional_policy_v1(
        atomic_capture=_batch(payload, pttl_ms=pttl_ms, server_at=server_at),
        source_payload_store=store,
        symbol=symbol,
        feature_snapshot_identity=snapshot,
        feature_snapshot_decision_time=decision_at,
    )
    return token, store


def _rehash_contract(status: dict[str, Any]) -> None:
    contract = status["candidate_allocations_canonical_aggregate_contract"]
    material = dict(contract)
    material.pop("contract_hash", None)
    contract["contract_hash"] = _canonical_sha256(material)


def test_factory_derives_full_aggregate_mean_and_is_directly_cost_compatible(
    tmp_path,
) -> None:
    token, store = _build(tmp_path)

    assert token.expected_notional_usd == 1_500.0
    assert token.aggregate_candidate_count == 2
    assert token.aggregate_gross_notional_usd == 3_000.0
    assert token.notional_artifact["expected_notional_usd"] == 1_500.0
    assert token.notional_artifact["policy_id"] == CAUSAL_EXPECTED_NOTIONAL_POLICY_ID
    assert token.notional_artifact["fallback_used"] is False
    assert token.notional_artifact["static_default_used"] is False
    assert token.source_read_receipt["operator_projection_used"] is False
    assert token.source_read_receipt["candidate_supply_status"] == (
        "POSITIVE_HASH_BOUND_AGGREGATE_AVAILABLE"
    )
    assert token.source_read_receipt["zero_candidate_handling"] == (
        "FAIL_CLOSED_NO_ARTIFACT_NO_DEFAULT"
    )
    assert token.source_read_receipt["derivation_formula"] == (
        "capital.numeric_sums.gross_notional_usd/capital.candidate_count"
    )
    assert token.source_read_receipt["implementation_contract_sha256"] == (
        CAUSAL_EXPECTED_NOTIONAL_IMPLEMENTATION_CONTRACT_SHA256
    )
    assert token.source_read_receipt["policy_config_sha256"] == (
        CAUSAL_EXPECTED_NOTIONAL_POLICY_CONFIG_SHA256
    )
    assert (
        store.get(
            token.raw_status_address.payload_sha256,
            expected_byte_count=token.raw_status_address.payload_byte_count,
        )
        == token.raw_status_bytes
    )
    for authority in (
        "trainer_authority",
        "prediction_authority",
        "paper_authority",
        "live_authority",
        "order_authority",
    ):
        assert token.contract[authority] is False

    source, receipt, objects = causal_cost_evidence_v1._validate_notional_evidence(  # noqa: SLF001
        store=store,
        artifact_bytes=token.notional_artifact_bytes,
        receipt=token.notional_receipt,
        expected_notional_usd=token.expected_notional_usd,
        symbol=_SYMBOL,
        feature_snapshot_identity=_SNAPSHOT,
        decision_at=_DECISION_AT,
    )
    assert source["expected_notional_usd"] == 1_500.0
    assert receipt["receipt_sha256"] == token.notional_receipt_sha256
    assert len(objects) == 2


def test_outer_whitespace_and_key_order_are_exactly_distinct_but_semantically_equal(
    tmp_path,
) -> None:
    status = _status()
    normal = json.dumps(status).encode()
    reordered = json.dumps(dict(reversed(list(status.items()))), indent=2).encode()

    first, _ = _build(tmp_path / "first", raw=normal)
    second, _ = _build(tmp_path / "second", raw=reordered)

    assert first.raw_status_address.payload_sha256 != second.raw_status_address.payload_sha256
    assert first.expected_notional_usd == second.expected_notional_usd == 1_500.0
    assert first.embedded_aggregate_contract_hash == second.embedded_aggregate_contract_hash
    assert first.source_read_receipt["outer_status_canonical_serialization_required"] is False


@pytest.mark.parametrize(
    ("pttl_ms", "decision_at", "reason"),
    [
        (-1, _DECISION_AT, "EXPECTED_NOTIONAL_SOURCE_PERSISTED_EXPIRY_MISSING"),
        (0, _DECISION_AT, "EXPECTED_NOTIONAL_SOURCE_PERSISTED_EXPIRY_MISSING"),
        (500, _DECISION_AT, "EXPECTED_NOTIONAL_SOURCE_EXPIRED_AT_DECISION"),
    ],
)
def test_missing_persistent_or_expired_ttl_fails_closed(
    tmp_path,
    pttl_ms: int,
    decision_at: datetime,
    reason: str,
) -> None:
    with pytest.raises(CausalExpectedNotionalPolicyV1ValidationError, match=reason):
        _build(tmp_path, pttl_ms=pttl_ms, decision_at=decision_at)


def test_missing_source_fails_closed(tmp_path) -> None:
    missing = read_atomic_redis_sources(
        _Client([b"none", b"", -2, (int(_SERVER_AT.timestamp()), 0)]),
        [CAUSAL_EXPECTED_NOTIONAL_SOURCE_KEY],
    )
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_SOURCE_MISSING",
    ):
        build_causal_expected_notional_policy_v1(
            atomic_capture=missing,
            source_payload_store=ImmutableSourcePayloadStore(tmp_path / "cas"),
            symbol=_SYMBOL,
            feature_snapshot_identity=_SNAPSHOT,
            feature_snapshot_decision_time=_DECISION_AT,
        )


def test_future_atomic_or_generated_clocks_fail_closed(tmp_path) -> None:
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_ATOMIC_CAPTURE_AFTER_DECISION",
    ):
        _build(
            tmp_path / "atomic",
            server_at=datetime(2026, 7, 21, 12, 0, 1, tzinfo=UTC),
        )

    future = _status()
    future["generated_utc"] = "2026-07-21T12:00:00.250Z"
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_SOURCE_GENERATED_AFTER_OBSERVATION_OR_DECISION",
    ):
        _build(tmp_path / "generated", status=future)


@pytest.mark.parametrize("tamper", ["hash", "count", "sum"])
def test_hash_count_and_sum_tamper_fail_closed(tmp_path, tamper: str) -> None:
    status = _status()
    contract = status["candidate_allocations_canonical_aggregate_contract"]
    if tamper == "hash":
        contract["contract_hash"] = "0" * 64
    elif tamper == "count":
        contract["source_row_count"] = 3
    else:
        contract["capital"]["numeric_sums"]["gross_notional_usd"] = 3_001.0

    with pytest.raises(CausalExpectedNotionalPolicyV1IntegrityError):
        _build(tmp_path, status=status)


def test_rehashed_internal_count_inconsistency_fails_closed(tmp_path) -> None:
    status = _status()
    contract = status["candidate_allocations_canonical_aggregate_contract"]
    contract["source_row_count"] = 3
    _rehash_contract(status)

    with pytest.raises(
        CausalExpectedNotionalPolicyV1IntegrityError,
        match="EXPECTED_NOTIONAL_SOURCE_COUNT_MISMATCH",
    ):
        _build(tmp_path, status=status)


@pytest.mark.parametrize("kind", ["nan", "duplicate", "invalid_utf8"])
def test_nonfinite_duplicate_or_invalid_json_bytes_fail_closed(tmp_path, kind: str) -> None:
    raw = _raw_status(_status())
    if kind == "nan":
        raw = raw.replace(b'"gross_notional_usd": 3000.0', b'"gross_notional_usd": NaN')
    elif kind == "duplicate":
        raw = raw.replace(b'"paper_only": true', b'"paper_only": true, "paper_only": true', 1)
    else:
        raw += b"\xff"

    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_SOURCE_JSON_INVALID",
    ):
        _build(tmp_path, raw=raw)


def test_zero_candidates_and_nonpositive_or_nonfinite_sum_fail_closed(tmp_path) -> None:
    zero = _status(count=0, gross_notional_usd=0.0)
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_CANDIDATE_SUPPLY_ZERO_NO_POLICY_ARTIFACT",
    ):
        _build(tmp_path / "zero", status=zero)

    nonpositive = _status(gross_notional_usd=0.0)
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_AGGREGATE_GROSS_NOTIONAL_ZERO_NO_POLICY_ARTIFACT",
    ):
        _build(tmp_path / "nonpositive", status=nonpositive)

    raw = _raw_status(_status()).replace(
        b'"gross_notional_usd": 3000.0',
        b'"gross_notional_usd": 1e999',
    )
    with pytest.raises(CausalExpectedNotionalPolicyV1ValidationError):
        _build(tmp_path / "nonfinite", raw=raw)


def test_factory_exposes_no_default_notional_and_rejects_static_source_flags(
    tmp_path,
) -> None:
    signature = inspect.signature(build_causal_expected_notional_policy_v1)
    assert "expected_notional_usd" not in signature.parameters
    assert "default_notional_usd" not in signature.parameters
    assert "fallback_notional_usd" not in signature.parameters

    static = _status()
    static["fixed_runtime_notional_removed"] = False
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_SOURCE_AUTHORITY_OR_ADAPTIVITY_INVALID",
    ):
        _build(tmp_path, status=static)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("allocator", "DIFFERENT_ALLOCATOR"),
        ("candidate_allocations_complete", True),
    ),
)
def test_wrong_outer_source_identity_fails_closed(
    tmp_path,
    field: str,
    replacement: object,
) -> None:
    status = _status()
    status[field] = replacement
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_SOURCE_IDENTITY_INVALID",
    ):
        _build(tmp_path, status=status)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("producer", "different_paper_loop"),
        ("paper_only", False),
    ),
)
def test_wrong_rehashed_embedded_producer_identity_fails_closed(
    tmp_path,
    field: str,
    replacement: object,
) -> None:
    status = _status()
    status["candidate_allocations_canonical_aggregate_contract"][field] = replacement
    _rehash_contract(status)
    with pytest.raises(
        CausalExpectedNotionalPolicyV1ValidationError,
        match="EXPECTED_NOTIONAL_CANONICAL_AGGREGATE_CONTRACT_INVALID",
    ):
        _build(tmp_path, status=status)


def test_cross_symbol_and_snapshot_substitution_is_rejected_by_consumer(tmp_path) -> None:
    token, store = _build(tmp_path)
    with pytest.raises(causal_cost_evidence_v1.CausalCostEvidenceV1ValidationError):
        causal_cost_evidence_v1._validate_notional_evidence(  # noqa: SLF001
            store=store,
            artifact_bytes=token.notional_artifact_bytes,
            receipt=token.notional_receipt,
            expected_notional_usd=token.expected_notional_usd,
            symbol="ETHUSDT",
            feature_snapshot_identity=_SNAPSHOT,
            decision_at=_DECISION_AT,
        )
    with pytest.raises(causal_cost_evidence_v1.CausalCostEvidenceV1ValidationError):
        causal_cost_evidence_v1._validate_notional_evidence(  # noqa: SLF001
            store=store,
            artifact_bytes=token.notional_artifact_bytes,
            receipt=token.notional_receipt,
            expected_notional_usd=token.expected_notional_usd,
            symbol=_SYMBOL,
            feature_snapshot_identity="different-snapshot",
            decision_at=_DECISION_AT,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("source_read_receipt_bytes", b"{}"),
        ("notional_artifact_bytes", b"{}"),
        ("notional_receipt_bytes", b"{}"),
        ("module_code_sha256", "0" * 64),
        ("source_read_receipt_sha256", "0" * 64),
        ("expected_notional_usd", 42.0),
    ],
)
def test_receipt_cas_code_and_scalar_token_tamper_fail_closed(
    tmp_path,
    field: str,
    replacement: object,
) -> None:
    token, _ = _build(tmp_path)
    object.__setattr__(token, field, replacement)

    with pytest.raises(CausalExpectedNotionalPolicyV1IntegrityError):
        _ = token.contract


def test_raw_cas_binding_and_atomic_batch_tamper_fail_closed(tmp_path) -> None:
    token, _ = _build(tmp_path)
    object.__setattr__(token, "raw_status_bytes", b"{}")
    with pytest.raises(CausalExpectedNotionalPolicyV1IntegrityError):
        _ = token.contract

    clean, _ = _build(tmp_path / "batch")
    altered = deepcopy(clean._atomic_capture)  # noqa: SLF001
    object.__setattr__(altered, "batch_material_sha256", "0" * 64)
    object.__setattr__(clean, "_atomic_capture", altered)
    with pytest.raises(
        CausalExpectedNotionalPolicyV1IntegrityError,
        match="EXPECTED_NOTIONAL_ATOMIC_CAPTURE_BINDING_INVALID",
    ):
        _ = clean.contract
