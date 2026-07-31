from __future__ import annotations

import hashlib
import json
import math
from abc import ABCMeta
from collections import UserDict
from collections.abc import ItemsView, Iterator, Mapping
from typing import cast

import pytest

from v2.backend.app.services.paper_trade_management import (
    margin_accounting as margin_accounting_module,
)
from v2.backend.app.services.paper_trade_management.margin_accounting import (
    PAPER_CANDIDATE_COLLECTION_INVALID_REASON,
    PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID_REASON,
    PAPER_INSUFFICIENT_FREE_MARGIN_REASON,
    PAPER_MARGIN_BUFFER_INVALID_REASON,
    PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON,
    PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON,
    PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON,
    PAPER_MARGIN_RESERVATION_INCLUSION_FLAG_INVALID_REASON,
    PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON,
    build_paper_margin_status,
    canonical_margin_requirement,
    reserve_paper_candidate_margin,
)

_BRACKET_SOURCE = "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET"


class _ExplodingCandidateMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError(f"unreadable:{key}")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("unreadable")

    def __len__(self) -> int:
        return 1


class _ExplodeOnceThenValidMapping(Mapping[str, object]):
    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = dict(values)
        self.iteration_count = 0

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        self.iteration_count += 1
        if self.iteration_count == 1:
            raise RuntimeError("first snapshot explodes")
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class _ValidOnceThenExplodingMapping(Mapping[str, object]):
    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = dict(values)
        self.iteration_count = 0

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        self.iteration_count += 1
        if self.iteration_count > 1:
            raise RuntimeError("mapping was read more than once")
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class _DuplicateRouteItemsMapping(Mapping[str, object]):
    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = dict(values)
        self.items_call_count = 0

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def items(self) -> ItemsView[str, object]:
        self.items_call_count += 1
        return cast(
            ItemsView[str, object],
            [
                *self._values.items(),
                ("routes_to_live", True),
                ("routes_to_live", False),
            ],
        )


class _MalformedItemsMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0

    def items(self) -> ItemsView[str, object]:
        return cast(ItemsView[str, object], [("routes_to_live",)])


class _RaiseAfterOneIterable:
    def __init__(self, value: object) -> None:
        self._value = value

    def __iter__(self) -> Iterator[object]:
        yield self._value
        raise RuntimeError("attacker-controlled outer iterator text")


class _ExplodingFloat:
    def __float__(self) -> float:
        raise RuntimeError("attacker-controlled scalar text")


class _ExplodingIdentity:
    def __str__(self) -> str:
        raise RuntimeError("ATTACKER_SECRET_IDENTITY_TEXT")

    def __repr__(self) -> str:
        return "ATTACKER_SECRET_IDENTITY_TEXT"


class _LeakingIdentity:
    def __str__(self) -> str:
        return "ATTACKER_SECRET_NONRAISING_IDENTITY_TEXT"

    def __repr__(self) -> str:
        return "ATTACKER_SECRET_NONRAISING_IDENTITY_TEXT"


class _HostileScalar:
    def __eq__(self, other: object) -> bool:
        del other
        raise RuntimeError("ATTACKER_SECRET_EQ_TEXT")

    def __ne__(self, other: object) -> bool:
        del other
        raise RuntimeError("ATTACKER_SECRET_NE_TEXT")

    def __float__(self) -> float:
        raise RuntimeError("ATTACKER_SECRET_FLOAT_TEXT")

    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("ATTACKER_SECRET_ITER_TEXT")

    def __str__(self) -> str:
        return "ATTACKER_SECRET_STR_TEXT"

    def __repr__(self) -> str:
        return "ATTACKER_SECRET_REPR_TEXT"


class _HostileList(list[object]):
    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("ATTACKER_SECRET_LIST_ITER_TEXT")


class _ClassMetadataTrap:
    def __init__(self) -> None:
        self.class_metadata_observations = 0

    def __getattribute__(self, name: str) -> object:
        if name == "__class__":
            observed = object.__getattribute__(self, "class_metadata_observations")
            object.__setattr__(self, "class_metadata_observations", observed + 1)
            raise RuntimeError("ATTACKER_SECRET_CLASS_METADATA_TEXT")
        return object.__getattribute__(self, name)

    def __float__(self) -> float:
        raise RuntimeError("ATTACKER_SECRET_CLASS_FLOAT_TEXT")

    def __str__(self) -> str:
        return "ATTACKER_SECRET_CLASS_STR_TEXT"

    def __repr__(self) -> str:
        return "ATTACKER_SECRET_CLASS_REPR_TEXT"


_HOSTILE_METACLASS_NAME_OBSERVATIONS = {"count": 0}


class _HostileMappingMeta(ABCMeta):
    def __getattribute__(cls, name: str) -> object:
        if name == "__name__":
            _HOSTILE_METACLASS_NAME_OBSERVATIONS["count"] += 1
            raise RuntimeError("ATTACKER_SECRET_METACLASS_NAME_TEXT")
        return super().__getattribute__(name)


class _HostileMetaclassNameMapping(
    Mapping[str, object],
    metaclass=_HostileMappingMeta,
):
    def __init__(self) -> None:
        self._values = {
            "fill_id": "",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "fill_price": 100.0,
            "maintenance_margin_rate": 0.005,
        }

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _hash(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_final_admission_receipt(row: dict[str, object]) -> dict[str, object]:
    allocation = row.get("adaptive_allocation")
    if not isinstance(allocation, dict):
        current_capital = row.get("current_capital_accounting")
        current_leverage = (
            current_capital.get("effective_leverage") if isinstance(current_capital, dict) else None
        )
        allocation = {
            "effective_leverage": row.get("effective_leverage") or current_leverage or 1.0,
        }
        row["adaptive_allocation"] = allocation
    raw_quantity = row.get("net_quantity") or row.get("quantity") or row.get("qty")
    raw_price = (
        row.get("avg_entry_price")
        or row.get("fill_price")
        or row.get("entry_price")
        or row.get("price")
    )
    assert raw_quantity is not None
    assert raw_price is not None
    notional = abs(float(str(raw_quantity)) * float(str(raw_price)))
    allocation.setdefault("gross_notional_usd", notional)
    symbol = row.get("symbol")
    lineage_ids = {"signal_id": row.get("fill_id") or row.get("position_id")}
    model_inputs = allocation.get("model_inputs")
    risk_envelope = model_inputs.get("risk_envelope") if isinstance(model_inputs, dict) else {}
    allocation_input_material = {
        "schema_version": "adaptive_capital_allocation_input_v1",
        "mode": "paper",
        "risk_envelope": dict(risk_envelope) if isinstance(risk_envelope, dict) else {},
        "allocation_input": {
            "symbol": symbol,
            "lineage_ids": lineage_ids,
            "gross_notional_usd": notional,
        },
    }
    allocation_input_hash = _hash(allocation_input_material)
    allocation.update(
        {
            "symbol": symbol,
            "allocator_decision": "ALLOW_WITH_SIZE",
            "allocation_input_schema_version": ("adaptive_capital_allocation_input_v1"),
            "allocation_input_hash_algorithm": "sha256(canonical-json-v1)",
            "allocation_input_hash": allocation_input_hash,
            "allocation_input_material": allocation_input_material,
            "allocation_id": f"alloc_{allocation_input_hash[:24]}",
            "lineage_ids": lineage_ids,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )
    allocation_hash = _hash(allocation)
    leverage = float(allocation["effective_leverage"])
    final_decision_time = "2026-07-18T12:00:01.750000Z"
    final_reread = {
        "status": "READY",
        "evidence_usable": True,
        "symbol": row.get("symbol"),
        "candidate_notional": notional,
        "candidate_notional_contract": (
            "TOTAL_ABSOLUTE_SYMBOL_POSITION_NOTIONAL_AFTER_CANDIDATE_FILL"
        ),
        "evidence_key": "paper:test:bracket:BTCUSDT",
        "decision_time": row.get("paper_allocation_decision_time"),
        "consumer_observed_at": "2026-07-18T12:00:01.250000Z",
        "current_checked_at": "2026-07-18T12:00:01.500000Z",
        "maintenance_margin_rate": row.get("maintenance_bracket_maint_margin_ratio"),
        "maintenance_margin_cum": row.get("maintenance_bracket_cum"),
        "max_initial_leverage": row.get("maintenance_bracket_max_initial_leverage"),
        "selected_bracket": row.get("maintenance_bracket_id"),
        "source": row.get("maintenance_bracket_source"),
        "source_endpoint": "GET /fapi/v1/leverageBracket",
        "available_at": row.get("maintenance_bracket_available_at"),
        "expires_at": row.get("maintenance_bracket_expires_at"),
        "content_checksum_sha256": row.get("maintenance_bracket_evidence_checksum_sha256"),
        "evidence_hmac_sha256": row.get("maintenance_bracket_evidence_hmac_sha256"),
        "credential_binding_id": row.get("maintenance_bracket_account_binding_id"),
        "exchange_environment": row.get("maintenance_bracket_environment_id"),
        "evidence_auth_key_id": row.get("maintenance_bracket_key_id"),
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    maintenance_contract = {
        field: row.get(field)
        for field in (
            "maintenance_bracket_id",
            "maintenance_bracket_maint_margin_ratio",
            "maintenance_bracket_cum",
            "maintenance_bracket_max_initial_leverage",
            "maintenance_bracket_evidence_checksum_sha256",
            "maintenance_bracket_evidence_hmac_sha256",
            "maintenance_bracket_account_binding_id",
            "maintenance_bracket_environment_id",
            "maintenance_bracket_key_id",
            "maintenance_bracket_source",
            "maintenance_bracket_available_at",
            "maintenance_bracket_expires_at",
            "maintenance_bracket_consumer_observed_at",
        )
    }
    maintenance_contract["final_authenticated_reread"] = final_reread
    bound_material = {
        "final_decision_time": final_decision_time,
        "identity": {
            "intent_id": row.get("fill_id") or row.get("position_id"),
            "symbol": row.get("symbol"),
            "allocation_id": allocation["allocation_id"],
        },
        "allocator_contract": {
            "allocation_hash": allocation_hash,
            "allocation_id": allocation["allocation_id"],
            "allocation_input_hash": allocation_input_hash,
            "allocation_input_material": allocation_input_material,
        },
        "maintenance_bracket_contract": maintenance_contract,
        "adaptive_allocation_hash": allocation_hash,
        "sizing": {
            "notional": notional,
            "effective_leverage": leverage,
        },
    }
    bound_hash = _hash(bound_material)
    contract_material = {
        "schema_version": "paper_final_admission_contract_v3",
        "status": "PASS",
        "validation_started_at": "2026-07-18T12:00:01.100000Z",
        "final_decision_time": final_decision_time,
        "maintenance_bracket_revalidation": final_reread,
        "bound_material_hash": bound_hash,
        "bound_material": bound_material,
        "rejection_reasons": [],
    }
    receipt_hash = _hash(contract_material)
    row.update(
        {
            "paper_final_admission_contract": {
                **contract_material,
                "receipt_hash": receipt_hash,
            },
            "paper_final_admission_status": "PASS",
            "paper_final_admission_decision_time": final_decision_time,
            "paper_final_admission_bound_material_hash": bound_hash,
            "paper_final_admission_receipt_hash": receipt_hash,
        }
    )
    return row


def _without_final_admission_receipt(row: dict[str, object]) -> dict[str, object]:
    for field in (
        "paper_final_admission_contract",
        "paper_final_admission_status",
        "paper_final_admission_decision_time",
        "paper_final_admission_bound_material_hash",
        "paper_final_admission_receipt_hash",
    ):
        row.pop(field, None)
    return row


def _with_bracket_proof(
    row: dict[str, object],
    *,
    maximum_leverage: float,
) -> dict[str, object]:
    checksum = "a" * 64
    hmac_sha256 = "b" * 64
    binding = "testnet:paper-account:test-key"
    evidence = {
        "prevalidated": True,
        "symbol": row.get("symbol"),
        "bracket_id": 1,
        "maint_margin_ratio": 0.005,
        "cum": 0.0,
        "max_initial_leverage": maximum_leverage,
        "evidence_hash": checksum,
        "evidence_checksum_sha256": checksum,
        "evidence_hmac_sha256": hmac_sha256,
        "binding": binding,
        "environment_id": "testnet",
        "key_id": "test-key",
        "source": _BRACKET_SOURCE,
        "available_at": "2026-07-18T12:00:00Z",
        "expires_at": "2026-07-19T12:00:00Z",
        "consumer_observed_at": "2026-07-18T12:00:01Z",
    }
    row.update(
        {
            "maintenance_margin_rate": 0.005,
            "maintenance_bracket_prevalidated": True,
            "maintenance_bracket_evidence_status": "READY",
            "maintenance_bracket_id": 1,
            "maintenance_bracket_maint_margin_ratio": 0.005,
            "maintenance_bracket_cum": 0.0,
            "maintenance_bracket_max_initial_leverage": maximum_leverage,
            "maintenance_bracket_evidence_hash": checksum,
            "maintenance_bracket_evidence_checksum_sha256": checksum,
            "maintenance_bracket_evidence_hmac_sha256": hmac_sha256,
            "maintenance_bracket_binding": binding,
            "maintenance_bracket_account_binding_id": binding,
            "maintenance_bracket_environment_id": "testnet",
            "maintenance_bracket_key_id": "test-key",
            "maintenance_bracket_source": _BRACKET_SOURCE,
            "maintenance_bracket_available_at": "2026-07-18T12:00:00Z",
            "maintenance_bracket_expires_at": "2026-07-19T12:00:00Z",
            "maintenance_bracket_consumer_observed_at": ("2026-07-18T12:00:01Z"),
            "maintenance_bracket_evidence": evidence,
            "paper_allocation_decision_time": "2026-07-18T12:00:00.500000Z",
            "maintenance_margin_mark_time": "2026-07-18T12:00:02Z",
        }
    )
    return _with_final_admission_receipt(row)


def _complete_raw_bracket_context(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "prevalidated": row.get("maintenance_bracket_prevalidated"),
        "status": row.get("maintenance_bracket_evidence_status"),
        "evidence_usable": True,
        "symbol": row.get("symbol"),
        "selected_bracket": row.get("maintenance_bracket_id"),
        "maintenance_margin_rate": row.get("maintenance_bracket_maint_margin_ratio"),
        "maintenance_margin_cum": row.get("maintenance_bracket_cum"),
        "max_initial_leverage": row.get("maintenance_bracket_max_initial_leverage"),
        "content_checksum_sha256": row.get("maintenance_bracket_evidence_checksum_sha256"),
        "evidence_hmac_sha256": row.get("maintenance_bracket_evidence_hmac_sha256"),
        "credential_binding_id": row.get("maintenance_bracket_account_binding_id"),
        "exchange_environment": row.get("maintenance_bracket_environment_id"),
        "evidence_auth_key_id": row.get("maintenance_bracket_key_id"),
        "source": row.get("maintenance_bracket_source"),
        "available_at": row.get("maintenance_bracket_available_at"),
        "expires_at": row.get("maintenance_bracket_expires_at"),
        "consumer_observed_at": row.get("maintenance_bracket_consumer_observed_at"),
    }


def _candidate(
    symbol: str,
    *,
    fill_id: str,
    notional: float,
    leverage: float,
    confidence: float,
) -> dict[str, object]:
    row: dict[str, object] = {
        "fill_id": fill_id,
        "symbol": symbol,
        "timeframe": "1m",
        "side": "long",
        "quantity": notional / 100.0,
        "fill_price": 100.0,
        "effective_leverage": leverage,
        "maintenance_margin_rate": 0.005,
        "adaptive_allocation": {
            "effective_leverage": leverage,
            "model_inputs": {
                "maintenance_margin_rate": 0.005,
                "risk_envelope": {
                    "max_effective_leverage": max(3.0, leverage),
                },
            },
        },
        "confidence_calibrated": confidence,
        "paper_fill_allowed": True,
    }
    if leverage > 1.0:
        _with_bracket_proof(row, maximum_leverage=75.0)
    return row


def test_candidates_cannot_overbook_and_static_symbol_preference_is_ignored() -> None:
    eth = _candidate(
        "ETHUSDT",
        fill_id="fill-eth",
        notional=500.0,
        leverage=1.0,
        confidence=0.99,
    )
    btc = _candidate(
        "BTCUSDT",
        fill_id="fill-btc",
        notional=500.0,
        leverage=1.0,
        confidence=0.70,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [eth, btc],
        equity=1_000.0,
        wallet_balance=1_000.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.10,
        preferred_symbols={"BTCUSDT"},
    )

    assert [row["fill_id"] for row in accepted] == ["fill-eth"]
    assert [row["fill_id"] for row in blocked] == ["fill-btc"]
    assert (
        PAPER_INSUFFICIENT_FREE_MARGIN_REASON
        in blocked[0]["paper_margin_reservation_block_reasons"]
    )
    assert status["used_margin_usd"] == 0.0
    assert status["newly_reserved_margin_usd"] == pytest.approx(500.0)
    assert status["free_margin_usd"] == pytest.approx(500.0)
    assert status["margin_buffer_usd"] == pytest.approx(100.0)
    assert status["free_margin_after_buffer_usd"] == pytest.approx(400.0)
    assert status["invariant_holds"] is True
    assert status["no_negative_free_margin"] is True
    assert status["cross_process_atomic"] is False
    assert status["single_active_writer_required"] is True
    assert status["static_symbol_priority_applied"] is False


def test_direct_reservation_crossing_adaptive_buffer_fails_status_closed() -> None:
    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=[],
        min_available_margin_buffer_pct=0.50,
        newly_reserved_margin_usd=75.0,
    )

    assert status["usable_margin_after_buffer_before_reservations_usd"] == 50.0
    assert status["newly_reserved_margin_usd"] == 75.0
    assert status["margin_buffer_deficit_usd"] == 25.0
    assert status["margin_buffer_invariant_holds"] is False
    assert status["numeric_invariant_holds"] is True
    assert status["status"] == "FAIL_CLOSED"
    assert status["invariant_holds"] is False
    assert status["admission_inputs_valid"] is False
    assert PAPER_INSUFFICIENT_FREE_MARGIN_REASON in status["failure_reasons"]


def test_existing_open_position_margin_is_reserved_before_new_candidate() -> None:
    existing_position = _with_bracket_proof(
        {
            "position_id": "paper_pos_existing",
            "symbol": "SOLUSDT",
            "side": "long",
            "net_quantity": 8.0,
            "avg_entry_price": 100.0,
            "effective_leverage": 2.0,
            "maintenance_margin_rate": 0.005,
            "current_capital_accounting": {
                "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
                "effective_leverage": 2.0,
                "effective_leverage_validated": True,
                "decision_time_max_effective_leverage": 20.0,
                "maintenance_margin_rate": 0.005,
            },
            # Deliberately stale: canonical accounting must ignore this value.
            "allocated_margin_usd": 1.0,
        },
        maximum_leverage=50.0,
    )
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-new",
        notional=550.0,
        leverage=1.0,
        confidence=0.90,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=1_000.0,
        wallet_balance=1_000.0,
        existing_open_positions=[existing_position],
        min_available_margin_buffer_pct=0.10,
        preferred_symbols={"BTCUSDT"},
    )

    assert accepted == []
    assert len(blocked) == 1
    assert status["used_margin_usd"] == pytest.approx(400.0)
    assert status["free_margin_before_reservations_usd"] == pytest.approx(600.0)
    assert status["margin_buffer_usd"] == pytest.approx(60.0)
    assert status["free_margin_after_buffer_usd"] == pytest.approx(540.0)
    assert status["newly_reserved_margin_usd"] == 0.0
    assert status["invariant_holds"] is True


def test_final_status_does_not_double_count_reservation_already_in_open_book() -> None:
    new_open_position = _with_bracket_proof(
        {
            "position_id": "paper_pos_new",
            "symbol": "BTCUSDT",
            "side": "long",
            "net_quantity": 5.0,
            "avg_entry_price": 100.0,
            "effective_leverage": 5.0,
            "maintenance_margin_rate": 0.005,
            "current_capital_accounting": {
                "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
                "effective_leverage": 5.0,
                "effective_leverage_validated": True,
                "decision_time_max_effective_leverage": 20.0,
                "maintenance_margin_rate": 0.005,
            },
        },
        maximum_leverage=75.0,
    )

    status = build_paper_margin_status(
        equity=1_000.0,
        wallet_balance=1_000.0,
        open_positions=[new_open_position],
        min_available_margin_buffer_pct=0.10,
        newly_reserved_margin_usd=100.0,
        reservations_included_in_open_positions=True,
    )

    assert status["used_margin_usd"] == pytest.approx(100.0)
    assert status["newly_reserved_margin_usd"] == pytest.approx(100.0)
    assert status["newly_reserved_included_in_used_margin"] is True
    assert status["projected_used_margin_usd"] == pytest.approx(100.0)
    assert status["free_margin_usd"] == pytest.approx(900.0)
    assert status["invariant_holds"] is True


def test_recommendation_only_leverage_never_reduces_candidate_margin() -> None:
    candidate = {
        "fill_id": "fill-recommendation-only",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "quantity": 5.0,
        "fill_price": 100.0,
        "recommended_leverage": 10.0,
        "maintenance_margin_rate": 0.005,
        "paper_fill_allowed": True,
    }

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=400.0,
        wallet_balance=400.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    requirement = blocked[0]["paper_margin_requirement"]
    assert requirement["effective_leverage"] == 1.0
    assert requirement["leverage_source"] == "FAIL_SAFE_DEFAULT_1X"
    assert requirement["canonical_margin_usd"] == pytest.approx(500.0)
    assert status["newly_reserved_margin_usd"] == 0.0


def test_recommendation_only_open_position_is_accounted_at_one_x() -> None:
    status = build_paper_margin_status(
        equity=1_000.0,
        wallet_balance=1_000.0,
        open_positions=[
            {
                "position_id": "paper_pos_recommendation_only",
                "symbol": "BTCUSDT",
                "side": "long",
                "net_quantity": 5.0,
                "avg_entry_price": 100.0,
                "recommended_leverage": 10.0,
                "maintenance_margin_rate": 0.005,
            }
        ],
    )

    assert status["accounting_complete"] is True
    assert status["used_margin_usd"] == pytest.approx(500.0)
    assert status["position_margin_rows"][0]["effective_leverage"] == 1.0


def test_target_only_open_position_fails_accounting_closed() -> None:
    status = build_paper_margin_status(
        equity=1_000.0,
        wallet_balance=1_000.0,
        open_positions=[
            {
                "position_id": "paper_pos_target_only",
                "symbol": "BTCUSDT",
                "side": "long",
                "target_quantity": 5.0,
                "fill_price": 100.0,
                "target_notional_usd": 500.0,
                "order_size_usd": 500.0,
                "maintenance_margin_rate": 0.005,
            }
        ],
    )

    assert status["accounting_complete"] is False
    assert status["invariant_holds"] is False
    assert status["free_margin_usd"] == 0.0
    assert status["free_margin_after_buffer_usd"] == 0.0
    invalid = status["invalid_open_position_margin_rows"][0]
    assert invalid["canonical_notional_usd"] is None
    assert "OPEN_EXECUTED_NOTIONAL_MISSING_OR_NON_POSITIVE" in invalid["invalid_reasons"]


def test_candidate_above_decision_time_envelope_is_rejected() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-above-envelope",
        notional=500.0,
        leverage=5.0,
        confidence=0.9,
    )
    candidate["adaptive_allocation"]["model_inputs"]["risk_envelope"][  # type: ignore[index]
        "max_effective_leverage"
    ] = 3.0
    _with_final_admission_receipt(candidate)

    accepted, blocked, _ = reserve_paper_candidate_margin(
        [candidate],
        equity=1_000.0,
        wallet_balance=1_000.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    assert (
        "EFFECTIVE_LEVERAGE_EXCEEDS_DECISION_TIME_ENVELOPE"
        in blocked[0]["paper_margin_requirement"]["invalid_reasons"]
    )


def test_uncapped_unsealed_extreme_allocation_leverage_stays_at_one_x() -> None:
    candidate = {
        "fill_id": "fill-uncapped-extreme",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "quantity": 5.0,
        "fill_price": 100.0,
        "effective_leverage": 1_000_000_000.0,
        "maintenance_margin_rate": 0.005,
        "adaptive_allocation": {
            "effective_leverage": 1_000_000_000.0,
            "model_inputs": {"maintenance_margin_rate": 0.005},
        },
        "paper_fill_allowed": True,
    }

    accepted, blocked, _ = reserve_paper_candidate_margin(
        [candidate],
        equity=400.0,
        wallet_balance=400.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    requirement = blocked[0]["paper_margin_requirement"]
    assert requirement["requested_effective_leverage"] == 1_000_000_000.0
    assert requirement["effective_leverage"] == 1.0
    assert requirement["unauthenticated_leverage_claim_downgraded_to_one_x"] is True
    assert requirement["canonical_margin_usd"] == pytest.approx(500.0)
    assert requirement["valid"] is True


def test_current_capital_leverage_uses_conservative_minimum_of_all_caps() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-cap-minimum",
        notional=100.0,
        leverage=10.0,
        confidence=0.9,
    )
    candidate["decision_time_max_effective_leverage"] = 30.0
    candidate["current_capital_accounting"] = {
        "decision_time_max_effective_leverage": 75.0,
    }
    candidate["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ]["max_effective_leverage"] = 20.0  # type: ignore[index]
    _with_bracket_proof(candidate, maximum_leverage=50.0)

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["decision_time_max_effective_leverage"] == 20.0
    assert requirement["leverage_cap_source"] == (
        "ALLOCATION_MODEL_INPUT_RISK_ENVELOPE_MAX_EFFECTIVE_LEVERAGE"
    )
    assert requirement["decision_time_leverage_cap_evidence"] == [
        {
            "source": "CURRENT_CAPITAL_DECISION_TIME_MAX_EFFECTIVE_LEVERAGE",
            "value": 75.0,
        },
        {
            "source": ("ALLOCATION_MODEL_INPUT_RISK_ENVELOPE_MAX_EFFECTIVE_LEVERAGE"),
            "value": 20.0,
        },
        {
            "source": "ROW_DECISION_TIME_MAX_EFFECTIVE_LEVERAGE",
            "value": 30.0,
        },
    ]
    assert requirement["canonical_margin_usd"] == pytest.approx(10.0)


def test_doge_current_75x_cannot_shadow_20x_allocation_cap() -> None:
    position = _candidate(
        "DOGEUSDT",
        fill_id="fill-doge-shadow",
        notional=100.0,
        leverage=50.0,
        confidence=0.9,
    )
    position["current_capital_accounting"] = {
        "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
        "effective_leverage": 50.0,
        "effective_leverage_validated": True,
        "decision_time_max_effective_leverage": 75.0,
        "maintenance_margin_rate": 0.005,
    }
    position["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ]["max_effective_leverage"] = 20.0  # type: ignore[index]
    _with_final_admission_receipt(position)

    requirement = canonical_margin_requirement(
        position,
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["valid"] is False
    assert requirement["decision_time_max_effective_leverage"] == 20.0
    assert requirement["canonical_margin_usd"] is None
    assert "EFFECTIVE_LEVERAGE_EXCEEDS_DECISION_TIME_ENVELOPE" in requirement["invalid_reasons"]
    assert "EFFECTIVE_LEVERAGE_EXCEEDS_OPERATOR_SYMBOL_CEILING" in requirement["invalid_reasons"]


def test_validated_current_capital_above_one_without_any_cap_is_rejected() -> None:
    position = _candidate(
        "BTCUSDT",
        fill_id="fill-current-without-cap",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    position["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ] = {}  # type: ignore[index]
    position["current_capital_accounting"] = {
        "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
        "effective_leverage": 5.0,
        "effective_leverage_validated": True,
        "maintenance_margin_rate": 0.005,
    }
    _with_final_admission_receipt(position)

    requirement = canonical_margin_requirement(
        position,
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["valid"] is False
    assert requirement["canonical_margin_usd"] is None
    assert "EFFECTIVE_LEVERAGE_MISSING_DECISION_TIME_CAP" in requirement["invalid_reasons"]


def test_operator_symbol_ceiling_is_enforced_independently() -> None:
    candidate = _candidate(
        "DOGEUSDT",
        fill_id="fill-symbol-cap",
        notional=100.0,
        leverage=26.0,
        confidence=0.9,
    )
    candidate["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ]["max_effective_leverage"] = 75.0  # type: ignore[index]
    _with_final_admission_receipt(candidate)

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["operator_authorized_symbol_leverage_ceiling"] == 25.0
    assert "EFFECTIVE_LEVERAGE_EXCEEDS_OPERATOR_SYMBOL_CEILING" in requirement["invalid_reasons"]


def test_prevalidated_maintenance_bracket_max_is_enforced_independently() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-bracket-cap",
        notional=100.0,
        leverage=10.0,
        confidence=0.9,
    )
    _with_bracket_proof(candidate, maximum_leverage=5.0)

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["maintenance_bracket_structural_binding_valid"] is True
    assert requirement["maintenance_bracket_proof_valid"] is False
    assert requirement["maintenance_bracket_authentication_revalidated_here"] is False
    assert requirement["maintenance_bracket_max_initial_leverage"] == 5.0
    assert "EFFECTIVE_LEVERAGE_EXCEEDS_MAINTENANCE_BRACKET_MAX" in requirement["invalid_reasons"]


def test_invalid_cap_shape_cannot_be_hidden_by_another_valid_cap() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-invalid-cap-shape",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    candidate["decision_time_max_effective_leverage"] = {"unexpected": 20.0}

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["decision_time_max_effective_leverage"] == 5.0
    assert (
        "DECISION_TIME_LEVERAGE_CAP_INVALID:" "ROW_DECISION_TIME_MAX_EFFECTIVE_LEVERAGE"
    ) in requirement["invalid_reasons"]


def test_one_x_legacy_accounting_does_not_require_cap_or_bracket_proof() -> None:
    requirement = canonical_margin_requirement(
        {
            "position_id": "legacy-one-x",
            "symbol": "BTCUSDT",
            "side": "long",
            "net_quantity": 5.0,
            "avg_entry_price": 100.0,
            "maintenance_margin_rate": 0.005,
        },
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["valid"] is True
    assert requirement["effective_leverage"] == 1.0
    assert requirement["canonical_margin_usd"] == pytest.approx(500.0)
    assert requirement["maintenance_bracket_proof_required"] is False


def test_missing_maintenance_evidence_fails_candidate_closed() -> None:
    candidate = {
        "fill_id": "fill-maintenance-missing",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "quantity": 5.0,
        "fill_price": 100.0,
        "paper_fill_allowed": True,
    }

    accepted, blocked, _ = reserve_paper_candidate_margin(
        [candidate],
        equity=1_000.0,
        wallet_balance=1_000.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    requirement = blocked[0]["paper_margin_requirement"]
    assert requirement["maintenance_margin_rate"] is None
    assert "MAINTENANCE_MARGIN_RATE_MISSING_OR_INVALID" in requirement["invalid_reasons"]


def test_conflicting_current_capital_leverage_cannot_shadow_allocation() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-current-conflict",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate["current_capital_accounting"] = {
        "accounting_scope": "CURRENT_EXECUTED_PAPER_FILL",
        "effective_leverage": 10.0,
        "effective_leverage_validated": True,
        "decision_time_max_effective_leverage": 20.0,
        "maintenance_margin_rate": 0.005,
    }
    candidate["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ]["max_effective_leverage"] = 20.0  # type: ignore[index]
    _with_final_admission_receipt(candidate)

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["effective_leverage"] == 2.0
    assert requirement["canonical_margin_usd"] is None
    assert "EFFECTIVE_LEVERAGE_EVIDENCE_CONFLICT" in requirement["invalid_reasons"]


@pytest.mark.parametrize(
    "status",
    ["READY_FORGED", "READY_CONSERVATIVE_SAME_SIDE_FILL", "READY "],
)
def test_bracket_status_must_be_exact_ready(status: str) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-status-{status}",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate["maintenance_bracket_evidence_status"] = status

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["maintenance_bracket_structural_binding_valid"] is False
    assert (
        "MAINTENANCE_BRACKET_EVIDENCE_STATUS_NOT_EXACT_READY"
        in requirement["maintenance_bracket_structural_binding_invalid_reasons"]
    )


@pytest.mark.parametrize(
    ("top_field", "nested_field", "value", "expected_reason"),
    [
        (
            "maintenance_bracket_available_at",
            "available_at",
            "not-a-time",
            "MAINTENANCE_BRACKET_TIMESTAMP_INVALID_OR_NAIVE",
        ),
        (
            "maintenance_bracket_expires_at",
            "expires_at",
            "2026-07-18T12:00:01Z",
            "MAINTENANCE_BRACKET_TIMESTAMP_ORDER_INVALID",
        ),
        (
            "paper_allocation_decision_time",
            None,
            "2026-07-18T11:59:59Z",
            "MAINTENANCE_BRACKET_CANDIDATE_CLOCK_ORDER_INVALID",
        ),
    ],
)
def test_bracket_clock_contract_fails_closed(
    top_field: str,
    nested_field: str | None,
    value: str,
    expected_reason: str,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-clock-{top_field}",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate[top_field] = value
    if nested_field is not None:
        candidate["maintenance_bracket_evidence"][nested_field] = value  # type: ignore[index]

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert expected_reason in requirement["maintenance_bracket_structural_binding_invalid_reasons"]


def test_open_position_bracket_must_be_fresh_at_mark_reference() -> None:
    position = _candidate(
        "BTCUSDT",
        fill_id="fill-open-expired",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    position.update(
        {
            "net_quantity": 1.0,
            "avg_entry_price": 100.0,
            "maintenance_margin_mark_time": "2026-07-19T12:00:00Z",
        }
    )

    requirement = canonical_margin_requirement(
        position,
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["valid"] is False
    assert (
        "MAINTENANCE_BRACKET_OPEN_POSITION_CLOCK_ORDER_INVALID"
        in requirement["maintenance_bracket_structural_binding_invalid_reasons"]
    )


@pytest.mark.parametrize("symbol", ["NOT/A/SYMBOL", "btcusdt", " BTCUSDT", "USDT"])
def test_malformed_symbol_cannot_receive_alt_leverage_ceiling(symbol: str) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-symbol-{symbol}",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate["symbol"] = symbol

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["operator_authorized_symbol_leverage_ceiling"] is None
    assert "EFFECTIVE_LEVERAGE_SYMBOL_INVALID_OR_UNAUTHORIZED" in requirement["invalid_reasons"]


def test_valid_usdc_perpetual_symbol_uses_alt_ceiling_without_static_allowlist() -> None:
    candidate = _candidate(
        "BTCUSDC",
        fill_id="fill-btc-usdc",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["operator_authorized_symbol_leverage_ceiling"] == 25.0


def test_bracket_symbol_binding_must_match_candidate() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-symbol-binding",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate["maintenance_bracket_evidence"]["symbol"] = "ETHUSDT"  # type: ignore[index]

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert (
        "MAINTENANCE_BRACKET_SYMBOL_BINDING_MISMATCH:maintenance_bracket_evidence"
        in requirement["maintenance_bracket_structural_binding_invalid_reasons"]
    )


def test_empty_bracket_binding_components_fail_closed() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-empty-binding",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate["maintenance_bracket_binding"] = "testnet::"
    candidate["maintenance_bracket_account_binding_id"] = "testnet::"
    candidate["maintenance_bracket_evidence"]["binding"] = "testnet::"  # type: ignore[index]

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert (
        "MAINTENANCE_BRACKET_PROVENANCE_STRUCTURE_INVALID"
        in requirement["maintenance_bracket_structural_binding_invalid_reasons"]
    )


def test_bracket_binding_key_id_must_match_embedded_binding_key() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-binding-key-id-mismatch",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    candidate["maintenance_bracket_key_id"] = "different-key"
    nested = candidate["maintenance_bracket_evidence"]
    assert isinstance(nested, dict)
    nested["key_id"] = "different-key"
    _with_final_admission_receipt(candidate)

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["maintenance_bracket_structural_binding_valid"] is False
    assert requirement["final_admission_leverage_authorization_valid"] is False
    assert (
        "MAINTENANCE_BRACKET_PROVENANCE_STRUCTURE_INVALID"
        in requirement["maintenance_bracket_structural_binding_invalid_reasons"]
    )
    assert (
        "LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_BINDING_INVALID"
        in requirement["leverage_authorization_downgrade_reasons"]
    )


def test_non_string_bracket_hmac_shape_fails_closed() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-non-string-hmac",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    numeric_hmac = int("1" * 64)
    candidate["maintenance_bracket_evidence_hmac_sha256"] = numeric_hmac
    candidate["maintenance_bracket_evidence"]["evidence_hmac_sha256"] = numeric_hmac  # type: ignore[index]

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert (
        "MAINTENANCE_BRACKET_PROVENANCE_STRUCTURE_INVALID"
        in requirement["maintenance_bracket_structural_binding_invalid_reasons"]
    )


def test_structural_bracket_is_not_reported_as_authenticated_or_authorizing() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-structural-only",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["maintenance_bracket_structural_binding_valid"] is True
    assert requirement["maintenance_bracket_authentication_revalidated_here"] is False
    assert requirement["maintenance_bracket_proof_valid"] is False
    assert requirement["maintenance_bracket_authorizes_leverage"] is False
    assert requirement["maintenance_bracket_cap_effect"] == ("LOWER_ONLY_NEVER_AUTHORIZES_LEVERAGE")
    assert requirement["maintenance_bracket_authentication_gap_reasons"] == [
        "MAINTENANCE_BRACKET_HMAC_NOT_REVALIDATED_AT_PURE_ACCOUNTING_BOUNDARY"
    ]


def test_structural_bracket_cannot_authorize_leverage_without_allocator_or_current_cap() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-structural-no-authorizer",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ] = {}  # type: ignore[index]
    candidate["decision_time_max_effective_leverage"] = 75.0
    _with_final_admission_receipt(candidate)

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["maintenance_bracket_structural_binding_valid"] is True
    assert requirement["decision_time_leverage_cap_authorization_valid"] is False
    assert (
        "EFFECTIVE_LEVERAGE_MISSING_AUTHORIZING_DECISION_TIME_CAP" in requirement["invalid_reasons"]
    )


def test_forged_high_structural_bracket_cannot_raise_lower_allocator_cap() -> None:
    candidate = _candidate(
        "SOLUSDT",
        fill_id="fill-lower-allocator-cap",
        notional=100.0,
        leverage=21.0,
        confidence=0.9,
    )
    candidate["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ]["max_effective_leverage"] = 20.0  # type: ignore[index]
    _with_bracket_proof(candidate, maximum_leverage=75.0)

    requirement = canonical_margin_requirement(candidate)

    assert requirement["maintenance_bracket_structural_binding_valid"] is True
    assert requirement["decision_time_max_effective_leverage"] == 20.0
    assert requirement["valid"] is False
    assert "EFFECTIVE_LEVERAGE_EXCEEDS_DECISION_TIME_ENVELOPE" in requirement["invalid_reasons"]


def test_conflicting_proposal_notionals_use_conservative_maximum() -> None:
    candidate = {
        "fill_id": "fill-notional-conflict",
        "symbol": "BTCUSDT",
        "side": "long",
        "order_size_usd": 10.0,
        "target_notional_usd": 1_000.0,
        "maintenance_margin_rate": 0.005,
    }

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["notional_source"] == "CONSERVATIVE_MAX_CANDIDATE_NOTIONAL"
    assert requirement["canonical_notional_usd"] == pytest.approx(1_000.0)
    assert requirement["canonical_margin_usd"] == pytest.approx(1_000.0)


def test_current_capital_notional_cannot_shadow_larger_candidate_estimate() -> None:
    candidate = {
        "fill_id": "fill-current-notional-conflict",
        "symbol": "BTCUSDT",
        "side": "long",
        "target_notional_usd": 1_000.0,
        "maintenance_margin_rate": 0.005,
        "current_capital_accounting": {"gross_notional_usd": 10.0},
    }

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["canonical_notional_usd"] == pytest.approx(1_000.0)
    assert requirement["canonical_margin_usd"] == pytest.approx(1_000.0)


def test_maintenance_rate_must_match_structural_bracket() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-maintenance-conflict",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    candidate["maintenance_margin_rate"] = 0.9
    candidate["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "maintenance_margin_rate"
    ] = 0.9  # type: ignore[index]

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert "MAINTENANCE_MARGIN_RATE_CONFLICTS_WITH_BRACKET" in requirement["invalid_reasons"]


def test_malformed_populated_maintenance_rate_cannot_be_hidden() -> None:
    candidate = {
        "fill_id": "fill-malformed-maintenance",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "fill_price": 100.0,
        "maintenance_margin_rate": 0.005,
        "current_capital_accounting": {"maintenance_margin_rate": "bad"},
    }

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert (
        "MAINTENANCE_MARGIN_RATE_INVALID:CURRENT_CAPITAL_MAINTENANCE_MARGIN_RATE"
        in requirement["invalid_reasons"]
    )


def test_corrupt_open_position_collection_row_reserves_all_capacity() -> None:
    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=["corrupt-open-row"],  # type: ignore[list-item]
    )

    assert status["accounting_complete"] is False
    assert status["invariant_holds"] is False
    assert status["open_position_count"] == 1
    assert status["invalid_open_position_margin_count"] == 1
    assert status["free_margin_usd"] == 0.0
    assert (
        PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON
        in status["invalid_open_position_margin_rows"][0]["invalid_reasons"]
    )


def test_open_position_mapping_snapshot_runtime_error_fails_collection_closed() -> None:
    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=[_ExplodingCandidateMapping()],
    )

    assert status["accounting_complete"] is False
    assert status["invariant_holds"] is False
    assert status["open_position_count"] == 1
    assert status["accounted_open_position_count"] == 0
    assert status["invalid_open_position_margin_count"] == 1
    assert status["free_margin_usd"] == 0.0
    assert status["invalid_open_position_margin_rows"][0]["invalid_reasons"] == [
        PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON
    ]


def test_malformed_adaptive_buffer_fails_reservation_closed() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-bad-buffer",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct="malformed",
    )

    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        PAPER_MARGIN_BUFFER_INVALID_REASON
    ]
    assert status["margin_buffer_input_valid"] is False
    assert status["free_margin_usd"] == 0.0
    assert status["invariant_holds"] is False


def test_existing_position_generator_is_snapshotted_once_for_final_status() -> None:
    existing = (
        {
            "position_id": "paper_pos_generator",
            "symbol": "BTCUSDT",
            "side": "long",
            "net_quantity": 5.0,
            "avg_entry_price": 100.0,
            "maintenance_margin_rate": 0.005,
        }
        for _ in range(1)
    )
    candidate = _candidate(
        "ETHUSDT",
        fill_id="fill-generator",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=1_000.0,
        wallet_balance=1_000.0,
        existing_open_positions=existing,
        min_available_margin_buffer_pct=0.0,
    )

    assert len(accepted) == 1
    assert blocked == []
    assert status["used_margin_usd"] == pytest.approx(500.0)
    assert status["newly_reserved_margin_usd"] == pytest.approx(100.0)
    assert status["free_margin_usd"] == pytest.approx(400.0)
    assert status["invariant_holds"] is True


def test_calibrated_zero_confidence_does_not_fall_through_to_raw_confidence() -> None:
    zero = _candidate(
        "ETHUSDT",
        fill_id="fill-zero-calibrated",
        notional=100.0,
        leverage=1.0,
        confidence=0.0,
    )
    zero["confidence"] = 1.0
    middle = _candidate(
        "BTCUSDT",
        fill_id="fill-middle-calibrated",
        notional=100.0,
        leverage=1.0,
        confidence=0.5,
    )

    accepted, blocked, _ = reserve_paper_candidate_margin(
        [zero, middle],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert [row["fill_id"] for row in accepted] == ["fill-middle-calibrated"]
    assert [row["fill_id"] for row in blocked] == ["fill-zero-calibrated"]


def test_malformed_calibrated_confidence_does_not_fall_through_to_raw_confidence() -> None:
    malformed = _candidate(
        "ETHUSDT",
        fill_id="fill-malformed-calibrated",
        notional=100.0,
        leverage=1.0,
        confidence=0.0,
    )
    malformed["confidence_calibrated"] = "bad"
    malformed["confidence"] = 1.0
    middle = _candidate(
        "BTCUSDT",
        fill_id="fill-middle-valid",
        notional=100.0,
        leverage=1.0,
        confidence=0.5,
    )

    accepted, blocked, _ = reserve_paper_candidate_margin(
        [malformed, middle],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert [row["fill_id"] for row in accepted] == ["fill-middle-valid"]
    assert [row["fill_id"] for row in blocked] == ["fill-malformed-calibrated"]


def test_invalid_reasons_are_deduplicated() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-reason-dedupe",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    candidate["adaptive_allocation"]["model_inputs"][  # type: ignore[index]
        "risk_envelope"
    ]["max_effective_leverage"] = 1.0  # type: ignore[index]
    _with_final_admission_receipt(candidate)
    candidate["paper_margin_accounting_invalid_reason"] = (
        "EFFECTIVE_LEVERAGE_EXCEEDS_DECISION_TIME_ENVELOPE"
    )

    requirement = canonical_margin_requirement(candidate)

    assert (
        requirement["invalid_reasons"].count("EFFECTIVE_LEVERAGE_EXCEEDS_DECISION_TIME_ENVELOPE")
        == 1
    )


def test_mapping_subclasses_are_snapshotted_and_supported() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-user-dict",
        notional=100.0,
        leverage=2.0,
        confidence=0.9,
    )
    maintenance_evidence = candidate["maintenance_bracket_evidence"]
    assert isinstance(maintenance_evidence, dict)
    candidate["maintenance_bracket_evidence"] = UserDict(maintenance_evidence)

    requirement = canonical_margin_requirement(UserDict(candidate))

    assert requirement["valid"] is True
    assert requirement["canonical_margin_usd"] == pytest.approx(50.0)


@pytest.mark.parametrize("equity", [0.0, -25.0])
def test_nonpositive_equity_never_falls_back_to_spendable_wallet(
    equity: float,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-nonpositive-equity-{equity}",
        notional=10.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=equity,
        wallet_balance=1_000.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        "PAPER_MARGIN_BASE_MISSING_OR_NON_POSITIVE"
    ]
    assert status["margin_base_usd"] == 0.0
    assert status["free_margin_usd"] == 0.0
    assert status["free_margin_after_buffer_usd"] == 0.0
    assert status["margin_base_source"] == ("EQUITY_MISSING_INVALID_OR_NON_POSITIVE_FAIL_CLOSED")
    assert status["invariant_holds"] is False


def test_executed_candidate_notional_reconciles_every_larger_alias() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-executed-alias-conflict",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "fill_price": 100.0,
            "gross_notional_usd": 250.0,
            "gross_notional_usd_upstream": 1_500.0,
            "order_size_usd": 1_000.0,
            "target_notional_usd": 500.0,
            "adaptive_allocation": {"gross_notional_usd": 2_000.0},
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(2_000.0)
    assert requirement["canonical_margin_usd"] is None
    assert requirement["valid"] is False
    assert (
        "CANDIDATE_EXECUTED_AND_PROPOSAL_NOTIONAL_CONFLICT"
        in requirement["notional_evidence_invalid_reasons"]
    )
    assert {item["value"] for item in requirement["notional_evidence"]} == {
        100.0,
        250.0,
        500.0,
        1_000.0,
        1_500.0,
        2_000.0,
    }


def test_corrupt_populated_executed_qty_alias_fails_closed() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-corrupt-qty-alias",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "qty": "corrupt",
            "fill_price": 100.0,
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(100.0)
    assert requirement["valid"] is False
    assert (
        "CANDIDATE_EXECUTED_QUANTITY_EVIDENCE_INVALID:qty"
        in requirement["notional_evidence_invalid_reasons"]
    )


def test_corrupt_populated_entry_price_alias_fails_closed() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-corrupt-entry-price-alias",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "fill_price": 100.0,
            "entry_price": "corrupt",
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(100.0)
    assert requirement["valid"] is False
    assert (
        "CANDIDATE_EXECUTED_PRICE_EVIDENCE_INVALID:entry_price"
        in requirement["notional_evidence_invalid_reasons"]
    )


def test_negative_populated_mark_price_at_fill_alias_fails_closed() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-negative-mark-price-at-fill-alias",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "fill_price": 100.0,
            "mark_price_at_fill": -99.0,
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(100.0)
    assert requirement["valid"] is False
    assert (
        "CANDIDATE_EXECUTED_PRICE_EVIDENCE_INVALID:mark_price_at_fill"
        in requirement["notional_evidence_invalid_reasons"]
    )


def test_current_mark_drift_does_not_conflict_with_sealed_execution_notional() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-current-mark-drift",
            "symbol": "AAVEUSDT",
            "quantity": 0.8,
            "fill_price": 97.96,
            "entry_price": 97.96,
            "mark_price": 97.91,
            "gross_notional_usd": 78.368,
            "effective_leverage": 1.0,
            "maintenance_margin_rate": 0.005,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
    )

    assert requirement["valid"] is True
    assert requirement["canonical_notional_usd"] == pytest.approx(78.368)
    assert requirement["canonical_margin_usd"] == pytest.approx(78.368)
    assert all(
        item["source"] != "ABS_QUANTITY_TIMES_MARK_PRICE"
        for item in requirement["notional_evidence"]
    )


def test_current_open_mark_drift_does_not_conflict_with_execution_notional() -> None:
    requirement = canonical_margin_requirement(
        {
            "position_id": "paper_pos_AAVEUSDT_generation",
            "symbol": "AAVEUSDT",
            "net_quantity": 0.8,
            "avg_entry_price": 97.9,
            "quantity": 0.8,
            "entry_price": 97.9,
            "mark_price": 97.55,
            "gross_notional_usd": 78.32,
            "effective_leverage": 1.0,
            "maintenance_margin_rate": 0.005,
        },
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["valid"] is True
    assert requirement["canonical_notional_usd"] == pytest.approx(78.32)
    assert requirement["canonical_margin_usd"] == pytest.approx(78.32)
    assert all(
        item["source"] != "ABS_NET_QUANTITY_TIMES_MARK_PRICE"
        for item in requirement["notional_evidence"]
    )


def test_invalid_open_mark_price_at_fill_still_fails_closed() -> None:
    requirement = canonical_margin_requirement(
        {
            "position_id": "paper_pos_invalid_mark_at_fill",
            "symbol": "BTCUSDT",
            "net_quantity": 1.0,
            "avg_entry_price": 100.0,
            "quantity": 1.0,
            "fill_price": 100.0,
            "mark_price_at_fill": -99.0,
            "effective_leverage": 1.0,
            "maintenance_margin_rate": 0.005,
        },
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["valid"] is False
    assert (
        "OPEN_EXECUTED_PRICE_EVIDENCE_INVALID:mark_price_at_fill"
        in requirement["notional_evidence_invalid_reasons"]
    )
    assert requirement["canonical_margin_usd"] is None


def test_every_valid_quantity_and_price_alias_participates_in_conservative_reconciliation() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-all-valid-execution-aliases",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "fill_price": 100.0,
            "avg_entry_price": 250.0,
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(250.0)
    assert requirement["valid"] is False
    assert (
        "CANDIDATE_EXECUTED_QUANTITY_PRICE_EVIDENCE_CONFLICT"
        in requirement["notional_evidence_invalid_reasons"]
    )
    assert {item["value"] for item in requirement["notional_evidence"]} == {100.0, 250.0}


def test_open_quantity_price_reconciles_larger_current_capital_notional() -> None:
    requirement = canonical_margin_requirement(
        {
            "position_id": "open-executed-alias-conflict",
            "symbol": "BTCUSDT",
            "net_quantity": 1.0,
            "avg_entry_price": 100.0,
            "gross_notional_usd": 500.0,
            "maintenance_margin_rate": 0.005,
            "current_capital_accounting": {
                "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
                "execution_notional_validated": True,
                "gross_notional_usd": 1_000.0,
                "maintenance_margin_rate": 0.005,
            },
        },
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(1_000.0)
    assert requirement["canonical_margin_usd"] is None
    assert requirement["valid"] is False
    assert "OPEN_EXECUTED_NOTIONAL_EVIDENCE_CONFLICT" in requirement["invalid_reasons"]


def test_conflicting_open_executed_quantity_price_aliases_fail_closed() -> None:
    requirement = canonical_margin_requirement(
        {
            "position_id": "open-conflicting-quantity-price-aliases",
            "symbol": "BTCUSDT",
            "net_quantity": 1.0,
            "avg_entry_price": 100.0,
            "quantity": 10.0,
            "fill_price": 100.0,
            "maintenance_margin_rate": 0.005,
        },
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(1_000.0)
    assert requirement["canonical_margin_usd"] is None
    assert requirement["valid"] is False
    assert "OPEN_EXECUTED_QUANTITY_PRICE_EVIDENCE_CONFLICT" in requirement["invalid_reasons"]
    assert {item["value"] for item in requirement["notional_evidence"]} == {
        100.0,
        1_000.0,
    }


def test_unvalidated_current_capital_notional_cannot_create_open_execution() -> None:
    requirement = canonical_margin_requirement(
        {
            "position_id": "open-current-only-unvalidated",
            "symbol": "BTCUSDT",
            "maintenance_margin_rate": 0.005,
            "current_capital_accounting": {
                "gross_notional_usd": 1_000.0,
                "maintenance_margin_rate": 0.005,
            },
        },
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(1_000.0)
    assert requirement["canonical_margin_usd"] is None
    assert requirement["valid"] is False
    assert "OPEN_CURRENT_CAPITAL_EXECUTED_NOTIONAL_NOT_VALIDATED" in requirement["invalid_reasons"]


def test_structural_bracket_and_plain_allocation_mapping_stay_at_one_x() -> None:
    candidate = _without_final_admission_receipt(
        _candidate(
            "BTCUSDT",
            fill_id="fill-unsealed-structural",
            notional=100.0,
            leverage=5.0,
            confidence=0.9,
        )
    )

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["requested_effective_leverage"] == 5.0
    assert requirement["effective_leverage"] == 1.0
    assert requirement["canonical_margin_usd"] == pytest.approx(100.0)
    assert requirement["maintenance_bracket_structural_binding_valid"] is True
    assert requirement["maintenance_bracket_authorizes_leverage"] is False
    assert requirement["final_admission_leverage_authorization_valid"] is False
    assert requirement["unauthenticated_leverage_claim_downgraded_to_one_x"] is True


def test_plain_current_capital_mapping_without_final_receipt_stays_at_one_x() -> None:
    position = _with_bracket_proof(
        {
            "position_id": "open-unsealed-current-capital",
            "symbol": "BTCUSDT",
            "net_quantity": 1.0,
            "avg_entry_price": 100.0,
            "effective_leverage": 5.0,
            "maintenance_margin_rate": 0.005,
            "current_capital_accounting": {
                "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
                "effective_leverage": 5.0,
                "effective_leverage_validated": True,
                "decision_time_max_effective_leverage": 20.0,
                "maintenance_margin_rate": 0.005,
            },
        },
        maximum_leverage=75.0,
    )
    _without_final_admission_receipt(position)
    position.pop("adaptive_allocation")

    requirement = canonical_margin_requirement(
        position,
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["valid"] is True
    assert requirement["requested_effective_leverage"] == 5.0
    assert requirement["effective_leverage"] == 1.0
    assert requirement["canonical_margin_usd"] == pytest.approx(100.0)
    assert requirement["final_admission_leverage_authorization_valid"] is False


def test_forged_final_admission_receipt_hash_cannot_authorize_leverage() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-forged-final-receipt",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    candidate["paper_final_admission_receipt_hash"] = "c" * 64

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["effective_leverage"] == 1.0
    assert requirement["canonical_margin_usd"] == pytest.approx(100.0)
    assert requirement["final_admission_leverage_authorization_valid"] is False
    assert (
        "LEVERAGE_FINAL_ADMISSION_RECEIPT_HASH_INVALID"
        in requirement["leverage_authorization_downgrade_reasons"]
    )


def test_final_reread_candidate_notional_must_match_sealed_canonical_sizing() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-reread-notional-mismatch",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    contract = candidate["paper_final_admission_contract"]
    assert isinstance(contract, dict)
    bound = contract["bound_material"]
    assert isinstance(bound, dict)
    maintenance_contract = bound["maintenance_bracket_contract"]
    assert isinstance(maintenance_contract, dict)
    reread = maintenance_contract["final_authenticated_reread"]
    assert isinstance(reread, dict)
    assert bound["sizing"]["notional"] == 100.0  # type: ignore[index]
    reread["candidate_notional"] = 1.0
    contract["maintenance_bracket_revalidation"] = reread
    bound_hash = _hash(bound)
    contract["bound_material_hash"] = bound_hash
    candidate["paper_final_admission_bound_material_hash"] = bound_hash
    contract_without_receipt = dict(contract)
    contract_without_receipt.pop("receipt_hash")
    receipt_hash = _hash(contract_without_receipt)
    contract["receipt_hash"] = receipt_hash
    candidate["paper_final_admission_receipt_hash"] = receipt_hash

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["requested_effective_leverage"] == 5.0
    assert requirement["effective_leverage"] == 1.0
    assert requirement["canonical_margin_usd"] == pytest.approx(100.0)
    assert requirement["final_admission_leverage_authorization_valid"] is False
    assert (
        "LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_NOTIONAL_MISMATCH"
        in requirement["leverage_authorization_downgrade_reasons"]
    )


def test_coherently_rehashed_plain_allocation_receipt_cannot_authorize_leverage() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-coherent-plain-allocation-forgery",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    allocation = candidate["adaptive_allocation"]
    assert isinstance(allocation, dict)
    for field in (
        "allocation_input_schema_version",
        "allocation_input_hash_algorithm",
        "allocation_input_hash",
        "allocation_input_material",
        "allocation_id",
        "lineage_ids",
    ):
        allocation.pop(field)
    allocation_hash = _hash(allocation)
    contract = candidate["paper_final_admission_contract"]
    assert isinstance(contract, dict)
    bound = contract["bound_material"]
    assert isinstance(bound, dict)
    bound["adaptive_allocation_hash"] = allocation_hash
    bound["allocator_contract"] = {"allocation_hash": allocation_hash}
    identity = bound["identity"]
    assert isinstance(identity, dict)
    identity.pop("allocation_id")
    bound_hash = _hash(bound)
    contract["bound_material_hash"] = bound_hash
    candidate["paper_final_admission_bound_material_hash"] = bound_hash
    contract_without_hash = dict(contract)
    contract_without_hash.pop("receipt_hash")
    receipt_hash = _hash(contract_without_hash)
    contract["receipt_hash"] = receipt_hash
    candidate["paper_final_admission_receipt_hash"] = receipt_hash

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["requested_effective_leverage"] == 5.0
    assert requirement["effective_leverage"] == 1.0
    assert requirement["canonical_margin_usd"] == pytest.approx(100.0)
    assert requirement["final_admission_leverage_authorization_valid"] is False
    assert (
        "LEVERAGE_DECISION_TIME_ALLOCATION_IDENTITY_INVALID"
        in requirement["leverage_authorization_downgrade_reasons"]
    )


def test_nested_maintenance_bracket_symbol_is_required() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-bracket-symbol-missing",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    maintenance_evidence = candidate["maintenance_bracket_evidence"]
    assert isinstance(maintenance_evidence, dict)
    maintenance_evidence.pop("symbol")

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert (
        "MAINTENANCE_BRACKET_SYMBOL_BINDING_MISSING:maintenance_bracket_evidence"
        in requirement["maintenance_bracket_structural_binding_invalid_reasons"]
    )


@pytest.mark.parametrize("symbol", ["btcusdt", " BTCUSDT", "USDT", "BTC/USDT"])
def test_malformed_symbol_is_blocked_even_when_leverage_is_one_x(symbol: str) -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": f"fill-one-x-malformed-{symbol}",
            "symbol": symbol,
            "quantity": 1.0,
            "fill_price": 100.0,
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["effective_leverage"] == 1.0
    assert requirement["valid"] is False
    assert "PAPER_SYMBOL_INVALID_OR_UNAUTHORIZED" in requirement["invalid_reasons"]


def test_corrupt_candidate_collection_row_is_explicitly_blocked() -> None:
    accepted, blocked, status = reserve_paper_candidate_margin(
        ["corrupt-candidate-row", _ExplodingCandidateMapping()],  # type: ignore[list-item]
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 2
    assert all(
        row["paper_margin_reservation_block_reasons"] == [PAPER_CANDIDATE_COLLECTION_INVALID_REASON]
        for row in blocked
    )
    assert all(row["paper_margin_requirement"]["valid"] is False for row in blocked)
    assert status["candidate_count"] == 2
    assert status["accountable_candidate_count"] == 0
    assert status["candidate_collection_invalid_count"] == 2
    assert status["candidate_collection_inputs_valid"] is False
    assert status["blocked_candidate_count"] == 2
    assert PAPER_CANDIDATE_COLLECTION_INVALID_REASON in status["failure_reasons"]


def test_canonical_requirement_exploding_top_level_mapping_returns_invalid_evidence() -> None:
    requirement = canonical_margin_requirement(_ExplodingCandidateMapping())

    assert requirement["mapping_snapshot_valid"] is False
    assert requirement["valid"] is False
    assert requirement["canonical_margin_usd"] is None
    assert requirement["mapping_snapshot_invalid_reason"] == (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:margin_row"
    )
    assert requirement["mapping_snapshot_invalid_reason"] in requirement["invalid_reasons"]
    assert requirement["paper_only"] is True
    assert requirement["routes_to_live"] is False
    assert requirement["places_real_order"] is False


def test_canonical_requirement_exploding_nested_allocation_returns_invalid_evidence() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-exploding-nested-allocation",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )
    candidate["adaptive_allocation"] = _ExplodingCandidateMapping()

    requirement = canonical_margin_requirement(candidate)

    assert requirement["mapping_snapshot_valid"] is False
    assert requirement["valid"] is False
    assert requirement["mapping_snapshot_invalid_reason"] == (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:margin_row.adaptive_allocation"
    )


def test_build_status_exploding_nested_evidence_fails_collection_closed() -> None:
    open_position = {
        "position_id": "open-exploding-nested-evidence",
        "symbol": "BTCUSDT",
        "net_quantity": 1.0,
        "avg_entry_price": 100.0,
        "maintenance_margin_rate": 0.005,
        "maintenance_bracket_evidence": _ExplodingCandidateMapping(),
    }

    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=[open_position],
    )

    assert status["accounting_complete"] is False
    assert status["accounted_open_position_count"] == 0
    assert status["free_margin_usd"] == 0.0
    evidence = status["invalid_open_position_margin_rows"][0]
    assert evidence["invalid_reasons"] == [PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON]
    assert evidence["mapping_snapshot_invalid_reason"] == (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:"
        "open_positions[0].maintenance_bracket_evidence"
    )


def test_reservation_exploding_nested_allocation_is_explicitly_blocked() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-reserve-exploding-allocation",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )
    candidate["adaptive_allocation"] = _ExplodingCandidateMapping()

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        PAPER_CANDIDATE_COLLECTION_INVALID_REASON
    ]
    assert blocked[0]["paper_candidate_mapping_snapshot_invalid_reason"] == (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:candidates[0].adaptive_allocation"
    )
    assert status["candidate_collection_inputs_valid"] is False
    assert status["candidate_collection_invalid_count"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("paper_only", False),
        ("paper_only", None),
        ("routes_to_live", True),
        ("places_real_order", True),
    ],
)
def test_explicit_contradictory_paper_route_flags_block_reservation(
    field: str,
    value: object,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-unsafe-route-{field}",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )
    candidate[field] = value

    requirement = canonical_margin_requirement(candidate)
    accepted, blocked, _ = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    expected_reason = f"{PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID_REASON}:{field}"
    assert requirement["paper_input_route_safety_flags_valid"] is False
    assert requirement["paper_input_route_safety_flag_invalid_reasons"] == [expected_reason]
    assert expected_reason in requirement["invalid_reasons"]
    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_status"] == "BLOCKED"
    assert blocked[0]["paper_only"] is True
    assert blocked[0]["routes_to_live"] is False
    assert blocked[0]["places_real_order"] is False


def test_missing_route_flags_remain_compatible_and_reserved_output_is_exactly_paper_safe() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-missing-route-flags-compatible",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )
    assert all(
        field not in candidate for field in ("paper_only", "routes_to_live", "places_real_order")
    )

    accepted, blocked, _ = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert blocked == []
    assert len(accepted) == 1
    assert accepted[0]["paper_only"] is True
    assert accepted[0]["routes_to_live"] is False
    assert accepted[0]["places_real_order"] is False


def test_explicit_live_route_on_open_position_reserves_all_capacity() -> None:
    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=[
            {
                "position_id": "open-explicit-live-route",
                "symbol": "BTCUSDT",
                "net_quantity": 0.5,
                "avg_entry_price": 100.0,
                "maintenance_margin_rate": 0.005,
                "paper_only": True,
                "routes_to_live": True,
                "places_real_order": False,
            }
        ],
    )

    assert status["accounting_complete"] is False
    assert status["free_margin_usd"] == 0.0
    assert status["invariant_holds"] is False
    position_requirement = status["position_margin_rows"][0]
    assert position_requirement["paper_input_route_safety_flags_valid"] is False
    assert (
        f"{PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID_REASON}:routes_to_live"
        in position_requirement["invalid_reasons"]
    )


def test_stale_open_position_receipt_notional_downgrades_to_one_x() -> None:
    position = _candidate(
        "BTCUSDT",
        fill_id="open-stale-final-admission-notional",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    position["fill_price"] = 200.0

    requirement = canonical_margin_requirement(
        position,
        accounting_scope="OPEN_EXECUTED_POSITION",
    )
    accepted, blocked, status = reserve_paper_candidate_margin(
        [],
        equity=1_000.0,
        wallet_balance=1_000.0,
        existing_open_positions=[position],
        min_available_margin_buffer_pct=0.0,
    )

    assert requirement["canonical_notional_usd"] == pytest.approx(200.0)
    assert requirement["requested_effective_leverage"] == 5.0
    assert requirement["effective_leverage"] == 1.0
    assert requirement["canonical_margin_usd"] == pytest.approx(200.0)
    assert requirement["valid"] is True
    assert requirement["final_admission_leverage_authorization_valid"] is False
    assert (
        "LEVERAGE_FINAL_ADMISSION_CANONICAL_NOTIONAL_MISMATCH"
        in requirement["leverage_authorization_downgrade_reasons"]
    )
    assert (
        "LEVERAGE_FINAL_ADMISSION_AUTHENTICATED_REREAD_NOTIONAL_MISMATCH"
        in requirement["leverage_authorization_downgrade_reasons"]
    )
    assert accepted == []
    assert blocked == []
    assert status["used_margin_usd"] == pytest.approx(200.0)
    assert status["free_margin_usd"] == pytest.approx(800.0)
    assert status["invariant_holds"] is True


def test_current_open_position_receipt_notional_still_authorizes_authenticated_leverage() -> None:
    position = _candidate(
        "BTCUSDT",
        fill_id="open-current-final-admission-notional",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )

    requirement = canonical_margin_requirement(
        position,
        accounting_scope="OPEN_EXECUTED_POSITION",
    )

    assert requirement["final_admission_leverage_authorization_valid"] is True
    assert requirement["effective_leverage"] == 5.0
    assert requirement["canonical_notional_usd"] == pytest.approx(100.0)
    assert requirement["canonical_margin_usd"] == pytest.approx(20.0)
    assert requirement["valid"] is True


def test_existing_mapping_that_explodes_once_is_not_retried_as_valid() -> None:
    changing_evidence = _ExplodeOnceThenValidMapping({"maintenance_margin_rate": 0.005})
    existing_position = {
        "position_id": "open-explode-once",
        "symbol": "BTCUSDT",
        "net_quantity": 1.0,
        "avg_entry_price": 100.0,
        "maintenance_margin_rate": 0.005,
        "current_capital_accounting": changing_evidence,
    }
    candidate = _candidate(
        "ETHUSDT",
        fill_id="fill-after-explode-once-existing",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=500.0,
        wallet_balance=500.0,
        existing_open_positions=[existing_position],
        min_available_margin_buffer_pct=0.0,
    )

    assert changing_evidence.iteration_count == 1
    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        "PAPER_EXISTING_OPEN_POSITION_MARGIN_ACCOUNTING_INCOMPLETE"
    ]
    assert status["accounting_complete"] is False
    assert status["invariant_holds"] is False
    persisted = status["invalid_open_position_margin_rows"][0]
    assert persisted["mapping_snapshot_valid"] is False
    assert persisted["mapping_snapshot_invalid_reason"] == (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:"
        "INTERNAL_EXISTING_OPEN_POSITION_SNAPSHOT_FAILED"
    )


def test_existing_nested_mapping_is_deep_snapshotted_exactly_once() -> None:
    changing_evidence = _ValidOnceThenExplodingMapping({"maintenance_margin_rate": 0.005})
    existing_position = {
        "position_id": "open-valid-once",
        "symbol": "BTCUSDT",
        "net_quantity": 1.0,
        "avg_entry_price": 100.0,
        "maintenance_margin_rate": 0.005,
        "current_capital_accounting": changing_evidence,
    }
    candidate = _candidate(
        "ETHUSDT",
        fill_id="fill-after-valid-once-existing",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=500.0,
        wallet_balance=500.0,
        existing_open_positions=[existing_position],
        min_available_margin_buffer_pct=0.0,
    )

    assert changing_evidence.iteration_count == 1
    assert [row["fill_id"] for row in accepted] == ["fill-after-valid-once-existing"]
    assert blocked == []
    assert status["used_margin_usd"] == pytest.approx(100.0)
    assert status["newly_reserved_margin_usd"] == pytest.approx(100.0)
    assert status["invariant_holds"] is True


@pytest.mark.parametrize(
    ("container_name", "field", "value"),
    [
        ("adaptive_allocation", "paper_only", False),
        ("adaptive_allocation", "routes_to_live", True),
        ("adaptive_allocation", "places_real_order", True),
        ("current_capital_accounting", "paper_only", False),
        ("current_capital_accounting", "routes_to_live", True),
        ("current_capital_accounting", "places_real_order", True),
    ],
)
def test_nested_contradictory_paper_route_flags_block_reservation(
    container_name: str,
    field: str,
    value: object,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-unsafe-nested-route-{container_name}-{field}",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )
    container = candidate.setdefault(container_name, {})
    assert isinstance(container, dict)
    container[field] = value

    requirement = canonical_margin_requirement(candidate)
    accepted, blocked, _ = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    expected_reason = f"{PAPER_INPUT_ROUTE_SAFETY_FLAG_INVALID_REASON}:{container_name}.{field}"
    assert expected_reason in requirement["paper_input_route_safety_flag_invalid_reasons"]
    assert requirement["paper_input_route_safety_flags_valid"] is False
    assert accepted == []
    assert len(blocked) == 1


def test_json_valid_huge_quantity_alias_fails_closed_without_overflow() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-huge-quantity",
            "symbol": "BTCUSDT",
            "quantity": 10**400,
            "fill_price": 100.0,
            "order_size_usd": 100.0,
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["valid"] is False
    assert "CANDIDATE_EXECUTED_QUANTITY_EVIDENCE_INVALID:quantity" in requirement["invalid_reasons"]


def test_json_valid_huge_notional_alias_fails_closed_without_overflow() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-huge-notional",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "fill_price": 100.0,
            "gross_notional_usd": 10**400,
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["valid"] is False
    assert (
        "CANDIDATE_NOTIONAL_EVIDENCE_INVALID:REPORTED_EXECUTED_NOTIONAL_FALLBACK:"
        "gross_notional_usd" in requirement["invalid_reasons"]
    )


def test_json_valid_huge_maintenance_alias_fails_closed_without_overflow() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-huge-maintenance",
            "symbol": "BTCUSDT",
            "quantity": 1.0,
            "fill_price": 100.0,
            "maintenance_margin_rate": 10**400,
        }
    )

    assert requirement["valid"] is False
    assert (
        "MAINTENANCE_MARGIN_RATE_INVALID:POSITION_MAINTENANCE_MARGIN_RATE"
        in requirement["invalid_reasons"]
    )


def test_margin_status_declares_authoritative_account_balance_input_contract() -> None:
    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=[],
    )

    assert status["cash_balance_input_supported"] is False
    assert status["cash_balance_alias_inferred"] is False
    assert status["account_balance_input_contract"] == (
        "AUTHORITATIVE_EQUITY_AND_WALLET_BALANCE_REQUIRED_FROM_CALLER"
    )


def test_duplicate_mapping_items_cannot_last_win_away_live_route_claim() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-duplicate-route-items",
        notional=100.0,
        leverage=1.0,
        confidence=0.9,
    )
    hostile = _DuplicateRouteItemsMapping(candidate)

    accepted, blocked, status = reserve_paper_candidate_margin(
        [hostile],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert hostile.items_call_count == 1
    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        PAPER_CANDIDATE_COLLECTION_INVALID_REASON
    ]
    assert blocked[0]["paper_candidate_mapping_snapshot_invalid_reason"] == (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:" "candidates[0]:DUPLICATE_MAPPING_KEY"
    )
    assert status["candidate_collection_inputs_valid"] is False


def test_malformed_mapping_item_is_fixed_snapshot_invalid_evidence() -> None:
    requirement = canonical_margin_requirement(_MalformedItemsMapping())

    assert requirement["valid"] is False
    assert requirement["mapping_snapshot_invalid_reason"] == (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:" "margin_row:MALFORMED_MAPPING_ITEM"
    )
    assert "attacker" not in requirement["mapping_snapshot_invalid_reason"]


def test_candidate_outer_iterator_failure_blocks_entire_captured_prefix() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-before-candidate-iterator-failure",
        notional=50.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        _RaiseAfterOneIterable(candidate),  # type: ignore[arg-type]
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    expected_iteration_reason = f"{PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON}:candidates"
    assert accepted == []
    assert len(blocked) == 2
    assert all(
        row["paper_margin_reservation_block_reasons"] == [PAPER_CANDIDATE_COLLECTION_INVALID_REASON]
        for row in blocked
    )
    assert status["candidate_collection_complete"] is False
    assert status["candidate_collection_iteration_invalid_reason"] == (expected_iteration_reason)
    assert status["candidate_collection_inputs_valid"] is False
    assert status["newly_reserved_margin_usd"] == 0.0


def test_open_position_outer_iterator_failure_reserves_all_capacity() -> None:
    open_position = {
        "position_id": "open-before-iterator-failure",
        "symbol": "BTCUSDT",
        "net_quantity": 1.0,
        "avg_entry_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }

    status = build_paper_margin_status(
        equity=500.0,
        wallet_balance=500.0,
        open_positions=_RaiseAfterOneIterable(open_position),  # type: ignore[arg-type]
    )

    assert status["status"] == "FAIL_CLOSED"
    assert status["open_position_collection_complete"] is False
    assert status["open_position_collection_iteration_invalid_reason"] == (
        f"{PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON}:open_positions"
    )
    assert status["used_margin_usd"] == pytest.approx(100.0)
    assert status["free_margin_usd"] == 0.0
    assert status["accounting_complete"] is False
    assert (
        PAPER_OPEN_POSITION_COLLECTION_INVALID_REASON
        in status["invalid_open_position_margin_rows"][0]["invalid_reasons"]
    )


def test_existing_open_outer_iterator_failure_blocks_all_admission() -> None:
    open_position = {
        "position_id": "existing-before-iterator-failure",
        "symbol": "BTCUSDT",
        "net_quantity": 1.0,
        "avg_entry_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }
    candidate = _candidate(
        "ETHUSDT",
        fill_id="fill-after-existing-iterator-failure",
        notional=50.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=500.0,
        wallet_balance=500.0,
        existing_open_positions=_RaiseAfterOneIterable(open_position),  # type: ignore[arg-type]
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        "PAPER_EXISTING_OPEN_POSITION_MARGIN_ACCOUNTING_INCOMPLETE"
    ]
    assert status["existing_open_position_collection_complete"] is False
    assert status["existing_open_position_collection_iteration_invalid_reason"] == (
        f"{PAPER_MARGIN_COLLECTION_ITERATION_INVALID_REASON}:existing_open_positions"
    )
    assert status["accounting_complete"] is False
    assert status["free_margin_usd"] == 0.0


def test_runtime_error_from_custom_float_fails_canonical_requirement_closed() -> None:
    requirement = canonical_margin_requirement(
        {
            "fill_id": "fill-exploding-float",
            "symbol": "BTCUSDT",
            "quantity": _ExplodingFloat(),
            "fill_price": 100.0,
            "order_size_usd": 100.0,
            "maintenance_margin_rate": 0.005,
        }
    )

    assert requirement["valid"] is False
    assert requirement["canonical_margin_usd"] is None
    assert "CANDIDATE_EXECUTED_QUANTITY_EVIDENCE_INVALID:quantity" in requirement["invalid_reasons"]


def test_runtime_error_from_custom_account_scalar_fails_status_closed() -> None:
    status = build_paper_margin_status(
        equity=_ExplodingFloat(),
        wallet_balance=100.0,
        open_positions=[],
    )

    assert status["status"] == "FAIL_CLOSED"
    assert status["margin_base_available"] is False
    assert status["free_margin_usd"] == 0.0
    assert status["margin_base_source"] == ("EQUITY_MISSING_INVALID_OR_NON_POSITIVE_FAIL_CLOSED")


@pytest.mark.parametrize("valid_fallback", [None, 100.0])
def test_target_quantity_price_nonfinite_product_fails_closed(
    valid_fallback: float | None,
) -> None:
    row: dict[str, object] = {
        "fill_id": "fill-target-product-overflow",
        "symbol": "BTCUSDT",
        "target_quantity": 1e308,
        "price": 1e308,
        "maintenance_margin_rate": 0.005,
    }
    if valid_fallback is not None:
        row["order_size_usd"] = valid_fallback

    requirement = canonical_margin_requirement(row)

    assert requirement["valid"] is False
    assert requirement["canonical_notional_usd"] == valid_fallback
    assert requirement["canonical_margin_usd"] is None
    assert "CANDIDATE_TARGET_QUANTITY_PRICE_PRODUCT_INVALID" in requirement["invalid_reasons"]


def test_open_margin_aggregate_overflow_fails_closed_without_nonfinite_output() -> None:
    positions = [
        {
            "position_id": f"open-huge-margin-{index}",
            "symbol": "BTCUSDT",
            "net_quantity": 1e308,
            "avg_entry_price": 1.0,
            "maintenance_margin_rate": 0.005,
        }
        for index in range(2)
    ]

    status = build_paper_margin_status(
        equity=1e308,
        wallet_balance=1e308,
        open_positions=positions,
    )

    aggregate_reason = f"{PAPER_MARGIN_DERIVED_VALUE_NONFINITE_REASON}:USED_MARGIN_AGGREGATE"
    assert status["status"] == "FAIL_CLOSED"
    assert status["used_margin_aggregation_valid"] is False
    assert status["projected_used_margin_aggregation_valid"] is True
    assert aggregate_reason in status["failure_reasons"]
    assert status["free_margin_usd"] == 0.0
    for field in (
        "used_margin_usd",
        "projected_used_margin_usd",
        "free_margin_usd",
        "margin_buffer_usd",
        "margin_deficit_usd",
    ):
        assert math.isfinite(status[field])


def test_complete_raw_bracket_context_reconciles_and_keeps_authorized_leverage() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-complete-raw-bracket-context",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    candidate["paper_maintenance_margin_bracket_evidence"] = _complete_raw_bracket_context(
        candidate
    )

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is True
    assert requirement["effective_leverage"] == 5.0
    assert requirement["canonical_margin_usd"] == pytest.approx(20.0)
    assert requirement["maintenance_bracket_raw_context_binding_valid"] is True


def test_malformed_raw_bracket_context_cannot_be_ignored_at_authorized_leverage() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-malformed-raw-bracket-context",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    candidate["paper_maintenance_margin_bracket_evidence"] = "CORRUPT"

    requirement = canonical_margin_requirement(candidate)

    expected_reason = (
        "MAINTENANCE_BRACKET_RAW_CONTEXT_SHAPE_INVALID:" "paper_maintenance_margin_bracket_evidence"
    )
    assert requirement["valid"] is False
    assert requirement["canonical_margin_usd"] is None
    assert requirement["maintenance_bracket_raw_context_binding_valid"] is False
    assert expected_reason in requirement["maintenance_bracket_raw_context_binding_invalid_reasons"]


@pytest.mark.parametrize(
    ("field", "conflicting_value"),
    [
        ("max_initial_leverage", 1.0),
        ("evidence_hmac_sha256", "c" * 64),
    ],
)
def test_conflicting_raw_bracket_alias_cannot_preserve_authorized_margin(
    field: str,
    conflicting_value: object,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-conflicting-raw-bracket-{field}",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    raw_context = _complete_raw_bracket_context(candidate)
    raw_context[field] = conflicting_value
    candidate["paper_maintenance_margin_bracket_evidence"] = raw_context

    requirement = canonical_margin_requirement(candidate)

    expected_reason = (
        "MAINTENANCE_BRACKET_RAW_CONTEXT_BINDING_MISMATCH:"
        f"paper_maintenance_margin_bracket_evidence:{field}"
    )
    assert requirement["valid"] is False
    assert requirement["canonical_margin_usd"] is None
    assert requirement["maintenance_bracket_structural_binding_valid"] is False
    assert expected_reason in requirement["maintenance_bracket_raw_context_binding_invalid_reasons"]


def test_allocation_raw_bracket_alias_is_also_reconciled() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-allocation-raw-bracket-conflict",
        notional=100.0,
        leverage=5.0,
        confidence=0.9,
    )
    allocation = candidate["adaptive_allocation"]
    assert isinstance(allocation, dict)
    raw_context = _complete_raw_bracket_context(candidate)
    raw_context["max_initial_leverage"] = 1.0
    allocation["paper_maintenance_margin_bracket_evidence"] = raw_context

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["canonical_margin_usd"] is None
    assert (
        "MAINTENANCE_BRACKET_RAW_CONTEXT_BINDING_MISMATCH:"
        "adaptive_allocation.paper_maintenance_margin_bracket_evidence:"
        "max_initial_leverage"
        in requirement["maintenance_bracket_raw_context_binding_invalid_reasons"]
    )


@pytest.mark.parametrize("invalid_flag", ["false", "true", 0, 1, None])
def test_non_boolean_reservation_inclusion_flag_cannot_skip_reservation(
    invalid_flag: object,
) -> None:
    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=[],
        newly_reserved_margin_usd=80.0,
        reservations_included_in_open_positions=invalid_flag,  # type: ignore[arg-type]
    )

    assert status["status"] == "FAIL_CLOSED"
    assert status["control_inputs_valid"] is False
    assert status["reservations_included_in_open_positions_input_valid"] is False
    assert status["newly_reserved_included_in_used_margin"] is False
    assert status["projected_used_margin_usd"] == pytest.approx(80.0)
    assert status["free_margin_usd"] == 0.0
    assert PAPER_MARGIN_RESERVATION_INCLUSION_FLAG_INVALID_REASON in status["failure_reasons"]


def test_repeated_tiny_margins_cannot_accumulate_epsilon_over_acceptance() -> None:
    candidates = [
        _candidate(
            "BTCUSDT",
            fill_id=f"fill-tiny-margin-{index}",
            notional=1e-8,
            leverage=1.0,
            confidence=0.9,
        )
        for index in range(3)
    ]

    accepted, blocked, status = reserve_paper_candidate_margin(
        candidates,
        equity=1e-8,
        wallet_balance=1e-8,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert [row["fill_id"] for row in accepted] == ["fill-tiny-margin-0"]
    assert len(blocked) == 2
    assert all(
        row["paper_margin_reservation_block_reasons"] == [PAPER_INSUFFICIENT_FREE_MARGIN_REASON]
        for row in blocked
    )
    assert status["status"] == "PASS"
    assert status["invariant_holds"] is True
    assert status["newly_reserved_margin_usd"] == pytest.approx(1e-8)
    assert status["reserved_candidate_count"] == 1
    assert status["blocked_candidate_count"] == 2
    assert status["final_reservation_reconciliation_valid"] is True
    assert not accepted or status["status"] == "PASS"


def test_final_reconciliation_failure_rolls_back_every_accepted_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_build_status = margin_accounting_module.build_paper_margin_status

    def fail_only_final_reserved_reconciliation(**kwargs: object) -> dict[str, object]:
        result = real_build_status(**kwargs)  # type: ignore[arg-type]
        reserved_value = kwargs.get("newly_reserved_margin_usd", 0.0)
        if isinstance(reserved_value, int | float) and reserved_value > 0.0:
            result.update(
                {
                    "status": "FAIL_CLOSED",
                    "invariant": False,
                    "invariant_holds": False,
                    "failure_reasons": ["INJECTED_FINAL_RECONCILIATION_FAILURE"],
                }
            )
        return result

    monkeypatch.setattr(
        margin_accounting_module,
        "build_paper_margin_status",
        fail_only_final_reserved_reconciliation,
    )
    candidates = [
        _candidate(
            "BTCUSDT",
            fill_id=f"fill-final-reconciliation-{index}",
            notional=10.0,
            leverage=1.0,
            confidence=0.9,
        )
        for index in range(3)
    ]

    accepted, blocked, status = reserve_paper_candidate_margin(
        candidates,
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    expected_reason = "PAPER_MARGIN_FINAL_RESERVATION_RECONCILIATION_FAILED"
    assert accepted == []
    assert len(blocked) == 3
    assert all(
        row["paper_margin_reservation_block_reasons"] == [expected_reason] for row in blocked
    )
    assert status["status"] == "FAIL_CLOSED"
    assert status["invariant_holds"] is False
    assert status["newly_reserved_margin_usd"] == 0.0
    assert status["reserved_candidate_count"] == 0
    assert status["blocked_candidate_count"] == 3
    assert status["final_reservation_reconciliation_valid"] is False
    assert status["final_reservation_reconciliation_failure_reason"] == expected_reason
    assert status["post_rollback_accounting_invariant_holds"] is True
    assert expected_reason in status["failure_reasons"]


def test_hostile_fill_identity_is_fixed_secret_free_requirement_evidence() -> None:
    candidate = {
        "fill_id": _ExplodingIdentity(),
        "symbol": "BTCUSDT",
        "quantity": 1.0,
        "fill_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["row_id"] == "invalid_margin_row_identity"
    assert requirement["row_identity_valid"] is False
    assert requirement["row_identity_invalid_reason"] == "PAPER_MARGIN_ROW_IDENTITY_INVALID"
    assert "PAPER_MARGIN_ROW_IDENTITY_INVALID" in requirement["invalid_reasons"]
    assert "ATTACKER_SECRET_IDENTITY_TEXT" not in repr(requirement)


def test_hostile_fill_identity_is_blocked_without_escape_or_secret_copy() -> None:
    candidate = {
        "fill_id": _ExplodingIdentity(),
        "symbol": "BTCUSDT",
        "quantity": 1.0,
        "fill_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        PAPER_CANDIDATE_COLLECTION_INVALID_REASON
    ]
    assert blocked[0]["paper_candidate_row_identity_invalid_reason"] == (
        "PAPER_MARGIN_ROW_IDENTITY_INVALID"
    )
    assert status["candidate_collection_inputs_valid"] is False
    assert "ATTACKER_SECRET_IDENTITY_TEXT" not in repr((accepted, blocked, status))


def test_caller_injected_internal_snapshot_marker_is_fixed_secret_free_evidence() -> None:
    attacker_text = "ATTACKER_SECRET_SNAPSHOT_SENTINEL_TEXT"
    candidate = {
        "fill_id": "fill-injected-snapshot-marker",
        "symbol": "BTCUSDT",
        "quantity": 1.0,
        "fill_price": 100.0,
        "maintenance_margin_rate": 0.005,
        "_paper_margin_mapping_snapshot_invalid_reason": attacker_text,
    }

    requirement = canonical_margin_requirement(candidate)
    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    expected_reason = (
        f"{PAPER_MARGIN_MAPPING_SNAPSHOT_INVALID_REASON}:"
        "RESERVED_INTERNAL_SNAPSHOT_MARKER_INJECTED"
    )
    assert requirement["valid"] is False
    assert requirement["mapping_snapshot_invalid_reason"] == expected_reason
    assert attacker_text not in repr(requirement)
    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_candidate_mapping_snapshot_invalid_reason"] == expected_reason
    assert attacker_text not in repr((accepted, blocked, status))
    assert candidate["_paper_margin_mapping_snapshot_invalid_reason"] == attacker_text


@pytest.mark.parametrize(
    ("required_margin", "capacity"),
    [
        (1.49e-8, 1e-8),
        (1.000000004, 1.0),
    ],
)
def test_rounded_margin_display_never_controls_candidate_admission(
    required_margin: float,
    capacity: float,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-full-precision-{required_margin!r}",
        notional=required_margin,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=capacity,
        wallet_balance=capacity,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    requirement = blocked[0]["paper_margin_requirement"]
    assert requirement["canonical_margin_usd"] == round(required_margin, 8)
    assert requirement["canonical_margin_unrounded_usd"] > capacity
    assert blocked[0]["paper_margin_reservation_block_reasons"] == [
        PAPER_INSUFFICIENT_FREE_MARGIN_REASON
    ]
    assert status["newly_reserved_margin_unrounded_usd"] == 0.0


def test_full_precision_cumulative_reservation_accepts_exact_maximum_prefix() -> None:
    candidates = [
        _candidate(
            "BTCUSDT",
            fill_id=f"fill-precision-prefix-{index:03d}",
            notional=1.49e-8,
            leverage=1.0,
            confidence=0.9,
        )
        for index in range(100)
    ]

    accepted, blocked, status = reserve_paper_candidate_margin(
        candidates,
        equity=1e-6,
        wallet_balance=1e-6,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert len(accepted) == 67
    assert len(blocked) == 33
    assert all(
        row["paper_margin_reservation_block_reasons"] == [PAPER_INSUFFICIENT_FREE_MARGIN_REASON]
        for row in blocked
    )
    assert status["newly_reserved_margin_unrounded_usd"] == pytest.approx(67 * 1.49e-8)
    assert status["projected_used_margin_unrounded_usd"] <= 1e-6


def test_nonraising_object_fill_identity_is_never_canonicalized_or_emitted() -> None:
    candidate = {
        "fill_id": _LeakingIdentity(),
        "symbol": "BTCUSDT",
        "quantity": 1.0,
        "fill_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }

    requirement = canonical_margin_requirement(candidate)
    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert requirement["row_id"] == "invalid_margin_row_identity"
    assert requirement["row_identity_valid"] is False
    assert accepted == []
    assert len(blocked) == 1
    assert "ATTACKER_SECRET_NONRAISING_IDENTITY_TEXT" not in repr(
        (requirement, accepted, blocked, status)
    )


@pytest.mark.parametrize(
    "field",
    [
        "symbol",
        "paper_margin_accounting_invalid_reason",
        "maintenance_bracket_evidence_status",
        "maintenance_bracket_binding",
        "maintenance_bracket_evidence_hash",
        "adaptive_allocation",
        "routes_to_live",
    ],
)
def test_unsupported_hostile_scalar_is_rejected_before_comparison_hash_or_copy(
    field: str,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-hostile-scalar-{field}",
        notional=10.0,
        leverage=1.0,
        confidence=0.9,
    )
    candidate[field] = _HostileScalar()

    requirement = canonical_margin_requirement(candidate)
    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert requirement["valid"] is False
    assert requirement["mapping_snapshot_valid"] is False
    assert accepted == []
    assert len(blocked) == 1
    persisted = repr((requirement, accepted, blocked, status))
    assert "ATTACKER_SECRET" not in persisted


@pytest.mark.parametrize(
    ("field", "hostile_value"),
    [
        ("paper_fill_gate_block_reasons", [_HostileScalar()]),
        ("local_block_reasons", _HostileList(["ATTACKER_SECRET_REASON"])),
    ],
)
def test_hostile_prior_reason_container_or_element_is_never_iterated_or_emitted(
    field: str,
    hostile_value: object,
) -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id=f"fill-hostile-prior-reason-{field}",
        notional=101.0,
        leverage=1.0,
        confidence=0.9,
    )
    candidate[field] = hostile_value

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    assert "ATTACKER_SECRET" not in repr((accepted, blocked, status))


def test_invalid_exact_route_scalar_is_redacted_from_route_evidence() -> None:
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-route-value-redacted",
        notional=10.0,
        leverage=1.0,
        confidence=0.9,
    )
    candidate["routes_to_live"] = "ATTACKER_SECRET_ROUTE_VALUE"

    requirement = canonical_margin_requirement(candidate)

    assert requirement["valid"] is False
    assert requirement["paper_input_route_safety_flag_evidence"][0]["value"] == (
        "INVALID_NON_BOOLEAN_FLAG"
    )
    assert "ATTACKER_SECRET_ROUTE_VALUE" not in repr(requirement)


def test_unknown_mapping_key_is_redacted_from_snapshot_failure_path() -> None:
    unknown_key = "ATTACKER_SECRET_UNKNOWN_MAPPING_KEY"
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-unknown-key-redaction",
        notional=10.0,
        leverage=1.0,
        confidence=0.9,
    )
    candidate[unknown_key] = _HostileScalar()

    requirement = canonical_margin_requirement(candidate)

    assert requirement["mapping_snapshot_valid"] is False
    assert "mapping_value[" in requirement["mapping_snapshot_invalid_reason"]
    assert unknown_key not in repr(requirement)
    assert "ATTACKER_SECRET" not in repr(requirement)


def test_duplicate_candidate_identity_fails_entire_collection_closed() -> None:
    candidates = [
        _candidate(
            symbol,
            fill_id="duplicate-fill-id",
            notional=10.0,
            leverage=1.0,
            confidence=confidence,
        )
        for symbol, confidence in (("BTCUSDT", 0.9), ("ETHUSDT", 0.8))
    ]

    accepted, blocked, status = reserve_paper_candidate_margin(
        candidates,
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 2
    assert status["status"] == "FAIL_CLOSED"
    assert status["candidate_canonical_identities_unique"] is False
    assert status["duplicate_candidate_identity_count"] == 2
    assert status["candidate_collection_inputs_valid"] is False
    assert status["newly_reserved_margin_unrounded_usd"] == 0.0


def test_duplicate_open_position_identity_fails_closed_and_counts_conservatively() -> None:
    positions = [
        {
            "position_id": "duplicate-open-position-id",
            "symbol": symbol,
            "net_quantity": 1.0,
            "avg_entry_price": 100.0,
            "maintenance_margin_rate": 0.005,
        }
        for symbol in ("BTCUSDT", "ETHUSDT")
    ]

    status = build_paper_margin_status(
        equity=1_000.0,
        wallet_balance=1_000.0,
        open_positions=positions,
    )

    assert status["status"] == "FAIL_CLOSED"
    assert status["open_position_canonical_identities_unique"] is False
    assert status["duplicate_open_position_identity_group_count"] == 1
    assert status["duplicate_open_position_identity_row_count"] == 2
    assert status["used_margin_unrounded_usd"] == pytest.approx(200.0)
    assert status["free_margin_unrounded_usd"] == 0.0


def test_candidate_identity_overlap_with_open_book_fails_collection_closed() -> None:
    existing = {
        "position_id": "candidate-open-shared-id",
        "symbol": "BTCUSDT",
        "net_quantity": 0.1,
        "avg_entry_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }
    candidate = _candidate(
        "ETHUSDT",
        fill_id="candidate-open-shared-id",
        notional=10.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[existing],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 1
    assert status["status"] == "FAIL_CLOSED"
    assert status["candidate_identities_disjoint_from_existing_open_positions"] is False
    assert status["candidate_existing_identity_overlap_count"] == 1
    assert status["candidate_collection_inputs_valid"] is False


def test_top_level_row_class_metadata_is_never_observed_or_emitted() -> None:
    trap = _ClassMetadataTrap()

    requirement = canonical_margin_requirement(trap)  # type: ignore[arg-type]

    assert trap.class_metadata_observations == 0
    assert requirement["mapping_snapshot_valid"] is False
    assert requirement["valid"] is False
    assert "ATTACKER_SECRET_CLASS" not in repr(requirement)


def test_nested_scalar_class_metadata_is_never_observed_or_emitted() -> None:
    trap = _ClassMetadataTrap()
    candidate = {
        "fill_id": "fill-class-metadata-scalar",
        "symbol": "BTCUSDT",
        "quantity": trap,
        "fill_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }

    requirement = canonical_margin_requirement(candidate)

    assert trap.class_metadata_observations == 0
    assert requirement["mapping_snapshot_valid"] is False
    assert requirement["valid"] is False
    assert "ATTACKER_SECRET_CLASS" not in repr(requirement)


def test_accounting_scope_class_metadata_is_never_observed_or_emitted() -> None:
    trap = _ClassMetadataTrap()
    candidate = {
        "fill_id": "fill-class-metadata-accounting-scope",
        "symbol": "BTCUSDT",
        "quantity": 1.0,
        "fill_price": 100.0,
        "maintenance_margin_rate": 0.005,
    }

    requirement = canonical_margin_requirement(
        candidate,
        accounting_scope=trap,  # type: ignore[arg-type]
    )

    assert trap.class_metadata_observations == 0
    assert requirement["valid"] is False
    assert requirement["accounting_scope"] == "INVALID_ACCOUNTING_SCOPE"
    assert "PAPER_MARGIN_ACCOUNTING_SCOPE_INVALID" in requirement["invalid_reasons"]
    assert "ATTACKER_SECRET_CLASS" not in repr(requirement)


@pytest.mark.parametrize(
    "field",
    [
        "equity",
        "wallet_balance",
        "min_available_margin_buffer_pct",
        "newly_reserved_margin_usd",
    ],
)
def test_account_scalar_class_metadata_is_never_observed_or_emitted(field: str) -> None:
    trap = _ClassMetadataTrap()
    kwargs: dict[str, object] = {
        "equity": 100.0,
        "wallet_balance": 100.0,
        "open_positions": [],
        "min_available_margin_buffer_pct": 0.0,
        "newly_reserved_margin_usd": 0.0,
    }
    kwargs[field] = trap

    status = build_paper_margin_status(**kwargs)  # type: ignore[arg-type]

    assert trap.class_metadata_observations == 0
    assert status["status"] == "FAIL_CLOSED"
    assert "ATTACKER_SECRET_CLASS" not in repr(status)


def test_open_collection_row_class_metadata_is_never_observed_or_emitted() -> None:
    trap = _ClassMetadataTrap()

    status = build_paper_margin_status(
        equity=100.0,
        wallet_balance=100.0,
        open_positions=[trap],  # type: ignore[list-item]
    )

    assert trap.class_metadata_observations == 0
    assert status["status"] == "FAIL_CLOSED"
    assert status["accounting_complete"] is False
    assert "ATTACKER_SECRET_CLASS" not in repr(status)


def test_candidate_collection_row_class_metadata_is_never_observed_or_emitted() -> None:
    trap = _ClassMetadataTrap()

    accepted, blocked, status = reserve_paper_candidate_margin(
        [trap],  # type: ignore[list-item]
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert trap.class_metadata_observations == 0
    assert accepted == []
    assert len(blocked) == 1
    assert status["status"] == "FAIL_CLOSED"
    assert "ATTACKER_SECRET_CLASS" not in repr((accepted, blocked, status))


def test_existing_open_row_class_metadata_is_never_observed_or_emitted() -> None:
    trap = _ClassMetadataTrap()
    candidate = _candidate(
        "BTCUSDT",
        fill_id="fill-after-class-metadata-existing-row",
        notional=10.0,
        leverage=1.0,
        confidence=0.9,
    )

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[trap],  # type: ignore[list-item]
        min_available_margin_buffer_pct=0.0,
    )

    assert trap.class_metadata_observations == 0
    assert accepted == []
    assert len(blocked) == 1
    assert status["status"] == "FAIL_CLOSED"
    assert "ATTACKER_SECRET_CLASS" not in repr((accepted, blocked, status))


def test_candidate_alias_collision_fails_collection_closed() -> None:
    candidates = [
        _candidate(
            symbol,
            fill_id=f"unique-fill-{index}",
            notional=10.0,
            leverage=1.0,
            confidence=0.9 - index * 0.1,
        )
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT"))
    ]
    for candidate in candidates:
        candidate["signal_id"] = "shared-signal-alias"

    accepted, blocked, status = reserve_paper_candidate_margin(
        candidates,
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert accepted == []
    assert len(blocked) == 2
    assert status["status"] == "FAIL_CLOSED"
    assert status["candidate_canonical_identities_unique"] is False
    assert status["duplicate_candidate_identity_count"] == 2


def test_open_position_alias_collision_fails_accounting_closed() -> None:
    positions = [
        {
            "position_id": f"unique-position-{index}",
            "fill_id": "shared-open-fill-alias",
            "symbol": symbol,
            "net_quantity": 1.0,
            "avg_entry_price": 100.0,
            "maintenance_margin_rate": 0.005,
        }
        for index, symbol in enumerate(("BTCUSDT", "ETHUSDT"))
    ]

    status = build_paper_margin_status(
        equity=1_000.0,
        wallet_balance=1_000.0,
        open_positions=positions,
    )

    assert status["status"] == "FAIL_CLOSED"
    assert status["open_position_canonical_identities_unique"] is False
    assert status["duplicate_open_position_identity_group_count"] == 1
    assert status["duplicate_open_position_identity_row_count"] == 2
    assert status["used_margin_unrounded_usd"] == pytest.approx(200.0)
    assert status["free_margin_unrounded_usd"] == 0.0


def test_invalid_identity_mapping_metaclass_name_is_never_observed_or_emitted() -> None:
    _HOSTILE_METACLASS_NAME_OBSERVATIONS["count"] = 0
    candidate = _HostileMetaclassNameMapping()

    accepted, blocked, status = reserve_paper_candidate_margin(
        [candidate],
        equity=100.0,
        wallet_balance=100.0,
        existing_open_positions=[],
        min_available_margin_buffer_pct=0.0,
    )

    assert _HOSTILE_METACLASS_NAME_OBSERVATIONS["count"] == 0
    assert accepted == []
    assert len(blocked) == 1
    assert blocked[0]["paper_candidate_collection_observed_type"] == ("MAPPING_IDENTITY_INVALID")
    assert status["status"] == "FAIL_CLOSED"
    assert "ATTACKER_SECRET_METACLASS_NAME_TEXT" not in repr((accepted, blocked, status))
