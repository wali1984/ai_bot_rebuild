from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    MORALIS_OPTIONAL_FEATURE_NAMES,
)
from v2.backend.app.services.smart_money_wallets import (
    moralis_feature_bridge,
)
from v2.backend.app.services.smart_money_wallets import (
    publisher as moralis_publisher,
)
from v2.backend.app.services.smart_money_wallets.endpoint_registry import (
    MoralisEndpointSpec,
    moralis_endpoint_registry,
)
from v2.backend.app.services.smart_money_wallets.moralis_feature_bridge import (
    DIAGNOSTIC_FEATURE_NAMES,
    FEATURE_NAMES,
    build_moralis_feature_payload,
    publish_moralis_feature_payload,
)
from v2.backend.app.services.smart_money_wallets.normalizer import (
    classifier_evidence_reverification_reasons,
    classifier_source_event_id,
    normalize_moralis_payload,
)
from v2.backend.app.services.smart_money_wallets.publisher import publish_moralis_result

_CLASSIFIER_KEY = b"moralis-test-classifier-authentication-key"
_CLASSIFIER_KEY_ID = "moralis-test-key-2026-07"
_OBSERVED_AT = "2026-07-08T12:03:00Z"


class FakeRedis:
    def __init__(self, *, fail_key: str | None = None) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_key = fail_key

    def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool:
        if key == self.fail_key:
            return False
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return self.ttls.get(key, -1)

    def eval(self, script: str, numkeys: int, *args: object) -> int:
        assert numkeys == 1
        if "MORALIS_AGGREGATE_CAS_V1" not in script:
            raise AssertionError("unexpected Redis script")
        key, expected_exists, expected_raw, replacement, ttl = map(str, args)
        if key == self.fail_key:
            return -1
        current = self.data.get(key)
        if expected_exists == "0":
            if current is not None:
                return 0
        elif current != expected_raw:
            return 0
        self.data[key] = replacement
        self.ttls[key] = int(ttl)
        return 1


class ConcurrentAggregateRedis(FakeRedis):
    def __init__(
        self,
        *,
        competing_aggregate: str,
        competing_artifacts: dict[str, str],
    ) -> None:
        super().__init__()
        self.competing_aggregate = competing_aggregate
        self.competing_artifacts = competing_artifacts
        self.cas_call_count = 0

    def eval(self, script: str, numkeys: int, *args: object) -> int:
        self.cas_call_count += 1
        if self.cas_call_count == 1:
            key = str(args[0])
            self.data.update(self.competing_artifacts)
            for artifact_key in self.competing_artifacts:
                self.ttls[artifact_key] = 7200
            self.data[key] = self.competing_aggregate
            self.ttls[key] = 3600
            return 0
        return super().eval(script, numkeys, *args)


def _spec(endpoint_id: str) -> MoralisEndpointSpec:
    return next(spec for spec in moralis_endpoint_registry() if spec.endpoint_id == endpoint_id)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _iso_utc(value: str) -> str:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _authenticated_classifier_receipts(
    rows: list[dict[str, Any]],
    *,
    endpoint_id: str = "token_transfers",
    request_target_kind: str = "token",
    request_target: str = "0xtoken",
    symbol: str = "BTCUSDT",
) -> dict[str, Any]:
    receipts: dict[str, Any] = {}
    for index, row in enumerate(rows):
        row.setdefault("log_index", index)
        event_id = classifier_source_event_id(row)
        address = row.get("exchange_counterparty_address")
        direction = row.get("exchange_flow_direction")
        event_time = row.get("block_timestamp")
        if not all(
            isinstance(value, str) and value for value in (event_id, address, direction, event_time)
        ):
            continue
        try:
            row_bytes = _canonical_json(row)
        except (TypeError, ValueError):
            continue
        material = {
            "schema_version": "moralis_authenticated_exchange_classifier_receipt_v2",
            "classifier_key_id": _CLASSIFIER_KEY_ID,
            "endpoint_id": endpoint_id,
            "request_target_kind": request_target_kind,
            "request_target": request_target.lower(),
            "symbol": symbol.upper(),
            "chain": "eth",
            "transaction_hash": str(row["transaction_hash"]).lower(),
            "log_index": str(row["log_index"]),
            "counterparty_address": address.lower(),
            "category": "exchange_hot_wallet",
            "flow_direction": direction.lower(),
            "source_event_id": event_id,
            "source_row_sha256": hashlib.sha256(row_bytes).hexdigest(),
            "classifier_event_time": _iso_utc(event_time),
            "classifier_registry_key": "v2:moralis:exchange_classifier_registry:test",
            "classifier_registry_version": "test-registry-v1",
            "classifier_registry_sha256": "a" * 64,
            "classifier_source_key": f"v2:moralis:classifier_source:test:{event_id}",
            "classifier_source_payload_sha256": "b" * 64,
            "authentication_method": "HMAC_SHA256",
        }
        material_bytes = _canonical_json(material)
        receipts[event_id] = {
            **material,
            "claim_sha256": hashlib.sha256(material_bytes).hexdigest(),
            "hmac_sha256": hmac.new(
                _CLASSIFIER_KEY,
                material_bytes,
                hashlib.sha256,
            ).hexdigest(),
        }
    return receipts


def _payload_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("result"), list):
        return [row for row in payload["result"] if isinstance(row, dict)]
    return []


def _normalize(
    endpoint_id: str,
    payload: Any,
    *,
    wallet: str | None = None,
    authenticate_classification: bool = True,
) -> dict[str, Any]:
    rows = _payload_rows(payload)
    return normalize_moralis_payload(
        spec=_spec(endpoint_id),
        symbol="BTCUSDT",
        chain="eth",
        wallet=wallet,
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        payload=payload,
        authenticated_classifier_receipts=(
            _authenticated_classifier_receipts(
                rows,
                endpoint_id=endpoint_id,
                request_target_kind="wallet" if _spec(endpoint_id).requires_wallet else "token",
                request_target=wallet or "0xtoken",
            )
            if authenticate_classification
            else None
        ),
        classifier_authentication_key=(_CLASSIFIER_KEY if authenticate_classification else None),
        classifier_authentication_key_id=(
            _CLASSIFIER_KEY_ID if authenticate_classification else None
        ),
        observed_at=_OBSERVED_AT,
    )


def _publish(
    redis_client: FakeRedis,
    endpoint_id: str,
    payload: Any,
    *,
    wallet: str | None = None,
    token: str = "0xtoken",  # noqa: S107 - fixture contract identifier
    observed_at: str = _OBSERVED_AT,
) -> dict[str, Any]:
    rows = _payload_rows(payload)
    return publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec(endpoint_id),
        chain="eth",
        symbol="BTCUSDT",
        wallet=wallet,
        token=token,
        http_status=200,
        payload=payload,
        budget_status={"compute_budget": {"used_today": 10, "used_month": 10}},
        token_map_count=1,
        wallet_watchlist_count=1,
        authenticated_classifier_receipts=_authenticated_classifier_receipts(
            rows,
            endpoint_id=endpoint_id,
            request_target_kind="wallet" if _spec(endpoint_id).requires_wallet else "token",
            request_target=wallet or token,
        ),
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
        observed_at=observed_at,
    )


def _classified_transfer_rows(
    *, inflow: float = 100.0, outflow: float = 40.0
) -> list[dict[str, Any]]:
    return [
        {
            "exchange_counterparty_classification": "EXCHANGE",
            "exchange_counterparty_address": "0x" + ("1" * 40),
            "exchange_flow_direction": "exchange_inflow",
            "transaction_hash": "0xinflow",
            "value_usd": inflow,
            "block_timestamp": "2026-07-08T12:00:00Z",
        },
        {
            "exchange_counterparty_classification": "EXCHANGE",
            "exchange_counterparty_address": "0x" + ("2" * 40),
            "exchange_flow_direction": "exchange_outflow",
            "transaction_hash": "0xoutflow",
            "value_usd": outflow,
            "block_timestamp": "2026-07-08T12:01:00Z",
        },
    ]


def test_bridge_uses_exact_seven_optional_registry_slots_not_diagnostics() -> None:
    payload = build_moralis_feature_payload(symbol="BTCUSDT")

    assert FEATURE_NAMES == MORALIS_OPTIONAL_FEATURE_NAMES
    assert len(FEATURE_NAMES) == 7
    assert set(FEATURE_NAMES).isdisjoint(DIAGNOSTIC_FEATURE_NAMES)
    assert payload["required_feature_count"] == 0
    assert payload["optional_feature_count"] == 7
    assert set(payload["slot_readiness"]) == set(FEATURE_NAMES)
    assert all(
        row["requirement_class"] == "OPTIONAL_EVENT_DEPENDENT"
        for row in payload["slot_readiness"].values()
    )


@pytest.mark.parametrize(
    ("endpoint_id", "payload", "diagnostic_name", "typed_reason"),
    (
        (
            "wallet_token_balances_price",
            {"result": [{"usd_value": 125.0, "block_timestamp": "2026-07-08T12:00:00Z"}]},
            "moralis_observed_wallet_balance_usd",
            "ABSOLUTE_BALANCE_IS_NOT_FLOW",
        ),
        (
            "wallet_networth",
            {
                "total_networth_usd": 900.0,
                "block_timestamp": "2026-07-08T12:00:00Z",
            },
            "moralis_wallet_networth_usd",
            "ABSOLUTE_NETWORTH_IS_NOT_FLOW",
        ),
    ),
)
def test_absolute_wallet_values_are_diagnostics_never_flow_or_scores(
    endpoint_id: str,
    payload: dict[str, Any],
    diagnostic_name: str,
    typed_reason: str,
) -> None:
    normalized = _normalize(endpoint_id, payload, wallet="0xwallet")

    assert normalized["features"] == {}
    assert normalized["diagnostic_features"][diagnostic_name] > 0
    assert typed_reason in normalized["feature_rejection_reasons"]["moralis_whale_net_flow_usd"]
    assert "moralis_smart_wallet_accumulation_score" not in normalized["features"]
    assert "moralis_smart_wallet_distribution_score" not in normalized["features"]


def test_generic_transfer_direction_never_claims_exchange_flow() -> None:
    normalized = _normalize(
        "token_transfers",
        {
            "result": [
                {
                    "direction": "out",
                    "value_usd": 1200.0,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                }
            ]
        },
    )

    assert normalized["actual_payload_present"] is True
    assert normalized["features"] == {}
    assert normalized["feature_rejection_reasons"]["moralis_exchange_outflow_usd"] == [
        "AUTHENTICATED_CLASSIFIED_EXCHANGE_OUTFLOW_EVIDENCE_MISSING"
    ]


def test_self_declared_exchange_label_without_authenticated_receipt_is_rejected() -> None:
    normalized = _normalize(
        "token_transfers",
        {"result": _classified_transfer_rows()},
        authenticate_classification=False,
    )

    assert normalized["features"] == {}
    assert normalized["feature_evidence"] == {}
    assert normalized["semantic_payload_present"] is False
    assert normalized["normalization_rejection_reasons"] == [
        "ROW_0:AUTHENTICATED_EXCHANGE_CLASSIFIER_RECEIPT_MISSING_OR_INVALID",
        "ROW_1:AUTHENTICATED_EXCHANGE_CLASSIFIER_RECEIPT_MISSING_OR_INVALID",
    ]


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("classifier_registry_key", "v2:untrusted:classifier"),
        ("classifier_key_id", "wrong-key-id"),
        ("endpoint_id", "wallet_history"),
        ("request_target_kind", "wallet"),
        ("request_target", "0xwrong-token"),
        ("symbol", "ETHUSDT"),
        ("transaction_hash", "0xwrong-transaction"),
        ("log_index", "99"),
        ("classifier_registry_version", ""),
        ("classifier_registry_sha256", "0" * 64),
        ("classifier_source_key", ""),
        ("classifier_source_payload_sha256", "0" * 64),
        ("classifier_event_time", "2026-07-08T11:59:59Z"),
        ("source_row_sha256", "0" * 64),
        ("source_event_id", "0xwrong-event"),
        ("counterparty_address", "0x" + ("9" * 40)),
        ("flow_direction", "exchange_outflow"),
        ("category", "unknown_contract"),
        ("claim_sha256", "0" * 64),
        ("hmac_sha256", "0" * 64),
    ),
)
def test_classifier_receipt_tampering_fails_closed(field: str, replacement: str) -> None:
    row = _classified_transfer_rows()[0]
    receipts = _authenticated_classifier_receipts([row])
    event_id = classifier_source_event_id(row)
    assert event_id is not None
    receipts[event_id][field] = replacement

    normalized = normalize_moralis_payload(
        spec=_spec("token_transfers"),
        symbol="BTCUSDT",
        chain="eth",
        wallet=None,
        token="0xtoken",  # noqa: S106 - fixture contract identifier
        payload={"result": [row]},
        authenticated_classifier_receipts=receipts,
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
        observed_at=_OBSERVED_AT,
    )

    assert normalized["features"] == {}
    assert normalized["feature_evidence"] == {}
    assert normalized["normalization_rejection_reasons"] == [
        "ROW_0:AUTHENTICATED_EXCHANGE_CLASSIFIER_RECEIPT_MISSING_OR_INVALID"
    ]


def test_unrelated_later_row_cannot_advance_feature_clock_or_contributor_digest() -> None:
    contributing_rows = _classified_transfer_rows()
    unrelated_row = {
        "transaction_hash": "0xunrelated",
        "block_timestamp": "2026-07-08T12:02:59Z",
        "value_usd": 999999.0,
        "counterparty": "not-classified",
    }
    normalized = _normalize(
        "token_transfers",
        {"result": [*contributing_rows, unrelated_row]},
    )

    assert normalized["event_time"] == "2026-07-08T12:01:00.000000Z"
    for name in (
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
    ):
        evidence = normalized["feature_evidence"][name]
        expected_count = 2 if name == "moralis_net_exchange_flow_usd" else 1
        assert evidence["contributing_row_count"] == expected_count
        assert all(
            receipt["row_canonical_json"] != _canonical_json(unrelated_row).decode("utf-8")
            for receipt in evidence["contributing_rows"]
        )
        assert (
            hashlib.sha256(_canonical_json(evidence["contributing_rows"])).hexdigest()
            == (evidence["contributing_rows_sha256"])
        )


def test_stale_and_clockless_rows_are_rejected_without_erasing_fresh_contributor() -> None:
    fresh = _classified_transfer_rows()[0]
    fresh["block_timestamp"] = "2026-07-08T12:02:00Z"
    stale = _classified_transfer_rows(inflow=700.0)[0]
    stale["transaction_hash"] = "0xstale"
    stale["block_timestamp"] = "2026-07-08T10:00:00Z"
    clockless = _classified_transfer_rows(inflow=900.0)[0]
    clockless["transaction_hash"] = "0xclockless"
    clockless.pop("block_timestamp")

    normalized = _normalize(
        "token_transfers",
        {"result": [fresh, stale, clockless]},
    )

    assert normalized["features"] == {"moralis_exchange_inflow_usd": 100.0}
    evidence = normalized["feature_evidence"]["moralis_exchange_inflow_usd"]
    assert evidence["source_window_seconds"] == 3600
    assert evidence["event_time"] == "2026-07-08T12:02:00.000000Z"
    assert evidence["contributing_row_count"] == 1
    assert evidence["contributing_rows"][0]["row_index"] == 0
    assert normalized["normalization_rejection_reasons"] == [
        "ROW_1:CONTRIBUTOR_STALE_OUTSIDE_SOURCE_WINDOW",
        "ROW_2:AUTHENTICATED_EXCHANGE_CLASSIFIER_RECEIPT_MISSING_OR_INVALID",
    ]


def test_classified_exchange_rows_have_exact_units_direction_and_identity() -> None:
    normalized = _normalize(
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )

    assert normalized["features"] == {
        "moralis_exchange_inflow_usd": 100.0,
        "moralis_exchange_outflow_usd": 40.0,
        "moralis_net_exchange_flow_usd": 60.0,
    }
    net_evidence = normalized["feature_evidence"]["moralis_net_exchange_flow_usd"]
    assert net_evidence["unit"] == "USD"
    assert net_evidence["direction"] == "exchange_inflow_minus_exchange_outflow"
    assert net_evidence["classified_identities"] == [
        "0x" + ("1" * 40),
        "0x" + ("2" * 40),
    ]
    persisted_receipt = net_evidence["contributing_rows"][0]["authenticated_classifier_receipt"]
    assert persisted_receipt["schema_version"] == (
        "moralis_authenticated_exchange_classifier_receipt_v2"
    )
    assert persisted_receipt["classifier_key_id"] == _CLASSIFIER_KEY_ID
    assert persisted_receipt["endpoint_id"] == "token_transfers"
    assert persisted_receipt["request_target"] == "0xtoken"
    assert persisted_receipt["symbol"] == "BTCUSDT"
    assert persisted_receipt["transaction_hash"] == "0xinflow"
    assert persisted_receipt["log_index"] == "0"
    assert persisted_receipt["classifier_registry_key"].startswith(
        "v2:moralis:exchange_classifier_registry:"
    )
    assert persisted_receipt["classifier_source_key"].startswith("v2:moralis:classifier_source:")
    assert len(persisted_receipt["classifier_source_payload_sha256"]) == 64
    assert len(persisted_receipt["claim_sha256"]) == 64
    assert len(persisted_receipt["hmac_sha256"]) == 64

    malformed_identity = _classified_transfer_rows()[0]
    malformed_identity["exchange_counterparty_address"] = "not-an-evm-address"
    rejected = _normalize("token_transfers", {"result": [malformed_identity]})
    assert rejected["features"] == {}


def test_one_sided_classified_flow_does_not_zero_fill_other_side_or_net() -> None:
    normalized = _normalize(
        "token_transfers",
        {"result": [_classified_transfer_rows()[0]]},
    )

    assert normalized["features"] == {"moralis_exchange_inflow_usd": 100.0}
    assert "moralis_exchange_outflow_usd" not in normalized["features"]
    assert "moralis_net_exchange_flow_usd" not in normalized["features"]


def test_holder_price_metadata_stream_and_swap_rows_do_not_fabricate_abi_values() -> None:
    holders = _normalize(
        "token_holders",
        {
            "total": 1000,
            "block_timestamp": "2026-07-08T12:00:00Z",
            "result": [
                {
                    "owner_address": "0xholder",
                    "balance": "99",
                    "block_timestamp": "2026-07-08T12:00:00Z",
                }
            ],
        },
    )
    price = _normalize(
        "token_price",
        {"usdPrice": 7.5, "block_timestamp": "2026-07-08T12:00:00Z"},
    )
    metadata = _normalize(
        "token_metadata",
        [{"address": "0xtoken", "symbol": "TKN", "decimals": 18}],
    )
    streams = _normalize(
        "streams",
        {
            "erc20Transfers": [{"transactionHash": "0x1"}],
            "txs": [{"hash": "0x2"}],
            "block_timestamp": "2026-07-08T12:00:00Z",
        },
    )
    swaps = _normalize(
        "wallet_swaps",
        {
            "result": [
                {
                    "side": "buy",
                    "total_value_usd": 50,
                    "block_timestamp": "2026-07-08T12:00:00Z",
                }
            ]
        },
        wallet="0xwallet",
    )

    assert holders["features"] == {}
    assert holders["diagnostic_features"] == {"moralis_reported_holder_count": 1000.0}
    assert "moralis_holder_delta" not in holders["diagnostic_features"]
    assert price["features"] == {}
    assert price["diagnostic_features"] == {"moralis_observed_token_price_usd": 7.5}
    assert metadata["features"] == {}
    assert streams["features"] == {}
    assert streams["diagnostic_features"] == {
        "moralis_stream_transfer_count": 1.0,
        "moralis_stream_transaction_count": 1.0,
    }
    assert swaps["features"] == {}
    assert swaps["diagnostic_features"] == {"moralis_observed_swap_buy_usd": 50.0}


@pytest.mark.parametrize("invalid", (True, False, float("nan"), float("inf"), float("-inf")))
def test_bool_and_nonfinite_values_never_enter_source_features(invalid: Any) -> None:
    normalized = _normalize(
        "token_transfers",
        {
            "result": [
                {
                    **_classified_transfer_rows()[0],
                    "value_usd": invalid,
                }
            ]
        },
    )
    bridge = build_moralis_feature_payload(
        symbol="BTCUSDT",
        features={"moralis_exchange_inflow_usd": invalid},
        actual_payload_present=True,
    )

    assert normalized["features"] == {}
    assert bridge["source_features"] == {}
    assert bridge["features"] == {}


def test_nonfinite_canonical_projection_is_omitted_and_publication_does_not_crash() -> None:
    redis_client = FakeRedis()
    result = _publish(
        redis_client,
        "token_holders",
        {
            "total": 1,
            "block_timestamp": "2026-07-08T12:00:00Z",
            "result": [
                {
                    "owner_address": "0x" + ("3" * 40),
                    "usd_value": float("nan"),
                    "balance": float("inf"),
                    "block_timestamp": "2026-07-08T12:00:00Z",
                }
            ],
        },
    )
    assert result["publication_acknowledged"] is True
    assert result["raw_transport_actual_payload_present"] is False
    assert not any(key.startswith("v2:moralis:raw:v2:") for key in result["planned_keys"])
    assert set(redis_client.data) == {
        "v2:provider:moralis:usage",
        "v2:provider:moralis:endpoint_status",
        "v2:provider:moralis:health",
    }


def test_clockless_payload_and_supplied_available_at_remain_nonadmissible() -> None:
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        features={"moralis_exchange_inflow_usd": 10.0},
        actual_payload_present=True,
        available_at="2026-07-08T12:00:04Z",
    )

    assert payload["available_at"] is None
    assert payload["source_clock_order_valid"] is False
    assert payload["source_temporal_contract_valid"] is False
    assert payload["provider_ready"] is False
    assert "EVENT_TIME_MISSING" in payload["source_temporal_rejection_reasons"]
    assert "INGESTED_AT_MISSING" in payload["source_temporal_rejection_reasons"]
    assert (
        "SUPPLIED_AVAILABLE_AT_IGNORED_NO_POSTCOMMIT_RECEIPT"
        in payload["source_temporal_rejection_reasons"]
    )


def test_complete_source_clock_order_still_waits_for_postcommit_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        moralis_feature_bridge,
        "_now",
        lambda: "2026-07-08T12:00:03Z",
    )
    name = "moralis_exchange_inflow_usd"
    source_row = _classified_transfer_rows()[0]
    row_canonical_json = _canonical_json(source_row).decode("utf-8")
    contributor = {
        "row_index": 0,
        "event_time": "2026-07-08T12:00:00.000000Z",
        "row_sha256": hashlib.sha256(row_canonical_json.encode("utf-8")).hexdigest(),
        "row_canonical_json": row_canonical_json,
    }
    contributors = [contributor]
    contributors_sha256 = hashlib.sha256(_canonical_json(contributors)).hexdigest()
    evidence = {
        "unit": "USD",
        "direction": "exchange_inflow",
        "measurement_scope": "classified_exchange_counterparties_only",
        "contributing_row_count": 1,
        "contributing_rows": contributors,
        "contributing_rows_sha256": contributors_sha256,
        "event_time": "2026-07-08T12:00:00.000000Z",
        "feature_cutoff": "2026-07-08T12:00:00.000000Z",
        "source_window_seconds": 3600,
        "freshness_status": "FRESH_WITHIN_SOURCE_WINDOW",
    }
    payload = build_moralis_feature_payload(
        symbol="BTCUSDT",
        features={name: 10.0},
        feature_evidence={name: evidence},
        feature_origins={
            name: {
                "provider": "moralis",
                "endpoint_id": "token_transfers",
                "source_key": "v2:moralis:raw:v2:token_transfers:test:source",
                "source_schema_version": "moralis_normalized_payload_v2",
                "source_payload_sha256": "a" * 64,
                "source_binding_sha256": "b" * 64,
                "unit": "USD",
                "direction": "exchange_inflow",
                "measurement_scope": "classified_exchange_counterparties_only",
                "contributing_rows_sha256": contributors_sha256,
                "event_time": "2026-07-08T12:00:00.000000Z",
                "feature_cutoff": "2026-07-08T12:00:00.000000Z",
            }
        },
        actual_payload_present=True,
        event_time="2026-07-08T12:00:00Z",
        feature_cutoff="2026-07-08T12:00:01Z",
        ingested_at="2026-07-08T12:00:02Z",
    )

    slot = payload["slot_readiness"][name]
    assert payload["source_clock_order_valid"] is True
    assert slot["semantic_value_present"] is True
    assert slot["semantic_evidence_present"] is True
    assert slot["source_origin_bound"] is True
    assert payload["source_lineage_ready_feature_count"] == 1
    assert slot["admissible"] is False
    assert payload["available_at"] is None
    assert payload["features"] == {}
    assert "POSTCOMMIT_RECEIPT_UNBOUND" in slot["reasons"]


def test_publication_binds_exact_normalized_bytes_digest_key_and_origin() -> None:
    redis_client = FakeRedis()
    result = _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source_text = redis_client.data[source_key]
    source = json.loads(source_text)
    source_bytes = source_text.encode("utf-8")
    digest = hashlib.sha256(source_bytes).hexdigest()
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    endpoint = aggregate["endpoint_payloads"]["token_transfers"]
    binding_bytes = endpoint["source_binding_canonical_json"].encode("utf-8")
    binding_digest = hashlib.sha256(binding_bytes).hexdigest()

    assert endpoint["source_payload_canonical_json"] == source_text
    assert digest == endpoint["source_payload_sha256"]
    assert source_key.endswith(digest)
    assert binding_digest == endpoint["source_binding_sha256"]
    assert json.loads(binding_bytes) == {
        "endpoint_id": "token_transfers",
        "provider": "moralis",
        "source_identity": endpoint["source_identity"],
        "source_key": source_key,
        "source_payload_sha256": digest,
        "source_schema_version": "moralis_normalized_payload_v2",
    }
    for origin in endpoint["feature_origins"].values():
        assert origin["source_key"] == source_key
        assert origin["source_identity"] == endpoint["source_identity"]
        assert origin["source_schema_version"] == "moralis_normalized_payload_v2"
        assert origin["source_payload_sha256"] == digest
        assert origin["source_binding_sha256"] == binding_digest
    assert source["available_at"] is None
    assert source["publication_authority"] is False
    assert endpoint["provider_ready"] is False


def test_raw_registry_keys_are_endpoint_qualified_content_addressed_and_collision_free() -> None:
    keys: dict[str, str] = {}
    for spec in moralis_endpoint_registry():
        key = moralis_publisher._raw_keys(
            spec,
            chain="eth",
            wallet="0x" + ("7" * 40),
            token="0x" + ("8" * 40),
            symbol="BTCUSDT",
            source_payload_sha256="c" * 64,
        )[0]
        keys[spec.endpoint_id] = key
        assert key.startswith(f"v2:moralis:raw:v2:{spec.endpoint_id}:")
        assert key.endswith("c" * 64)

    assert len(keys) == len(moralis_endpoint_registry())
    assert len(set(keys.values())) == len(keys)


def test_monotonic_updates_never_refresh_duplicates_or_accept_older_or_divergent_clocks() -> None:
    redis_client = FakeRedis()
    rows = _classified_transfer_rows()
    first = _publish(
        redis_client,
        "token_transfers",
        {"result": rows},
    )
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    bridge_keys = list(
        moralis_publisher.moralis_feature_fanout_keys(symbol="BTCUSDT", timeframe="1m")
    )
    immutable_keys = [aggregate_key, *bridge_keys]
    first_values = {key: redis_client.data[key] for key in immutable_keys}
    first_ttls = {key: redis_client.ttls[key] for key in immutable_keys}
    source_key = next(key for key in first["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source_ttl = redis_client.ttls[source_key]

    duplicate = _publish(
        redis_client,
        "token_transfers",
        {"result": rows},
        observed_at="2026-07-08T12:04:00Z",
    )
    assert duplicate["aggregate_update_status"] == "EXACT_DUPLICATE_NO_REFRESH"
    assert duplicate["duplicate_keys"] == [source_key]
    assert redis_client.ttls[source_key] == source_ttl
    assert {key: redis_client.data[key] for key in immutable_keys} == first_values
    assert {key: redis_client.ttls[key] for key in immutable_keys} == first_ttls

    older_rows = deepcopy(rows)
    older_rows[0]["block_timestamp"] = "2026-07-08T11:58:00Z"
    older_rows[1]["block_timestamp"] = "2026-07-08T11:59:00Z"
    older = _publish(
        redis_client,
        "token_transfers",
        {"result": older_rows},
        observed_at="2026-07-08T12:04:00Z",
    )
    assert older["aggregate_update_status"] == "OLDER_SOURCE_EVENT_REJECTED"
    assert {key: redis_client.data[key] for key in immutable_keys} == first_values
    assert {key: redis_client.ttls[key] for key in immutable_keys} == first_ttls

    divergent_rows = _classified_transfer_rows(inflow=999.0, outflow=1.0)
    divergent = _publish(
        redis_client,
        "token_transfers",
        {"result": divergent_rows},
        observed_at="2026-07-08T12:04:00Z",
    )
    assert divergent["aggregate_update_status"] == ("SAME_CLOCK_DIVERGENT_DIGEST_QUARANTINED")
    assert {key: redis_client.data[key] for key in immutable_keys} == first_values
    assert {key: redis_client.ttls[key] for key in immutable_keys} == first_ttls

    newer_rows = _classified_transfer_rows(inflow=250.0, outflow=50.0)
    newer_rows[0]["block_timestamp"] = "2026-07-08T12:02:00Z"
    newer_rows[1]["block_timestamp"] = "2026-07-08T12:03:00Z"
    newer = _publish(
        redis_client,
        "token_transfers",
        {"result": newer_rows},
        observed_at="2026-07-08T12:04:00Z",
    )
    assert newer["aggregate_update_status"] == "APPLIED_NEWER_ATOMIC_CAS"
    aggregate = json.loads(redis_client.data[aggregate_key])
    assert aggregate["endpoint_payloads"]["token_transfers"]["features"] == {
        "moralis_exchange_inflow_usd": 250.0,
        "moralis_exchange_outflow_usd": 50.0,
        "moralis_net_exchange_flow_usd": 200.0,
    }


def test_atomic_cas_retry_preserves_concurrent_distinct_source_update() -> None:
    competitor = FakeRedis()
    _publish(
        competitor,
        "token_transfers",
        {"result": _classified_transfer_rows(inflow=900.0, outflow=10.0)},
        token="0xtoken-b",  # noqa: S106 - fixture contract identifier
    )
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    competing_artifacts = {
        key: value for key, value in competitor.data.items() if key.startswith("v2:moralis:raw:v2:")
    }
    redis_client = ConcurrentAggregateRedis(
        competing_aggregate=competitor.data[aggregate_key],
        competing_artifacts=competing_artifacts,
    )

    result = _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows(inflow=100.0, outflow=40.0)},
        token="0xtoken-a",  # noqa: S106 - fixture contract identifier
    )

    aggregate = json.loads(redis_client.data[aggregate_key])
    assert result["aggregate_update_status"] == "APPLIED_NEWER_ATOMIC_CAS"
    assert redis_client.cas_call_count == 2
    assert len(aggregate["endpoint_payloads"]) == 2
    assert all(key.startswith("token_transfers#") for key in aggregate["endpoint_payloads"])
    assert set(aggregate["feature_conflicts"]) == {
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
    }


def test_conflicting_feature_claims_are_quarantined_not_last_writer_wins() -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows(inflow=100.0, outflow=40.0)},
    )
    _publish(
        redis_client,
        "wallet_history",
        {"result": _classified_transfer_rows(inflow=900.0, outflow=10.0)},
        wallet="0xwallet",
    )

    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    canonical = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    conflicts = aggregate["feature_conflicts"]
    assert set(conflicts) == {
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
    }
    assert all(len(row["claims"]) == 2 for row in conflicts.values())
    assert aggregate["source_features"] == {}
    assert canonical["source_features"] == {}
    assert canonical["features"] == {}
    assert canonical["provider_ready"] is False


def test_same_endpoint_distinct_source_keys_are_both_retained_and_quarantined() -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows(inflow=100.0, outflow=40.0)},
        token="0xtoken-a",  # noqa: S106 - fixture contract identifier
    )
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows(inflow=900.0, outflow=10.0)},
        token="0xtoken-b",  # noqa: S106 - fixture contract identifier
    )

    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    assert len(aggregate["endpoint_payloads"]) == 2
    assert all(key.startswith("token_transfers#") for key in aggregate["endpoint_payloads"])
    assert set(aggregate["feature_conflicts"]) == {
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
    }
    assert aggregate["raw_transport_record_count"] == 4
    assert aggregate["source_feature_claim_count"] == 6
    assert aggregate["source_semantic_claim_count"] == 6
    assert aggregate["admitted_feature_count"] == 0
    assert aggregate["source_features"] == {}
    bridge = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    assert bridge["source_feature_count"] == 0
    assert bridge["source_feature_claim_count"] == 6
    assert bridge["source_semantic_claim_count"] == 6
    assert bridge["admitted_feature_count"] == 0


def test_tampered_aggregate_claim_is_rejected_against_exact_source_bytes() -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    prior = json.loads(redis_client.data[aggregate_key])
    prior["endpoint_payloads"]["token_transfers"]["features"]["moralis_exchange_inflow_usd"] = (
        999999.0
    )
    redis_client.data[aggregate_key] = _canonical_json(prior).decode("utf-8")

    _publish(
        redis_client,
        "wallet_swaps",
        {
            "result": [
                {
                    "side": "buy",
                    "total_value_usd": 25.0,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                }
            ]
        },
        wallet="0xwallet",
    )

    aggregate = json.loads(redis_client.data[aggregate_key])
    assert set(aggregate["endpoint_payloads"]) == {"wallet_swaps"}
    assert aggregate["source_features"] == {}
    assert (
        "token_transfers:SOURCE_FEATURES_MISMATCH"
        in aggregate["endpoint_temporal_rejection_reasons"]
    )


@pytest.mark.parametrize(
    ("field", "replacement", "expected_reason"),
    (
        (
            "raw_transport_record_count",
            999_999,
            "EXACT_SOURCE_RAW_TRANSPORT_RECORD_COUNT_MISMATCH",
        ),
        (
            "source_feature_claim_count",
            888_888,
            "EXACT_SOURCE_FEATURE_CLAIM_COUNT_MISMATCH",
        ),
        (
            "source_diagnostic_claim_count",
            777_777,
            "EXACT_SOURCE_DIAGNOSTIC_CLAIM_COUNT_MISMATCH",
        ),
        (
            "source_semantic_claim_count",
            666_666,
            "EXACT_SOURCE_SEMANTIC_CLAIM_COUNT_MISMATCH",
        ),
        (
            "admitted_feature_count",
            1,
            "EXACT_SOURCE_ADMITTED_FEATURE_COUNT_MISMATCH",
        ),
        (
            "raw_transport_record_count",
            "not-an-int",
            "RAW_TRANSPORT_RECORD_COUNT_INVALID",
        ),
    ),
)
def test_tampered_or_malformed_source_counts_are_quarantined_without_crashing(
    field: str,
    replacement: Any,
    expected_reason: str,
) -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    prior = json.loads(redis_client.data[aggregate_key])
    endpoint = prior["endpoint_payloads"]["token_transfers"]
    endpoint[field] = replacement
    reasons = moralis_publisher._endpoint_integrity_rejection_reasons(  # noqa: SLF001
        endpoint,
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
    )
    assert expected_reason in reasons
    redis_client.data[aggregate_key] = _canonical_json(prior).decode("utf-8")

    _publish(
        redis_client,
        "wallet_swaps",
        {
            "result": [
                {
                    "side": "buy",
                    "total_value_usd": 25.0,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                }
            ]
        },
        wallet="0xwallet",
    )

    repaired = json.loads(redis_client.data[aggregate_key])
    assert set(repaired["endpoint_payloads"]) == {"wallet_swaps"}
    assert f"token_transfers:{expected_reason}" in repaired["endpoint_temporal_rejection_reasons"]
    assert repaired["raw_transport_record_count"] == 1
    assert repaired["source_feature_claim_count"] == 0
    assert repaired["source_diagnostic_claim_count"] == 1
    assert repaired["source_semantic_claim_count"] == 1
    assert repaired["admitted_feature_count"] == 0


@pytest.mark.parametrize(
    ("path", "replacement", "expected_reason"),
    (
        (("event_time",), "2026-07-08T11:59:59Z", "SOURCE_EVENT_TIME_MISMATCH"),
        (
            ("feature_origins", "moralis_exchange_inflow_usd", "unit"),
            "events",
            "SOURCE_FEATURE_ORIGIN_MISMATCH",
        ),
    ),
)
def test_tampered_source_clock_or_semantic_origin_is_quarantined(
    path: tuple[str, ...],
    replacement: Any,
    expected_reason: str,
) -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    prior = json.loads(redis_client.data[aggregate_key])
    target = prior["endpoint_payloads"]["token_transfers"]
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = replacement
    redis_client.data[aggregate_key] = _canonical_json(prior).decode("utf-8")

    _publish(
        redis_client,
        "wallet_swaps",
        {
            "result": [
                {
                    "side": "buy",
                    "total_value_usd": 25.0,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                }
            ]
        },
        wallet="0xwallet",
    )

    aggregate = json.loads(redis_client.data[aggregate_key])
    assert set(aggregate["endpoint_payloads"]) == {"wallet_swaps"}
    assert f"token_transfers:{expected_reason}" in aggregate["endpoint_temporal_rejection_reasons"]


def test_false_feature_publication_ack_stops_following_writes_and_stays_masked() -> None:
    failed_key = "v2:features:provider:moralis:BTCUSDT:1m"
    redis_client = FakeRedis(fail_key=failed_key)
    result = publish_moralis_feature_payload(
        redis_client,
        symbol="BTCUSDT",
        features={"moralis_exchange_inflow_usd": 10.0},
        actual_payload_present=True,
    )

    assert result["publication_acknowledged"] is False
    assert result["publication_attempt_status"] == "PARTIAL_WRITE_FAILED_NON_AUTHORITATIVE"
    assert result["failed_keys"] == [failed_key]
    assert result["keys_written"] == ["v2:features:moralis:BTCUSDT:1m"]
    assert "v2:smart_money:signals:BTCUSDT" in result["unattempted_keys"]
    stored = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    assert stored["available_at"] is None
    assert stored["publication_authority"] is False
    assert stored["features"] == {}


def test_false_source_ack_prevents_aggregate_and_bridge_publication() -> None:
    probe_result = _publish(
        FakeRedis(),
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    source_key = next(
        key for key in probe_result["planned_keys"] if key.startswith("v2:moralis:raw:v2:")
    )
    redis_client = FakeRedis(fail_key=source_key)
    result = _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )

    assert result["publication_acknowledged"] is False
    assert result["failed_keys"] == [source_key]
    assert "v2:moralis:feature_aggregate:BTCUSDT:1m" not in redis_client.data
    assert "v2:features:moralis:BTCUSDT:1m" not in redis_client.data
    assert result["available_at"] is None
    assert result["provider_ready"] is False


def test_every_fanout_failure_reports_exact_planned_failed_and_unattempted_graph() -> None:
    payload = {"result": _classified_transfer_rows()}
    probe = _publish(FakeRedis(), "token_transfers", payload)
    planned = probe["planned_keys"]

    assert planned[0].startswith("v2:moralis:raw:v2:token_transfers:")
    assert planned[1] == "v2:moralis:feature_aggregate:BTCUSDT:1m"
    assert planned[-3:] == [
        "v2:provider:moralis:usage",
        "v2:provider:moralis:endpoint_status",
        "v2:provider:moralis:health",
    ]
    assert len(planned) == 11

    for index, failed_key in enumerate(planned):
        redis_client = FakeRedis(fail_key=failed_key)
        result = _publish(redis_client, "token_transfers", payload)

        assert result["planned_keys"] == planned
        assert result["publication_acknowledged"] is False
        assert result["failed_keys"] == [failed_key]
        assert result["unattempted_keys"] == planned[index + 1 :]
        assert all(key not in redis_client.data for key in planned[index + 1 :])


def test_rate_limit_cadence_expiry_and_partial_control_failure_never_refresh_source_state() -> None:
    redis_client = FakeRedis()
    success = _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    source_key = next(
        key for key in success["planned_keys"] if key.startswith("v2:moralis:raw:v2:")
    )
    source_state_keys = [
        source_key,
        "v2:moralis:feature_aggregate:BTCUSDT:1m",
        *moralis_publisher.moralis_feature_fanout_keys(symbol="BTCUSDT", timeframe="1m"),
    ]
    source_values = {key: redis_client.data[key] for key in source_state_keys}
    source_ttls = {key: redis_client.ttls[key] for key in source_state_keys}

    def publish_transport_state(
        *,
        observed_at: str,
        http_status: int | None,
        error_class: str,
    ) -> dict[str, Any]:
        return publish_moralis_result(
            redis_client,
            env={"MORALIS_API_KEY": "fixture-key"},
            spec=_spec("token_transfers"),
            chain="eth",
            symbol="BTCUSDT",
            token="0xtoken",  # noqa: S106 - fixture contract identifier
            http_status=http_status,
            payload=None,
            budget_status={"compute_budget": {"used_today": 10, "used_month": 10}},
            error_class=error_class,
            token_map_count=1,
            wallet_watchlist_count=1,
            observed_at=observed_at,
        )

    rate_limited = publish_transport_state(
        observed_at="2026-07-08T12:10:00Z",
        http_status=429,
        error_class="RATE_LIMITED",
    )
    health = json.loads(redis_client.data["v2:provider:moralis:health"])
    assert rate_limited["planned_keys"] == [
        "v2:provider:moralis:usage",
        "v2:provider:moralis:endpoint_status",
        "v2:provider:moralis:health",
    ]
    assert health["current_transport_status"] == "RATE_LIMITED"
    assert health["retained_state"]["state"] == ("RETAINED_SOURCE_STATE_FRESH_NON_AUTHORITATIVE")
    assert health["retained_state"]["source_age_seconds"] == 540.0
    assert health["retained_state"]["admitted_carry_forward"] is False
    assert health["retained_state"]["freshness_refreshed"] is False
    assert health["retained_state"]["expiry_refreshed"] is False
    assert health["retained_state"]["authority_refreshed"] is False
    assert {key: redis_client.data[key] for key in source_state_keys} == source_values
    assert {key: redis_client.ttls[key] for key in source_state_keys} == source_ttls
    for key in moralis_publisher.moralis_feature_fanout_keys(
        symbol="BTCUSDT",
        timeframe="1m",
    ):
        retained_payload = json.loads(redis_client.data[key])
        if "features" in retained_payload:
            assert retained_payload["features"] == {}
        assert retained_payload["available_at"] is None
        assert retained_payload["trainer_authority"] is False

    cadence = publish_transport_state(
        observed_at="2026-07-08T12:20:00Z",
        http_status=None,
        error_class="DURABLE_CADENCE_CLAIM_ACTIVE",
    )
    health = json.loads(redis_client.data["v2:provider:moralis:health"])
    assert cadence["status"] == "CADENCE_DEFERRED"
    assert health["current_transport_status"] == "CADENCE_DEFERRED"
    assert health["retained_state"]["state"] == ("RETAINED_SOURCE_STATE_FRESH_NON_AUTHORITATIVE")
    assert {key: redis_client.data[key] for key in source_state_keys} == source_values
    assert {key: redis_client.ttls[key] for key in source_state_keys} == source_ttls

    redis_client.fail_key = "v2:provider:moralis:endpoint_status"
    partial = publish_transport_state(
        observed_at="2026-07-08T12:30:00Z",
        http_status=429,
        error_class="RATE_LIMITED",
    )
    assert partial["failed_keys"] == ["v2:provider:moralis:endpoint_status"]
    assert partial["unattempted_keys"] == ["v2:provider:moralis:health"]
    assert {key: redis_client.data[key] for key in source_state_keys} == source_values
    assert {key: redis_client.ttls[key] for key in source_state_keys} == source_ttls

    redis_client.fail_key = None
    expired = publish_transport_state(
        observed_at="2026-07-08T13:04:00Z",
        http_status=429,
        error_class="RATE_LIMITED",
    )
    endpoint_status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])
    retained = endpoint_status["endpoints"]["token_transfers"]["retained_state"]
    assert expired["status"] == "RATE_LIMITED"
    assert retained["state"] == "RETAINED_SOURCE_STATE_EXPIRED"
    assert retained["source_carry_forward_observable"] is False
    assert retained["admitted_carry_forward"] is False
    assert {key: redis_client.data[key] for key in source_state_keys} == source_values
    assert {key: redis_client.ttls[key] for key in source_state_keys} == source_ttls


@pytest.mark.parametrize("invalid", (object(), float("nan"), float("inf"), float("-inf")))
def test_strict_json_preflight_rejects_unsupported_and_nonfinite_budget_values(
    invalid: Any,
) -> None:
    redis_client = FakeRedis()
    rows = _classified_transfer_rows()
    result = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec("token_transfers"),
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture contract identifier
        http_status=200,
        payload={"result": rows},
        budget_status={"invalid": invalid},
        authenticated_classifier_receipts=_authenticated_classifier_receipts(rows),
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
        observed_at=_OBSERVED_AT,
    )

    assert result["publication_acknowledged"] is False
    assert result["publication_attempt_status"] == "STRICT_JSON_SERIALIZATION_REJECTED"
    assert result["failed_keys"] == ["STRICT_JSON_PREFLIGHT"]
    assert result["unattempted_keys"] == result["planned_keys"]
    assert len(result["planned_keys"]) == 11
    assert redis_client.data == {}
    assert redis_client.ttls == {}


def test_rate_limited_state_is_typed_and_never_zero_filled() -> None:
    redis_client = FakeRedis()
    result = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec("token_transfers"),
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=429,
        payload=None,
        budget_status={"compute_budget": {"used_today": 10, "used_month": 10}},
        error_class="RATE_LIMITED",
        token_map_count=1,
        wallet_watchlist_count=1,
        observed_at=_OBSERVED_AT,
    )
    endpoint_status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])

    assert result["status"] == "RATE_LIMITED"
    assert endpoint_status["endpoints"]["token_transfers"]["status"] == "RATE_LIMITED"
    assert endpoint_status["endpoints"]["token_transfers"]["retained_state"]["state"] == (
        "NO_RETAINED_SOURCE_STATE"
    )
    assert "v2:features:moralis:BTCUSDT:1m" not in redis_client.data
    assert result["aggregate_update_status"] == "NO_SEMANTIC_SOURCE_OBSERVATION"
    assert result["planned_keys"] == [
        "v2:provider:moralis:usage",
        "v2:provider:moralis:endpoint_status",
        "v2:provider:moralis:health",
    ]


def test_cadence_deferred_state_is_typed_and_never_zero_filled() -> None:
    redis_client = FakeRedis()
    result = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec("token_transfers"),
        chain="eth",
        symbol="BTCUSDT",
        token="0xtoken",  # noqa: S106 - fixture token identifier, not a credential
        http_status=None,
        payload=None,
        budget_status={"compute_budget": {"used_today": 10, "used_month": 10}},
        error_class="DURABLE_CADENCE_CLAIM_ACTIVE",
        token_map_count=1,
        wallet_watchlist_count=1,
        observed_at=_OBSERVED_AT,
    )
    endpoint_status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])

    assert result["status"] == "CADENCE_DEFERRED"
    assert endpoint_status["endpoints"]["token_transfers"]["status"] == "CADENCE_DEFERRED"
    assert endpoint_status["endpoints"]["token_transfers"]["retained_state"]["state"] == (
        "NO_RETAINED_SOURCE_STATE"
    )
    assert "v2:features:moralis:BTCUSDT:1m" not in redis_client.data
    assert result["aggregate_update_status"] == "NO_SEMANTIC_SOURCE_OBSERVATION"


def test_incomplete_fanout_is_durably_completed_on_exact_duplicate_retry() -> None:
    failed_key = "v2:features:provider:moralis:BTCUSDT:1m"
    redis_client = FakeRedis(fail_key=failed_key)
    payload = {"result": _classified_transfer_rows()}

    first = _publish(redis_client, "token_transfers", payload)
    source_key = next(key for key in first["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    aggregate_before = redis_client.data[aggregate_key]
    aggregate_ttl_before = redis_client.ttls[aggregate_key]
    source_ttl_before = redis_client.ttls[source_key]
    completion_key = "v2:provider:moralis:fanout_completion:BTCUSDT:1m"
    assert first["publication_acknowledged"] is False
    assert first["failed_keys"] == [failed_key]
    assert completion_key not in redis_client.data

    redis_client.fail_key = None
    repaired = _publish(
        redis_client,
        "token_transfers",
        payload,
        observed_at="2026-07-08T12:59:30Z",
    )
    assert repaired["aggregate_update_status"] == "EXACT_DUPLICATE_NO_REFRESH"
    assert repaired["publication_acknowledged"] is True
    assert repaired["failed_keys"] == []
    assert redis_client.data[aggregate_key] == aggregate_before
    assert redis_client.ttls[aggregate_key] == aggregate_ttl_before
    assert redis_client.ttls[source_key] == source_ttl_before
    aggregate_sha = hashlib.sha256(aggregate_before.encode("utf-8")).hexdigest()
    assert moralis_feature_bridge.verify_moralis_feature_fanout_completion(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        aggregate_artifact_sha256=aggregate_sha,
        expires_at=json.loads(aggregate_before)["expires_at"],
        observed_at="2026-07-08T12:59:30Z",
    )

    fanout_keys = moralis_publisher.moralis_feature_fanout_keys(
        symbol="BTCUSDT",
        timeframe="1m",
    )
    fanout_before = {key: redis_client.data[key] for key in fanout_keys}
    fanout_ttls_before = {key: redis_client.ttls[key] for key in fanout_keys}
    assert all(ttl <= 210 for ttl in fanout_ttls_before.values())
    third = _publish(
        redis_client,
        "token_transfers",
        payload,
        observed_at="2026-07-08T12:59:40Z",
    )
    assert third["publication_acknowledged"] is True
    assert {key: redis_client.data[key] for key in fanout_keys} == fanout_before
    assert {key: redis_client.ttls[key] for key in fanout_keys} == fanout_ttls_before
    assert all(
        third["skip_reasons"][key] == "FANOUT_ALREADY_COMPLETE_NO_REFRESH" for key in fanout_keys
    )


def test_exact_duplicate_retry_repairs_short_lived_fanout_completion_graph() -> None:
    redis_client = FakeRedis()
    payload = {"result": _classified_transfer_rows()}
    _publish(redis_client, "token_transfers", payload)
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    aggregate_raw = redis_client.data[aggregate_key]
    aggregate = json.loads(aggregate_raw)
    aggregate_sha = hashlib.sha256(aggregate_raw.encode("utf-8")).hexdigest()
    fanout_keys = moralis_publisher.moralis_feature_fanout_keys(
        symbol="BTCUSDT",
        timeframe="1m",
    )
    completion_key = moralis_feature_bridge.MORALIS_FANOUT_COMPLETION_KEY.format(
        symbol="BTCUSDT",
        timeframe="1m",
    )
    short_lived_artifact = fanout_keys[0]
    redis_client.ttls[short_lived_artifact] = 1
    redis_client.ttls[completion_key] = 1

    assert not moralis_feature_bridge.verify_moralis_feature_fanout_completion(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        aggregate_artifact_sha256=aggregate_sha,
        expires_at=aggregate["expires_at"],
        observed_at="2026-07-08T12:03:10Z",
    )

    repaired = _publish(
        redis_client,
        "token_transfers",
        payload,
        observed_at="2026-07-08T12:03:10Z",
    )

    assert repaired["aggregate_update_status"] == "EXACT_DUPLICATE_NO_REFRESH"
    assert repaired["publication_acknowledged"] is True
    assert short_lived_artifact in repaired["keys_written"]
    assert completion_key in repaired["keys_written"]
    assert redis_client.ttls[short_lived_artifact] > 1
    assert redis_client.ttls[completion_key] > 1
    assert moralis_feature_bridge.verify_moralis_feature_fanout_completion(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        aggregate_artifact_sha256=aggregate_sha,
        expires_at=aggregate["expires_at"],
        observed_at="2026-07-08T12:03:10Z",
    )


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("postcommit_receipt_bound", True),
        ("admitted_feature_count", 1),
        ("admitted_feature_count", False),
        ("available_at", "2026-07-08T12:03:01Z"),
        ("trainer_authority", True),
        ("actual_consumption", True),
        ("actual_payload_present", True),
        ("feature_count", 1),
        ("trainer_consumption", True),
        ("trainer_consumption_prerequisites_bound", True),
        ("consumer_receipts_bound", True),
        ("admitted_ready", True),
        ("feature_bridge_ready", True),
        ("provider_ready", True),
        ("moralis_can_approve_trade_alone", True),
        ("publication_atomic", True),
    ),
)
def test_exact_duplicate_retry_repairs_authority_bearing_fanout_completion(
    field: str,
    forged_value: object,
) -> None:
    redis_client = FakeRedis()
    payload = {"result": _classified_transfer_rows()}
    _publish(redis_client, "token_transfers", payload)
    aggregate_key = "v2:moralis:feature_aggregate:BTCUSDT:1m"
    aggregate_raw = redis_client.data[aggregate_key]
    aggregate = json.loads(aggregate_raw)
    aggregate_sha = hashlib.sha256(aggregate_raw.encode("utf-8")).hexdigest()
    completion_key = moralis_feature_bridge.MORALIS_FANOUT_COMPLETION_KEY.format(
        symbol="BTCUSDT",
        timeframe="1m",
    )
    completion = json.loads(redis_client.data[completion_key])
    completion[field] = forged_value
    redis_client.data[completion_key] = _canonical_json(completion).decode("utf-8")

    assert not moralis_feature_bridge.verify_moralis_feature_fanout_completion(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        aggregate_artifact_sha256=aggregate_sha,
        expires_at=aggregate["expires_at"],
        observed_at="2026-07-08T12:03:10Z",
    )

    repaired = _publish(
        redis_client,
        "token_transfers",
        payload,
        observed_at="2026-07-08T12:03:10Z",
    )
    repaired_completion = json.loads(redis_client.data[completion_key])
    assert repaired["publication_acknowledged"] is True
    assert completion_key in repaired["keys_written"]
    assert repaired_completion["postcommit_receipt_bound"] is False
    assert type(repaired_completion["admitted_feature_count"]) is int
    assert repaired_completion["admitted_feature_count"] == 0
    assert repaired_completion["available_at"] is None
    assert repaired_completion["trainer_authority"] is False
    assert moralis_feature_bridge.verify_moralis_feature_fanout_completion(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        aggregate_artifact_sha256=aggregate_sha,
        expires_at=aggregate["expires_at"],
        observed_at="2026-07-08T12:03:10Z",
    )


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("trainer_authority", True),
        ("actual_consumption", True),
        ("actual_payload_present", True),
        ("feature_count", 1),
        ("trainer_consumption", True),
        ("trainer_consumption_prerequisites_bound", True),
        ("consumer_receipts_bound", True),
        ("admitted_ready", True),
        ("moralis_can_approve_trade_alone", True),
        ("publication_atomic", True),
        ("trainer_isolation_active", False),
        ("heartbeat_only", False),
        ("missing_mask", {FEATURE_NAMES[0]: False}),
    ),
)
def test_fanout_completion_rejects_authority_bearing_durable_artifact(
    field: str,
    forged_value: object,
) -> None:
    redis_client = FakeRedis()
    payload = {"result": _classified_transfer_rows()}
    _publish(redis_client, "token_transfers", payload)
    aggregate_raw = redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"]
    aggregate = json.loads(aggregate_raw)
    aggregate_sha = hashlib.sha256(aggregate_raw.encode("utf-8")).hexdigest()
    completion_key = moralis_feature_bridge.MORALIS_FANOUT_COMPLETION_KEY.format(
        symbol="BTCUSDT",
        timeframe="1m",
    )
    completion = json.loads(redis_client.data[completion_key])
    artifact_key = "v2:features:moralis:BTCUSDT:1m"
    artifact = json.loads(redis_client.data[artifact_key])
    artifact[field] = forged_value
    artifact_raw = _canonical_json(artifact).decode("utf-8")
    redis_client.data[artifact_key] = artifact_raw
    completion["artifact_sha256"][artifact_key] = hashlib.sha256(
        artifact_raw.encode("utf-8")
    ).hexdigest()
    redis_client.data[completion_key] = _canonical_json(completion).decode("utf-8")

    assert not moralis_feature_bridge.verify_moralis_feature_fanout_completion(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        aggregate_artifact_sha256=aggregate_sha,
        expires_at=aggregate["expires_at"],
        observed_at="2026-07-08T12:03:10Z",
    )

    repaired = _publish(
        redis_client,
        "token_transfers",
        payload,
        observed_at="2026-07-08T12:03:10Z",
    )
    repaired_artifact = json.loads(redis_client.data[artifact_key])
    assert repaired["publication_acknowledged"] is True
    assert artifact_key in repaired["keys_written"]
    assert repaired_artifact.get(field) != forged_value
    assert moralis_feature_bridge.verify_moralis_feature_fanout_completion(
        redis_client,
        symbol="BTCUSDT",
        timeframe="1m",
        aggregate_artifact_sha256=aggregate_sha,
        expires_at=aggregate["expires_at"],
        observed_at="2026-07-08T12:03:10Z",
    )


def test_cross_symbol_status_projection_cannot_invalidate_completion_receipts() -> None:
    redis_client = FakeRedis()
    generated_at = "2026-07-08T12:03:00Z"
    expires_at = "2026-07-08T13:03:00Z"
    source_expires_at = "2026-07-08T14:03:00Z"
    btc_digest = "a" * 64
    eth_digest = "b" * 64

    for symbol, digest in (("BTCUSDT", btc_digest), ("ETHUSDT", eth_digest)):
        published = publish_moralis_feature_payload(
            redis_client,
            symbol=symbol,
            timeframe="1m",
            generated_at_override=generated_at,
            expires_at_override=expires_at,
            source_provenance_expires_at=source_expires_at,
            ttl_seconds=3600,
            fanout_generation_id=digest,
            aggregate_artifact_sha256=digest,
        )
        assert published["publication_acknowledged"] is True

    global_status = json.loads(
        redis_client.data[moralis_feature_bridge.MORALIS_FEATURE_BRIDGE_STATUS_KEY]
    )
    assert global_status["symbol"] == "ETHUSDT"
    for symbol, digest in (("BTCUSDT", btc_digest), ("ETHUSDT", eth_digest)):
        assert moralis_feature_bridge.verify_moralis_feature_fanout_completion(
            redis_client,
            symbol=symbol,
            timeframe="1m",
            aggregate_artifact_sha256=digest,
            expires_at=expires_at,
            observed_at=generated_at,
        )
        receipt_key = moralis_feature_bridge.MORALIS_FANOUT_COMPLETION_KEY.format(
            symbol=symbol,
            timeframe="1m",
        )
        receipt = json.loads(redis_client.data[receipt_key])
        assert (
            moralis_feature_bridge.MORALIS_FEATURE_BRIDGE_STATUS_KEY
            not in receipt["artifact_sha256"]
        )
        assert receipt["auxiliary_observability_keys"] == [
            moralis_feature_bridge.MORALIS_FEATURE_BRIDGE_STATUS_KEY
        ]
        assert receipt["auxiliary_observability_authority"] is False


def test_aggregate_and_fanout_expiry_are_bounded_by_raw_provenance() -> None:
    redis_client = FakeRedis()
    result = _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    endpoint = next(iter(aggregate["endpoint_payloads"].values()))
    assert aggregate["aggregate_expiry_bounded_by_source_provenance"] is True
    assert aggregate["expires_at"] <= aggregate["source_provenance_expires_at"]
    assert endpoint["expires_at"] <= endpoint["source_artifact_expires_at"]
    assert (
        redis_client.ttls[source_key] > redis_client.ttls["v2:moralis:feature_aggregate:BTCUSDT:1m"]
    )
    for key in moralis_publisher.moralis_feature_fanout_keys(
        symbol="BTCUSDT",
        timeframe="1m",
    ):
        assert redis_client.ttls[key] <= redis_client.ttls[source_key]

    redis_client.ttls[source_key] = 1
    _publish(
        redis_client,
        "wallet_swaps",
        {
            "result": [
                {
                    "side": "buy",
                    "total_value_usd": 10.0,
                    "block_timestamp": "2026-07-08T12:02:00Z",
                }
            ]
        },
        wallet="0xwallet",
    )
    repaired = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    assert set(repaired["endpoint_payloads"]) == {"wallet_swaps"}
    assert any(
        "SOURCE_ARTIFACT_TTL_SHORTER_THAN_ENDPOINT_LIFETIME" in reason
        for reason in repaired["source_resolution_rejection_reasons"]
    )

    class RedisWithoutTTL:
        def get(self, key: str) -> str | None:
            return redis_client.get(key)

    endpoint = next(iter(repaired["endpoint_payloads"].values()))
    ttl_unverifiable = moralis_publisher._source_artifact_resolution_reasons(  # noqa: SLF001
        RedisWithoutTTL(),
        endpoint,
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
        observed_at=_OBSERVED_AT,
    )
    assert "SOURCE_ARTIFACT_TTL_READ_FAILED" in ttl_unverifiable


def test_persisted_classifier_receipt_is_reverified_from_canonical_row() -> None:
    normalized = _normalize(
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    evidence = deepcopy(normalized["feature_evidence"])
    assert (
        classifier_evidence_reverification_reasons(
            evidence,
            chain="eth",
            endpoint_id="token_transfers",
            request_target_kind="token",
            request_target="0xtoken",
            symbol="BTCUSDT",
            authentication_key=_CLASSIFIER_KEY,
            authentication_key_id=_CLASSIFIER_KEY_ID,
        )
        == []
    )
    receipt = evidence["moralis_exchange_inflow_usd"]["contributing_rows"][0][
        "authenticated_classifier_receipt"
    ]
    receipt["request_target"] = "0xtampered"
    reasons = classifier_evidence_reverification_reasons(
        evidence,
        chain="eth",
        endpoint_id="token_transfers",
        request_target_kind="token",
        request_target="0xtoken",
        symbol="BTCUSDT",
        authentication_key=_CLASSIFIER_KEY,
        authentication_key_id=_CLASSIFIER_KEY_ID,
    )
    assert reasons == [
        "moralis_exchange_inflow_usd:0:CLASSIFIER_RECEIPT_REVERIFY_FAILED",
        "moralis_net_exchange_flow_usd:0:CLASSIFIER_RECEIPT_REVERIFY_FAILED",
    ]


def _deeply_nested_payload() -> dict[str, Any]:
    nested: Any = 1
    for name in reversed(tuple("abcdefghijklm")):
        nested = {name: nested}
    return {"result": [{"nested": nested}]}


@pytest.mark.parametrize(
    "payload",
    (
        {"result": [{"name": "x" * 4097}]},
        {"result": [{} for _ in range(501)]},
        {"result": [{str(index): index for index in range(129)}]},
        {"result": [{"name": "unsafe\u202eunicode"}]},
        _deeply_nested_payload(),
    ),
)
def test_unbounded_or_unsafe_source_json_is_rejected_before_projection(payload: Any) -> None:
    normalized = normalize_moralis_payload(
        spec=_spec("token_metadata"),
        symbol=None,
        chain="eth",
        wallet=None,
        token="0x" + ("1" * 40),
        payload=payload,
        observed_at=_OBSERVED_AT,
    )
    assert normalized["actual_payload_present"] is False
    assert normalized["canonical_records"] == []
    assert normalized["raw_transport_record_count"] == 0
    assert any(
        reason in {"PAYLOAD_NOT_BOUNDED_CLOSED_JSON", "PAYLOAD_BYTE_LIMIT_EXCEEDED"}
        for reason in normalized["normalization_rejection_reasons"]
    )


def test_safe_nfc_unicode_metadata_is_retained_but_never_admitted() -> None:
    normalized = normalize_moralis_payload(
        spec=_spec("token_metadata"),
        symbol=None,
        chain="eth",
        wallet=None,
        token="0x" + ("1" * 40),
        payload=[
            {
                "address": "0x" + ("1" * 40),
                "name": "Café",
                "symbol": "CAFE",
                "decimals": "18",
            }
        ],
        observed_at=_OBSERVED_AT,
    )
    assert normalized["canonical_records"][0]["name"] == "Café"
    assert normalized["features"] == {}
    assert normalized["admitted_feature_count"] == 0
    assert normalized["available_at"] is None
    assert normalized["postcommit_receipt_bound"] is False
    assert all(
        normalized[field] is False
        for field in (
            "publication_authority",
            "trainer_authority",
            "prediction_authority",
            "risk_authority",
            "orchestrator_authority",
            "allocator_authority",
            "paper_authority",
            "live_authority",
        )
    )


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    (
        ({"symbol": "BTC:USDT"}, "SYMBOL"),
        ({"timeframe": "1m:evil"}, "TIMEFRAME"),
        ({"chain": "eth:evil"}, "CHAIN"),
    ),
)
def test_redis_key_segments_are_validated_before_any_write(
    kwargs: dict[str, str],
    expected_reason: str,
) -> None:
    redis_client = FakeRedis()
    call = {
        "chain": "eth",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **kwargs,
    }
    result = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec("token_transfers"),
        token="0xtoken",  # noqa: S106 - fixture token identifier
        http_status=200,
        payload={"result": _classified_transfer_rows()},
        budget_status={},
        observed_at=_OBSERVED_AT,
        **call,
    )
    assert result["publication_attempt_status"] == "STRICT_JSON_SERIALIZATION_REJECTED"
    assert expected_reason in result["serialization_rejection_reasons"][0]
    assert redis_client.data == {}


def test_metadata_and_direct_fanout_reject_unsafe_key_segments() -> None:
    redis_client = FakeRedis()
    metadata = publish_moralis_result(
        redis_client,
        env={"MORALIS_API_KEY": "fixture-key"},
        spec=_spec("token_metadata"),
        chain="eth",
        symbol=None,
        token="token:escape",  # noqa: S106 - hostile Redis key fixture, not a credential
        http_status=200,
        payload=[{"address": "token:escape", "symbol": "BAD"}],
        budget_status={},
        observed_at=_OBSERVED_AT,
    )
    assert metadata["publication_acknowledged"] is False
    assert "TOKEN_METADATA_TOKEN" in metadata["serialization_rejection_reasons"][0]
    direct = publish_moralis_feature_payload(
        redis_client,
        symbol="BTC:USDT",
        timeframe="1m",
    )
    assert direct["publication_acknowledged"] is False
    assert direct["planned_keys"] == []
    assert redis_client.data == {}


def test_raw_source_and_admitted_counts_are_reported_separately() -> None:
    redis_client = FakeRedis()
    result = _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source = json.loads(redis_client.data[source_key])
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    bridge = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])
    assert result["raw_transport_record_count"] == 2
    assert result["source_semantic_claim_count"] == 3
    assert result["admitted_feature_count"] == 0
    assert source["raw_transport_record_count"] == 2
    assert source["source_semantic_claim_count"] == 3
    assert aggregate["raw_transport_record_count"] == 2
    assert aggregate["source_semantic_claim_count"] == 3
    assert aggregate["admitted_feature_count"] == 0
    assert bridge["source_feature_count"] == 3
    assert bridge["admitted_feature_count"] == 0
    assert bridge["features"] == {}
    assert bridge["missing_mask_true"] is True
    assert sum(bridge["missing_mask"].values()) == 7
    assert status["raw_transport_record_count"] == 2
    assert status["source_semantic_claim_count"] == 3
    assert status["admitted_feature_count"] == 0


def test_source_identity_is_rederived_instead_of_trusted_from_persisted_row() -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    endpoint = deepcopy(next(iter(aggregate["endpoint_payloads"].values())))
    assert (
        moralis_publisher._endpoint_integrity_rejection_reasons(  # noqa: SLF001
            endpoint,
            classifier_authentication_key=_CLASSIFIER_KEY,
            classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
        )
        == []
    )
    endpoint["source_identity"] = "token_transfers:" + ("0" * 64)
    reasons = moralis_publisher._endpoint_integrity_rejection_reasons(  # noqa: SLF001
        endpoint,
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
    )
    assert "SOURCE_IDENTITY_REDERIVATION_MISMATCH" in reasons
    assert "SOURCE_CONTENT_ADDRESS_KEY_MISMATCH" in reasons


def test_deep_persisted_source_json_is_quarantined_without_raising() -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    endpoint = deepcopy(next(iter(aggregate["endpoint_payloads"].values())))
    nested: Any = "leaf"
    for _ in range(18):
        nested = {"nested": nested}
    endpoint["source_payload_canonical_json"] = json.dumps(
        nested,
        sort_keys=True,
        separators=(",", ":"),
    )

    reasons = moralis_publisher._endpoint_integrity_rejection_reasons(  # noqa: SLF001
        endpoint,
        classifier_authentication_key=_CLASSIFIER_KEY,
        classifier_authentication_key_id=_CLASSIFIER_KEY_ID,
    )

    assert "SOURCE_PAYLOAD_JSON_INVALID" in reasons


def test_integration_capability_never_implies_source_readiness_or_consumption() -> None:
    redis_client = FakeRedis()
    _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    endpoint_status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])
    endpoint = endpoint_status["endpoints"]["token_transfers"]
    bridge_status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])
    assert endpoint["transport_status"] == "READY"
    assert endpoint["status"] == "SOURCE_OBSERVATION_NON_AUTHORITATIVE"
    assert endpoint["actual_payload_present"] is False
    assert bridge_status["integration_configured"] is True
    assert bridge_status["integration_capable"] is True
    assert bridge_status["source_ready"] is False
    assert bridge_status["admitted_ready"] is False
    assert bridge_status["actual_consumption"] is False
    for name in (
        "trainer_consumption",
        "provider_tensor_consumption",
        "ppo_consumption",
        "masa_consumption",
        "risk_consumption",
        "orchestrator_consumption",
        "allocator_consumption",
        "paper_consumption",
        "live_dryrun_consumption",
    ):
        assert bridge_status[name] is False


def test_every_authority_flag_remains_hard_false() -> None:
    redis_client = FakeRedis()
    result = _publish(
        redis_client,
        "token_transfers",
        {"result": _classified_transfer_rows()},
    )
    payload = json.loads(redis_client.data["v2:features:moralis:BTCUSDT:1m"])
    status = json.loads(redis_client.data["v2:provider:moralis:feature_bridge_status"])

    authority_names = (
        "publication_authority",
        "trainer_authority",
        "prediction_authority",
        "risk_authority",
        "orchestrator_authority",
        "allocator_authority",
        "paper_authority",
        "live_authority",
    )
    for key in moralis_publisher.moralis_feature_fanout_keys(
        symbol="BTCUSDT",
        timeframe="1m",
    ):
        artifact = json.loads(redis_client.data[key])
        assert artifact["postcommit_receipt_bound"] is False
        for name in authority_names:
            assert artifact[name] is False
    endpoint_status = json.loads(redis_client.data["v2:provider:moralis:endpoint_status"])
    endpoint = endpoint_status["endpoints"]["token_transfers"]
    source_key = next(key for key in result["planned_keys"] if key.startswith("v2:moralis:raw:v2:"))
    source = json.loads(redis_client.data[source_key])
    aggregate = json.loads(redis_client.data["v2:moralis:feature_aggregate:BTCUSDT:1m"])
    for artifact in (payload, status, endpoint_status, endpoint, source, aggregate):
        for name in authority_names:
            assert artifact[name] is False
    for name in (
        "trainer_consumption",
        "provider_tensor_consumption",
        "ppo_consumption",
        "masa_consumption",
        "risk_consumption",
        "orchestrator_consumption",
        "allocator_consumption",
        "paper_consumption",
        "live_dryrun_consumption",
        "feedback_attribution",
    ):
        assert status[name] is False
