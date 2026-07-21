"""Moralis payload normalization with explicit feature semantics.

This module intentionally does not decide whether an observation is available
to a consumer.  It only projects bounded source observations and records which
numeric claims can be made without changing units, inventing a direction, or
inferring an identity.  Publication availability is established downstream by
a durable post-commit receipt; that authority is deliberately absent today.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.services.smart_money_wallets.endpoint_registry import MoralisEndpointSpec
from app.services.smart_money_wallets.transport_json import canonical_transport_json_bytes

# These are the only Moralis fields present in the immutable trainer ABI.  The
# bridge independently asserts this tuple against the v4 registry in tests.
MORALIS_ABI_FEATURE_NAMES = (
    "moralis_exchange_inflow_usd",
    "moralis_exchange_outflow_usd",
    "moralis_net_exchange_flow_usd",
    "moralis_whale_net_flow_usd",
    "moralis_smart_wallet_accumulation_score",
    "moralis_smart_wallet_distribution_score",
    "moralis_onchain_risk_score",
)

# Diagnostics are observable source measurements, not model features.  Their
# names state their scope so a page count, balance, or stream count cannot be
# confused with a delta, risk score, or USD flow.
MORALIS_DIAGNOSTIC_NAMES = (
    "moralis_observed_wallet_balance_usd",
    "moralis_wallet_networth_usd",
    "moralis_observed_swap_buy_usd",
    "moralis_observed_swap_sell_usd",
    "moralis_observed_swap_net_usd",
    "moralis_reported_holder_count",
    "moralis_observed_token_price_usd",
    "moralis_stream_transfer_count",
    "moralis_stream_transaction_count",
)

_EXCHANGE_INFLOW = "exchange_inflow"
_EXCHANGE_OUTFLOW = "exchange_outflow"
_CLASSIFIED_EXCHANGE = "EXCHANGE"
_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHENTICATED_EXCHANGE_CATEGORIES = frozenset({"exchange_hot_wallet", "exchange_cold_wallet"})
_CLASSIFIER_RECEIPT_SCHEMA = "moralis_authenticated_exchange_classifier_receipt_v2"
_CLASSIFIER_REGISTRY_KEY_PREFIX = "v2:moralis:exchange_classifier_registry:"
_MAX_CONTRIBUTING_ROWS = 250
_MAX_JSON_DEPTH = 12
_MAX_JSON_LIST_ITEMS = 500
_MAX_JSON_OBJECT_FIELDS = 128
_MAX_JSON_STRING_BYTES = 4096
_MAX_JSON_TOTAL_NODES = 5000
_MAX_JSON_BYTES = 1_048_576
_CLASSIFIER_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ENDPOINT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_PATH_COMPONENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_MAX_SEMANTIC_QUARANTINE_REASONS = 250
_SEMANTIC_PROJECTION_SCHEMA = "moralis_endpoint_semantic_projection_v1"
_CLOCK_PROJECTION_FIELDS = ("block_timestamp", "timestamp")
_TRANSFER_PROJECTION_FIELDS = (
    "value_usd",
    "usd_value",
    "transaction_hash",
    "transactionHash",
    "hash",
    "log_index",
    "logIndex",
    "exchange_counterparty_address",
    *_CLOCK_PROJECTION_FIELDS,
)
_SWAP_PROJECTION_FIELDS = (
    "side",
    "transaction_type",
    "total_value_usd",
    "usd_value",
    *_CLOCK_PROJECTION_FIELDS,
)
_PRICE_PROJECTION_FIELDS = ("usdPrice", "usd_price", *_CLOCK_PROJECTION_FIELDS)
_SEMANTIC_FIELDS_BY_GROUP: dict[str, tuple[str, ...]] = {
    "wallet_balances": ("usd_value", *_CLOCK_PROJECTION_FIELDS),
    "wallet_token_balances_price": ("usd_value", *_CLOCK_PROJECTION_FIELDS),
    "wallet_networth": (
        "total_networth_usd",
        "networth_usd",
        *_CLOCK_PROJECTION_FIELDS,
    ),
    "wallet_history": _TRANSFER_PROJECTION_FIELDS,
    "wallet_transactions": _TRANSFER_PROJECTION_FIELDS,
    "wallet_address_transfers": _TRANSFER_PROJECTION_FIELDS,
    "token_transfers": _TRANSFER_PROJECTION_FIELDS,
    "token_address_transfers": _TRANSFER_PROJECTION_FIELDS,
    "token_holders": ("total", *_CLOCK_PROJECTION_FIELDS),
    "swaps": _SWAP_PROJECTION_FIELDS,
    "wallet_swaps": _SWAP_PROJECTION_FIELDS,
    "token_swaps": _SWAP_PROJECTION_FIELDS,
    "price_ohlc": _PRICE_PROJECTION_FIELDS,
    "token_price": _PRICE_PROJECTION_FIELDS,
    "multiple_token_prices": _PRICE_PROJECTION_FIELDS,
    "streams": (*_CLOCK_PROJECTION_FIELDS, "confirmed"),
}


def normalize_moralis_payload(
    *,
    spec: MoralisEndpointSpec,
    symbol: str | None,
    chain: str,
    wallet: str | None,
    token: str | None,
    payload: Any,
    authenticated_classifier_receipts: Mapping[str, Any] | None = None,
    classifier_authentication_key: bytes | None = None,
    classifier_authentication_key_id: str | None = None,
    observed_at: str | None = None,
    raw_response_sha256: str | None = None,
    raw_response_evidence_bound: bool = False,
) -> dict[str, Any]:
    rows, row_rejections = _rows(payload)
    row_rejections.extend(_semantic_quarantine_reasons(payload))
    response_binding = _raw_response_binding(
        raw_response_sha256=raw_response_sha256,
        raw_response_evidence_bound=raw_response_evidence_bound,
    )
    if raw_response_evidence_bound and not response_binding["raw_response_evidence_bound"]:
        row_rejections.append("RAW_RESPONSE_BINDING_INVALID")
    generated_at = _strict_source_time(observed_at) if observed_at is not None else None
    if observed_at is not None and generated_at is None:
        row_rejections.append("NORMALIZATION_OBSERVED_AT_NOT_STRICT_UTC")
    generated_at = generated_at or datetime.now(UTC)
    generated_at_text = _iso_utc(generated_at)
    source_window_seconds = max(1, int(spec.ttl_seconds))
    if len(rows) > _MAX_CONTRIBUTING_ROWS:
        row_rejections.append("SOURCE_ROW_LIMIT_EXCEEDED")
        rows = []
    canonical_records = _canonical_cache_projection(spec.group, rows)
    features: dict[str, float] = {}
    diagnostics: dict[str, float] = {}
    feature_evidence: dict[str, dict[str, Any]] = {}
    diagnostic_evidence: dict[str, dict[str, Any]] = {}
    feature_rejections = {
        name: ["NO_SEMANTIC_PRODUCER_FOR_ENDPOINT"] for name in MORALIS_ABI_FEATURE_NAMES
    }

    if spec.group in {"wallet_balances", "wallet_token_balances_price"}:
        total, contributor_receipts, contributor_rejections = _sum_nonnegative_usd(
            rows,
            ("usd_value",),
            feature_family=spec.group,
            raw_response_binding=response_binding,
            observed_at=generated_at,
            source_window_seconds=source_window_seconds,
        )
        row_rejections.extend(contributor_rejections)
        if total is not None:
            name = "moralis_observed_wallet_balance_usd"
            diagnostics[name] = total
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="USD",
                direction="absolute_balance",
                scope="observed_response_rows",
                contributor_receipts=contributor_receipts,
                source_window_seconds=source_window_seconds,
            )
        feature_rejections["moralis_whale_net_flow_usd"] = ["ABSOLUTE_BALANCE_IS_NOT_FLOW"]
        feature_rejections["moralis_smart_wallet_accumulation_score"] = [
            "ABSOLUTE_BALANCE_HAS_NO_CAUSAL_ACCUMULATION_BASELINE"
        ]
        feature_rejections["moralis_smart_wallet_distribution_score"] = [
            "ABSOLUTE_BALANCE_HAS_NO_CAUSAL_DISTRIBUTION_BASELINE"
        ]
    elif spec.group == "wallet_networth":
        networth_row = _first_mapping(payload)
        networth = _first_nonnegative_float(networth_row, ("total_networth_usd", "networth_usd"))
        receipt, rejection = _contributor_receipt(
            networth_row,
            row_index=0,
            feature_family=spec.group,
            raw_response_binding=response_binding,
            observed_at=generated_at,
            source_window_seconds=source_window_seconds,
        )
        if rejection:
            row_rejections.append(rejection)
        if networth is not None and receipt is not None:
            name = "moralis_wallet_networth_usd"
            diagnostics[name] = networth
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="USD",
                direction="absolute_networth",
                scope="provider_reported_wallet_total",
                contributor_receipts=[receipt],
                source_window_seconds=source_window_seconds,
            )
        feature_rejections["moralis_whale_net_flow_usd"] = ["ABSOLUTE_NETWORTH_IS_NOT_FLOW"]
        feature_rejections["moralis_smart_wallet_accumulation_score"] = [
            "ABSOLUTE_NETWORTH_HAS_NO_CAUSAL_ACCUMULATION_BASELINE"
        ]
        feature_rejections["moralis_smart_wallet_distribution_score"] = [
            "ABSOLUTE_NETWORTH_HAS_NO_CAUSAL_DISTRIBUTION_BASELINE"
        ]
    elif spec.group in {
        "wallet_history",
        "wallet_transactions",
        "wallet_address_transfers",
        "token_transfers",
        "token_address_transfers",
    }:
        flow, identities, contribution_receipts, classification_rejections = (
            _classified_exchange_flow_usd(
                rows,
                chain=chain,
                authenticated_classifier_receipts=authenticated_classifier_receipts,
                classifier_authentication_key=classifier_authentication_key,
                classifier_authentication_key_id=classifier_authentication_key_id,
                endpoint_id=spec.endpoint_id,
                request_target_kind=_request_target_kind(spec),
                request_target=_request_target(
                    spec,
                    wallet=wallet,
                    token=token,
                    symbol=symbol,
                ),
                symbol=symbol,
                feature_family=spec.group,
                raw_response_binding=response_binding,
                observed_at=generated_at,
                source_window_seconds=source_window_seconds,
            )
        )
        row_rejections.extend(classification_rejections)
        if _EXCHANGE_INFLOW in flow:
            features["moralis_exchange_inflow_usd"] = flow[_EXCHANGE_INFLOW]
            feature_evidence["moralis_exchange_inflow_usd"] = _evidence(
                spec,
                unit="USD",
                direction=_EXCHANGE_INFLOW,
                scope="classified_exchange_counterparties_only",
                contributor_receipts=contribution_receipts[_EXCHANGE_INFLOW],
                source_window_seconds=source_window_seconds,
                classified_identities=identities[_EXCHANGE_INFLOW],
            )
            feature_rejections.pop("moralis_exchange_inflow_usd", None)
        else:
            feature_rejections["moralis_exchange_inflow_usd"] = [
                "AUTHENTICATED_CLASSIFIED_EXCHANGE_INFLOW_EVIDENCE_MISSING"
            ]
        if _EXCHANGE_OUTFLOW in flow:
            features["moralis_exchange_outflow_usd"] = flow[_EXCHANGE_OUTFLOW]
            feature_evidence["moralis_exchange_outflow_usd"] = _evidence(
                spec,
                unit="USD",
                direction=_EXCHANGE_OUTFLOW,
                scope="classified_exchange_counterparties_only",
                contributor_receipts=contribution_receipts[_EXCHANGE_OUTFLOW],
                source_window_seconds=source_window_seconds,
                classified_identities=identities[_EXCHANGE_OUTFLOW],
            )
            feature_rejections.pop("moralis_exchange_outflow_usd", None)
        else:
            feature_rejections["moralis_exchange_outflow_usd"] = [
                "AUTHENTICATED_CLASSIFIED_EXCHANGE_OUTFLOW_EVIDENCE_MISSING"
            ]
        if _EXCHANGE_INFLOW in flow and _EXCHANGE_OUTFLOW in flow:
            # Positive means net movement into classified exchanges.
            features["moralis_net_exchange_flow_usd"] = (
                flow[_EXCHANGE_INFLOW] - flow[_EXCHANGE_OUTFLOW]
            )
            feature_evidence["moralis_net_exchange_flow_usd"] = _evidence(
                spec,
                unit="USD",
                direction="exchange_inflow_minus_exchange_outflow",
                scope="classified_exchange_counterparties_only",
                contributor_receipts=(
                    contribution_receipts[_EXCHANGE_INFLOW]
                    + contribution_receipts[_EXCHANGE_OUTFLOW]
                ),
                source_window_seconds=source_window_seconds,
                classified_identities=sorted(
                    set(identities[_EXCHANGE_INFLOW] + identities[_EXCHANGE_OUTFLOW])
                ),
            )
            feature_rejections.pop("moralis_net_exchange_flow_usd", None)
        else:
            feature_rejections["moralis_net_exchange_flow_usd"] = [
                "BIDIRECTIONAL_AUTHENTICATED_EXCHANGE_FLOW_EVIDENCE_INCOMPLETE"
            ]
    elif spec.group == "token_holders":
        holder_count = _strict_nonnegative_int(
            payload.get("total") if isinstance(payload, Mapping) else None
        )
        holder_row = _first_mapping(payload)
        holder_receipt, holder_rejection = _contributor_receipt(
            holder_row,
            row_index=0,
            feature_family=spec.group,
            raw_response_binding=response_binding,
            observed_at=generated_at,
            source_window_seconds=source_window_seconds,
        )
        if holder_rejection:
            row_rejections.append(holder_rejection)
        if holder_count is not None and holder_receipt is not None:
            name = "moralis_reported_holder_count"
            diagnostics[name] = float(holder_count)
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="holders",
                direction="absolute_count",
                scope="provider_reported_total",
                contributor_receipts=[holder_receipt],
                source_window_seconds=source_window_seconds,
            )
        # A current count or one response page cannot establish a causal delta
        # or the full-distribution denominator required for concentration.
    elif spec.group in {"swaps", "wallet_swaps", "token_swaps"}:
        swap, swap_receipts, swap_rejections = _observed_swap_usd(
            rows,
            feature_family=spec.group,
            raw_response_binding=response_binding,
            observed_at=generated_at,
            source_window_seconds=source_window_seconds,
        )
        row_rejections.extend(swap_rejections)
        if "buy" in swap:
            name = "moralis_observed_swap_buy_usd"
            diagnostics[name] = swap["buy"]
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="USD",
                direction="buy",
                scope="observed_response_rows",
                contributor_receipts=swap_receipts["buy"],
                source_window_seconds=source_window_seconds,
            )
        if "sell" in swap:
            name = "moralis_observed_swap_sell_usd"
            diagnostics[name] = swap["sell"]
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="USD",
                direction="sell",
                scope="observed_response_rows",
                contributor_receipts=swap_receipts["sell"],
                source_window_seconds=source_window_seconds,
            )
        if "buy" in swap and "sell" in swap:
            name = "moralis_observed_swap_net_usd"
            diagnostics[name] = swap["buy"] - swap["sell"]
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="USD",
                direction="buy_minus_sell",
                scope="observed_response_rows",
                contributor_receipts=swap_receipts["buy"] + swap_receipts["sell"],
                source_window_seconds=source_window_seconds,
            )
        feature_rejections["moralis_whale_net_flow_usd"] = [
            "CLASSIFIED_WHALE_IDENTITY_AND_COMPLETE_FLOW_WINDOW_MISSING"
        ]
    elif spec.group in {"price_ohlc", "token_price", "multiple_token_prices"}:
        price_row = _first_mapping(payload)
        price = _first_nonnegative_float(price_row, ("usdPrice", "usd_price"))
        price_receipt, price_rejection = _contributor_receipt(
            price_row,
            row_index=0,
            feature_family=spec.group,
            raw_response_binding=response_binding,
            observed_at=generated_at,
            source_window_seconds=source_window_seconds,
        )
        if price_rejection:
            row_rejections.append(price_rejection)
        if price is not None and price_receipt is not None:
            name = "moralis_observed_token_price_usd"
            diagnostics[name] = price
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="USD_per_token",
                direction="absolute_price",
                scope="provider_observation",
                contributor_receipts=[price_receipt],
                source_window_seconds=source_window_seconds,
            )
        feature_rejections["moralis_onchain_risk_score"] = ["PRICE_OBSERVATION_IS_NOT_ONCHAIN_RISK"]
    elif spec.group == "token_metadata":
        if _first_mapping(payload):
            feature_rejections["moralis_onchain_risk_score"] = [
                "METADATA_PRESENCE_IS_NOT_ONCHAIN_RISK"
            ]
    elif spec.group == "streams":
        stream_diagnostics = _stream_diagnostics(payload)
        stream_row = _first_mapping(payload)
        stream_receipt, stream_rejection = _contributor_receipt(
            stream_row,
            row_index=0,
            feature_family=spec.group,
            raw_response_binding=response_binding,
            observed_at=generated_at,
            source_window_seconds=source_window_seconds,
        )
        if stream_rejection:
            row_rejections.append(stream_rejection)
        for name, value in stream_diagnostics.items():
            if stream_receipt is None:
                continue
            diagnostics[name] = value
            diagnostic_evidence[name] = _evidence(
                spec,
                unit="events",
                direction="count",
                scope="single_stream_envelope",
                contributor_receipts=[stream_receipt],
                source_window_seconds=source_window_seconds,
            )
        feature_rejections["moralis_whale_net_flow_usd"] = [
            "STREAM_EVENT_COUNT_HAS_NO_USD_FLOW_SEMANTICS"
        ]

    event_time = _latest_evidence_event_time(feature_evidence, diagnostic_evidence)
    if rows and event_time is None and (features or diagnostics):
        row_rejections.append("CONTRIBUTING_SOURCE_CLOCK_MISSING_OR_INVALID")
    # Transport presence is distinct from feature semantics.  A real response
    # can carry rows that are intentionally unusable as a numeric feature.
    transport_actual = bool(rows)
    semantic_actual = bool(features or diagnostics)
    return {
        "schema_version": "moralis_normalized_payload_v2",
        "provider": "moralis",
        "endpoint_id": spec.endpoint_id,
        "feature_family": spec.group,
        "symbol": symbol,
        "chain": chain,
        "wallet": wallet,
        "token": token,
        "event_time": event_time,
        "generated_at": generated_at_text,
        "source_window_seconds": source_window_seconds,
        "features": features,
        "abi_feature_names": list(MORALIS_ABI_FEATURE_NAMES),
        "feature_evidence": feature_evidence,
        "feature_rejection_reasons": feature_rejections,
        "diagnostic_features": diagnostics,
        "diagnostic_feature_names": list(MORALIS_DIAGNOSTIC_NAMES),
        "diagnostic_evidence": diagnostic_evidence,
        "normalization_rejection_reasons": sorted(set(row_rejections)),
        # Bounded, endpoint-specific public-chain records are retained for
        # audit. They remain non-admissible until publication receipts exist.
        "canonical_records": canonical_records,
        "canonical_record_count": len(canonical_records),
        "raw_transport_record_count": len(rows),
        "source_feature_claim_count": len(features),
        "source_diagnostic_claim_count": len(diagnostics),
        "source_semantic_claim_count": len(features) + len(diagnostics),
        "admitted_feature_count": 0,
        "raw_response_sha256": response_binding["raw_response_sha256"],
        "raw_response_evidence_bound": response_binding["raw_response_evidence_bound"],
        "classifier_authentication_key_id": classifier_authentication_key_id,
        "classifier_request_target_kind": _request_target_kind(spec),
        "classifier_request_target": _request_target(
            spec,
            wallet=wallet,
            token=token,
            symbol=symbol,
        ),
        "actual_payload_present": transport_actual,
        "semantic_payload_present": semantic_actual,
        "feature_payload_present": bool(features),
        "diagnostic_payload_present": bool(diagnostics),
        "heartbeat_only": not transport_actual,
        "available_at": None,
        "postcommit_receipt_bound": False,
        "publication_authority": False,
        "trainer_authority": False,
        "prediction_authority": False,
        "risk_authority": False,
        "orchestrator_authority": False,
        "allocator_authority": False,
        "paper_authority": False,
        "live_authority": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _rows(payload: Any) -> tuple[list[Mapping[str, Any]], list[str]]:
    payload_rejection = _bounded_transport_json_rejection(payload)
    if payload_rejection is not None:
        return [], [payload_rejection]
    candidates: Any
    if isinstance(payload, Mapping):
        result = payload.get("result")
        if isinstance(result, list):
            candidates = result
        elif isinstance(result, Mapping):
            candidates = [result]
        else:
            candidates = [payload]
    elif isinstance(payload, list):
        candidates = payload
    else:
        return [], ["PAYLOAD_TYPE_INVALID"] if payload is not None else ["PAYLOAD_MISSING"]
    rows = [row for row in candidates if isinstance(row, Mapping)]
    rejections = []
    if len(rows) != len(candidates):
        rejections.append("ROW_TYPE_INVALID")
    if not rows:
        rejections.append("SOURCE_ROWS_MISSING")
    return rows, rejections


def _first_mapping(payload: Any) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return payload
    rows, _ = _rows(payload)
    return rows[0] if rows else {}


def _classified_exchange_flow_usd(
    rows: list[Mapping[str, Any]],
    *,
    chain: str,
    authenticated_classifier_receipts: Mapping[str, Any] | None,
    classifier_authentication_key: bytes | None,
    classifier_authentication_key_id: str | None,
    endpoint_id: str,
    request_target_kind: str,
    request_target: str,
    symbol: str | None,
    feature_family: str,
    raw_response_binding: Mapping[str, Any],
    observed_at: datetime,
    source_window_seconds: int,
) -> tuple[
    dict[str, float],
    dict[str, list[str]],
    dict[str, list[dict[str, Any]]],
    list[str],
]:
    totals: dict[str, float] = {}
    identities: dict[str, list[str]] = {_EXCHANGE_INFLOW: [], _EXCHANGE_OUTFLOW: []}
    receipts: dict[str, list[dict[str, Any]]] = {
        _EXCHANGE_INFLOW: [],
        _EXCHANGE_OUTFLOW: [],
    }
    rejections: list[str] = []
    verified_claims = (
        authenticated_classifier_receipts
        if isinstance(authenticated_classifier_receipts, Mapping)
        else {}
    )
    for row_index, row in enumerate(rows):
        value = _first_nonnegative_float(row, ("value_usd", "usd_value"))
        if value is None:
            continue
        event_id = classifier_source_event_id(row)
        claim = verified_claims.get(event_id) if event_id is not None else None
        claim_result = _authenticated_classifier_claim(
            row=row,
            claim=claim,
            chain=chain,
            event_id=event_id,
            authentication_key=classifier_authentication_key,
            authentication_key_id=classifier_authentication_key_id,
            endpoint_id=endpoint_id,
            request_target_kind=request_target_kind,
            request_target=request_target,
            symbol=symbol,
        )
        if claim_result is None:
            rejections.append(
                f"ROW_{row_index}:AUTHENTICATED_EXCHANGE_CLASSIFIER_RECEIPT_MISSING_OR_INVALID"
            )
            continue
        direction = str(claim_result["flow_direction"])
        address = str(claim_result["counterparty_address"])
        contributor, rejection = _contributor_receipt(
            row,
            row_index=row_index,
            feature_family=feature_family,
            raw_response_binding=raw_response_binding,
            observed_at=observed_at,
            source_window_seconds=source_window_seconds,
        )
        if contributor is None:
            rejections.append(f"ROW_{row_index}:{rejection}")
            continue
        contributor["classifier_receipt_sha256"] = claim_result["claim_sha256"]
        contributor["classifier_registry_key"] = claim_result["classifier_registry_key"]
        contributor["classifier_registry_version"] = claim_result["classifier_registry_version"]
        contributor["classifier_registry_sha256"] = claim_result["classifier_registry_sha256"]
        # Persist the complete authenticated claim so a later audit can
        # reconstruct the exact registry/source/event material and verify the
        # HMAC tag.  The authentication key itself is never persisted.
        contributor["authenticated_classifier_receipt"] = claim_result
        totals[direction] = totals.get(direction, 0.0) + value
        identities[direction].append(address)
        receipts[direction].append(contributor)
    return totals, identities, receipts, rejections


def _authenticated_classifier_claim(
    *,
    row: Mapping[str, Any],
    claim: Any,
    chain: str,
    event_id: str | None,
    authentication_key: bytes | None,
    authentication_key_id: str | None,
    endpoint_id: str,
    request_target_kind: str,
    request_target: str,
    symbol: str | None,
) -> dict[str, Any] | None:
    if (
        not isinstance(claim, Mapping)
        or not isinstance(authentication_key, bytes)
        or not authentication_key
        or not isinstance(authentication_key_id, str)
        or not _CLASSIFIER_KEY_ID_RE.fullmatch(authentication_key_id)
        or event_id is None
    ):
        return None
    address = _strict_evm_address(claim.get("counterparty_address"))
    row_address = _strict_evm_address(row.get("exchange_counterparty_address"))
    direction = str(claim.get("flow_direction") or "").strip().lower()
    category = str(claim.get("category") or "").strip().lower()
    registry_key = claim.get("classifier_registry_key")
    registry_version = claim.get("classifier_registry_version")
    registry_digest = claim.get("classifier_registry_sha256")
    classifier_source_key = claim.get("classifier_source_key")
    classifier_source_digest = claim.get("classifier_source_payload_sha256")
    claim_event_time = _strict_source_time(claim.get("classifier_event_time"))
    row_event_time = _strict_source_time(row.get("block_timestamp") or row.get("timestamp"))
    transaction_hash = _transaction_hash(row)
    log_index = _log_index(row)
    expected_symbol = str(symbol or "").strip().upper()
    try:
        row_bytes = canonical_transport_json_bytes(dict(row))
    except (TypeError, ValueError):
        return None
    row_digest = hashlib.sha256(row_bytes).hexdigest()
    material = {
        "schema_version": claim.get("schema_version"),
        "classifier_key_id": claim.get("classifier_key_id"),
        "endpoint_id": claim.get("endpoint_id"),
        "request_target_kind": claim.get("request_target_kind"),
        "request_target": claim.get("request_target"),
        "symbol": claim.get("symbol"),
        "chain": str(claim.get("chain") or "").strip().lower(),
        "transaction_hash": claim.get("transaction_hash"),
        "log_index": claim.get("log_index"),
        "counterparty_address": address,
        "category": category,
        "flow_direction": direction,
        "source_event_id": claim.get("source_event_id"),
        "source_row_sha256": claim.get("source_row_sha256"),
        "classifier_event_time": _iso_utc(claim_event_time) if claim_event_time else None,
        "classifier_registry_key": registry_key,
        "classifier_registry_version": registry_version,
        "classifier_registry_sha256": registry_digest,
        "classifier_source_key": classifier_source_key,
        "classifier_source_payload_sha256": classifier_source_digest,
        "authentication_method": claim.get("authentication_method"),
    }
    try:
        material_bytes = _strict_json_bytes(material)
    except (TypeError, ValueError):
        return None
    claim_sha256 = hashlib.sha256(material_bytes).hexdigest()
    expected_hmac = hmac.new(authentication_key, material_bytes, hashlib.sha256).hexdigest()
    supplied_hmac = claim.get("hmac_sha256")
    if not (
        claim.get("schema_version") == _CLASSIFIER_RECEIPT_SCHEMA
        and claim.get("classifier_key_id") == authentication_key_id
        and claim.get("endpoint_id") == endpoint_id
        and claim.get("request_target_kind") == request_target_kind
        and claim.get("request_target") == request_target
        and claim.get("symbol") == expected_symbol
        and material["chain"] == str(chain).strip().lower()
        and transaction_hash is not None
        and claim.get("transaction_hash") == transaction_hash
        and log_index is not None
        and claim.get("log_index") == log_index
        and address is not None
        and address == row_address
        and category in _AUTHENTICATED_EXCHANGE_CATEGORIES
        and direction in {_EXCHANGE_INFLOW, _EXCHANGE_OUTFLOW}
        and claim.get("source_event_id") == event_id
        and claim.get("source_row_sha256") == row_digest
        and claim_event_time is not None
        and row_event_time is not None
        and claim_event_time == row_event_time
        and isinstance(registry_key, str)
        and registry_key.startswith(_CLASSIFIER_REGISTRY_KEY_PREFIX)
        and _redis_key_valid(registry_key)
        and isinstance(registry_version, str)
        and registry_version
        and isinstance(registry_digest, str)
        and _SHA256_RE.fullmatch(registry_digest)
        and isinstance(classifier_source_key, str)
        and _redis_key_valid(classifier_source_key)
        and isinstance(classifier_source_digest, str)
        and _SHA256_RE.fullmatch(classifier_source_digest)
        and claim.get("authentication_method") == "HMAC_SHA256"
        and claim.get("claim_sha256") == claim_sha256
        and isinstance(supplied_hmac, str)
        and _SHA256_RE.fullmatch(supplied_hmac)
        and hmac.compare_digest(supplied_hmac, expected_hmac)
    ):
        return None
    return {
        **material,
        "claim_sha256": claim_sha256,
        "hmac_sha256": supplied_hmac,
    }


def classifier_evidence_reverification_reasons(
    feature_evidence: Any,
    *,
    chain: str,
    endpoint_id: str,
    request_target_kind: str,
    request_target: str,
    symbol: str | None,
    authentication_key: bytes | None,
    authentication_key_id: str | None,
) -> list[str]:
    """Reverify every persisted classifier claim against its canonical source row."""

    if not isinstance(feature_evidence, Mapping):
        return []
    reasons: list[str] = []
    for feature_name in (
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
    ):
        evidence = feature_evidence.get(feature_name)
        if not isinstance(evidence, Mapping):
            continue
        contributors = evidence.get("contributing_rows")
        if not isinstance(contributors, list) or len(contributors) > _MAX_CONTRIBUTING_ROWS:
            reasons.append(f"{feature_name}:CLASSIFIER_CONTRIBUTORS_INVALID")
            continue
        for contributor_index, contributor in enumerate(contributors):
            if not isinstance(contributor, Mapping):
                reasons.append(f"{feature_name}:{contributor_index}:CLASSIFIER_CONTRIBUTOR_INVALID")
                continue
            canonical = contributor.get("row_canonical_json")
            claim = contributor.get("authenticated_classifier_receipt")
            if not isinstance(canonical, str) or not isinstance(claim, Mapping):
                reasons.append(f"{feature_name}:{contributor_index}:CLASSIFIER_RECEIPT_MISSING")
                continue
            try:
                row = json.loads(canonical)
                canonical_roundtrip = canonical_transport_json_bytes(row).decode("ascii")
            except (TypeError, ValueError):
                reasons.append(f"{feature_name}:{contributor_index}:CLASSIFIER_SOURCE_ROW_INVALID")
                continue
            if not isinstance(row, Mapping) or canonical_roundtrip != canonical:
                reasons.append(
                    f"{feature_name}:{contributor_index}:CLASSIFIER_SOURCE_ROW_NONCANONICAL"
                )
                continue
            event_id = classifier_source_event_id(row)
            verified = _authenticated_classifier_claim(
                row=row,
                claim=claim,
                chain=chain,
                event_id=event_id,
                authentication_key=authentication_key,
                authentication_key_id=authentication_key_id,
                endpoint_id=endpoint_id,
                request_target_kind=request_target_kind,
                request_target=request_target,
                symbol=symbol,
            )
            if verified is None or dict(verified) != dict(claim):
                reasons.append(
                    f"{feature_name}:{contributor_index}:CLASSIFIER_RECEIPT_REVERIFY_FAILED"
                )
    return sorted(set(reasons))


def _canonical_cache_projection(
    group: str,
    rows: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fields: tuple[str, ...]
    if group == "token_metadata":
        fields = ("address", "name", "symbol", "decimals")
    elif group == "token_holders":
        fields = (
            "owner_address",
            "owner_address_label",
            "is_contract",
            "usd_value",
            "balance",
            "balance_decimal",
            "balance_formatted",
        )
    else:
        return []
    projected: list[dict[str, Any]] = []
    for row in rows[:250]:
        item: dict[str, Any] = {}
        for field in fields:
            if field not in row:
                continue
            value = _json_safe_scalar(row.get(field))
            if value is not None:
                item[field] = value
        projected.append(item)
    return projected


def _observed_swap_usd(
    rows: list[Mapping[str, Any]],
    *,
    feature_family: str,
    raw_response_binding: Mapping[str, Any],
    observed_at: datetime,
    source_window_seconds: int,
) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]], list[str]]:
    totals: dict[str, float] = {}
    receipts: dict[str, list[dict[str, Any]]] = {"buy": [], "sell": []}
    rejections: list[str] = []
    for row_index, row in enumerate(rows):
        side = str(row.get("side") or row.get("transaction_type") or "").strip().lower()
        value = _first_nonnegative_float(row, ("total_value_usd", "usd_value"))
        if side not in {"buy", "sell"} or value is None:
            continue
        receipt, rejection = _contributor_receipt(
            row,
            row_index=row_index,
            feature_family=feature_family,
            raw_response_binding=raw_response_binding,
            observed_at=observed_at,
            source_window_seconds=source_window_seconds,
        )
        if receipt is None:
            rejections.append(f"ROW_{row_index}:{rejection}")
            continue
        totals[side] = totals.get(side, 0.0) + value
        receipts[side].append(receipt)
    return totals, receipts, rejections


def _stream_diagnostics(payload: Any) -> dict[str, float]:
    if not isinstance(payload, Mapping):
        return {}
    out: dict[str, float] = {}
    transfers = payload.get("erc20Transfers")
    txs = payload.get("txs")
    if isinstance(transfers, list) and transfers:
        out["moralis_stream_transfer_count"] = float(len(transfers))
    if isinstance(txs, list) and txs:
        out["moralis_stream_transaction_count"] = float(len(txs))
    return out


def _strict_source_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        return None
    return parsed.astimezone(UTC)


def _sum_nonnegative_usd(
    rows: list[Mapping[str, Any]],
    fields: tuple[str, ...],
    *,
    feature_family: str,
    raw_response_binding: Mapping[str, Any],
    observed_at: datetime,
    source_window_seconds: int,
) -> tuple[float | None, list[dict[str, Any]], list[str]]:
    total = 0.0
    receipts: list[dict[str, Any]] = []
    rejections: list[str] = []
    for row_index, row in enumerate(rows):
        value = _first_nonnegative_float(row, fields)
        if value is None:
            continue
        receipt, rejection = _contributor_receipt(
            row,
            row_index=row_index,
            feature_family=feature_family,
            raw_response_binding=raw_response_binding,
            observed_at=observed_at,
            source_window_seconds=source_window_seconds,
        )
        if receipt is None:
            rejections.append(f"ROW_{row_index}:{rejection}")
            continue
        total += value
        receipts.append(receipt)
    return (total, receipts, rejections) if receipts else (None, [], rejections)


def _first_nonnegative_float(
    values: Mapping[str, Any],
    fields: tuple[str, ...],
) -> float | None:
    for field in fields:
        if field in values:
            return _strict_nonnegative_float(values.get(field))
    return None


def _strict_nonnegative_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _strict_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed_float = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed_float) or parsed_float < 0 or not parsed_float.is_integer():
        return None
    return int(parsed_float)


def _strict_evm_address(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if _EVM_ADDRESS_RE.fullmatch(normalized) else None


def _json_safe_scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return value if not value or _safe_text(value) else None
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def classifier_source_event_id(row: Mapping[str, Any]) -> str | None:
    """Return a collision-resistant transaction+log identity for classifier receipts."""

    transaction_hash = _transaction_hash(row)
    log_index = _log_index(row)
    if transaction_hash is None or log_index is None:
        return None
    return hashlib.sha256(
        _strict_json_bytes(
            {
                "log_index": log_index,
                "transaction_hash": transaction_hash,
            }
        )
    ).hexdigest()


def _transaction_hash(row: Mapping[str, Any]) -> str | None:
    for field in ("transaction_hash", "transactionHash", "hash"):
        value = row.get(field)
        if _safe_text(value, max_bytes=128):
            return str(value).strip().lower()
    return None


def _log_index(row: Mapping[str, Any]) -> str | None:
    value = row.get("log_index", row.get("logIndex"))
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) and value >= 0:
        return str(value)
    if isinstance(value, str):
        candidate = value.strip().lower()
        try:
            parsed = int(candidate, 16 if candidate.startswith("0x") else 10)
        except ValueError:
            return None
        if parsed >= 0:
            return str(parsed)
    return None


def _request_target_kind(spec: MoralisEndpointSpec) -> str:
    if spec.requires_wallet:
        return "wallet"
    if spec.requires_token:
        return "token"
    if spec.stream_based or spec.group == "streams":
        return "stream"
    return "symbol"


def _request_target(
    spec: MoralisEndpointSpec,
    *,
    wallet: str | None,
    token: str | None,
    symbol: str | None,
) -> str:
    kind = _request_target_kind(spec)
    raw = {
        "wallet": wallet,
        "token": token,
        "stream": "global",
        "symbol": symbol,
    }[kind]
    return str(raw or "").strip().lower()


def _redis_key_valid(value: str) -> bool:
    if len(value.encode("utf-8")) > 512:
        return False
    segments = value.split(":")
    return bool(
        segments
        and all(
            _safe_text(segment, max_bytes=128) and re.fullmatch(r"[A-Za-z0-9_.-]+", segment)
            for segment in segments
        )
    )


def _safe_text(value: Any, *, max_bytes: int = _MAX_JSON_STRING_BYTES) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if unicodedata.normalize("NFC", value) != value:
        return False
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return bool(
        len(encoded) <= max_bytes
        and all(not unicodedata.category(char).startswith("C") for char in value)
    )


def _bounded_transport_json_rejection(value: Any) -> str | None:
    try:
        canonical_transport_json_bytes(value)
    except (TypeError, ValueError, UnicodeError):
        return "PAYLOAD_NOT_BOUNDED_TRANSPORT_JSON"
    return None


def _raw_response_binding(
    *,
    raw_response_sha256: str | None,
    raw_response_evidence_bound: bool,
) -> dict[str, Any]:
    digest = (
        raw_response_sha256
        if isinstance(raw_response_sha256, str) and _SHA256_RE.fullmatch(raw_response_sha256)
        else None
    )
    return {
        "raw_response_sha256": digest,
        "raw_response_evidence_bound": bool(raw_response_evidence_bound and digest is not None),
    }


def _semantic_projection(feature_family: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Project only fields with defined endpoint semantics into a strict row."""

    projection: dict[str, Any] = {}
    for field in _SEMANTIC_FIELDS_BY_GROUP.get(feature_family, ("block_timestamp", "timestamp")):
        if field not in row:
            continue
        value = row.get(field)
        if not (
            value is None
            or isinstance(value, bool | int)
            or isinstance(value, float) and math.isfinite(value)
            or isinstance(value, str) and (not value or _safe_text(value))
        ):
            continue
        projection[field] = value
    return projection


def _semantic_quarantine_reasons(value: Any) -> list[str]:
    """Report unsafe metadata paths without copying them into semantic output."""

    try:
        canonical_transport_json_bytes(value)
    except (TypeError, ValueError, UnicodeError):
        return []

    reasons: list[str] = []

    def record(reason: str) -> None:
        if len(reasons) < _MAX_SEMANTIC_QUARANTINE_REASONS:
            reasons.append(reason)

    def walk(item: Any, path: str) -> None:
        if len(reasons) >= _MAX_SEMANTIC_QUARANTINE_REASONS:
            return
        if isinstance(item, str):
            if item and not _safe_text(item):
                record(f"SEMANTIC_FIELD_QUARANTINED:{path}")
            return
        if isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(key, str) and _SAFE_PATH_COMPONENT_RE.fullmatch(key):
                    child_path = f"{path}.{key}"
                else:
                    key_bytes = str(key).encode("utf-8", errors="backslashreplace")
                    key_digest = hashlib.sha256(key_bytes).hexdigest()[:16]
                    child_path = f"{path}[key_sha256_{key_digest}]"
                    if not isinstance(key, str) or not _safe_text(key):
                        record(f"SEMANTIC_OBJECT_KEY_QUARANTINED:{child_path}")
                walk(child, child_path)

    walk(value, "$")
    if len(reasons) >= _MAX_SEMANTIC_QUARANTINE_REASONS:
        reasons.append("SEMANTIC_QUARANTINE_REASON_LIMIT_REACHED")
    return sorted(set(reasons))


def _contributor_receipt(
    row: Mapping[str, Any],
    *,
    row_index: int,
    feature_family: str,
    raw_response_binding: Mapping[str, Any],
    observed_at: datetime,
    source_window_seconds: int,
) -> tuple[dict[str, Any] | None, str | None]:
    event_time = _strict_source_time(row.get("block_timestamp") or row.get("timestamp"))
    if event_time is None:
        return None, "CONTRIBUTOR_EVENT_TIME_MISSING_OR_INVALID"
    age_seconds = (observed_at - event_time).total_seconds()
    if age_seconds < 0:
        return None, "CONTRIBUTOR_EVENT_TIME_AFTER_NORMALIZATION"
    if age_seconds > source_window_seconds:
        return None, "CONTRIBUTOR_STALE_OUTSIDE_SOURCE_WINDOW"
    try:
        row_bytes = canonical_transport_json_bytes(dict(row))
        projection = _semantic_projection(feature_family, row)
        projection_bytes = _strict_json_bytes(projection)
    except (TypeError, ValueError):
        return None, "CONTRIBUTOR_ROW_NOT_CLOSED_STRICT_JSON"
    row_canonical_json = row_bytes.decode("ascii")
    if not _safe_text(row_canonical_json):
        return None, "CONTRIBUTOR_ROW_CANONICAL_LIMIT_EXCEEDED"
    return (
        {
            "row_index": int(row_index),
            "event_time": _iso_utc(event_time),
            "row_sha256": hashlib.sha256(row_bytes).hexdigest(),
            "row_canonical_json": row_canonical_json,
            "semantic_projection_schema_version": _SEMANTIC_PROJECTION_SCHEMA,
            "semantic_projection_sha256": hashlib.sha256(projection_bytes).hexdigest(),
            "semantic_projection_canonical_json": projection_bytes.decode("utf-8"),
            "raw_response_sha256": raw_response_binding.get("raw_response_sha256"),
            "raw_response_evidence_bound": (
                raw_response_binding.get("raw_response_evidence_bound") is True
            ),
        },
        None,
    )


def _latest_evidence_event_time(
    feature_evidence: Mapping[str, Mapping[str, Any]],
    diagnostic_evidence: Mapping[str, Mapping[str, Any]],
) -> str | None:
    parsed = [
        clock
        for row in (*feature_evidence.values(), *diagnostic_evidence.values())
        if (clock := _strict_source_time(row.get("event_time"))) is not None
    ]
    return _iso_utc(max(parsed)) if parsed else None


def _strict_json_bytes(value: Any) -> bytes:
    _validate_closed_json(value)
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > _MAX_JSON_BYTES:
        raise ValueError("JSON_BYTE_LIMIT_EXCEEDED")
    return encoded


def _validate_closed_json(
    value: Any,
    *,
    path: str = "$",
    depth: int = 0,
    node_budget: list[int] | None = None,
) -> None:
    if node_budget is None:
        node_budget = [_MAX_JSON_TOTAL_NODES]
    node_budget[0] -= 1
    if node_budget[0] < 0:
        raise ValueError(f"{path}: JSON node limit exceeded")
    if depth > _MAX_JSON_DEPTH:
        raise ValueError(f"{path}: JSON depth limit exceeded")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if value and not _safe_text(value):
            raise ValueError(f"{path}: unsafe or oversized string")
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite number")
        return
    if isinstance(value, list):
        if len(value) > _MAX_JSON_LIST_ITEMS:
            raise ValueError(f"{path}: JSON list cardinality exceeded")
        for index, item in enumerate(value):
            _validate_closed_json(
                item,
                path=f"{path}[{index}]",
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    if isinstance(value, dict):
        if len(value) > _MAX_JSON_OBJECT_FIELDS:
            raise ValueError(f"{path}: JSON object cardinality exceeded")
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: non-string object key")
            if not _safe_text(key):
                raise ValueError(f"{path}: unsafe or oversized object key")
            _validate_closed_json(
                item,
                path=f"{path}.{key}",
                depth=depth + 1,
                node_budget=node_budget,
            )
        return
    raise TypeError(f"{path}: unsupported JSON type {type(value).__name__}")


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _evidence(
    spec: MoralisEndpointSpec,
    *,
    unit: str,
    direction: str,
    scope: str,
    contributor_receipts: list[dict[str, Any]],
    source_window_seconds: int,
    classified_identities: list[str] | None = None,
) -> dict[str, Any]:
    clocks = [
        parsed
        for receipt in contributor_receipts
        if (parsed := _strict_source_time(receipt.get("event_time"))) is not None
    ]
    contributing_rows_sha256 = hashlib.sha256(_strict_json_bytes(contributor_receipts)).hexdigest()
    return {
        "endpoint_id": spec.endpoint_id,
        "feature_family": spec.group,
        "unit": unit,
        "direction": direction,
        "measurement_scope": scope,
        "contributing_row_count": len(contributor_receipts),
        "contributing_rows": contributor_receipts,
        "contributing_rows_sha256": contributing_rows_sha256,
        "event_time": _iso_utc(max(clocks)),
        "feature_cutoff": _iso_utc(max(clocks)),
        "source_window_seconds": int(source_window_seconds),
        "freshness_status": "FRESH_WITHIN_SOURCE_WINDOW",
        "classified_identities": list(classified_identities or []),
    }
