from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .accounting import coerce_float, pnl_bps, pnl_usd
from .generation_identity import POSITION_ID_VERSION, entry_generation_identity

ADAPTIVE_CAPITAL_POLICY_VERSION = "ADAPTIVE_CAPITAL_ALLOCATOR_V1"
PAPER_ENTRY_COST_ACCOUNTING_VERSION = "PAPER_ENTRY_COST_BASIS_V1"
PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION = (
    "PAPER_OPEN_POSITION_RECONSTRUCTION_V3"
)
EXACT_ON_POLICY_POSITION_LINEAGE_SCHEMA_VERSION = (
    "PAPER_EXACT_ON_POLICY_POSITION_LINEAGE_V1"
)
_BINANCE_USDM_BRACKET_SOURCE = (
    "BINANCE_USDM_USER_DATA_GET_FAPI_V1_LEVERAGE_BRACKET"
)
_KNOWN_BINANCE_USDM_ENVIRONMENTS = frozenset({"mainnet", "testnet"})
_SHA256_HEX_CHARS = frozenset("0123456789abcdef")

_PAPER_POSITION_RECONSTRUCTION_FIELDS = (
    "position_reconstruction_schema_version",
    "position_reconstruction_generated_at",
    "position_id",
    "legacy_position_id",
    "position_generation_id",
    "position_id_version",
    "entry_generation_time_utc",
    "symbol",
    "side",
    "net_quantity",
    "avg_entry_price",
    "gross_notional_usd",
    "allocated_margin_usd",
    "effective_leverage",
    "recommended_leverage",
    "leverage_source",
    "recommended_margin_mode",
    "margin_mode_simulated",
    "adaptive_allocation",
    "adaptive_policy_authoritative",
    "adaptive_policy_action_id",
    "adaptive_policy_action_sha256",
    "adaptive_paper_policy_authorization_sha256",
    "adaptive_policy_exit_plan",
    "adaptive_policy_stop_price",
    "adaptive_policy_profit_target_price",
    "adaptive_policy_max_hold_seconds",
    "adaptive_policy_time_exit_at",
    "maintenance_margin_rate",
    "maintenance_margin_cum",
    "maintenance_margin_notional_usd",
    "maintenance_bracket_id",
    "maintenance_bracket_maint_margin_ratio",
    "maintenance_bracket_cum",
    "maintenance_bracket_max_initial_leverage",
    "maintenance_bracket_evidence_hash",
    "maintenance_bracket_evidence_checksum_sha256",
    "maintenance_bracket_evidence_hmac_sha256",
    "maintenance_bracket_binding",
    "maintenance_bracket_environment_id",
    "maintenance_bracket_key_id",
    "maintenance_bracket_source",
    "maintenance_bracket_available_at",
    "maintenance_bracket_expires_at",
    "maintenance_bracket_consumer_observed_at",
    "maintenance_bracket_prevalidated",
    "maintenance_bracket_evidence_status",
    "maintenance_bracket_evidence_reason",
    "liquidation_price_estimate",
    "liquidation_buffer_bps",
    "opened_est",
    "source_fill_ids",
    "realized_pnl",
    "entry_cost_accounting_version",
    "entry_fees_incurred_usd",
    "entry_fees_remaining_usd",
    "entry_fees_allocated_to_closes_usd",
    "entry_fee_fallback_bps_per_side",
    "entry_slippage_incurred_usd",
    "entry_slippage_remaining_usd",
    "entry_slippage_allocated_to_closes_usd",
    "entry_slippage_fallback_bps_per_side",
    "entry_fee_cost_sources",
    "entry_slippage_cost_sources",
    "entry_cost_basis_status",
    "position_state",
    "paper_only",
    "places_real_order",
)
_EXACT_ON_POLICY_POSITION_RECONSTRUCTION_FIELDS = (
    "exact_on_policy_position_lineage_schema_version",
    "behavior_policy_receipt_hash",
    "behavior_policy_receipt_archive_entry_event_hash",
    "behavior_policy_receipt_archive_verified_at_entry",
    "behavior_policy_receipt_archive_retention_required",
    "behavior_policy_receipt_entry_event_pending",
    "on_policy_action_receipt_prevalidated",
    "on_policy_action_receipt_valid",
    "exact_on_policy_entry_outbox_record_id",
    "exact_on_policy_entry_outbox_state",
    "exact_on_policy_sealed_fill_sha256",
    "behavior_policy_fingerprint",
    "behavior_policy_checkpoint_hash",
    "selected_action",
    "selected_action_index",
    "selected_action_log_prob",
    "old_log_prob",
    "old_value",
    "rollout_id",
    "trajectory_index",
    "decision_time",
    "opened_est",
    "source_fill_ids",
)
PAPER_POSITION_RECONSTRUCTION_PERSISTENCE_FIELDS = (
    *_PAPER_POSITION_RECONSTRUCTION_FIELDS,
    *_EXACT_ON_POLICY_POSITION_RECONSTRUCTION_FIELDS,
    "position_reconstruction_hash",
)


def _paper_position_reconstruction_material(row: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical, content-addressed persisted-position material."""

    material = {
        field_name: row.get(field_name)
        for field_name in _PAPER_POSITION_RECONSTRUCTION_FIELDS
    }
    material["symbol"] = str(material.get("symbol") or "").upper()
    material["side"] = str(material.get("side") or "").lower()
    for field_name in (
        "net_quantity",
        "avg_entry_price",
        "gross_notional_usd",
        "allocated_margin_usd",
        "effective_leverage",
        "recommended_leverage",
        "maintenance_margin_rate",
        "maintenance_margin_cum",
        "maintenance_margin_notional_usd",
        "adaptive_policy_stop_price",
        "adaptive_policy_profit_target_price",
        "adaptive_policy_max_hold_seconds",
        "maintenance_bracket_id",
        "maintenance_bracket_maint_margin_ratio",
        "maintenance_bracket_cum",
        "maintenance_bracket_max_initial_leverage",
        "liquidation_price_estimate",
        "liquidation_buffer_bps",
        "realized_pnl",
        "entry_fees_incurred_usd",
        "entry_fees_remaining_usd",
        "entry_fees_allocated_to_closes_usd",
        "entry_fee_fallback_bps_per_side",
        "entry_slippage_incurred_usd",
        "entry_slippage_remaining_usd",
        "entry_slippage_allocated_to_closes_usd",
        "entry_slippage_fallback_bps_per_side",
    ):
        material[field_name] = coerce_float(material.get(field_name))
    for field_name in (
        "source_fill_ids",
        "entry_fee_cost_sources",
        "entry_slippage_cost_sources",
    ):
        raw = material.get(field_name)
        material[field_name] = (
            [str(value) for value in raw if value not in (None, "")]
            if isinstance(raw, list | tuple)
            else []
        )
    # Missing maintenance evidence and explicitly non-prevalidated evidence
    # are the same fail-closed state. Normalizing the tri-state prevents a
    # harmless ``None`` -> ``False`` restore from changing the content hash.
    material["maintenance_bracket_prevalidated"] = (
        material.get("maintenance_bracket_prevalidated") is True
    )
    exact_claimed = bool(
        row.get("ppo_on_policy_entry_fields_present") is True
        or row.get("behavior_policy_receipt_entry_event_pending") is True
        or row.get("on_policy_action_receipt_prevalidated") is True
        or row.get("on_policy_action_receipt_valid") is True
        or row.get("behavior_policy_receipt_archive_entry_event_hash")
    )
    if exact_claimed:
        exact_lineage = {
            field_name: row.get(field_name)
            for field_name in _EXACT_ON_POLICY_POSITION_RECONSTRUCTION_FIELDS
        }
        for field_name in (
            "selected_action_index",
            "trajectory_index",
        ):
            value = coerce_float(exact_lineage.get(field_name))
            exact_lineage[field_name] = (
                int(value)
                if value is not None and value.is_integer()
                else value
            )
        for field_name in (
            "selected_action_log_prob",
            "old_log_prob",
            "old_value",
        ):
            exact_lineage[field_name] = coerce_float(
                exact_lineage.get(field_name)
            )
        source_fill_ids = exact_lineage.get("source_fill_ids")
        exact_lineage["source_fill_ids"] = (
            [str(value) for value in source_fill_ids if value not in (None, "")]
            if isinstance(source_fill_ids, list | tuple)
            else []
        )
        material["exact_on_policy_lineage"] = exact_lineage
    return material


def paper_position_reconstruction_hash(row: dict[str, Any]) -> str | None:
    """Hash exact open-position identity, capital, risk, fills, and costs."""

    try:
        canonical = json.dumps(
            _paper_position_reconstruction_material(row),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_paper_position_reconstruction(
    row: dict[str, Any],
    *,
    observed_at: Any = None,
) -> list[str]:
    """Validate a persisted open snapshot before it can recreate economics.

    This is an integrity/conservation envelope, not an authentication claim.
    Legacy rows without it may still supply non-economic context, but they can
    never restore a partially consumed position or its remaining entry basis.
    """

    reasons: list[str] = []
    if (
        row.get("position_reconstruction_schema_version")
        != PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION
    ):
        reasons.append("POSITION_RECONSTRUCTION_SCHEMA_VERSION_INVALID")
    supplied_hash = str(row.get("position_reconstruction_hash") or "")
    computed_hash = paper_position_reconstruction_hash(row)
    if not _is_lower_sha256_hex(supplied_hash):
        reasons.append("POSITION_RECONSTRUCTION_HASH_INVALID")
    elif computed_hash != supplied_hash:
        reasons.append("POSITION_RECONSTRUCTION_HASH_MISMATCH")
    for field_name in (
        "position_id",
        "position_generation_id",
        "entry_generation_time_utc",
        "position_reconstruction_generated_at",
    ):
        if row.get(field_name) in (None, ""):
            reasons.append(
                f"POSITION_RECONSTRUCTION_{field_name.upper()}_MISSING"
            )
    entry_time = parse_aware_utc(row.get("entry_generation_time_utc"))
    opened_time = parse_aware_utc(row.get("opened_est"))
    reconstruction_time = parse_aware_utc(
        row.get("position_reconstruction_generated_at")
    )
    observed_time = (
        parse_aware_utc(observed_at) if observed_at not in (None, "") else None
    )
    if entry_time is None:
        reasons.append("POSITION_RECONSTRUCTION_ENTRY_TIME_NOT_AWARE_UTC")
    if opened_time is None:
        reasons.append("POSITION_RECONSTRUCTION_OPENED_TIME_NOT_AWARE")
    if reconstruction_time is None:
        reasons.append("POSITION_RECONSTRUCTION_GENERATED_TIME_NOT_AWARE_UTC")
    if observed_at not in (None, "") and observed_time is None:
        reasons.append("POSITION_RECONSTRUCTION_OBSERVED_TIME_NOT_AWARE_UTC")
    if (
        entry_time is not None
        and reconstruction_time is not None
        and entry_time > reconstruction_time
    ):
        reasons.append("POSITION_RECONSTRUCTION_ENTRY_AFTER_GENERATED_TIME")
    if (
        opened_time is not None
        and reconstruction_time is not None
        and opened_time > reconstruction_time
    ):
        reasons.append("POSITION_RECONSTRUCTION_OPENED_AFTER_GENERATED_TIME")
    if (
        entry_time is not None
        and opened_time is not None
        and entry_time > opened_time
    ):
        reasons.append("POSITION_RECONSTRUCTION_ENTRY_AFTER_OPENED_TIME")
    if (
        reconstruction_time is not None
        and observed_time is not None
        and reconstruction_time > observed_time
    ):
        reasons.append("POSITION_RECONSTRUCTION_GENERATED_AFTER_OBSERVED_TIME")
    if row.get("position_id_version") != POSITION_ID_VERSION:
        reasons.append("POSITION_RECONSTRUCTION_POSITION_ID_VERSION_INVALID")
    if str(row.get("symbol") or "").strip().upper() == "":
        reasons.append("POSITION_RECONSTRUCTION_SYMBOL_MISSING")
    if str(row.get("side") or "").strip().lower() not in {
        "long",
        "short",
        "buy",
        "sell",
    }:
        reasons.append("POSITION_RECONSTRUCTION_SIDE_INVALID")
    quantity = coerce_float(row.get("net_quantity"))
    entry_price = coerce_float(row.get("avg_entry_price"))
    gross_notional = coerce_float(row.get("gross_notional_usd"))
    allocated_margin = coerce_float(row.get("allocated_margin_usd"))
    effective_leverage = coerce_float(row.get("effective_leverage"))
    recommended_leverage = coerce_float(row.get("recommended_leverage"))
    realized_pnl = coerce_float(row.get("realized_pnl"))
    if quantity is None or not math.isfinite(quantity) or quantity <= 0.0:
        reasons.append("POSITION_RECONSTRUCTION_NET_QUANTITY_INVALID")
    if entry_price is None or not math.isfinite(entry_price) or entry_price <= 0.0:
        reasons.append("POSITION_RECONSTRUCTION_AVG_ENTRY_PRICE_INVALID")
    if (
        gross_notional is None
        or not math.isfinite(gross_notional)
        or gross_notional <= 0.0
    ):
        reasons.append("POSITION_RECONSTRUCTION_GROSS_NOTIONAL_INVALID")
    if (
        allocated_margin is None
        or not math.isfinite(allocated_margin)
        or allocated_margin <= 0.0
    ):
        reasons.append("POSITION_RECONSTRUCTION_ALLOCATED_MARGIN_INVALID")
    if (
        effective_leverage is None
        or not math.isfinite(effective_leverage)
        or effective_leverage < 1.0
    ):
        reasons.append("POSITION_RECONSTRUCTION_EFFECTIVE_LEVERAGE_INVALID")
    if (
        recommended_leverage is None
        or not math.isfinite(recommended_leverage)
        or recommended_leverage < 1.0
    ):
        reasons.append("POSITION_RECONSTRUCTION_RECOMMENDED_LEVERAGE_INVALID")
    if (
        quantity is not None
        and math.isfinite(quantity)
        and quantity > 0.0
        and entry_price is not None
        and math.isfinite(entry_price)
        and entry_price > 0.0
        and gross_notional is not None
        and math.isfinite(gross_notional)
        and not _accounting_values_match(
            gross_notional,
            abs(quantity * entry_price),
        )
    ):
        reasons.append("POSITION_RECONSTRUCTION_GROSS_NOTIONAL_IDENTITY_INVALID")
    if (
        gross_notional is not None
        and math.isfinite(gross_notional)
        and gross_notional > 0.0
        and allocated_margin is not None
        and math.isfinite(allocated_margin)
        and allocated_margin > 0.0
        and effective_leverage is not None
        and math.isfinite(effective_leverage)
        and effective_leverage >= 1.0
        and not _accounting_values_match(
            allocated_margin,
            gross_notional / effective_leverage,
        )
    ):
        reasons.append("POSITION_RECONSTRUCTION_MARGIN_LEVERAGE_IDENTITY_INVALID")
    if str(row.get("margin_mode_simulated") or "").strip().lower() not in {
        "isolated",
        "isolated_paper_simulated",
    }:
        reasons.append("POSITION_RECONSTRUCTION_MARGIN_MODE_NOT_ISOLATED")

    allocation = row.get("adaptive_allocation")
    if allocation not in (None, {}):
        if not isinstance(allocation, dict):
            reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_ALLOCATION_INVALID")
        else:
            allocation_effective = coerce_float(
                allocation.get("effective_leverage")
            )
            allocation_margin = coerce_float(allocation.get("allocated_margin_usd"))
            allocation_notional = coerce_float(allocation.get("gross_notional_usd"))
            for field_name, allocation_value, position_value in (
                (
                    "EFFECTIVE_LEVERAGE",
                    allocation_effective,
                    effective_leverage,
                ),
                ("ALLOCATED_MARGIN", allocation_margin, allocated_margin),
                ("GROSS_NOTIONAL", allocation_notional, gross_notional),
            ):
                if allocation_value is not None and not _accounting_values_match(
                    allocation_value,
                    position_value,
                ):
                    reasons.append(
                        "POSITION_RECONSTRUCTION_ADAPTIVE_ALLOCATION_"
                        f"{field_name}_MISMATCH"
                    )
            model_inputs = allocation.get("model_inputs")
            model_inputs = model_inputs if isinstance(model_inputs, dict) else {}
            risk_envelope = model_inputs.get("risk_envelope")
            risk_envelope = risk_envelope if isinstance(risk_envelope, dict) else {}
            decision_time_cap = coerce_float(
                risk_envelope.get("max_effective_leverage")
            )
            if (
                bool(risk_envelope)
                and
                effective_leverage is not None
                and math.isfinite(effective_leverage)
                and effective_leverage > 1.0
                and (
                    decision_time_cap is None
                    or not math.isfinite(decision_time_cap)
                    or effective_leverage > decision_time_cap + 1e-9
                )
            ):
                reasons.append(
                    "POSITION_RECONSTRUCTION_EFFECTIVE_LEVERAGE_EXCEEDS_"
                    "DECISION_TIME_ENVELOPE"
                )
            selected_leverage = coerce_float(model_inputs.get("selected_leverage"))
            if (
                selected_leverage is not None
                and not _accounting_values_match(
                    selected_leverage,
                    effective_leverage,
                )
            ):
                reasons.append(
                    "POSITION_RECONSTRUCTION_SELECTED_LEVERAGE_MISMATCH"
                )
            permitted_values = model_inputs.get("permitted_leverage_values")
            if isinstance(permitted_values, list | tuple) and effective_leverage is not None:
                permitted = [
                    parsed
                    for value in permitted_values
                    if (parsed := coerce_float(value)) is not None
                    and math.isfinite(parsed)
                    and parsed >= 1.0
                ]
                if not permitted or not any(
                    _accounting_values_match(value, effective_leverage)
                    for value in permitted
                ):
                    reasons.append(
                        "POSITION_RECONSTRUCTION_EFFECTIVE_LEVERAGE_NOT_PERMITTED"
                    )
            if (
                model_inputs.get("mode") == "paper"
                and effective_leverage is not None
                and math.isfinite(effective_leverage)
                and effective_leverage > 1.0
            ):
                allocation_lineage = allocation.get("lineage_ids")
                allocation_lineage = (
                    allocation_lineage
                    if isinstance(allocation_lineage, dict)
                    else {}
                )
                atr_receipt = allocation_lineage.get(
                    "paper_liquidation_atr_evidence"
                )
                atr_receipt_hash = allocation_lineage.get(
                    "paper_liquidation_atr_evidence_sha256"
                )
                allocation_input_material = allocation.get(
                    "allocation_input_material"
                )
                allocation_input_material = (
                    allocation_input_material
                    if isinstance(allocation_input_material, dict)
                    else {}
                )
                allocation_input = allocation_input_material.get(
                    "allocation_input"
                )
                allocation_input = (
                    allocation_input
                    if isinstance(allocation_input, dict)
                    else {}
                )
                allocation_input_lineage = allocation_input.get("lineage_ids")
                allocation_input_lineage = (
                    allocation_input_lineage
                    if isinstance(allocation_input_lineage, dict)
                    else {}
                )
                try:
                    canonical_allocation_input = json.dumps(
                        allocation_input_material,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                        allow_nan=False,
                    )
                except (TypeError, ValueError):
                    canonical_allocation_input = None
                recomputed_allocation_input_hash = (
                    hashlib.sha256(
                        canonical_allocation_input.encode("utf-8")
                    ).hexdigest()
                    if canonical_allocation_input is not None
                    else None
                )
                paper_liquidation_geometry = None
                maintenance_rate_for_geometry = coerce_float(
                    model_inputs.get("maintenance_margin_rate_effective")
                )
                try:
                    from v2.backend.app.services.adaptive_capital_allocator.allocator import (  # noqa: PLC0415
                        paper_isolated_liquidation_geometry,
                        validate_paper_liquidation_atr_evidence,
                    )

                    validated_atr_bps, atr_validation_reasons = (
                        validate_paper_liquidation_atr_evidence(
                            atr_receipt
                            if isinstance(atr_receipt, dict)
                            else None,
                            atr_receipt_hash,
                            symbol=str(row.get("symbol") or ""),
                            timeframe=str(
                                allocation_input.get("timeframe")
                                or allocation.get("timeframe")
                                or ""
                            ),
                            entry_atr_bps=allocation_input.get(
                                "entry_atr_bps"
                            ),
                        )
                    )
                    normalized_side = str(row.get("side") or "").strip().lower()
                    if (
                        entry_price is not None
                        and math.isfinite(entry_price)
                        and maintenance_rate_for_geometry is not None
                        and math.isfinite(maintenance_rate_for_geometry)
                    ):
                        paper_liquidation_geometry = (
                            paper_isolated_liquidation_geometry(
                                side=(
                                    "long"
                                    if normalized_side in {"long", "buy"}
                                    else "short"
                                ),
                                entry_price=entry_price,
                                leverage=effective_leverage,
                                maintenance_margin_rate=(
                                    maintenance_rate_for_geometry
                                ),
                            )
                        )
                except Exception:
                    validated_atr_bps = None
                    atr_validation_reasons = [
                        "PAPER_LIQUIDATION_ATR_VALIDATOR_UNAVAILABLE"
                    ]
                model_atr_bps = coerce_float(
                    model_inputs.get("paper_liquidation_atr_bps")
                )
                if (
                    atr_validation_reasons
                    or validated_atr_bps is None
                    or model_atr_bps is None
                    or not _accounting_values_match(
                        validated_atr_bps,
                        model_atr_bps,
                    )
                    or model_inputs.get("paper_liquidation_atr_evidence_sha256")
                    != atr_receipt_hash
                    or allocation_input_material.get("mode") != "paper"
                    or allocation_input.get("symbol") != row.get("symbol")
                    or allocation_input_lineage.get(
                        "paper_liquidation_atr_evidence"
                    )
                    != atr_receipt
                    or allocation_input_lineage.get(
                        "paper_liquidation_atr_evidence_sha256"
                    )
                    != atr_receipt_hash
                    or not _is_lower_sha256_hex(
                        allocation.get("allocation_input_hash")
                    )
                    or recomputed_allocation_input_hash
                    != allocation.get("allocation_input_hash")
                    or model_inputs.get("allocation_input_hash")
                    != allocation.get("allocation_input_hash")
                ):
                    reasons.append(
                        "POSITION_RECONSTRUCTION_PAPER_LIQUIDATION_ATR_RECEIPT_INVALID"
                    )
                required_buffer = coerce_float(
                    model_inputs.get("paper_required_liquidation_buffer_bps")
                )
                selected_residual_buffer = coerce_float(
                    allocation.get("liquidation_buffer_bps")
                )
                maintenance_rate = maintenance_rate_for_geometry
                stop_distance = coerce_float(model_inputs.get("stop_distance_bps"))
                fee_bps = coerce_float(model_inputs.get("fee_bps"))
                slippage_bps = coerce_float(model_inputs.get("slippage_bps"))
                funding_bps = coerce_float(model_inputs.get("expected_funding_bps"))
                recomputed_residual_buffer = None
                if (
                    paper_liquidation_geometry is not None
                    and maintenance_rate is not None
                    and math.isfinite(maintenance_rate)
                    and stop_distance is not None
                    and math.isfinite(stop_distance)
                    and fee_bps is not None
                    and math.isfinite(fee_bps)
                    and slippage_bps is not None
                    and math.isfinite(slippage_bps)
                    and funding_bps is not None
                    and math.isfinite(funding_bps)
                ):
                    recomputed_residual_buffer = (
                        paper_liquidation_geometry[0]
                        - stop_distance
                        - max(0.0, fee_bps)
                        - max(0.0, slippage_bps)
                        - abs(funding_bps)
                    )
                if (
                    model_inputs.get("paper_liquidation_buffer_contract_status")
                    != "READY"
                    or required_buffer is None
                    or required_buffer <= 0.0
                    or selected_residual_buffer is None
                    or selected_residual_buffer + 1e-8 < required_buffer
                    or recomputed_residual_buffer is None
                    or not _accounting_values_match(
                        selected_residual_buffer,
                        recomputed_residual_buffer,
                    )
                ):
                    reasons.append(
                        "POSITION_RECONSTRUCTION_PAPER_LIQUIDATION_BUFFER_INVALID"
                    )

    bracket_max_leverage = coerce_float(
        row.get("maintenance_bracket_max_initial_leverage")
    )
    if (
        bracket_max_leverage is not None
        and effective_leverage is not None
        and math.isfinite(effective_leverage)
        and effective_leverage > bracket_max_leverage + 1e-9
    ):
        reasons.append(
            "POSITION_RECONSTRUCTION_EFFECTIVE_LEVERAGE_EXCEEDS_BRACKET"
        )
    if realized_pnl is None or not math.isfinite(realized_pnl):
        reasons.append("POSITION_RECONSTRUCTION_REALIZED_PNL_INVALID")
    source_ids = row.get("source_fill_ids")
    normalized_source_ids = (
        [str(value) for value in source_ids if value not in (None, "")]
        if isinstance(source_ids, list | tuple)
        else []
    )
    if not normalized_source_ids:
        reasons.append("POSITION_RECONSTRUCTION_SOURCE_FILL_IDS_MISSING")
    elif len(normalized_source_ids) != len(set(normalized_source_ids)):
        reasons.append("POSITION_RECONSTRUCTION_SOURCE_FILL_IDS_DUPLICATED")
    if row.get("entry_cost_accounting_version") != PAPER_ENTRY_COST_ACCOUNTING_VERSION:
        reasons.append("POSITION_RECONSTRUCTION_ENTRY_COST_VERSION_INVALID")
    for prefix in ("entry_fees", "entry_slippage"):
        raw_supplied = (
            row.get(f"{prefix}_incurred_usd"),
            row.get(f"{prefix}_remaining_usd"),
            row.get(f"{prefix}_allocated_to_closes_usd"),
        )
        incurred, remaining, allocated = (
            coerce_float(value) for value in raw_supplied
        )
        supplied = (incurred, remaining, allocated)
        if any(
            raw_value not in (None, "") and parsed_value is None
            for raw_value, parsed_value in zip(
                raw_supplied,
                supplied,
                strict=True,
            )
        ):
            reasons.append(
                f"POSITION_RECONSTRUCTION_{prefix.upper()}_LEDGER_INVALID"
            )
        pristine_missing_basis = (
            incurred is None
            and remaining is None
            and (allocated is None or allocated == 0.0)
        )
        if not pristine_missing_basis and any(value is not None for value in supplied):
            if any(
                value is None or not math.isfinite(value) or value < 0.0
                for value in supplied
            ):
                reasons.append(
                    f"POSITION_RECONSTRUCTION_{prefix.upper()}_LEDGER_INCOMPLETE"
                )
            elif not math.isclose(
                float(incurred),
                float(remaining) + float(allocated),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                reasons.append(
                    f"POSITION_RECONSTRUCTION_{prefix.upper()}_CONSERVATION_FAILED"
                )
        if allocated is not None and allocated > 0.0 and (
            incurred is None or remaining is None
        ):
            reasons.append(
                f"POSITION_RECONSTRUCTION_{prefix.upper()}_PARTIAL_BASIS_MISSING"
            )
    for field_name in (
        "entry_fee_fallback_bps_per_side",
        "entry_slippage_fallback_bps_per_side",
    ):
        raw_value = row.get(field_name)
        parsed_value = coerce_float(raw_value)
        if raw_value not in (None, "") and (
            parsed_value is None
            or not math.isfinite(parsed_value)
            or parsed_value < 0.0
        ):
            reasons.append(
                f"POSITION_RECONSTRUCTION_{field_name.upper()}_INVALID"
            )
    for field_name in (
        "entry_fee_cost_sources",
        "entry_slippage_cost_sources",
    ):
        if not isinstance(row.get(field_name), list | tuple):
            reasons.append(
                f"POSITION_RECONSTRUCTION_{field_name.upper()}_INVALID"
            )
    if str(row.get("entry_cost_basis_status") or "").strip() == "":
        reasons.append("POSITION_RECONSTRUCTION_ENTRY_COST_BASIS_STATUS_MISSING")
    if row.get("adaptive_policy_authoritative") is True:
        exit_plan = row.get("adaptive_policy_exit_plan")
        stop_price = coerce_float(row.get("adaptive_policy_stop_price"))
        target_price = coerce_float(
            row.get("adaptive_policy_profit_target_price")
        )
        max_hold_seconds = coerce_float(
            row.get("adaptive_policy_max_hold_seconds")
        )
        time_exit = parse_aware_utc(row.get("adaptive_policy_time_exit_at"))
        if not str(row.get("adaptive_policy_action_id") or "").strip():
            reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_ACTION_ID_MISSING")
        for field_name in (
            "adaptive_policy_action_sha256",
            "adaptive_paper_policy_authorization_sha256",
        ):
            if not _is_lower_sha256_hex(row.get(field_name)):
                reasons.append(
                    "POSITION_RECONSTRUCTION_"
                    f"{field_name.upper()}_INVALID"
                )
        if (
            not isinstance(exit_plan, dict)
            or exit_plan.get("status") != "ADAPTIVE_POLICY_EXIT_PLAN_ACTIVE"
            or exit_plan.get("paper_only") is not True
            or exit_plan.get("routes_to_live") is not False
            or exit_plan.get("places_real_order") is not False
        ):
            reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_EXIT_PLAN_INVALID")
        elif (
            not _accounting_values_match(
                coerce_float(exit_plan.get("stop_loss_price")),
                stop_price,
            )
            or not _accounting_values_match(
                coerce_float(exit_plan.get("take_profit_price")),
                target_price,
            )
            or not _accounting_values_match(
                coerce_float(exit_plan.get("max_hold_seconds")),
                max_hold_seconds,
            )
            or str(exit_plan.get("time_exit_at") or "")
            != str(row.get("adaptive_policy_time_exit_at") or "")
            or str(exit_plan.get("adaptive_policy_action_id") or "")
            != str(row.get("adaptive_policy_action_id") or "")
        ):
            reasons.append(
                "POSITION_RECONSTRUCTION_ADAPTIVE_EXIT_PLAN_BINDING_MISMATCH"
            )
        if stop_price is None or not math.isfinite(stop_price) or stop_price <= 0.0:
            reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_STOP_PRICE_INVALID")
        if (
            max_hold_seconds is None
            or not math.isfinite(max_hold_seconds)
            or max_hold_seconds <= 0.0
        ):
            reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_MAX_HOLD_INVALID")
        if time_exit is None:
            reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_TIME_EXIT_INVALID")
        elif opened_time is not None and time_exit <= opened_time:
            reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_TIME_EXIT_NOT_AFTER_OPEN")
        normalized_side = str(row.get("side") or "").strip().lower()
        if stop_price is not None and entry_price is not None:
            if normalized_side in {"long", "buy"} and stop_price >= entry_price:
                reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_LONG_STOP_INVALID")
            if normalized_side in {"short", "sell"} and stop_price <= entry_price:
                reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_SHORT_STOP_INVALID")
        if target_price is not None and entry_price is not None:
            if normalized_side in {"long", "buy"} and target_price <= entry_price:
                reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_LONG_TARGET_INVALID")
            if normalized_side in {"short", "sell"} and target_price >= entry_price:
                reasons.append("POSITION_RECONSTRUCTION_ADAPTIVE_SHORT_TARGET_INVALID")
    exact_claimed = bool(
        row.get("ppo_on_policy_entry_fields_present") is True
        or row.get("behavior_policy_receipt_entry_event_pending") is True
        or row.get("on_policy_action_receipt_prevalidated") is True
        or row.get("on_policy_action_receipt_valid") is True
        or row.get("behavior_policy_receipt_archive_entry_event_hash")
    )
    if exact_claimed:
        if (
            row.get("exact_on_policy_position_lineage_schema_version")
            != EXACT_ON_POLICY_POSITION_LINEAGE_SCHEMA_VERSION
        ):
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_LINEAGE_SCHEMA_INVALID"
            )
        for field_name in (
            "behavior_policy_receipt_hash",
            "behavior_policy_receipt_archive_entry_event_hash",
            "exact_on_policy_entry_outbox_record_id",
            "exact_on_policy_sealed_fill_sha256",
            "behavior_policy_fingerprint",
            "behavior_policy_checkpoint_hash",
        ):
            if not _is_lower_sha256_hex(row.get(field_name)):
                reasons.append(
                    "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_"
                    f"{field_name.upper()}_INVALID"
                )
        if row.get("behavior_policy_receipt_archive_verified_at_entry") is not True:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_ENTRY_ARCHIVE_NOT_VERIFIED"
            )
        if row.get("behavior_policy_receipt_archive_retention_required") is not True:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_ARCHIVE_RETENTION_NOT_REQUIRED"
            )
        if row.get("behavior_policy_receipt_entry_event_pending") is not False:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_ENTRY_EVENT_STILL_PENDING"
            )
        if row.get("on_policy_action_receipt_prevalidated") is not True:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_RECEIPT_NOT_PREVALIDATED"
            )
        if row.get("on_policy_action_receipt_valid") is not True:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_RECEIPT_NOT_VALID"
            )
        if row.get("exact_on_policy_entry_outbox_state") not in {
            "ENTRY_EVENT_APPENDED",
            "COMMITTED",
        }:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_OUTBOX_STATE_INVALID"
            )
        if str(row.get("selected_action") or "").lower() not in {
            "long",
            "short",
        }:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_ACTION_INVALID"
            )
        for field_name in (
            "selected_action_log_prob",
            "old_log_prob",
            "old_value",
        ):
            value = coerce_float(row.get(field_name))
            if value is None or not math.isfinite(value):
                reasons.append(
                    "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_"
                    f"{field_name.upper()}_INVALID"
                )
        selected_log_prob = coerce_float(row.get("selected_action_log_prob"))
        old_log_prob = coerce_float(row.get("old_log_prob"))
        if (
            selected_log_prob is not None
            and old_log_prob is not None
            and not math.isclose(
                selected_log_prob,
                old_log_prob,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_LOG_PROBABILITY_MISMATCH"
            )
        for field_name in ("selected_action_index", "trajectory_index"):
            value = coerce_float(row.get(field_name))
            if value is None or not value.is_integer() or value < 0.0:
                reasons.append(
                    "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_"
                    f"{field_name.upper()}_INVALID"
                )
        if len(normalized_source_ids) != 1:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_REQUIRES_ONE_SOURCE_FILL"
            )
        policy_decision_time = parse_aware_utc(row.get("decision_time"))
        if policy_decision_time is None:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_DECISION_TIME_INVALID"
            )
        elif opened_time is not None and policy_decision_time > opened_time:
            reasons.append(
                "POSITION_RECONSTRUCTION_EXACT_ON_POLICY_DECISION_AFTER_ENTRY"
            )
    if row.get("position_state") != "OPEN_POSITION":
        reasons.append("POSITION_RECONSTRUCTION_STATE_NOT_OPEN")
    if row.get("paper_only") is not True or row.get("places_real_order") is not False:
        reasons.append("POSITION_RECONSTRUCTION_PAPER_SAFETY_INVALID")
    return list(dict.fromkeys(reasons))


def _is_lower_sha256_hex(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in _SHA256_HEX_CHARS for char in text)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_aware_utc(value: Any) -> datetime | None:
    """Parse an explicitly timezone-aware timestamp.

    Maintenance-bracket evidence is account-bound risk evidence.  Unlike the
    legacy display helpers above, a naive timestamp must never be assumed to
    be UTC when deciding whether that evidence was available or expired.
    """

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def utc_iso_from_any(value: Any) -> str | None:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_to_est_iso(value: Any) -> str | None:
    """Convert any ISO timestamp (UTC or offset-aware) to Eastern Time with -04:00/-05:00 offset.

    Passing an already-EST string is safe — result is idempotent.
    Returns None if value cannot be parsed.
    """
    dt = parse_utc(value)
    if dt is None:
        return None
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
    except ImportError:
        try:
            from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]
        except ImportError:
            return None
    return dt.astimezone(ZoneInfo("America/New_York")).isoformat(
        timespec="microseconds"
    )


def seconds_between(start_iso: Any, end_iso: str) -> int:
    start = parse_utc(start_iso)
    end = parse_utc(end_iso)
    if start is None or end is None:
        return 0
    return max(0, int((end - start).total_seconds()))


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def first_number(*values: Any) -> float | None:
    for value in values:
        parsed = coerce_float(value)
        if parsed is not None:
            return parsed
    return None


def atr_bps_from_payloads(*payloads: dict[str, Any] | None, price: Any = None) -> float | None:
    bps_keys = ("entry_atr_bps", "atr_bps", "true_range_bps", "natr_bps")
    pct_keys = ("atr_pct", "true_range_pct", "ta_NATR", "ta_NATR_14")
    price_keys = ("atr_14", "ta_ATR", "ta_ATR_14", "ATR", "TRANGE", "ta_TRANGE")

    # A literal 0.0 stamped upstream is MISSING evidence, not a real ATR — a
    # zero average true range does not exist in a live market. Treating it as
    # present short-circuited every fallback (2026-07-16: intents carried
    # entry_atr_bps=0.0, degrading the adaptive stop, exit-aligned sizing,
    # hedge triggers, and the A+ exit_plan_valid check while real ATR sat in
    # the pct/price fallbacks).
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        parsed = first_number(*(payload.get(key) for key in bps_keys))
        if parsed is not None and abs(parsed) > 0:
            return abs(parsed)

    # Current feature pct fields are percent-units: 0.05 means 0.05%, or 5 bps.
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        parsed = first_number(*(payload.get(key) for key in pct_keys))
        if parsed is not None and abs(parsed) > 0:
            return abs(parsed) * 100.0

    reference_price = first_number(price)
    if reference_price is not None and reference_price > 0:
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            parsed = first_number(*(payload.get(key) for key in price_keys))
            if parsed is not None and abs(parsed) > 0:
                return abs(parsed) / reference_price * 10000.0
    return None


def _nested_first_number(mapping: dict[str, Any] | None, *keys: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    return first_number(*(mapping.get(key) for key in keys))


def _liquidation_estimate(
    *,
    side: str,
    entry_price: float,
    quantity: float,
    allocated_margin: float,
    maintenance_rate: float,
    maintenance_cum: float,
) -> float | None:
    """Estimate isolated-paper liquidation using one whole-position bracket.

    This is intentionally *not* a weighted per-fill calculation.  ``cum`` is
    Binance's cumulative maintenance deduction for the selected notional
    bracket.  The estimate solves isolated equity == bracket maintenance for
    the current net position; fees and funding remain outside this estimate.
    """

    if (
        entry_price <= 0
        or quantity <= 0
        or allocated_margin <= 0
        or not 0.0 < maintenance_rate < 1.0
        or maintenance_cum < 0
    ):
        return None
    if side == "long":
        numerator = quantity * entry_price - allocated_margin - maintenance_cum
        denominator = quantity * (1.0 - maintenance_rate)
        return max(0.0, numerator / denominator)
    numerator = quantity * entry_price + allocated_margin + maintenance_cum
    denominator = quantity * (1.0 + maintenance_rate)
    return numerator / denominator


def _liquidation_buffer_bps(*, side: str, entry_price: float, liquidation_price: float | None) -> float | None:
    if entry_price <= 0 or liquidation_price is None or liquidation_price < 0:
        return None
    if side == "long":
        distance = entry_price - liquidation_price
    else:
        distance = liquidation_price - entry_price
    return max(0.0, distance / entry_price * 10000.0)


def _accounting_values_match(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-8)


_MAINTENANCE_EVIDENCE_UNSET = object()


@dataclass
class PaperNetPosition:
    position_id: str
    symbol: str
    side: str
    net_quantity: float
    avg_entry_price: float
    opened_est: str
    legacy_position_id: str | None = None
    position_generation_id: str | None = None
    position_id_version: str | None = None
    entry_generation_time_utc: str | None = None
    source_signal_id: str | None = None
    prediction_id: str | None = None
    preemptive_decision_id: str | None = None
    risk_decision_id: str | None = None
    orchestrator_decision_id: str | None = None
    allocator_decision_id: str | None = None
    materialization_queue_id: str | None = None
    materialization_queue_accepted_at: str | None = None
    materialization_queue_expires_at: str | None = None
    market_state_id: str | None = None
    trainer_source: str | None = None
    timeframe: str | None = None
    feature_snapshot_id: str | None = None
    feature_tensor_id: str | None = None
    decision_id: str | None = None
    mtf_snapshot_id: str | None = None
    feature_cutoff: str | None = None
    decision_time: str | None = None
    available_at: str | None = None
    selected_action: str | None = None
    model_version: str | None = None
    checkpoint_id: str | None = None
    checkpoint_id_source: str | None = None
    entry_prediction_snapshot: dict[str, Any] | None = None
    risk_decision_record_key: str | None = None
    risk_decision_record_hash: str | None = None
    risk_decision_record_resolved: bool | None = None
    risk_decision_source: str | None = None
    orchestrator_decision_record_key: str | None = None
    orchestrator_decision_record_hash: str | None = None
    orchestrator_decision_record_resolved: bool | None = None
    orchestrator_decision_source: str | None = None
    decision_record_missing_reasons: list[Any] | None = None
    source_hashes: dict[str, Any] | None = None
    feature_vector_hash: str | None = None
    provider_hashes: dict[str, Any] | None = None
    confidence_raw: float | None = None
    confidence_calibrated: float | None = None
    confidence_executable_trade: float | None = None
    dynamic_exploration_floor: float | None = None
    dynamic_exploration_floor_formula: str | None = None
    exploration_floor_inputs: dict[str, Any] | None = None
    paper_risk_controller_exploration_above_floor: bool | None = None
    paper_risk_controller_exploration_eligible: bool | None = None
    bootstrap_exploration: bool | None = None
    bootstrap_overridden_blockers: list[Any] | None = None
    action_labels: list[Any] | None = None
    raw_action_logits: list[Any] | None = None
    raw_action_probabilities: list[Any] | None = None
    selected_action_probability: float | None = None
    selected_action_index: int | None = None
    expected_move_bps: float | None = None
    action_probabilities: Any | None = None
    policy_value: float | None = None
    value_baseline: float | None = None
    selected_action_log_prob: float | None = None
    old_log_prob: float | None = None
    old_value: float | None = None
    rollout_id: str | None = None
    trajectory_index: int | None = None
    ppo_on_policy_entry_fields_present: bool | None = None
    ppo_on_policy_ineligible_reason: str | None = None
    behavior_action_index: int | None = None
    behavior_action: str | None = None
    behavior_action_mask: list[Any] | None = None
    behavior_action_source: str | None = None
    behavior_policy_sampling_mode: str | None = None
    behavior_policy_distribution_contract: str | None = None
    behavior_policy_fingerprint: str | None = None
    behavior_policy_checkpoint_hash: str | None = None
    behavior_policy_receipt: dict[str, Any] | None = None
    behavior_policy_receipt_hash: str | None = None
    behavior_policy_receipt_key: str | None = None
    behavior_policy_receipt_write_success: bool | None = None
    exact_on_policy_position_lineage_schema_version: str | None = None
    behavior_policy_receipt_archive_entry_event_hash: str | None = None
    behavior_policy_receipt_archive_verified_at_entry: bool | None = None
    behavior_policy_receipt_archive_retention_required: bool | None = None
    behavior_policy_receipt_entry_event_pending: bool | None = None
    on_policy_action_receipt_prevalidated: bool | None = None
    on_policy_action_receipt_valid: bool | None = None
    exact_on_policy_entry_outbox_record_id: str | None = None
    exact_on_policy_entry_outbox_state: str | None = None
    exact_on_policy_sealed_fill_sha256: str | None = None
    on_policy_sampling_selected: bool | None = None
    on_policy_sampling_requested: bool | None = None
    on_policy_sampling_plan_hash: str | None = None
    on_policy_sampling_plan_input_hash: str | None = None
    on_policy_sampling_lane: str | None = None
    on_policy_sampling_evidence_class: str | None = None
    on_policy_sampling_counts_as_a_plus_evidence: bool | None = None
    on_policy_sampling_routes_to_live: bool | None = None
    strategy_supply_hypothesis: bool | None = None
    entry_policy_fields_source: str | None = None
    paper_learning_lane: str | None = None
    prediction_score_source: str | None = None
    prediction_score_missing_reason: str | None = None
    candidate_id: str | None = None
    paper_policy_owner: str | None = None
    policy_fingerprint: str | None = None
    model_source: str | None = None
    selector_policy_fingerprint: str | None = None
    frozen_selector_fingerprint: str | None = None
    candidate_selected_before_outcome: bool | None = None
    candidate_selected_after_outcome: bool | None = None
    post_outcome_candidate_selection: bool | None = None
    future_labels_used_as_features: bool | None = None
    paper_opportunity_tier: str | None = None
    paper_opportunity_tier_reason: str | None = None
    explicit_paper_opportunity_tier: str | None = None
    paper_fill_allowed_source: str | None = None
    strict_paper_fill_allowed_upstream: bool | None = None
    calibration_label_purpose: str | None = None
    entry_market_state_id: str | None = None
    strategy_id: str | None = None
    strategy_family: str | None = None
    strategy_selected_mode: str | None = None
    hedge_state: str | None = None
    hedge_reason: str | None = None
    # Adaptive hedging pair linkage (2026-07-16): a hedge child position keys
    # under "{symbol}::HEDGE" and carries its parent's position id; the parent
    # carries the child fill id while hedged.
    hedge_parent_id: str | None = None
    hedge_child_id: str | None = None
    hedge_ratio: float | None = None
    hedge_entry_parent_pnl_bps: float | None = None
    # Set when the adaptive trigger marks HEDGE_PENDING; bounds how long the
    # parent's TIER_1 stop stays deferred while the hedge fill is in flight.
    hedge_pending_since: str | None = None
    drawdown_at_entry: float | None = None
    market_regime_at_entry: str | None = None
    liquidity_zone_context: dict[str, Any] | None = None
    liquidation_distance_context: dict[str, Any] | None = None
    microstructure_context: dict[str, Any] | None = None
    oi_funding_context: dict[str, Any] | None = None
    public_intel_context: dict[str, Any] | None = None
    major_move_signal_id: str | None = None
    squeeze_evidence_score: float | None = None
    squeeze_evidence_source: str | None = None
    squeeze_evidence_components: dict[str, Any] | None = None
    squeeze_evidence_unavailable_reason: str | None = None
    future_window_label_source: str | None = None
    adaptive_allocation: dict[str, Any] | None = None
    adaptive_policy_authoritative: bool = False
    adaptive_policy_action_id: str | None = None
    adaptive_policy_action_sha256: str | None = None
    adaptive_paper_policy_authorization_sha256: str | None = None
    adaptive_policy_exit_plan: dict[str, Any] | None = None
    adaptive_policy_stop_price: float | None = None
    adaptive_policy_profit_target_price: float | None = None
    adaptive_policy_max_hold_seconds: float | None = None
    adaptive_policy_time_exit_at: str | None = None
    adaptive_capital_policy_version: str | None = None
    policy_activated_at: str | None = None
    gross_notional_usd: float | None = None
    gross_notional_usd_upstream: float | None = None
    allocated_margin_usd: float | None = None
    allocated_margin_usd_upstream: float | None = None
    effective_leverage: float | None = None
    recommended_leverage: float | None = None
    leverage_source: str | None = None
    leverage_recommendation_tier: str | None = None
    leverage_exploration: bool | None = None
    recommended_margin_mode: str | None = None
    margin_mode_simulated: str | None = None
    maintenance_margin_rate: float | None = None
    maintenance_margin_cum: float | None = None
    maintenance_margin_estimate: float | None = None
    maintenance_margin_notional_usd: float | None = None
    maintenance_margin_mark_price: float | None = None
    maintenance_margin_mark_time: str | None = None
    maintenance_bracket_id: Any | None = None
    maintenance_bracket_maint_margin_ratio: Any | None = None
    maintenance_bracket_cum: Any | None = None
    maintenance_bracket_max_initial_leverage: float | None = None
    maintenance_bracket_evidence_hash: str | None = None
    maintenance_bracket_evidence_checksum_sha256: str | None = None
    maintenance_bracket_evidence_hmac_sha256: str | None = None
    maintenance_bracket_binding: Any | None = None
    maintenance_bracket_environment_id: str | None = None
    maintenance_bracket_key_id: str | None = None
    maintenance_bracket_source: str | None = None
    maintenance_bracket_available_at: str | None = None
    maintenance_bracket_expires_at: str | None = None
    maintenance_bracket_consumer_observed_at: str | None = None
    maintenance_bracket_prevalidated: bool | None = None
    maintenance_bracket_evidence_status: str | None = None
    maintenance_bracket_evidence_reason: str | None = None
    liquidation_price_estimate: float | None = None
    liquidation_buffer_bps: float | None = None
    capital_accounting_reconciled: bool = False
    capital_accounting_reconciliation_reasons: list[str] = field(default_factory=list)
    risk_budget_usd: float | None = None
    risk_budget_source: str | None = None
    stop_distance_bps: float | None = None
    expected_fees_usd: float | None = None
    expected_funding_bps: float | None = None
    funding_rate: float | None = None
    funding_interval_seconds: float | None = None
    expected_funding_usd: float | None = None
    expected_net_pnl_usd: float | None = None
    expected_max_loss_usd: float | None = None
    expected_shortfall_usd: float | None = None
    hedge_budget_usd: float | None = None
    capital_allocation_reason: str | None = None
    entry_atr_bps: float | None = None
    entry_feature_available_at: str | None = None
    entry_feature_generated_at: str | None = None
    entry_feature_cutoff: str | None = None
    entry_feature_decision_time: str | None = None
    entry_feature_source: str | None = None
    entry_feature_candle_closed_confirmed: bool | None = None
    entry_feature_unavailable_reason: str | None = None
    entry_feature_snapshot: dict[str, Any] | None = None
    entry_observed_spread_bps: float | None = None
    entry_spread_source: str | None = None
    entry_spread_unavailable_reason: str | None = None
    observed_bid: float | None = None
    observed_ask: float | None = None
    observed_spread_bps: float | None = None
    order_size: float | None = None
    order_size_usd: float | None = None
    top_book_bid_depth_usd: float | None = None
    top_book_ask_depth_usd: float | None = None
    depth_derived_price_impact_bps: float | None = None
    bid_depth_usd: float | None = None
    ask_depth_usd: float | None = None
    orderbook_depth_usd: float | None = None
    entry_orderbook_depth_usd: float | None = None
    entry_orderbook_depth_side: str | None = None
    top_of_book_depth_usd: float | None = None
    market_depth_usd: float | None = None
    orderbook_depth_source: str | None = None
    depth_utilization_pct: float | None = None
    depth_price_impact_bps: float | None = None
    depth_price_impact_source: str | None = None
    depth_price_impact_model: str | None = None
    depth_price_impact_side: str | None = None
    depth_price_impact_quantity: float | None = None
    depth_price_impact_filled_quantity: float | None = None
    depth_price_impact_fill_complete: bool | None = None
    depth_price_impact_vwap: float | None = None
    depth_price_impact_touch_price: float | None = None
    expected_slippage_bps: float | None = None
    expected_slippage_usd: float | None = None
    expected_slippage_source: str | None = None
    expected_slippage_modeled: bool | None = None
    expected_slippage_unavailable_reason: str | None = None
    correlation_exposure_pct: float | None = None
    correlation_input_source: str | None = None
    correlation_input_status: str | None = None
    correlation_pair_count: int | None = None
    correlation_diagnostics: dict[str, Any] | None = None
    expected_move_after_cost_bps: float | None = None
    realized_slippage_bps: float | None = None
    realized_slippage_usd: float | None = None
    decision_latency_ms: float | None = None
    latency_source: str | None = None
    latency_reserve_bps: float | None = None
    latency_reserve_source: str | None = None
    maker_taker_assumption: str | None = None
    maker_probability: float | None = None
    taker_probability: float | None = None
    maker_taker_probability: float | None = None
    maker_taker_probability_detail: dict[str, Any] | None = None
    maker_taker_probabilities: dict[str, Any] | None = None
    maker_taker_probability_source: str | None = None
    fee_schedule: dict[str, Any] | None = None
    fee_bps: float | None = None
    fee_bps_source: str | None = None
    fee_bps_configured_schedule: bool | None = None
    # Entry execution costs are a consumed cost basis, separate from the
    # allocator's expectation fields above.  They are denominated in USD and
    # allocated pro-rata only after a close row has passed every lifecycle
    # admission check.  This makes sequential partial closes conservative and
    # exactly conserving; a rejected close cannot silently spend the basis.
    entry_cost_accounting_version: str = PAPER_ENTRY_COST_ACCOUNTING_VERSION
    entry_fees_incurred_usd: float | None = None
    entry_fees_remaining_usd: float | None = None
    entry_fees_allocated_to_closes_usd: float = 0.0
    entry_fee_fallback_bps_per_side: float | None = None
    entry_slippage_incurred_usd: float | None = None
    entry_slippage_remaining_usd: float | None = None
    entry_slippage_allocated_to_closes_usd: float = 0.0
    entry_slippage_fallback_bps_per_side: float | None = None
    entry_fee_cost_sources: list[str] = field(default_factory=list)
    entry_slippage_cost_sources: list[str] = field(default_factory=list)
    entry_cost_basis_status: str = "MISSING_ENTRY_COST_BASIS"
    holding_period_funding_bps: float | None = None
    holding_period_funding_source: str | None = None
    partial_fill_count: int | None = None
    partial_fill_estimate: dict[str, Any] | None = None
    partial_fill_probability: float | None = None
    partial_fill_adjustment_bps: float | None = None
    partial_fills: list[dict[str, Any]] | None = None
    fill_count: int | None = None
    all_partial_fills: list[dict[str, Any]] | None = None
    partial_fill_plan: dict[str, Any] | list[dict[str, Any]] | None = None
    execution_probability: float | None = None
    mark_index_divergence_bps: float | None = None
    mark_index_divergence: float | None = None
    mark_index_source: str | None = None
    mark_index_available_at: str | None = None
    mark_price: float | None = None
    index_price: float | None = None
    cost_source: str | None = None
    cost_source_timestamp: str | None = None
    source_timestamp: str | None = None
    cost_evidence_freshness_ms: float | None = None
    cost_evidence_source_fields: dict[str, Any] | None = None
    runtime_cost_capture_source: str | None = None
    runtime_cost_capture_status: str | None = None
    runtime_cost_capture_required_fields: list[str] | None = None
    runtime_cost_capture_missing_fields: list[str] | None = None
    runtime_cost_capture_explained_missing_fields: list[str] | None = None
    runtime_cost_capture_unexplained_missing_fields: list[str] | None = None
    runtime_cost_capture_order_cost_applicable: bool | None = None
    runtime_cost_capture_no_order_reason: str | None = None
    runtime_cost_capture_temporal_reject_reasons: list[str] | None = None
    fallback_cost_flag: bool | None = None
    fallback: bool | None = None
    production_grade_cost_flag: bool | None = None
    production_grade_cost_evidence: bool | None = None
    estimated_production_cost: float | None = None
    estimated_production_cost_bps: float | None = None
    counts_as_production_grade_training_evidence: bool | None = None
    fill_ids: list[str] = field(default_factory=list)
    best_favorable_price: float | None = None
    worst_adverse_price: float | None = None
    intra_trade_high_price: float | None = None
    intra_trade_low_price: float | None = None
    mfe_bps: float = 0.0
    mae_bps: float = 0.0
    mfe_usd: float = 0.0
    mae_usd: float = 0.0
    trailing_activation_price: float | None = None
    trailing_activation_time: str | None = None
    trailing_stop_price: float | None = None
    trailing_stop_history: list[dict[str, Any]] = field(default_factory=list)
    last_mark_price: float | None = None
    last_mark_est: str | None = None
    realized_pnl: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.net_quantity * self.avg_entry_price)

    def entry_cost_allocation(
        self,
        *,
        close_quantity: float,
        fallback_fee_bps_per_side: float,
        fallback_slippage_bps_per_side: float,
    ) -> dict[str, Any]:
        """Return (without consuming) entry costs attributable to a close.

        Complete entry-time evidence is allocated from the remaining USD cost
        basis.  Legacy/incomplete positions use the lifecycle's explicitly
        per-side fallback rates on the close-specific entry notional and are
        marked fallback, so downstream training evidence can fail closed.
        """

        if self.net_quantity <= 0.0 or close_quantity <= 0.0:
            raise ValueError("INVALID_ENTRY_COST_CLOSE_QUANTITY")
        quantity = min(float(close_quantity), float(self.net_quantity))
        allocation_fraction = min(1.0, quantity / float(self.net_quantity))
        is_final_close = math.isclose(
            quantity,
            float(self.net_quantity),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        entry_notional_usd = abs(quantity * self.avg_entry_price)

        if self.entry_fees_remaining_usd is None:
            entry_fee_usd = (
                entry_notional_usd
                * max(0.0, float(fallback_fee_bps_per_side))
                / 10000.0
            )
            fee_source = "LIFECYCLE_PER_SIDE_FEE_FALLBACK"
            fee_fallback = True
        else:
            entry_fee_usd = (
                float(self.entry_fees_remaining_usd)
                if is_final_close
                else float(self.entry_fees_remaining_usd) * allocation_fraction
            )
            fee_source = "+".join(self.entry_fee_cost_sources) or "ENTRY_USD_COST_BASIS"
            fee_fallback = bool(
                self.entry_fee_fallback_bps_per_side is not None
                or any("FALLBACK" in source for source in self.entry_fee_cost_sources)
            )

        if self.entry_slippage_remaining_usd is None:
            entry_slippage_usd = (
                entry_notional_usd
                * max(0.0, float(fallback_slippage_bps_per_side))
                / 10000.0
            )
            slippage_source = "LIFECYCLE_PER_SIDE_SLIPPAGE_FALLBACK"
            slippage_fallback = True
        else:
            entry_slippage_usd = (
                float(self.entry_slippage_remaining_usd)
                if is_final_close
                else float(self.entry_slippage_remaining_usd) * allocation_fraction
            )
            slippage_source = (
                "+".join(self.entry_slippage_cost_sources)
                or "ENTRY_USD_SLIPPAGE_COST_BASIS"
            )
            slippage_fallback = bool(
                self.entry_slippage_fallback_bps_per_side is not None
                or any(
                    "FALLBACK" in source
                    for source in self.entry_slippage_cost_sources
                )
            )

        return {
            "entry_cost_accounting_version": self.entry_cost_accounting_version,
            "entry_cost_allocation_method": (
                "PRO_RATA_BY_CLOSED_QUANTITY_WITH_FINAL_CLOSE_REMAINDER"
            ),
            "entry_cost_allocation_fraction_of_pre_close_position": allocation_fraction,
            "entry_cost_pre_close_quantity": float(self.net_quantity),
            "entry_cost_closed_quantity": quantity,
            "entry_cost_is_final_close": is_final_close,
            "entry_fee_usd": max(0.0, entry_fee_usd),
            "entry_fee_source": fee_source,
            "entry_fee_fallback": fee_fallback,
            "entry_fee_fallback_bps_per_side": (
                max(
                    0.0,
                    float(
                        self.entry_fee_fallback_bps_per_side
                        if self.entry_fee_fallback_bps_per_side is not None
                        else fallback_fee_bps_per_side
                    ),
                )
                if fee_fallback
                else None
            ),
            "entry_slippage_usd": max(0.0, entry_slippage_usd),
            "entry_slippage_source": slippage_source,
            "entry_slippage_fallback": slippage_fallback,
            "entry_slippage_fallback_bps_per_side": (
                max(
                    0.0,
                    float(
                        self.entry_slippage_fallback_bps_per_side
                        if self.entry_slippage_fallback_bps_per_side is not None
                        else fallback_slippage_bps_per_side
                    ),
                )
                if slippage_fallback
                else None
            ),
            "entry_cost_basis_status": self.entry_cost_basis_status,
        }

    def consume_entry_cost_allocation(self, allocation: dict[str, Any]) -> None:
        """Consume a previously calculated allocation after close admission."""

        if (
            allocation.get("entry_cost_accounting_version")
            != self.entry_cost_accounting_version
        ):
            raise ValueError("ENTRY_COST_ACCOUNTING_VERSION_MISMATCH")
        expected = self.entry_cost_allocation(
            close_quantity=float(allocation.get("entry_cost_closed_quantity") or 0.0),
            fallback_fee_bps_per_side=float(
                allocation.get("entry_fee_fallback_bps_per_side") or 0.0
            ),
            fallback_slippage_bps_per_side=float(
                allocation.get("entry_slippage_fallback_bps_per_side") or 0.0
            ),
        )
        for cost_field in ("entry_fee_usd", "entry_slippage_usd"):
            if allocation.get(cost_field) is None or not math.isclose(
                float(allocation[cost_field]),
                float(expected[cost_field]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    f"ENTRY_COST_ALLOCATION_MISMATCH:{cost_field}"
                )

        # Validate both prospective ledgers before mutating either one.  This
        # keeps fee and slippage consumption atomic and enforces the accounting
        # invariant incurred = remaining + allocated across every partial close.
        updates: dict[str, tuple[float, float, float]] = {}
        if self.entry_fees_remaining_usd is None:
            fallback_bps = coerce_float(
                allocation.get("entry_fee_fallback_bps_per_side")
            )
            if fallback_bps is None or fallback_bps < 0.0:
                raise ValueError("ENTRY_FEE_FALLBACK_RATE_MISSING")
            if self.entry_fees_allocated_to_closes_usd != 0.0:
                raise ValueError("ENTRY_FEE_PARTIAL_LEDGER_MISSING_REMAINING_BASIS")
            full_fee_basis = (
                float(self.net_quantity)
                * float(self.avg_entry_price)
                * fallback_bps
                / 10000.0
            )
            consumed_fee = float(allocation["entry_fee_usd"])
            next_fee_remaining = max(0.0, full_fee_basis - consumed_fee)
            if not math.isclose(
                full_fee_basis,
                next_fee_remaining + consumed_fee,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("ENTRY_FEE_FALLBACK_BASIS_CONSERVATION_FAILED")
            updates["fee"] = (
                full_fee_basis,
                next_fee_remaining,
                consumed_fee,
            )
        else:
            if self.entry_fees_incurred_usd is None:
                raise ValueError("ENTRY_FEE_COST_BASIS_INCURRED_MISSING")
            consumed_fee = float(allocation["entry_fee_usd"])
            next_fee_remaining = max(
                0.0,
                float(self.entry_fees_remaining_usd) - consumed_fee,
            )
            next_fee_allocated = (
                float(self.entry_fees_allocated_to_closes_usd) + consumed_fee
            )
            if not math.isclose(
                float(self.entry_fees_incurred_usd),
                next_fee_remaining + next_fee_allocated,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("ENTRY_FEE_COST_BASIS_CONSERVATION_FAILED")
            updates["fee"] = (
                float(self.entry_fees_incurred_usd),
                next_fee_remaining,
                next_fee_allocated,
            )
        if self.entry_slippage_remaining_usd is None:
            fallback_bps = coerce_float(
                allocation.get("entry_slippage_fallback_bps_per_side")
            )
            if fallback_bps is None or fallback_bps < 0.0:
                raise ValueError("ENTRY_SLIPPAGE_FALLBACK_RATE_MISSING")
            if self.entry_slippage_allocated_to_closes_usd != 0.0:
                raise ValueError(
                    "ENTRY_SLIPPAGE_PARTIAL_LEDGER_MISSING_REMAINING_BASIS"
                )
            full_slippage_basis = (
                float(self.net_quantity)
                * float(self.avg_entry_price)
                * fallback_bps
                / 10000.0
            )
            consumed_slippage = float(allocation["entry_slippage_usd"])
            next_slippage_remaining = max(
                0.0, full_slippage_basis - consumed_slippage
            )
            if not math.isclose(
                full_slippage_basis,
                next_slippage_remaining + consumed_slippage,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError(
                    "ENTRY_SLIPPAGE_FALLBACK_BASIS_CONSERVATION_FAILED"
                )
            updates["slippage"] = (
                full_slippage_basis,
                next_slippage_remaining,
                consumed_slippage,
            )
        else:
            if self.entry_slippage_incurred_usd is None:
                raise ValueError("ENTRY_SLIPPAGE_COST_BASIS_INCURRED_MISSING")
            consumed_slippage = float(allocation["entry_slippage_usd"])
            next_slippage_remaining = max(
                0.0,
                float(self.entry_slippage_remaining_usd) - consumed_slippage,
            )
            next_slippage_allocated = (
                float(self.entry_slippage_allocated_to_closes_usd)
                + consumed_slippage
            )
            if not math.isclose(
                float(self.entry_slippage_incurred_usd),
                next_slippage_remaining + next_slippage_allocated,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("ENTRY_SLIPPAGE_COST_BASIS_CONSERVATION_FAILED")
            updates["slippage"] = (
                float(self.entry_slippage_incurred_usd),
                next_slippage_remaining,
                next_slippage_allocated,
            )

        if "fee" in updates:
            (
                self.entry_fees_incurred_usd,
                self.entry_fees_remaining_usd,
                self.entry_fees_allocated_to_closes_usd,
            ) = updates["fee"]
            if allocation.get("entry_fee_fallback") is True:
                self.entry_fee_fallback_bps_per_side = float(
                    allocation["entry_fee_fallback_bps_per_side"]
                )
                self.entry_fee_cost_sources = list(
                    dict.fromkeys(
                        [
                            *self.entry_fee_cost_sources,
                            str(allocation.get("entry_fee_source")),
                        ]
                    )
                )
        if "slippage" in updates:
            (
                self.entry_slippage_incurred_usd,
                self.entry_slippage_remaining_usd,
                self.entry_slippage_allocated_to_closes_usd,
            ) = updates["slippage"]
            if allocation.get("entry_slippage_fallback") is True:
                self.entry_slippage_fallback_bps_per_side = float(
                    allocation["entry_slippage_fallback_bps_per_side"]
                )
                self.entry_slippage_cost_sources = list(
                    dict.fromkeys(
                        [
                            *self.entry_slippage_cost_sources,
                            str(allocation.get("entry_slippage_source")),
                        ]
                    )
                )
        if (
            self.entry_fee_fallback_bps_per_side is not None
            or self.entry_slippage_fallback_bps_per_side is not None
        ):
            self.entry_cost_basis_status = (
                "COMPLETE_MATERIALIZED_FALLBACK_ENTRY_COST_BASIS"
            )

    def _sync_adaptive_allocation_capital(self) -> None:
        # ``adaptive_allocation`` is immutable upstream decision provenance.
        # Current/aggregated capital is emitted in the position's top-level
        # canonical fields; rewriting the allocator record would destroy the
        # original recommendation and break historical audit compatibility.
        return

    def _maintenance_bracket_is_usable(self) -> bool:
        return str(self.maintenance_bracket_evidence_status or "").startswith("READY")

    def _set_maintenance_unknown(self, *, status: str, reason: str) -> None:
        """Invalidate active risk math while retaining prior lineage for audit."""

        self.maintenance_margin_rate = None
        self.maintenance_margin_cum = None
        self.maintenance_margin_estimate = None
        self.liquidation_price_estimate = None
        self.liquidation_buffer_bps = None
        self.maintenance_bracket_evidence_status = status
        self.maintenance_bracket_evidence_reason = reason
        self.capital_accounting_reconciled = True
        self.capital_accounting_reconciliation_reasons = list(
            dict.fromkeys([*self.capital_accounting_reconciliation_reasons, reason])
        )

    def _capture_maintenance_bracket_lineage(self, evidence: dict[str, Any]) -> None:
        raw_ratio = first_present(
            evidence.get("maint_margin_ratio"),
            evidence.get("maintMarginRatio"),
            evidence.get("maintenance_margin_rate"),
        )
        raw_cum = first_present(
            evidence.get("cum"),
            evidence.get("maintenance_margin_cum"),
        )
        self.maintenance_bracket_id = first_present(
            evidence.get("bracket_id"),
            evidence.get("selected_bracket"),
            evidence.get("bracket"),
        )
        self.maintenance_bracket_maint_margin_ratio = raw_ratio
        self.maintenance_bracket_cum = raw_cum
        self.maintenance_bracket_max_initial_leverage = first_number(
            evidence.get("max_initial_leverage"),
            evidence.get("initialLeverage"),
        )
        checksum = first_present(
            evidence.get("evidence_checksum"),
            evidence.get("evidence_checksum_sha256"),
            evidence.get("evidence_sha256"),
        )
        self.maintenance_bracket_evidence_hash = first_present(
            evidence.get("evidence_hash"),
            checksum,
        )
        self.maintenance_bracket_evidence_checksum_sha256 = (
            str(checksum) if checksum not in (None, "") else None
        )
        hmac_value = first_present(
            evidence.get("hmac"),
            evidence.get("evidence_hmac"),
            evidence.get("evidence_hmac_sha256"),
        )
        self.maintenance_bracket_evidence_hmac_sha256 = (
            str(hmac_value) if hmac_value not in (None, "") else None
        )
        self.maintenance_bracket_binding = first_present(
            evidence.get("binding"),
            evidence.get("evidence_binding"),
            evidence.get("account_binding_id"),
        )
        environment_id = evidence.get("environment_id")
        self.maintenance_bracket_environment_id = (
            str(environment_id) if environment_id not in (None, "") else None
        )
        key_id = evidence.get("key_id")
        self.maintenance_bracket_key_id = (
            str(key_id) if key_id not in (None, "") else None
        )
        source = evidence.get("source")
        self.maintenance_bracket_source = (
            str(source) if source not in (None, "") else None
        )
        self.maintenance_bracket_available_at = (
            str(evidence.get("available_at"))
            if evidence.get("available_at") not in (None, "")
            else None
        )
        self.maintenance_bracket_expires_at = (
            str(evidence.get("expires_at"))
            if evidence.get("expires_at") not in (None, "")
            else None
        )
        observed_at = evidence.get("consumer_observed_at")
        self.maintenance_bracket_consumer_observed_at = (
            str(observed_at) if observed_at not in (None, "") else None
        )
        self.maintenance_bracket_prevalidated = evidence.get("prevalidated") is True

    def apply_maintenance_bracket_evidence(
        self,
        evidence: dict[str, Any] | None,
        *,
        mark_price: float,
        mark_time: str,
    ) -> None:
        """Apply prevalidated account-bound evidence to the whole net position.

        The lifecycle still validates the evidence's structural and temporal
        envelope.  Missing, future-dated, expired, unbound, or malformed
        evidence makes maintenance and liquidation unknown; it never falls
        back to a constant maintenance rate.
        """

        mark = coerce_float(mark_price)
        if mark is None or not math.isfinite(mark) or mark <= 0:
            self.maintenance_margin_notional_usd = None
            self.maintenance_margin_mark_price = None
            self.maintenance_margin_mark_time = None
            self._set_maintenance_unknown(
                status="MARK_PRICE_INVALID",
                reason="MAINTENANCE_MARK_PRICE_INVALID_FAIL_CLOSED",
            )
            return
        self.maintenance_margin_notional_usd = abs(self.net_quantity) * mark
        self.maintenance_margin_mark_price = mark
        self.maintenance_margin_mark_time = mark_time
        if not isinstance(evidence, dict):
            self._set_maintenance_unknown(
                status="MISSING_FOR_CURRENT_MARK",
                reason="MAINTENANCE_BRACKET_EVIDENCE_MISSING_FOR_CURRENT_MARK",
            )
            return

        self._capture_maintenance_bracket_lineage(evidence)
        mark_dt = parse_aware_utc(mark_time)
        available_dt = parse_aware_utc(self.maintenance_bracket_available_at)
        expires_dt = parse_aware_utc(self.maintenance_bracket_expires_at)
        observed_dt = parse_aware_utc(self.maintenance_bracket_consumer_observed_at)
        ratio = coerce_float(self.maintenance_bracket_maint_margin_ratio)
        cum = coerce_float(self.maintenance_bracket_cum)
        max_leverage = coerce_float(self.maintenance_bracket_max_initial_leverage)
        binding_present = self.maintenance_bracket_binding not in (None, "", {}, [])
        checksum = self.maintenance_bracket_evidence_checksum_sha256
        evidence_hmac = self.maintenance_bracket_evidence_hmac_sha256
        evidence_hash = self.maintenance_bracket_evidence_hash
        environment_id = self.maintenance_bracket_environment_id
        key_id = self.maintenance_bracket_key_id
        binding_text = str(self.maintenance_bracket_binding or "")
        required_missing = [
            name
            for name, present in (
                ("prevalidated", evidence.get("prevalidated") is True),
                ("bracket_id", self.maintenance_bracket_id not in (None, "")),
                ("evidence_hash", self.maintenance_bracket_evidence_hash not in (None, "")),
                ("evidence_checksum_sha256", checksum not in (None, "")),
                ("evidence_hmac_sha256", evidence_hmac not in (None, "")),
                ("binding", binding_present),
                ("environment_id", environment_id not in (None, "")),
                ("key_id", key_id not in (None, "")),
                ("source", self.maintenance_bracket_source not in (None, "")),
                ("mark_time", mark_dt is not None),
                ("available_at", available_dt is not None),
                ("expires_at", expires_dt is not None),
                ("consumer_observed_at", observed_dt is not None),
            )
            if not present
        ]
        provenance_invalid = (
            not _is_lower_sha256_hex(checksum)
            or not _is_lower_sha256_hex(evidence_hmac)
            or evidence_hash != checksum
            or environment_id not in _KNOWN_BINANCE_USDM_ENVIRONMENTS
            or not binding_text.startswith(f"{environment_id}:")
            or len(binding_text.split(":")) != 3
            or not isinstance(key_id, str)
            or not key_id.strip()
            or self.maintenance_bracket_source != _BINANCE_USDM_BRACKET_SOURCE
        )
        numeric_invalid = (
            ratio is None
            or not math.isfinite(ratio)
            or not 0.0 < ratio < 1.0
            or cum is None
            or not math.isfinite(cum)
            or cum < 0.0
            or max_leverage is None
            or not math.isfinite(max_leverage)
            or max_leverage < 1.0
        )
        if required_missing or numeric_invalid or provenance_invalid:
            detail = (
                ",".join(required_missing)
                if required_missing
                else (
                    "numeric_fields" if numeric_invalid else "provenance_fields"
                )
            )
            self._set_maintenance_unknown(
                status="INVALID",
                reason=f"MAINTENANCE_BRACKET_EVIDENCE_INVALID:{detail}",
            )
            return
        assert (
            mark_dt is not None
            and available_dt is not None
            and expires_dt is not None
            and observed_dt is not None
        )
        if available_dt >= expires_dt:
            self._set_maintenance_unknown(
                status="INVALID_TIMESTAMP_ORDER",
                reason="MAINTENANCE_BRACKET_AVAILABLE_NOT_BEFORE_EXPIRY",
            )
            return
        if available_dt > mark_dt:
            self._set_maintenance_unknown(
                status="FUTURE_AT_MARK",
                reason="MAINTENANCE_BRACKET_AVAILABLE_AFTER_MARK_TIME",
            )
            return
        if expires_dt <= mark_dt:
            self._set_maintenance_unknown(
                status="STALE_AT_MARK",
                reason="MAINTENANCE_BRACKET_EXPIRED_AT_MARK_TIME",
            )
            return
        if observed_dt < available_dt or observed_dt > mark_dt:
            self._set_maintenance_unknown(
                status="INVALID_CONSUMER_OBSERVED_AT",
                reason="MAINTENANCE_BRACKET_CONSUMER_OBSERVED_AT_INVALID",
            )
            return

        self.maintenance_margin_rate = ratio
        self.maintenance_margin_cum = cum
        self.maintenance_bracket_evidence_status = "READY"
        self.maintenance_bracket_evidence_reason = None
        self.recompute_capital_accounting()

    def _copy_maintenance_bracket_from(self, source: PaperNetPosition) -> None:
        for field_name in (
            "maintenance_margin_rate",
            "maintenance_margin_cum",
            "maintenance_bracket_id",
            "maintenance_bracket_maint_margin_ratio",
            "maintenance_bracket_cum",
            "maintenance_bracket_max_initial_leverage",
            "maintenance_bracket_evidence_hash",
            "maintenance_bracket_evidence_checksum_sha256",
            "maintenance_bracket_evidence_hmac_sha256",
            "maintenance_bracket_binding",
            "maintenance_bracket_environment_id",
            "maintenance_bracket_key_id",
            "maintenance_bracket_source",
            "maintenance_bracket_available_at",
            "maintenance_bracket_expires_at",
            "maintenance_bracket_consumer_observed_at",
            "maintenance_bracket_prevalidated",
        ):
            setattr(self, field_name, getattr(source, field_name))

    def recompute_capital_accounting(self) -> None:
        """Reconcile entry-basis capital and mark-basis maintenance separately."""
        gross_notional = self.notional
        leverage = coerce_float(self.effective_leverage)
        if gross_notional <= 0 or leverage is None or leverage < 1.0:
            raise ValueError("INVALID_CURRENT_POSITION_CAPITAL_INPUTS")
        simulated_margin_mode = str(
            self.margin_mode_simulated or "isolated_paper_simulated"
        ).strip().lower()
        if simulated_margin_mode not in {"isolated", "isolated_paper_simulated"}:
            self.margin_mode_simulated = "isolated_paper_simulated"
            reason = (
                "CROSS_MARGIN_SIMULATION_DOWNGRADED_NO_ACCOUNT_WIDE_"
                "LIQUIDATION_MODEL"
            )
            if reason not in self.capital_accounting_reconciliation_reasons:
                self.capital_accounting_reconciliation_reasons.append(reason)
            self.capital_accounting_reconciled = True
        allocated_margin = gross_notional / leverage
        self.gross_notional_usd = gross_notional
        self.allocated_margin_usd = allocated_margin
        self.effective_leverage = leverage
        maintenance_rate = coerce_float(self.maintenance_margin_rate)
        maintenance_cum = coerce_float(self.maintenance_margin_cum)
        maintenance_notional = coerce_float(self.maintenance_margin_notional_usd)
        if (
            not self._maintenance_bracket_is_usable()
            or
            maintenance_rate is None
            or not math.isfinite(maintenance_rate)
            or not 0.0 < maintenance_rate < 1.0
            or maintenance_cum is None
            or not math.isfinite(maintenance_cum)
            or maintenance_cum < 0.0
            or maintenance_notional is None
            or not math.isfinite(maintenance_notional)
            or maintenance_notional <= 0.0
        ):
            self._set_maintenance_unknown(
                status=self.maintenance_bracket_evidence_status or "UNUSABLE",
                reason=(
                    self.maintenance_bracket_evidence_reason
                    or "MAINTENANCE_BRACKET_EVIDENCE_UNUSABLE_FAIL_CLOSED"
                ),
            )
            self._sync_adaptive_allocation_capital()
            return
        maintenance_amount = max(
            0.0,
            maintenance_notional * maintenance_rate - maintenance_cum,
        )
        liquidation_price = _liquidation_estimate(
            side=self.side,
            entry_price=self.avg_entry_price,
            quantity=abs(self.net_quantity),
            allocated_margin=allocated_margin,
            maintenance_rate=maintenance_rate,
            maintenance_cum=maintenance_cum,
        )
        if liquidation_price is None:
            self._set_maintenance_unknown(
                status="LIQUIDATION_ESTIMATE_FAILED",
                reason="LIQUIDATION_PRICE_RECOMPUTE_FAILED_FAIL_CLOSED",
            )
            self._sync_adaptive_allocation_capital()
            return
        self.maintenance_margin_estimate = maintenance_amount
        self.liquidation_price_estimate = liquidation_price
        self.liquidation_buffer_bps = _liquidation_buffer_bps(
            side=self.side,
            entry_price=self.avg_entry_price,
            liquidation_price=liquidation_price,
        )
        self._sync_adaptive_allocation_capital()

    def apply_same_side_fill(
        self,
        *,
        fill_id: str,
        quantity: float,
        price: float,
        incoming_position: PaperNetPosition | None = None,
    ) -> None:
        """Aggregate a validated same-side fill without stale capital fields.

        The caller must provide the canonical position derived from the incoming
        fill.  Missing or internally inconsistent capital evidence fails before
        this position is mutated.
        """
        if incoming_position is None:
            raise ValueError("MISSING_INCOMING_POSITION_CAPITAL_EVIDENCE")
        if incoming_position.symbol != self.symbol or incoming_position.side != self.side:
            raise ValueError("INCOMING_POSITION_IDENTITY_MISMATCH")
        if quantity <= 0 or price <= 0:
            raise ValueError("INVALID_SAME_SIDE_FILL_QUANTITY_OR_PRICE")
        prior_qty = self.net_quantity
        new_qty = prior_qty + quantity
        if new_qty <= 0:
            raise ValueError("INVALID_SAME_SIDE_NET_QUANTITY")

        prior_notional = self.notional
        incoming_notional = abs(quantity * price)
        prior_leverage = coerce_float(self.effective_leverage)
        incoming_leverage = coerce_float(incoming_position.effective_leverage)
        prior_margin = coerce_float(self.allocated_margin_usd)
        incoming_margin = coerce_float(incoming_position.allocated_margin_usd)
        if (
            prior_notional <= 0
            or incoming_notional <= 0
            or prior_leverage is None
            or incoming_leverage is None
            or prior_leverage < 1.0
            or incoming_leverage < 1.0
            or prior_margin is None
            or incoming_margin is None
            or prior_margin <= 0
            or incoming_margin <= 0
        ):
            raise ValueError("INVALID_SAME_SIDE_CAPITAL_EVIDENCE")
        if not _accounting_values_match(prior_margin * prior_leverage, prior_notional):
            raise ValueError("EXISTING_POSITION_MARGIN_LEVERAGE_MISMATCH")
        if not _accounting_values_match(
            incoming_margin * incoming_leverage,
            incoming_notional,
        ):
            raise ValueError("INCOMING_FILL_MARGIN_LEVERAGE_MISMATCH")

        def cost_ledger_state(
            *,
            label: str,
            incurred: float | None,
            remaining: float | None,
            allocated: float | None,
        ) -> str:
            parsed_incurred = coerce_float(incurred)
            parsed_remaining = coerce_float(remaining)
            parsed_allocated = coerce_float(allocated)
            if parsed_allocated is None:
                parsed_allocated = 0.0
            values = (parsed_incurred, parsed_remaining, parsed_allocated)
            if any(
                value is not None and (not math.isfinite(value) or value < 0.0)
                for value in values
            ):
                raise ValueError(f"{label}_ENTRY_COST_LEDGER_INVALID")
            if (
                parsed_incurred is None
                and parsed_remaining is None
                and parsed_allocated == 0.0
            ):
                return "PRISTINE_MISSING"
            if parsed_incurred is None or parsed_remaining is None:
                raise ValueError(f"{label}_ENTRY_COST_LEDGER_INCOMPLETE")
            if not math.isclose(
                parsed_incurred,
                parsed_remaining + parsed_allocated,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError(f"{label}_ENTRY_COST_LEDGER_NOT_CONSERVED")
            return "COMPLETE"

        for label, current_values, incoming_values in (
            (
                "FEE",
                (
                    self.entry_fees_incurred_usd,
                    self.entry_fees_remaining_usd,
                    self.entry_fees_allocated_to_closes_usd,
                ),
                (
                    incoming_position.entry_fees_incurred_usd,
                    incoming_position.entry_fees_remaining_usd,
                    incoming_position.entry_fees_allocated_to_closes_usd,
                ),
            ),
            (
                "SLIPPAGE",
                (
                    self.entry_slippage_incurred_usd,
                    self.entry_slippage_remaining_usd,
                    self.entry_slippage_allocated_to_closes_usd,
                ),
                (
                    incoming_position.entry_slippage_incurred_usd,
                    incoming_position.entry_slippage_remaining_usd,
                    incoming_position.entry_slippage_allocated_to_closes_usd,
                ),
            ),
        ):
            current_state = cost_ledger_state(
                label=f"EXISTING_{label}",
                incurred=current_values[0],
                remaining=current_values[1],
                allocated=current_values[2],
            )
            incoming_state = cost_ledger_state(
                label=f"INCOMING_{label}",
                incurred=incoming_values[0],
                remaining=incoming_values[1],
                allocated=incoming_values[2],
            )
            if current_state != incoming_state:
                raise ValueError(
                    f"MIXED_{label}_ENTRY_COST_BASIS_WOULD_DESTROY_EXACT_LEDGER"
                )

        def combine_complete_usd(
            current: float | None,
            incoming: float | None,
        ) -> float | None:
            if current is None or incoming is None:
                return None
            return max(0.0, float(current)) + max(0.0, float(incoming))

        aggregate_entry_fees_incurred = combine_complete_usd(
            self.entry_fees_incurred_usd,
            incoming_position.entry_fees_incurred_usd,
        )
        aggregate_entry_fees_remaining = combine_complete_usd(
            self.entry_fees_remaining_usd,
            incoming_position.entry_fees_remaining_usd,
        )
        aggregate_entry_slippage_incurred = combine_complete_usd(
            self.entry_slippage_incurred_usd,
            incoming_position.entry_slippage_incurred_usd,
        )
        aggregate_entry_slippage_remaining = combine_complete_usd(
            self.entry_slippage_remaining_usd,
            incoming_position.entry_slippage_remaining_usd,
        )

        total_notional = prior_notional + incoming_notional
        total_margin = prior_margin + incoming_margin
        aggregate_leverage = total_notional / total_margin
        prior_recommended = coerce_float(self.recommended_leverage)
        incoming_recommended = coerce_float(incoming_position.recommended_leverage)
        aggregate_recommended = None
        if (
            prior_recommended is not None
            and incoming_recommended is not None
            and prior_recommended > 0
            and incoming_recommended > 0
        ):
            recommended_margin = (
                prior_notional / prior_recommended
                + incoming_notional / incoming_recommended
            )
            if recommended_margin > 0:
                aggregate_recommended = total_notional / recommended_margin

        new_avg_entry = (
            (self.avg_entry_price * prior_qty) + (price * quantity)
        ) / new_qty
        self.avg_entry_price = new_avg_entry
        self.net_quantity = new_qty
        self.gross_notional_usd = total_notional
        self.allocated_margin_usd = total_margin
        self.effective_leverage = aggregate_leverage
        self.entry_fees_incurred_usd = aggregate_entry_fees_incurred
        self.entry_fees_remaining_usd = aggregate_entry_fees_remaining
        self.entry_fees_allocated_to_closes_usd += (
            incoming_position.entry_fees_allocated_to_closes_usd
        )
        self.entry_slippage_incurred_usd = aggregate_entry_slippage_incurred
        self.entry_slippage_remaining_usd = aggregate_entry_slippage_remaining
        self.entry_slippage_allocated_to_closes_usd += (
            incoming_position.entry_slippage_allocated_to_closes_usd
        )
        self.entry_fee_cost_sources = list(
            dict.fromkeys(
                [
                    *self.entry_fee_cost_sources,
                    *incoming_position.entry_fee_cost_sources,
                ]
            )
        )
        self.entry_slippage_cost_sources = list(
            dict.fromkeys(
                [
                    *self.entry_slippage_cost_sources,
                    *incoming_position.entry_slippage_cost_sources,
                ]
            )
        )
        self.entry_cost_basis_status = (
            "COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS"
            if (
                aggregate_entry_fees_remaining is not None
                and aggregate_entry_slippage_remaining is not None
            )
            else "INCOMPLETE_ENTRY_FEE_OR_SLIPPAGE_USD_BASIS"
        )
        if aggregate_recommended is not None:
            self.recommended_leverage = aggregate_recommended
        self.capital_accounting_reconciled = bool(
            self.capital_accounting_reconciled
            or incoming_position.capital_accounting_reconciled
        )
        self.capital_accounting_reconciliation_reasons = list(
            dict.fromkeys(
                [
                    *self.capital_accounting_reconciliation_reasons,
                    *incoming_position.capital_accounting_reconciliation_reasons,
                    "SAME_SIDE_CAPITAL_RECOMPUTED_FROM_EXECUTED_FILLS",
                    "SAME_SIDE_MAINTENANCE_NEVER_WEIGHTED_PER_FILL",
                ]
            )
        )
        # Until the next whole-position mark selects the exact tier, retain
        # only the more conservative of two complete fill-bound brackets.
        self.maintenance_margin_notional_usd = abs(new_qty) * price
        self.maintenance_margin_mark_price = price
        self.maintenance_margin_mark_time = first_present(
            incoming_position.entry_generation_time_utc,
            incoming_position.opened_est,
        )
        if self._maintenance_bracket_is_usable() and incoming_position._maintenance_bracket_is_usable():
            candidates = (self, incoming_position)

            def maintenance_for(candidate: PaperNetPosition) -> float:
                rate = coerce_float(candidate.maintenance_margin_rate) or 0.0
                cum_value = coerce_float(candidate.maintenance_margin_cum) or 0.0
                return max(0.0, self.maintenance_margin_notional_usd * rate - cum_value)

            selected = max(
                candidates,
                key=lambda candidate: (
                    maintenance_for(candidate),
                    coerce_float(candidate.maintenance_margin_rate) or 0.0,
                ),
            )
            self._copy_maintenance_bracket_from(selected)
            self.maintenance_bracket_evidence_status = "READY_CONSERVATIVE_SAME_SIDE_FILL"
            self.maintenance_bracket_evidence_reason = (
                "CONSERVATIVE_FILL_BRACKET_PENDING_WHOLE_POSITION_MARK_RESELECTION"
            )
        else:
            self._set_maintenance_unknown(
                status="SAME_SIDE_FILL_EVIDENCE_INCOMPLETE",
                reason="SAME_SIDE_FILL_MAINTENANCE_BRACKET_EVIDENCE_INCOMPLETE",
            )
        self.recompute_capital_accounting()
        if fill_id not in self.fill_ids:
            self.fill_ids.append(fill_id)

    def update_mark(
        self,
        *,
        mark_price: float | None,
        mark_time: str,
        maintenance_bracket_evidence: dict[str, Any] | None | object = _MAINTENANCE_EVIDENCE_UNSET,
    ) -> None:
        if mark_price is None or mark_price <= 0:
            return
        self.last_mark_price = mark_price
        self.last_mark_est = utc_to_est_iso(mark_time) or mark_time
        self.intra_trade_high_price = max(self.intra_trade_high_price or self.avg_entry_price, mark_price)
        self.intra_trade_low_price = min(self.intra_trade_low_price or self.avg_entry_price, mark_price)
        if self.best_favorable_price is None:
            self.best_favorable_price = self.avg_entry_price
        if self.worst_adverse_price is None:
            self.worst_adverse_price = self.avg_entry_price
        if self.side == "long":
            self.best_favorable_price = max(self.best_favorable_price, mark_price)
            self.worst_adverse_price = min(self.worst_adverse_price, mark_price)
            favorable_delta = max(0.0, (self.intra_trade_high_price or self.avg_entry_price) - self.avg_entry_price)
            adverse_delta = max(0.0, self.avg_entry_price - (self.intra_trade_low_price or self.avg_entry_price))
        else:
            self.best_favorable_price = min(self.best_favorable_price, mark_price)
            self.worst_adverse_price = max(self.worst_adverse_price, mark_price)
            favorable_delta = max(0.0, self.avg_entry_price - (self.intra_trade_low_price or self.avg_entry_price))
            adverse_delta = max(0.0, (self.intra_trade_high_price or self.avg_entry_price) - self.avg_entry_price)
        if self.avg_entry_price > 0:
            self.mfe_bps = max(self.mfe_bps, favorable_delta / self.avg_entry_price * 10000.0)
            self.mae_bps = max(self.mae_bps, adverse_delta / self.avg_entry_price * 10000.0)
        self.mfe_usd = max(self.mfe_usd, favorable_delta * self.net_quantity)
        self.mae_usd = max(self.mae_usd, adverse_delta * self.net_quantity)
        if maintenance_bracket_evidence is not _MAINTENANCE_EVIDENCE_UNSET:
            self.apply_maintenance_bracket_evidence(
                maintenance_bracket_evidence
                if isinstance(maintenance_bracket_evidence, dict)
                else None,
                mark_price=mark_price,
                mark_time=mark_time,
            )
        elif self._maintenance_bracket_is_usable():
            # Internal close/path updates may repeat the same externally
            # validated mark. They may update the price basis, but cannot
            # introduce or resurrect maintenance evidence.
            self.maintenance_margin_notional_usd = abs(self.net_quantity) * mark_price
            self.maintenance_margin_mark_price = mark_price
            self.maintenance_margin_mark_time = mark_time
            self.recompute_capital_accounting()

    def record_trailing_state(
        self,
        *,
        activation_price: float,
        activation_time: str,
        stop_price: float,
        reason: str,
    ) -> None:
        if self.trailing_activation_price is None:
            self.trailing_activation_price = activation_price
            self.trailing_activation_time = activation_time
        self.trailing_stop_price = stop_price
        event = {
            "generated_utc": activation_time,
            "activation_price": activation_price,
            "trailing_stop_price": stop_price,
            "reason": reason,
        }
        if not self.trailing_stop_history or self.trailing_stop_history[-1] != event:
            self.trailing_stop_history.append(event)

    def unrealized_pnl(self) -> float:
        if self.last_mark_price is None:
            return 0.0
        return pnl_usd(
            side=self.side,
            entry_price=self.avg_entry_price,
            exit_price=self.last_mark_price,
            quantity=self.net_quantity,
        )

    def unrealized_pnl_bps(self) -> float:
        if self.last_mark_price is None:
            return 0.0
        return pnl_bps(
            side=self.side,
            entry_price=self.avg_entry_price,
            exit_price=self.last_mark_price,
        )

    def reconstruction_envelope(self, *, generated_utc: str) -> dict[str, Any]:
        """Return the versioned content hash required for restart restoration."""

        material = {
            "position_reconstruction_schema_version": (
                PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION
            ),
            "position_reconstruction_generated_at": generated_utc,
            "position_id": self.position_id,
            "legacy_position_id": self.legacy_position_id,
            "position_generation_id": self.position_generation_id,
            "position_id_version": self.position_id_version,
            "entry_generation_time_utc": self.entry_generation_time_utc,
            "symbol": self.symbol,
            "side": self.side,
            "net_quantity": round(self.net_quantity, 12),
            "avg_entry_price": self.avg_entry_price,
            "gross_notional_usd": self.notional,
            "allocated_margin_usd": (
                self.notional
                / max(1.0, float(self.effective_leverage or 1.0))
            ),
            "effective_leverage": self.effective_leverage,
            "recommended_leverage": self.recommended_leverage,
            "leverage_source": self.leverage_source,
            "recommended_margin_mode": self.recommended_margin_mode,
            "margin_mode_simulated": self.margin_mode_simulated,
            "adaptive_allocation": self.adaptive_allocation,
            "adaptive_policy_authoritative": self.adaptive_policy_authoritative,
            "adaptive_policy_action_id": self.adaptive_policy_action_id,
            "adaptive_policy_action_sha256": self.adaptive_policy_action_sha256,
            "adaptive_paper_policy_authorization_sha256": (
                self.adaptive_paper_policy_authorization_sha256
            ),
            "adaptive_policy_exit_plan": self.adaptive_policy_exit_plan,
            "adaptive_policy_stop_price": self.adaptive_policy_stop_price,
            "adaptive_policy_profit_target_price": (
                self.adaptive_policy_profit_target_price
            ),
            "adaptive_policy_max_hold_seconds": self.adaptive_policy_max_hold_seconds,
            "adaptive_policy_time_exit_at": self.adaptive_policy_time_exit_at,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "maintenance_margin_cum": self.maintenance_margin_cum,
            "maintenance_margin_notional_usd": (
                self.maintenance_margin_notional_usd
            ),
            "maintenance_bracket_id": self.maintenance_bracket_id,
            "maintenance_bracket_maint_margin_ratio": (
                self.maintenance_bracket_maint_margin_ratio
            ),
            "maintenance_bracket_cum": self.maintenance_bracket_cum,
            "maintenance_bracket_max_initial_leverage": (
                self.maintenance_bracket_max_initial_leverage
            ),
            "maintenance_bracket_evidence_hash": (
                self.maintenance_bracket_evidence_hash
            ),
            "maintenance_bracket_evidence_checksum_sha256": (
                self.maintenance_bracket_evidence_checksum_sha256
            ),
            "maintenance_bracket_evidence_hmac_sha256": (
                self.maintenance_bracket_evidence_hmac_sha256
            ),
            "maintenance_bracket_binding": self.maintenance_bracket_binding,
            "maintenance_bracket_environment_id": (
                self.maintenance_bracket_environment_id
            ),
            "maintenance_bracket_key_id": self.maintenance_bracket_key_id,
            "maintenance_bracket_source": self.maintenance_bracket_source,
            "maintenance_bracket_available_at": (
                self.maintenance_bracket_available_at
            ),
            "maintenance_bracket_expires_at": (
                self.maintenance_bracket_expires_at
            ),
            "maintenance_bracket_consumer_observed_at": (
                self.maintenance_bracket_consumer_observed_at
            ),
            "maintenance_bracket_prevalidated": (
                self.maintenance_bracket_prevalidated
            ),
            "maintenance_bracket_evidence_status": (
                self.maintenance_bracket_evidence_status
            ),
            "maintenance_bracket_evidence_reason": (
                self.maintenance_bracket_evidence_reason
            ),
            "liquidation_price_estimate": self.liquidation_price_estimate,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "opened_est": self.opened_est,
            "source_fill_ids": list(self.fill_ids),
            "realized_pnl": self.realized_pnl,
            "entry_cost_accounting_version": self.entry_cost_accounting_version,
            "entry_fees_incurred_usd": self.entry_fees_incurred_usd,
            "entry_fees_remaining_usd": self.entry_fees_remaining_usd,
            "entry_fees_allocated_to_closes_usd": (
                self.entry_fees_allocated_to_closes_usd
            ),
            "entry_fee_fallback_bps_per_side": (
                self.entry_fee_fallback_bps_per_side
            ),
            "entry_slippage_incurred_usd": self.entry_slippage_incurred_usd,
            "entry_slippage_remaining_usd": self.entry_slippage_remaining_usd,
            "entry_slippage_allocated_to_closes_usd": (
                self.entry_slippage_allocated_to_closes_usd
            ),
            "entry_slippage_fallback_bps_per_side": (
                self.entry_slippage_fallback_bps_per_side
            ),
            "entry_fee_cost_sources": list(self.entry_fee_cost_sources),
            "entry_slippage_cost_sources": list(
                self.entry_slippage_cost_sources
            ),
            "entry_cost_basis_status": self.entry_cost_basis_status,
            "position_state": "OPEN_POSITION",
            "paper_only": True,
            "places_real_order": False,
        }
        exact_claimed = bool(
            self.ppo_on_policy_entry_fields_present is True
            or self.behavior_policy_receipt_entry_event_pending is True
            or self.on_policy_action_receipt_prevalidated is True
            or self.on_policy_action_receipt_valid is True
            or self.behavior_policy_receipt_archive_entry_event_hash
        )
        if exact_claimed:
            material.update(
                {
                    "exact_on_policy_position_lineage_schema_version": (
                        self.exact_on_policy_position_lineage_schema_version
                    ),
                    "behavior_policy_receipt_hash": (
                        self.behavior_policy_receipt_hash
                    ),
                    "behavior_policy_receipt_archive_entry_event_hash": (
                        self.behavior_policy_receipt_archive_entry_event_hash
                    ),
                    "behavior_policy_receipt_archive_verified_at_entry": (
                        self.behavior_policy_receipt_archive_verified_at_entry
                    ),
                    "behavior_policy_receipt_archive_retention_required": (
                        self.behavior_policy_receipt_archive_retention_required
                    ),
                    "behavior_policy_receipt_entry_event_pending": (
                        self.behavior_policy_receipt_entry_event_pending
                    ),
                    "on_policy_action_receipt_prevalidated": (
                        self.on_policy_action_receipt_prevalidated
                    ),
                    "on_policy_action_receipt_valid": (
                        self.on_policy_action_receipt_valid
                    ),
                    "exact_on_policy_entry_outbox_record_id": (
                        self.exact_on_policy_entry_outbox_record_id
                    ),
                    "exact_on_policy_entry_outbox_state": (
                        self.exact_on_policy_entry_outbox_state
                    ),
                    "exact_on_policy_sealed_fill_sha256": (
                        self.exact_on_policy_sealed_fill_sha256
                    ),
                    "behavior_policy_fingerprint": (
                        self.behavior_policy_fingerprint
                    ),
                    "behavior_policy_checkpoint_hash": (
                        self.behavior_policy_checkpoint_hash
                    ),
                    "selected_action": self.selected_action,
                    "selected_action_index": self.selected_action_index,
                    "selected_action_log_prob": self.selected_action_log_prob,
                    "old_log_prob": self.old_log_prob,
                    "old_value": self.old_value,
                    "rollout_id": self.rollout_id,
                    "trajectory_index": self.trajectory_index,
                    "decision_time": self.decision_time,
                }
            )
        reconstruction_hash = paper_position_reconstruction_hash(material)
        if reconstruction_hash is None:
            raise ValueError("PAPER_POSITION_RECONSTRUCTION_HASH_FAILED")
        return {
            "position_reconstruction_schema_version": (
                PAPER_POSITION_RECONSTRUCTION_SCHEMA_VERSION
            ),
            "position_reconstruction_generated_at": generated_utc,
            "position_reconstruction_hash": reconstruction_hash,
        }

    def to_payload(self, *, generated_utc: str) -> dict[str, Any]:
        allocation = self.adaptive_allocation if isinstance(self.adaptive_allocation, dict) else {}
        adaptive_capital_policy_version = first_present(
            self.adaptive_capital_policy_version,
            allocation.get("adaptive_capital_policy_version"),
        )
        policy_activated_at = first_present(
            self.policy_activated_at,
            allocation.get("policy_activated_at"),
        )
        allocation_id = first_present(
            allocation.get("allocation_id"),
            allocation.get("allocator_decision_id"),
        )
        allocator_decision_id = first_present(self.allocator_decision_id, allocation_id)
        allocator_decision_id_source = (
            "paper_position.allocator_decision_id"
            if self.allocator_decision_id not in (None, "")
            else "adaptive_allocation.allocation_id"
            if allocation_id not in (None, "")
            else None
        )
        provider_hashes = self.provider_hashes
        if not provider_hashes and isinstance(self.source_hashes, dict):
            provider_hashes = {
                key: value
                for key, value in self.source_hashes.items()
                if key not in {"feature_vector_hash", "prediction_hash", "source_lineage_hash"}
                and value not in (None, "")
            } or None
        feature_vector_hash = first_present(
            self.feature_vector_hash,
            self.source_hashes.get("feature_vector_hash") if isinstance(self.source_hashes, dict) else None,
        )
        raw_safety_fields = {
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "test_order": False,
            "live_order": False,
            "counts_as_A_plus": False,
            "counts_as_final_A_plus": False,
            "counts_as_live_ready": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
        invariant_checks = {
            "paper_only_is_true": True,
            "routes_to_live_is_false": True,
            "places_real_order_is_false": True,
            "test_order_is_false": True,
            "live_order_is_false": True,
            "counts_as_A_plus_is_false": True,
            "counts_as_final_A_plus_is_false": True,
            "counts_as_live_ready_is_false": True,
            "order_submitted_is_false": True,
            "test_order_submitted_is_false": True,
            "leverage_mutated_is_false": True,
            "margin_mutated_is_false": True,
        }
        maintenance_bracket_evidence = {
            "prevalidated": self.maintenance_bracket_prevalidated,
            "bracket_id": self.maintenance_bracket_id,
            "maint_margin_ratio": self.maintenance_bracket_maint_margin_ratio,
            "cum": self.maintenance_bracket_cum,
            "max_initial_leverage": self.maintenance_bracket_max_initial_leverage,
            "evidence_hash": self.maintenance_bracket_evidence_hash,
            "evidence_checksum_sha256": self.maintenance_bracket_evidence_checksum_sha256,
            "evidence_hmac_sha256": self.maintenance_bracket_evidence_hmac_sha256,
            "binding": self.maintenance_bracket_binding,
            "environment_id": self.maintenance_bracket_environment_id,
            "key_id": self.maintenance_bracket_key_id,
            "source": self.maintenance_bracket_source,
            "available_at": self.maintenance_bracket_available_at,
            "expires_at": self.maintenance_bracket_expires_at,
            "consumer_observed_at": self.maintenance_bracket_consumer_observed_at,
            "status": self.maintenance_bracket_evidence_status,
            "reason": self.maintenance_bracket_evidence_reason,
        }
        return {
            **self.reconstruction_envelope(generated_utc=generated_utc),
            "position_id": self.position_id,
            "legacy_position_id": self.legacy_position_id,
            "position_generation_id": self.position_generation_id,
            "position_id_version": self.position_id_version,
            "entry_generation_time_utc": self.entry_generation_time_utc,
            "symbol": self.symbol,
            "side": self.side,
            "net_quantity": round(self.net_quantity, 12),
            "avg_entry_price": self.avg_entry_price,
            "entry_price": self.avg_entry_price,
            "entry_price_source": "accepted_paper_fill.avg_entry_price",
            "entry_fill_id": self.fill_ids[0] if self.fill_ids else self.position_id,
            "entry_time": self.opened_est,
            "notional": self.notional,
            "gross_notional": self.notional,
            "adaptive_allocation": self.adaptive_allocation,
            "adaptive_policy_authoritative": self.adaptive_policy_authoritative,
            "adaptive_policy_action_id": self.adaptive_policy_action_id,
            "adaptive_policy_action_sha256": self.adaptive_policy_action_sha256,
            "adaptive_paper_policy_authorization_sha256": (
                self.adaptive_paper_policy_authorization_sha256
            ),
            "adaptive_policy_exit_plan": self.adaptive_policy_exit_plan,
            "adaptive_policy_stop_price": self.adaptive_policy_stop_price,
            "adaptive_policy_profit_target_price": (
                self.adaptive_policy_profit_target_price
            ),
            "adaptive_policy_max_hold_seconds": self.adaptive_policy_max_hold_seconds,
            "adaptive_policy_time_exit_at": self.adaptive_policy_time_exit_at,
            "adaptive_allocation_accounting_scope": (
                "UPSTREAM_ENTRY_ALLOCATION_PROVENANCE"
                if isinstance(self.adaptive_allocation, dict)
                else None
            ),
            "adaptive_capital_policy_version": adaptive_capital_policy_version,
            "policy_activated_at": policy_activated_at,
            "gross_notional_usd": self.notional,
            "gross_notional_accounting_basis": (
                "ABS_NET_QUANTITY_X_AVERAGE_EXECUTED_ENTRY_PRICE"
            ),
            # Canonical paper invariant for both full and partially-netted
            # positions: gross_notional == allocated_margin * leverage.
            "allocated_margin_usd": (
                self.notional / max(1.0, float(self.effective_leverage or 1.0))
            ),
            "allocated_margin_usd_at_entry": self.allocated_margin_usd,
            "gross_notional_usd_upstream": self.gross_notional_usd_upstream,
            "allocated_margin_usd_upstream": self.allocated_margin_usd_upstream,
            "effective_leverage": self.effective_leverage,
            "recommended_leverage": self.recommended_leverage,
            "leverage_source": self.leverage_source,
            "leverage_recommendation_tier": self.leverage_recommendation_tier,
            "leverage_exploration": self.leverage_exploration,
            "recommended_margin_mode": self.recommended_margin_mode,
            "margin_mode_simulated": self.margin_mode_simulated,
            "maintenance_margin_rate": self.maintenance_margin_rate,
            "maintenance_margin_cum": self.maintenance_margin_cum,
            "maintenance_margin_estimate": self.maintenance_margin_estimate,
            "maintenance_margin_notional_usd": self.maintenance_margin_notional_usd,
            "maintenance_margin_mark_price": self.maintenance_margin_mark_price,
            "maintenance_margin_mark_time": self.maintenance_margin_mark_time,
            "maintenance_margin_formula": "MAX(0,ABS_NET_QUANTITY_X_FRESH_MARK_X_MAINT_MARGIN_RATIO_MINUS_CUM)",
            "maintenance_bracket_evidence": maintenance_bracket_evidence,
            "maintenance_bracket_id": self.maintenance_bracket_id,
            "maintenance_bracket_maint_margin_ratio": self.maintenance_bracket_maint_margin_ratio,
            "maintenance_bracket_cum": self.maintenance_bracket_cum,
            "maintenance_bracket_max_initial_leverage": self.maintenance_bracket_max_initial_leverage,
            "maintenance_bracket_evidence_hash": self.maintenance_bracket_evidence_hash,
            "maintenance_bracket_evidence_checksum_sha256": self.maintenance_bracket_evidence_checksum_sha256,
            "maintenance_bracket_evidence_hmac_sha256": self.maintenance_bracket_evidence_hmac_sha256,
            "maintenance_bracket_binding": self.maintenance_bracket_binding,
            "maintenance_bracket_environment_id": self.maintenance_bracket_environment_id,
            "maintenance_bracket_key_id": self.maintenance_bracket_key_id,
            "maintenance_bracket_source": self.maintenance_bracket_source,
            "maintenance_bracket_available_at": self.maintenance_bracket_available_at,
            "maintenance_bracket_expires_at": self.maintenance_bracket_expires_at,
            "maintenance_bracket_consumer_observed_at": self.maintenance_bracket_consumer_observed_at,
            "maintenance_bracket_prevalidated": self.maintenance_bracket_prevalidated,
            "maintenance_bracket_evidence_status": self.maintenance_bracket_evidence_status,
            "maintenance_bracket_evidence_reason": self.maintenance_bracket_evidence_reason,
            "liquidation_price_estimate": self.liquidation_price_estimate,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "capital_accounting_reconciled": self.capital_accounting_reconciled,
            "capital_accounting_reconciliation_reasons": list(
                self.capital_accounting_reconciliation_reasons
            ),
            "current_capital_accounting": {
                "gross_notional_usd": self.notional,
                "allocated_margin_usd": (
                    self.notional / max(1.0, float(self.effective_leverage or 1.0))
                ),
                "effective_leverage": self.effective_leverage,
                "entry_capital_invariant": (
                    "GROSS_NOTIONAL_USD_EQUALS_ALLOCATED_MARGIN_USD_X_EFFECTIVE_LEVERAGE"
                ),
                "maintenance_margin_rate": self.maintenance_margin_rate,
                "maintenance_margin_cum": self.maintenance_margin_cum,
                "maintenance_margin_notional_usd": self.maintenance_margin_notional_usd,
                "maintenance_margin_estimate": self.maintenance_margin_estimate,
                "liquidation_price_estimate": self.liquidation_price_estimate,
                "liquidation_buffer_bps": self.liquidation_buffer_bps,
                "accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION",
                "entry_capital_accounting_scope": "CURRENT_EXECUTED_PAPER_POSITION_ENTRY_BASIS",
                "maintenance_accounting_scope": "WHOLE_NET_POSITION_FRESH_MARK_BASIS",
            },
            "risk_budget_usd": self.risk_budget_usd,
            "risk_budget_source": self.risk_budget_source,
            "stop_distance_bps": self.stop_distance_bps,
            "expected_fees_usd": self.expected_fees_usd,
            "expected_funding_bps": self.expected_funding_bps,
            "funding_rate": self.funding_rate,
            "funding_interval_seconds": self.funding_interval_seconds,
            "expected_funding_usd": self.expected_funding_usd,
            "expected_net_pnl_usd": self.expected_net_pnl_usd,
            "expected_max_loss_usd": self.expected_max_loss_usd,
            "expected_shortfall_usd": self.expected_shortfall_usd,
            "hedge_budget_usd": self.hedge_budget_usd,
            "capital_allocation_reason": self.capital_allocation_reason,
            "entry_atr_bps": self.entry_atr_bps,
            "atr_bps": self.entry_atr_bps,
            "entry_feature_available_at": self.entry_feature_available_at,
            "entry_feature_generated_at": self.entry_feature_generated_at,
            "entry_feature_cutoff": self.entry_feature_cutoff,
            "entry_feature_decision_time": self.entry_feature_decision_time,
            "entry_feature_source": self.entry_feature_source,
            "entry_feature_candle_closed_confirmed": self.entry_feature_candle_closed_confirmed,
            "entry_feature_unavailable_reason": self.entry_feature_unavailable_reason,
            "entry_feature_snapshot": self.entry_feature_snapshot,
            "opened_est": self.opened_est,
            "last_mark_est": self.last_mark_est,
            "last_mark_price": self.last_mark_price,
            "unrealized_pnl": self.unrealized_pnl(),
            "unrealized_pnl_bps": self.unrealized_pnl_bps(),
            "realized_pnl": self.realized_pnl,
            "source_signal_id": self.source_signal_id,
            "signal_id": self.source_signal_id,
            "entry_signal_id": self.source_signal_id,
            "prediction_id": self.prediction_id,
            "entry_prediction_id": self.prediction_id,
            "preemptive_decision_id": self.preemptive_decision_id,
            "risk_decision_id": self.risk_decision_id,
            "orchestrator_decision_id": self.orchestrator_decision_id,
            "allocator_decision_id": allocator_decision_id,
            "allocator_decision_id_source": allocator_decision_id_source,
            "allocation_id": allocation_id,
            "materialization_queue_id": self.materialization_queue_id,
            "materialization_queue_accepted_at": self.materialization_queue_accepted_at,
            "materialization_queue_expires_at": self.materialization_queue_expires_at,
            "market_state_id": self.market_state_id,
            "entry_market_state_id": self.entry_market_state_id or self.market_state_id,
            "trainer_source": self.trainer_source,
            "timeframe": self.timeframe,
            "feature_snapshot_id": self.feature_snapshot_id,
            "entry_feature_snapshot_id": self.feature_snapshot_id,
            "decision_id": self.decision_id,
            "mtf_snapshot_id": self.mtf_snapshot_id,
            "feature_cutoff": self.feature_cutoff,
            "decision_time": self.decision_time,
            "available_at": self.available_at,
            "selected_action": self.selected_action or self.side,
            "model_version": self.model_version,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_id_source": self.checkpoint_id_source,
            "entry_prediction_snapshot": self.entry_prediction_snapshot,
            "feature_tensor_id": self.feature_tensor_id,
            "risk_decision_record_key": self.risk_decision_record_key,
            "risk_decision_record_hash": self.risk_decision_record_hash,
            "risk_decision_record_resolved": self.risk_decision_record_resolved,
            "risk_decision_source": self.risk_decision_source,
            "orchestrator_decision_record_key": self.orchestrator_decision_record_key,
            "orchestrator_decision_record_hash": self.orchestrator_decision_record_hash,
            "orchestrator_decision_record_resolved": self.orchestrator_decision_record_resolved,
            "orchestrator_decision_source": self.orchestrator_decision_source,
            "decision_record_missing_reasons": self.decision_record_missing_reasons,
            "source_hashes": self.source_hashes,
            "feature_vector_hash": feature_vector_hash,
            "provider_hashes": provider_hashes,
            "confidence_raw": self.confidence_raw,
            "confidence_calibrated": self.confidence_calibrated,
            "confidence_executable_trade": self.confidence_executable_trade,
            "dynamic_exploration_floor": self.dynamic_exploration_floor,
            "dynamic_exploration_floor_formula": self.dynamic_exploration_floor_formula,
            "exploration_floor_inputs": self.exploration_floor_inputs,
            "paper_risk_controller_exploration_above_floor": (
                self.paper_risk_controller_exploration_above_floor
            ),
            "paper_risk_controller_exploration_eligible": (
                self.paper_risk_controller_exploration_eligible
            ),
            "bootstrap_exploration": self.bootstrap_exploration,
            "bootstrap_overridden_blockers": self.bootstrap_overridden_blockers,
            "action_labels": self.action_labels,
            "raw_action_logits": self.raw_action_logits,
            "raw_action_probabilities": self.raw_action_probabilities,
            "selected_action_probability": self.selected_action_probability,
            "selected_action_index": self.selected_action_index,
            "expected_move_bps": self.expected_move_bps,
            "expected_move_after_cost_bps": self.expected_move_after_cost_bps,
            "action_probabilities": self.action_probabilities,
            "policy_value": self.policy_value,
            "value_baseline": self.value_baseline,
            "selected_action_log_prob": self.selected_action_log_prob,
            "old_log_prob": self.old_log_prob,
            "old_value": self.old_value,
            "rollout_id": self.rollout_id,
            "trajectory_index": self.trajectory_index,
            "ppo_on_policy_entry_fields_present": (
                self.ppo_on_policy_entry_fields_present
            ),
            "ppo_on_policy_ineligible_reason": self.ppo_on_policy_ineligible_reason,
            "behavior_action_index": self.behavior_action_index,
            "behavior_action": self.behavior_action,
            "behavior_action_mask": self.behavior_action_mask,
            "behavior_action_source": self.behavior_action_source,
            "behavior_policy_sampling_mode": self.behavior_policy_sampling_mode,
            "behavior_policy_distribution_contract": (
                self.behavior_policy_distribution_contract
            ),
            "behavior_policy_fingerprint": self.behavior_policy_fingerprint,
            "behavior_policy_checkpoint_hash": self.behavior_policy_checkpoint_hash,
            "behavior_policy_receipt": self.behavior_policy_receipt,
            "behavior_policy_receipt_hash": self.behavior_policy_receipt_hash,
            "behavior_policy_receipt_key": self.behavior_policy_receipt_key,
            "behavior_policy_receipt_write_success": (
                self.behavior_policy_receipt_write_success
            ),
            "exact_on_policy_position_lineage_schema_version": (
                self.exact_on_policy_position_lineage_schema_version
            ),
            "behavior_policy_receipt_archive_entry_event_hash": (
                self.behavior_policy_receipt_archive_entry_event_hash
            ),
            "behavior_policy_receipt_archive_verified_at_entry": (
                self.behavior_policy_receipt_archive_verified_at_entry
            ),
            "behavior_policy_receipt_archive_retention_required": (
                self.behavior_policy_receipt_archive_retention_required
            ),
            "behavior_policy_receipt_entry_event_pending": (
                self.behavior_policy_receipt_entry_event_pending
            ),
            "on_policy_action_receipt_prevalidated": (
                self.on_policy_action_receipt_prevalidated
            ),
            "on_policy_action_receipt_valid": self.on_policy_action_receipt_valid,
            "exact_on_policy_entry_outbox_record_id": (
                self.exact_on_policy_entry_outbox_record_id
            ),
            "exact_on_policy_entry_outbox_state": (
                self.exact_on_policy_entry_outbox_state
            ),
            "exact_on_policy_sealed_fill_sha256": (
                self.exact_on_policy_sealed_fill_sha256
            ),
            "on_policy_sampling_selected": self.on_policy_sampling_selected,
            "on_policy_sampling_requested": self.on_policy_sampling_requested,
            "on_policy_sampling_plan_hash": self.on_policy_sampling_plan_hash,
            "on_policy_sampling_plan_input_hash": (
                self.on_policy_sampling_plan_input_hash
            ),
            "on_policy_sampling_lane": self.on_policy_sampling_lane,
            "on_policy_sampling_evidence_class": (
                self.on_policy_sampling_evidence_class
            ),
            "on_policy_sampling_counts_as_a_plus_evidence": (
                self.on_policy_sampling_counts_as_a_plus_evidence
            ),
            "on_policy_sampling_routes_to_live": (
                self.on_policy_sampling_routes_to_live
            ),
            "strategy_supply_hypothesis": self.strategy_supply_hypothesis,
            "entry_policy_fields_source": self.entry_policy_fields_source,
            "paper_learning_lane": self.paper_learning_lane,
            "prediction_score_source": self.prediction_score_source,
            "prediction_score_missing_reason": self.prediction_score_missing_reason,
            "candidate_id": self.candidate_id,
            "paper_policy_owner": self.paper_policy_owner,
            "policy_fingerprint": self.policy_fingerprint,
            "model_source": self.model_source,
            "selector_policy_fingerprint": self.selector_policy_fingerprint,
            "frozen_selector_fingerprint": self.frozen_selector_fingerprint,
            "candidate_selected_before_outcome": self.candidate_selected_before_outcome,
            "candidate_selected_after_outcome": self.candidate_selected_after_outcome,
            "post_outcome_candidate_selection": self.post_outcome_candidate_selection,
            "future_labels_used_as_features": self.future_labels_used_as_features,
            "paper_opportunity_tier": self.paper_opportunity_tier,
            "tier": (
                self.paper_opportunity_tier
                if str(self.paper_opportunity_tier or "").strip().upper()
                == "PAPER_RISK_CONTROLLER_EXPLORATION"
                else None
            ),
            "exploration_tier": (
                self.paper_opportunity_tier
                if str(self.paper_opportunity_tier or "").strip().upper()
                == "PAPER_RISK_CONTROLLER_EXPLORATION"
                else None
            ),
            "paper_exploration_tier": (
                self.paper_opportunity_tier
                if str(self.paper_opportunity_tier or "").strip().upper()
                == "PAPER_RISK_CONTROLLER_EXPLORATION"
                else None
            ),
            "paper_opportunity_tier_reason": self.paper_opportunity_tier_reason,
            "explicit_paper_opportunity_tier": self.explicit_paper_opportunity_tier,
            "paper_fill_allowed_source": self.paper_fill_allowed_source,
            "strict_paper_fill_allowed_upstream": self.strict_paper_fill_allowed_upstream,
            "calibration_label_purpose": self.calibration_label_purpose,
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "strategy_selected_mode": self.strategy_selected_mode,
            "hedge_state": self.hedge_state,
            "hedge_reason": self.hedge_reason,
            "hedge_parent_id": self.hedge_parent_id,
            "hedge_child_id": self.hedge_child_id,
            "hedge_ratio": self.hedge_ratio,
            "hedge_entry_parent_pnl_bps": self.hedge_entry_parent_pnl_bps,
            "hedge_pending_since": self.hedge_pending_since,
            "drawdown_at_entry": self.drawdown_at_entry,
            "market_regime_at_entry": self.market_regime_at_entry,
            "liquidity_zone_context": self.liquidity_zone_context,
            "liquidation_distance_context": self.liquidation_distance_context,
            "microstructure_context": self.microstructure_context,
            "oi_funding_context": self.oi_funding_context,
            "public_intel_context": self.public_intel_context,
            "major_move_signal_id": self.major_move_signal_id,
            "squeeze_evidence_score": self.squeeze_evidence_score,
            "squeeze_evidence_source": self.squeeze_evidence_source,
            "squeeze_evidence_components": self.squeeze_evidence_components,
            "squeeze_evidence_unavailable_reason": self.squeeze_evidence_unavailable_reason,
            "future_window_label_source": self.future_window_label_source,
            "mfe_bps": self.mfe_bps,
            "mfe_usd": self.mfe_usd,
            "mae_bps": self.mae_bps,
            "mae_usd": self.mae_usd,
            "intra_trade_high_price": self.intra_trade_high_price,
            "intra_trade_low_price": self.intra_trade_low_price,
            "trailing_activation_price": self.trailing_activation_price,
            "trailing_activation_time": self.trailing_activation_time,
            "trailing_stop_price": self.trailing_stop_price,
            "trailing_stop_history": list(self.trailing_stop_history),
            "actual_observed_spread_entry_bps": self.entry_observed_spread_bps,
            "observed_bid": self.observed_bid,
            "observed_ask": self.observed_ask,
            "observed_spread_bps": self.observed_spread_bps,
            "order_size": self.order_size,
            "order_size_usd": self.order_size_usd,
            "entry_spread_source": self.entry_spread_source,
            "entry_spread_unavailable_reason": self.entry_spread_unavailable_reason,
            "top_book_bid_depth_usd": self.top_book_bid_depth_usd,
            "top_book_ask_depth_usd": self.top_book_ask_depth_usd,
            "bid_depth_usd": self.bid_depth_usd,
            "ask_depth_usd": self.ask_depth_usd,
            "orderbook_depth_usd": self.orderbook_depth_usd,
            "entry_orderbook_depth_usd": self.entry_orderbook_depth_usd,
            "entry_orderbook_depth_side": self.entry_orderbook_depth_side,
            "top_of_book_depth_usd": self.top_of_book_depth_usd,
            "market_depth_usd": self.market_depth_usd,
            "orderbook_depth_source": self.orderbook_depth_source,
            "depth_utilization_pct": self.depth_utilization_pct,
            "depth_price_impact_bps": self.depth_price_impact_bps,
            "depth_derived_price_impact_bps": self.depth_derived_price_impact_bps,
            "depth_price_impact_source": self.depth_price_impact_source,
            "depth_price_impact_model": self.depth_price_impact_model,
            "depth_price_impact_side": self.depth_price_impact_side,
            "depth_price_impact_quantity": self.depth_price_impact_quantity,
            "depth_price_impact_filled_quantity": self.depth_price_impact_filled_quantity,
            "depth_price_impact_fill_complete": self.depth_price_impact_fill_complete,
            "depth_price_impact_vwap": self.depth_price_impact_vwap,
            "depth_price_impact_touch_price": self.depth_price_impact_touch_price,
            "expected_slippage_bps": self.expected_slippage_bps,
            "expected_slippage_usd": self.expected_slippage_usd,
            "expected_slippage_source": self.expected_slippage_source,
            "expected_slippage_modeled": self.expected_slippage_modeled,
            "expected_slippage_unavailable_reason": self.expected_slippage_unavailable_reason,
            "correlation_exposure_pct": self.correlation_exposure_pct,
            "correlation_input_source": self.correlation_input_source,
            "correlation_input_status": self.correlation_input_status,
            "correlation_pair_count": self.correlation_pair_count,
            "correlation_diagnostics": self.correlation_diagnostics,
            "realized_slippage_bps": self.realized_slippage_bps,
            "realized_slippage_usd": self.realized_slippage_usd,
            "decision_latency_ms": self.decision_latency_ms,
            "latency_ms": self.decision_latency_ms,
            "paper_fill_latency_ms": self.decision_latency_ms,
            "fill_latency_ms": self.decision_latency_ms,
            "execution_latency_ms": self.decision_latency_ms,
            "simulated_latency_ms": self.decision_latency_ms,
            "latency_source": self.latency_source,
            "latency_reserve_bps": self.latency_reserve_bps,
            "latency_reserve_source": self.latency_reserve_source,
            "maker_taker_assumption": self.maker_taker_assumption,
            "maker_probability": self.maker_probability,
            "taker_probability": self.taker_probability,
            "maker_taker_probability": self.maker_taker_probability,
            "maker_taker_probability_detail": self.maker_taker_probability_detail,
            "maker_taker_probabilities": self.maker_taker_probabilities,
            "maker_taker_probability_source": self.maker_taker_probability_source,
            "fee_schedule": self.fee_schedule,
            "fee_bps": self.fee_bps,
            "fee_bps_source": self.fee_bps_source,
            "fee_bps_configured_schedule": self.fee_bps_configured_schedule,
            "entry_cost_accounting_version": self.entry_cost_accounting_version,
            "entry_fees_incurred_usd": self.entry_fees_incurred_usd,
            "entry_fees_remaining_usd": self.entry_fees_remaining_usd,
            "entry_fees_allocated_to_closes_usd": (
                self.entry_fees_allocated_to_closes_usd
            ),
            "entry_fee_fallback_bps_per_side": (
                self.entry_fee_fallback_bps_per_side
            ),
            "entry_slippage_incurred_usd": self.entry_slippage_incurred_usd,
            "entry_slippage_remaining_usd": self.entry_slippage_remaining_usd,
            "entry_slippage_allocated_to_closes_usd": (
                self.entry_slippage_allocated_to_closes_usd
            ),
            "entry_slippage_fallback_bps_per_side": (
                self.entry_slippage_fallback_bps_per_side
            ),
            "entry_fee_cost_sources": list(self.entry_fee_cost_sources),
            "entry_slippage_cost_sources": list(
                self.entry_slippage_cost_sources
            ),
            "entry_cost_basis_status": self.entry_cost_basis_status,
            "holding_period_funding_bps": self.holding_period_funding_bps,
            "holding_period_funding_source": self.holding_period_funding_source,
            "partial_fill_count": self.partial_fill_count,
            "partial_fill_estimate": self.partial_fill_estimate,
            "partial_fill_probability": self.partial_fill_probability,
            "partial_fill_adjustment_bps": self.partial_fill_adjustment_bps,
            "partial_fills": self.partial_fills,
            "fill_count": self.fill_count,
            "all_partial_fills": self.all_partial_fills,
            "partial_fill_plan": self.partial_fill_plan,
            "execution_probability": self.execution_probability,
            "mark_index_divergence_bps": self.mark_index_divergence_bps,
            "mark_index_divergence": self.mark_index_divergence,
            "mark_index_source": self.mark_index_source,
            "mark_index_available_at": self.mark_index_available_at,
            "mark_price": self.mark_price,
            "index_price": self.index_price,
            "cost_source": self.cost_source,
            "cost_source_timestamp": self.cost_source_timestamp,
            "source_timestamp": self.source_timestamp,
            "cost_evidence_freshness_ms": self.cost_evidence_freshness_ms,
            "cost_evidence_source_fields": self.cost_evidence_source_fields,
            "runtime_cost_capture_source": self.runtime_cost_capture_source,
            "runtime_cost_capture_status": self.runtime_cost_capture_status,
            "runtime_cost_capture_required_fields": self.runtime_cost_capture_required_fields,
            "runtime_cost_capture_missing_fields": self.runtime_cost_capture_missing_fields,
            "runtime_cost_capture_explained_missing_fields": self.runtime_cost_capture_explained_missing_fields,
            "runtime_cost_capture_unexplained_missing_fields": self.runtime_cost_capture_unexplained_missing_fields,
            "runtime_cost_capture_order_cost_applicable": self.runtime_cost_capture_order_cost_applicable,
            "runtime_cost_capture_no_order_reason": self.runtime_cost_capture_no_order_reason,
            "runtime_cost_capture_temporal_reject_reasons": self.runtime_cost_capture_temporal_reject_reasons,
            "fallback_cost_flag": self.fallback_cost_flag,
            "fallback": self.fallback,
            "production_grade_cost_flag": self.production_grade_cost_flag,
            "production_grade_cost_evidence": self.production_grade_cost_evidence,
            "estimated_production_cost": self.estimated_production_cost,
            "estimated_production_cost_bps": self.estimated_production_cost_bps,
            "counts_as_production_grade_training_evidence": self.counts_as_production_grade_training_evidence,
            "source_fill_ids": list(self.fill_ids),
            "best_favorable_price": self.best_favorable_price,
            "worst_adverse_price": self.worst_adverse_price,
            "position_age_seconds": seconds_between(self.opened_est, generated_utc),
            "position_state": "OPEN_POSITION",
            "paper_fill_allowed": True,
            "decision": "ACCEPTED_PAPER_FILL",
            "account_scope": "PAPER_SIM_ACCOUNT",
            "source_type": "paper_sim_valid_economic_fill",
            "paper_or_live": "paper",
            "contains_simulated_positions": True,
            "contains_live_positions": False,
            "contains_quarantined_positions": False,
            "equity_trusted": True,
            "pnl_trusted": True,
            "reason_if_untrusted": None,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
            "live_order": False,
            "test_order": False,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
            "counts_as_A_plus": False,
            "counts_as_final_A_plus": False,
            "counts_as_final_a_plus": False,
            "counts_as_live_ready": False,
            "raw_safety_fields": raw_safety_fields,
            "invariant_checks": invariant_checks,
        }


def maintenance_bracket_evidence_from_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Recover the normalized lifecycle evidence mapping from a persisted row."""

    if not isinstance(payload, dict):
        return None
    allocation = (
        payload.get("adaptive_allocation")
        if isinstance(payload.get("adaptive_allocation"), dict)
        else {}
    )
    def normalize(value: dict[str, Any]) -> dict[str, Any]:
        checksum = first_present(
            value.get("evidence_checksum_sha256"),
            value.get("content_checksum_sha256"),
        )
        return {
            "prevalidated": value.get("prevalidated") is True,
            "bracket_id": first_present(
                value.get("bracket_id"),
                value.get("selected_bracket"),
                value.get("bracket"),
            ),
            "maint_margin_ratio": first_present(
                value.get("maint_margin_ratio"),
                value.get("maintenance_margin_rate"),
                value.get("maintMarginRatio"),
            ),
            "cum": first_present(
                value.get("cum"),
                value.get("maintenance_margin_cum"),
            ),
            "max_initial_leverage": first_present(
                value.get("max_initial_leverage"),
                value.get("initialLeverage"),
            ),
            "evidence_hash": first_present(
                value.get("evidence_hash"),
                checksum,
            ),
            "evidence_checksum_sha256": checksum,
            "evidence_hmac_sha256": first_present(
                value.get("evidence_hmac_sha256"),
                value.get("evidence_hmac"),
            ),
            "binding": first_present(
                value.get("binding"),
                value.get("credential_binding_id"),
                value.get("account_binding_id"),
            ),
            "environment_id": first_present(
                value.get("environment_id"),
                value.get("exchange_environment"),
            ),
            "key_id": first_present(
                value.get("key_id"),
                value.get("evidence_auth_key_id"),
            ),
            "source": value.get("source"),
            "available_at": value.get("available_at"),
            "expires_at": value.get("expires_at"),
            "consumer_observed_at": value.get("consumer_observed_at"),
        }

    for container in (payload, allocation):
        for key in (
            "maintenance_bracket_evidence",
            "paper_maintenance_margin_bracket_evidence",
        ):
            value = container.get(key)
            if isinstance(value, dict):
                return normalize(value)

    bracket_id = first_present(
        payload.get("maintenance_bracket_id"),
        allocation.get("maintenance_bracket_id"),
    )
    if bracket_id in (None, ""):
        return None
    return {
        "prevalidated": first_present(
            payload.get("maintenance_bracket_prevalidated"),
            allocation.get("maintenance_bracket_prevalidated"),
        )
        is True,
        "bracket_id": bracket_id,
        "maint_margin_ratio": first_present(
            payload.get("maintenance_bracket_maint_margin_ratio"),
            payload.get("maintenance_margin_rate"),
            allocation.get("maintenance_bracket_maint_margin_ratio"),
            allocation.get("maintenance_margin_rate"),
        ),
        "cum": first_present(
            payload.get("maintenance_bracket_cum"),
            payload.get("maintenance_margin_cum"),
            allocation.get("maintenance_bracket_cum"),
            allocation.get("maintenance_margin_cum"),
        ),
        "max_initial_leverage": first_present(
            payload.get("maintenance_bracket_max_initial_leverage"),
            allocation.get("maintenance_bracket_max_initial_leverage"),
        ),
        "evidence_hash": first_present(
            payload.get("maintenance_bracket_evidence_hash"),
            payload.get("maintenance_bracket_evidence_checksum_sha256"),
            allocation.get("maintenance_bracket_evidence_hash"),
            allocation.get("maintenance_bracket_evidence_checksum_sha256"),
        ),
        "evidence_checksum_sha256": first_present(
            payload.get("maintenance_bracket_evidence_checksum_sha256"),
            allocation.get("maintenance_bracket_evidence_checksum_sha256"),
        ),
        "evidence_hmac_sha256": first_present(
            payload.get("maintenance_bracket_evidence_hmac_sha256"),
            allocation.get("maintenance_bracket_evidence_hmac_sha256"),
        ),
        "binding": first_present(
            payload.get("maintenance_bracket_binding"),
            payload.get("maintenance_bracket_account_binding_id"),
            allocation.get("maintenance_bracket_binding"),
            allocation.get("maintenance_bracket_account_binding_id"),
        ),
        "environment_id": first_present(
            payload.get("maintenance_bracket_environment_id"),
            allocation.get("maintenance_bracket_environment_id"),
        ),
        "key_id": first_present(
            payload.get("maintenance_bracket_key_id"),
            allocation.get("maintenance_bracket_key_id"),
        ),
        "source": first_present(
            payload.get("maintenance_bracket_source"),
            payload.get("maintenance_margin_rate_source"),
            allocation.get("maintenance_bracket_source"),
            allocation.get("maintenance_margin_rate_source"),
        ),
        "available_at": first_present(
            payload.get("maintenance_bracket_available_at"),
            payload.get("maintenance_margin_evidence_available_at"),
            allocation.get("maintenance_bracket_available_at"),
            allocation.get("maintenance_margin_evidence_available_at"),
        ),
        "expires_at": first_present(
            payload.get("maintenance_bracket_expires_at"),
            allocation.get("maintenance_bracket_expires_at"),
        ),
        "consumer_observed_at": first_present(
            payload.get("maintenance_bracket_consumer_observed_at"),
            allocation.get("maintenance_bracket_consumer_observed_at"),
        ),
    }


def position_from_fill(fill: dict[str, Any], *, fill_id: str, side: str, quantity: float, price: float) -> PaperNetPosition:
    symbol = str(fill.get("symbol") or "").upper()
    generation = entry_generation_identity(
        fill,
        source_identity_override=fill_id,
    )
    entry_time_utc = (
        utc_iso_from_any(fill.get("entry_time"))
        or utc_iso_from_any(fill.get("execution_time"))
        or utc_iso_from_any(fill.get("paper_fill_materialized_at"))
        or utc_iso_from_any(fill.get("fill_price_utc"))
        or utc_iso_from_any(fill.get("entry_price_utc"))
        or utc_iso_from_any(fill.get("fill_time_est"))
        or utc_iso_from_any(fill.get("entry_generation_time_utc"))
        or utc_iso_from_any(fill.get("generated_utc"))
        or utc_iso_from_any(fill.get("opened_est"))
        or utc_now_iso()
    )
    # Bind the display-time projection to the exact timestamp that defines the
    # position generation.  Using a separately rounded ``fill_time_est`` can
    # make the same entry appear to occur after it opened during restart.
    opened = (
        utc_to_est_iso(generation.entry_time_utc)
        or utc_to_est_iso(fill.get("fill_time_est"))
        or utc_to_est_iso(entry_time_utc)
        or entry_time_utc
    )
    raw_allocation = (
        fill.get("adaptive_allocation")
        if isinstance(fill.get("adaptive_allocation"), dict)
        else {}
    )
    allocation = dict(raw_allocation)
    if isinstance(raw_allocation.get("model_inputs"), dict):
        allocation["model_inputs"] = dict(raw_allocation["model_inputs"])
    allocation_model_inputs = (
        allocation.get("model_inputs")
        if isinstance(allocation.get("model_inputs"), dict)
        else {}
    )
    leverage_recommendation = (
        fill.get("leverage_recommendation")
        if isinstance(fill.get("leverage_recommendation"), dict)
        else {}
    )
    gross_notional = abs(quantity * price)
    recommended_leverage = first_number(
        fill.get("recommended_leverage"),
        allocation.get("recommended_leverage"),
        leverage_recommendation.get("recommended_leverage"),
        leverage_recommendation.get("leverage"),
        1.0,
    )
    executed_leverage = first_number(
        fill.get("effective_leverage"),
        fill.get("leverage"),
    )
    effective_leverage = max(1.0, executed_leverage or 1.0)
    effective_leverage_source = (
        str(fill.get("leverage_source"))
        if executed_leverage is not None and fill.get("leverage_source")
        else (
            "EXECUTED_FILL_EFFECTIVE_LEVERAGE"
            if executed_leverage is not None
            else "FAIL_CLOSED_1X_EXECUTED_LEVERAGE_MISSING"
        )
    )
    gross_notional_upstream = first_number(
        fill.get("gross_notional_usd"),
        allocation.get("gross_notional_usd"),
        fill.get("notional_usd"),
        fill.get("notional_usdt"),
        fill.get("notional"),
    )
    allocated_margin_upstream = first_number(
        fill.get("allocated_margin_usd"),
        allocation.get("allocated_margin_usd"),
    )
    allocated_margin = gross_notional / effective_leverage
    bracket_evidence = maintenance_bracket_evidence_from_payload(fill)
    # A bare rate is not sufficient maintenance evidence.  The active values
    # are populated only by the complete, account-bound bracket contract below.
    maintenance_rate = None
    maintenance_cum = None
    maintenance_margin_upstream = first_number(
        fill.get("maintenance_margin_estimate"),
        allocation.get("maintenance_margin_estimate"),
    )
    maintenance_margin = None
    liquidation_price_upstream = first_number(
        fill.get("liquidation_price_estimate"),
        allocation.get("liquidation_price_estimate"),
    )
    liquidation_price = None
    liquidation_buffer_upstream = first_number(
        fill.get("liquidation_buffer_bps"),
        allocation.get("liquidation_buffer_bps"),
    )
    liquidation_buffer = _liquidation_buffer_bps(
        side=side,
        entry_price=price,
        liquidation_price=liquidation_price,
    )
    reconciliation_reasons: list[str] = []
    if bracket_evidence is None:
        reconciliation_reasons.append(
            "MAINTENANCE_BRACKET_EVIDENCE_MISSING_FAIL_CLOSED"
        )
    for reason, upstream, canonical in (
        ("GROSS_NOTIONAL_RECOMPUTED_FROM_EXECUTED_QTY_PRICE", gross_notional_upstream, gross_notional),
        ("ALLOCATED_MARGIN_RECOMPUTED_FROM_NOTIONAL_LEVERAGE", allocated_margin_upstream, allocated_margin),
        ("MAINTENANCE_MARGIN_RECOMPUTED_FROM_EXECUTED_NOTIONAL", maintenance_margin_upstream, maintenance_margin),
        ("LIQUIDATION_PRICE_RECOMPUTED_FROM_EXECUTED_POSITION", liquidation_price_upstream, liquidation_price),
        ("LIQUIDATION_BUFFER_RECOMPUTED_FROM_LIQUIDATION_PRICE", liquidation_buffer_upstream, liquidation_buffer),
    ):
        if upstream is not None and not _accounting_values_match(upstream, canonical):
            reconciliation_reasons.append(reason)

    risk_budget_pct = first_number(allocation.get("risk_budget_pct_of_equity"), allocation.get("risk_budget_pct"))
    allocation_equity = _nested_first_number(allocation.get("model_inputs"), "equity")
    risk_budget = first_number(fill.get("risk_budget_usd"), allocation.get("risk_budget_usd"))
    risk_budget_source = None
    if risk_budget is None and risk_budget_pct is not None and allocation_equity is not None:
        risk_budget = allocation_equity * risk_budget_pct
        risk_budget_source = "adaptive_allocation.risk_budget_pct_of_equity"
    micro = fill.get("microstructure_context") if isinstance(fill.get("microstructure_context"), dict) else {}
    features = fill.get("features") if isinstance(fill.get("features"), dict) else {}
    entry_spread = first_number(
        fill.get("actual_observed_spread_entry_bps"),
        fill.get("bid_ask_spread_bps"),
        micro.get("bid_ask_spread_bps"),
        micro.get("spread_bps"),
        micro.get("ob_spread_bps"),
    )
    expected_slippage_bps = first_number(fill.get("expected_slippage_bps"), fill.get("slippage_bps"))
    expected_slippage_usd = first_number(fill.get("expected_slippage_usd"))
    if expected_slippage_usd is None and expected_slippage_bps is not None:
        expected_slippage_usd = gross_notional * max(0.0, expected_slippage_bps) / 10000.0
    expected_fees_usd = first_number(fill.get("expected_fees_usd"), allocation.get("expected_fees_usd"))
    entry_fee_bps = first_number(
        fill.get("actual_fee_bps"),
        fill.get("fee_bps"),
        fill.get("taker_fee_bps"),
        fill.get("expected_fee_bps"),
    )
    entry_fee_usd = first_number(
        fill.get("entry_fee_usd"),
        fill.get("actual_entry_fee_usd"),
        fill.get("actual_fees_usd"),
        fill.get("fee_usd"),
        fill.get("fee_usdt"),
    )
    entry_fee_source = None
    if entry_fee_usd is not None:
        entry_fee_source = str(
            first_present(
                fill.get("entry_fee_source"),
                fill.get("actual_fee_source"),
                "PAPER_FILL_EXPLICIT_ENTRY_FEE_USD",
            )
        )
    elif entry_fee_bps is not None:
        entry_fee_usd = gross_notional * max(0.0, entry_fee_bps) / 10000.0
        entry_fee_source = str(
            first_present(
                fill.get("fee_bps_source"),
                "PAPER_FILL_PER_SIDE_FEE_BPS_X_ENTRY_NOTIONAL",
            )
        )
    elif expected_fees_usd is not None:
        # The adaptive allocator's expected_fees_usd is one entry/exit side:
        # allocator.py computes notional * per-side fee_bps / 10_000.
        entry_fee_usd = max(0.0, expected_fees_usd)
        entry_fee_source = "ADAPTIVE_ALLOCATOR_EXPECTED_ENTRY_FEE_USD_PER_SIDE"

    entry_slippage_usd = first_number(
        fill.get("entry_slippage_usd"),
        fill.get("actual_entry_slippage_usd"),
        fill.get("actual_slippage_usd"),
        fill.get("realized_slippage_usd"),
    )
    entry_slippage_source = None
    if entry_slippage_usd is not None:
        entry_slippage_source = str(
            first_present(
                fill.get("entry_slippage_source"),
                fill.get("realized_slippage_source"),
                fill.get("expected_slippage_source"),
                "PAPER_FILL_EXPLICIT_ENTRY_SLIPPAGE_USD",
            )
        )
    elif expected_slippage_usd is not None:
        entry_slippage_usd = max(0.0, expected_slippage_usd)
        entry_slippage_source = str(
            first_present(
                fill.get("expected_slippage_source"),
                "PAPER_FILL_EXPECTED_ENTRY_SLIPPAGE_USD_PER_SIDE",
            )
        )
    elif expected_slippage_bps is not None:
        entry_slippage_usd = (
            gross_notional * max(0.0, expected_slippage_bps) / 10000.0
        )
        entry_slippage_source = str(
            first_present(
                fill.get("expected_slippage_source"),
                "PAPER_FILL_PER_SIDE_SLIPPAGE_BPS_X_ENTRY_NOTIONAL",
            )
        )
    entry_cost_basis_status = (
        "COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS"
        if entry_fee_usd is not None and entry_slippage_usd is not None
        else "INCOMPLETE_ENTRY_FEE_OR_SLIPPAGE_USD_BASIS"
    )
    expected_funding_bps = first_number(
        fill.get("expected_funding_bps"),
        fill.get("funding_bps"),
        fill.get("funding_rate_bps"),
        allocation.get("expected_funding_bps"),
        allocation_model_inputs.get("expected_funding_bps"),
        allocation_model_inputs.get("funding_bps"),
        allocation_model_inputs.get("funding_rate_bps"),
    )
    funding_rate = first_number(fill.get("funding_rate"), allocation_model_inputs.get("funding_rate"))
    if funding_rate is None and expected_funding_bps is not None:
        funding_rate = expected_funding_bps / 10000.0
    if expected_funding_bps is None and funding_rate is not None:
        expected_funding_bps = funding_rate * 10000.0
    funding_interval_seconds = first_number(
        fill.get("funding_interval_seconds"),
        allocation_model_inputs.get("funding_interval_seconds"),
        28800.0,
    )
    expected_funding_usd = first_number(fill.get("expected_funding_usd"), allocation.get("expected_funding_usd"))
    expected_net_pnl_usd = first_number(fill.get("expected_net_pnl_usd"), allocation.get("expected_net_pnl_usd"))
    expected_shortfall_usd = first_number(fill.get("expected_shortfall_usd"), allocation.get("expected_shortfall_usd"))
    hedge_budget_usd = first_number(fill.get("hedge_budget_usd"), allocation.get("hedge_budget_usd"))
    correlation_exposure_pct = first_number(
        fill.get("correlation_exposure_pct"),
        allocation.get("correlation_exposure_pct"),
        allocation_model_inputs.get("correlation_exposure_pct"),
    )
    correlation_input_source = first_present(
        fill.get("correlation_input_source"),
        allocation.get("correlation_input_source"),
        allocation_model_inputs.get("correlation_input_source"),
        "ADAPTIVE_ALLOCATION_MODEL_INPUTS" if correlation_exposure_pct is not None else None,
    )
    correlation_input_status = first_present(
        fill.get("correlation_input_status"),
        allocation.get("correlation_input_status"),
        allocation_model_inputs.get("correlation_input_status"),
        "READY" if correlation_exposure_pct is not None else None,
    )
    correlation_pair_count_float = first_number(
        fill.get("correlation_pair_count"),
        allocation.get("correlation_pair_count"),
        allocation_model_inputs.get("correlation_pair_count"),
    )
    correlation_pair_count = (
        int(correlation_pair_count_float)
        if correlation_pair_count_float is not None and correlation_pair_count_float >= 0
        else None
    )
    recommended_margin_mode = str(
        first_present(
            fill.get("recommended_margin_mode"),
            allocation.get("recommended_margin_mode"),
            "isolated_paper_simulated",
        )
    )
    adaptive_capital_policy_version = first_present(
        fill.get("adaptive_capital_policy_version"),
        allocation.get("adaptive_capital_policy_version"),
    )
    policy_activated_at = (
        first_present(
            fill.get("policy_activated_at"),
            allocation.get("policy_activated_at"),
            entry_time_utc,
        )
        if adaptive_capital_policy_version
        else None
    )
    squeeze_score = first_number(fill.get("squeeze_evidence_score"))
    source_hashes = fill.get("source_hashes") if isinstance(fill.get("source_hashes"), dict) else {}
    if not source_hashes:
        source_hashes = {
            key: value
            for key, value in {
                "feature_vector_hash": first_present(
                    fill.get("feature_vector_hash"),
                    fill.get("input_feature_hash"),
                ),
                "prediction_hash": fill.get("prediction_hash"),
                "source_lineage_hash": fill.get("source_lineage_hash"),
            }.items()
            if value not in (None, "")
        }
    action_probabilities = first_present(
        fill.get("action_probabilities"),
        fill.get("policy_action_probabilities"),
        allocation.get("action_probabilities"),
        allocation_model_inputs.get("action_probabilities"),
    )
    if not isinstance(action_probabilities, (dict, list, tuple)):
        action_probabilities = None
    action_labels = first_present(
        fill.get("action_labels"),
        allocation.get("action_labels"),
        allocation_model_inputs.get("action_labels"),
    )
    if not isinstance(action_labels, (list, tuple)):
        action_labels = None
    raw_action_logits = first_present(
        fill.get("raw_action_logits"),
        allocation.get("raw_action_logits"),
        allocation_model_inputs.get("raw_action_logits"),
    )
    if not isinstance(raw_action_logits, (list, tuple)):
        raw_action_logits = None
    raw_action_probabilities = first_present(
        fill.get("raw_action_probabilities"),
        allocation.get("raw_action_probabilities"),
        allocation_model_inputs.get("raw_action_probabilities"),
    )
    if not isinstance(raw_action_probabilities, (list, tuple)):
        raw_action_probabilities = None
    behavior_action_mask = first_present(
        fill.get("behavior_action_mask"),
        allocation.get("behavior_action_mask"),
        allocation_model_inputs.get("behavior_action_mask"),
    )
    if not isinstance(behavior_action_mask, (list, tuple)):
        behavior_action_mask = None
    behavior_policy_receipt = first_present(
        fill.get("behavior_policy_receipt"),
        allocation.get("behavior_policy_receipt"),
        allocation_model_inputs.get("behavior_policy_receipt"),
    )
    if not isinstance(behavior_policy_receipt, dict):
        behavior_policy_receipt = None
    provider_hashes = (
        fill.get("provider_hashes")
        if isinstance(fill.get("provider_hashes"), dict)
        else allocation.get("provider_hashes")
        if isinstance(allocation.get("provider_hashes"), dict)
        else None
    )
    if not provider_hashes and isinstance(source_hashes, dict):
        provider_hashes = {
            key: value
            for key, value in source_hashes.items()
            if key not in {"feature_vector_hash", "prediction_hash", "source_lineage_hash"}
            and value not in (None, "")
        } or None
    feature_vector_hash = first_present(
        fill.get("feature_vector_hash"),
        fill.get("input_feature_hash"),
        source_hashes.get("feature_vector_hash") if isinstance(source_hashes, dict) else None,
        allocation.get("feature_vector_hash"),
    )
    candidate_id = first_present(fill.get("candidate_id"), allocation.get("candidate_id"))
    paper_opportunity_tier = first_present(fill.get("paper_opportunity_tier"), allocation.get("paper_opportunity_tier"))
    materialization_queue_id = first_present(
        fill.get("materialization_queue_id"),
        allocation.get("materialization_queue_id"),
    )
    if (
        materialization_queue_id in (None, "")
        and str(paper_opportunity_tier or "").strip().upper() == "PAPER_RISK_CONTROLLER_EXPLORATION"
        and first_present(candidate_id, fill.get("prediction_id"), fill.get("signal_id")) not in (None, "")
    ):
        materialization_queue_id = (
            "paper_exploration_materialize_"
            + str(first_present(candidate_id, fill.get("prediction_id"), fill.get("signal_id")))
        )
    allocator_decision_id = first_present(
        fill.get("allocator_decision_id"),
        allocation.get("allocator_decision_id"),
    )
    confidence_raw = first_number(
        fill.get("confidence_raw"),
        allocation.get("confidence_raw"),
        allocation_model_inputs.get("confidence_raw"),
    )
    confidence_calibrated = first_number(
        fill.get("confidence_calibrated"),
        fill.get("confidence"),
        allocation.get("confidence_calibrated"),
        allocation.get("confidence"),
        allocation_model_inputs.get("confidence_calibrated"),
        allocation_model_inputs.get("confidence"),
    )
    confidence_executable_trade = first_number(
        fill.get("confidence_executable_trade"),
        allocation.get("confidence_executable_trade"),
        allocation_model_inputs.get("confidence_executable_trade"),
    )
    dynamic_exploration_floor = first_number(
        fill.get("dynamic_exploration_floor"),
        allocation.get("dynamic_exploration_floor"),
        allocation_model_inputs.get("dynamic_exploration_floor"),
    )
    exploration_floor_inputs = first_present(
        fill.get("exploration_floor_inputs"),
        fill.get("floor_inputs"),
        allocation.get("exploration_floor_inputs"),
        allocation.get("floor_inputs"),
        allocation_model_inputs.get("exploration_floor_inputs"),
        allocation_model_inputs.get("floor_inputs"),
    )
    if not isinstance(exploration_floor_inputs, dict):
        exploration_floor_inputs = None
    bootstrap_overridden_blockers = first_present(
        fill.get("bootstrap_overridden_blockers"),
        allocation.get("bootstrap_overridden_blockers"),
        allocation_model_inputs.get("bootstrap_overridden_blockers"),
    )
    if not isinstance(bootstrap_overridden_blockers, list):
        bootstrap_overridden_blockers = None
    expected_move_bps = first_number(
        fill.get("expected_move_bps"),
        fill.get("price_target_bps"),
        allocation.get("expected_move_bps"),
        allocation.get("price_target_bps"),
        allocation_model_inputs.get("expected_move_bps"),
        allocation_model_inputs.get("price_target_bps"),
    )
    expected_move_after_cost_bps = first_number(
        fill.get("expected_move_after_cost_bps"),
        allocation.get("expected_move_after_cost_bps"),
        allocation.get("expected_net_edge_bps"),
        allocation_model_inputs.get("expected_move_after_cost_bps"),
        allocation_model_inputs.get("expected_net_edge_bps"),
    )
    selected_action_probability = first_number(
        fill.get("selected_action_probability"),
        fill.get("action_probability"),
        fill.get("probability_selected_action"),
        allocation.get("selected_action_probability"),
        allocation_model_inputs.get("selected_action_probability"),
    )
    selected_action_index_raw = first_number(
        fill.get("selected_action_index"),
        allocation.get("selected_action_index"),
        allocation_model_inputs.get("selected_action_index"),
    )
    behavior_action_index_raw = first_number(
        fill.get("behavior_action_index"),
        allocation.get("behavior_action_index"),
        allocation_model_inputs.get("behavior_action_index"),
    )
    policy_value = first_number(
        fill.get("policy_value"),
        fill.get("value_estimate"),
        allocation.get("policy_value"),
        allocation_model_inputs.get("policy_value"),
    )
    value_baseline = first_number(
        fill.get("value_baseline"),
        allocation.get("value_baseline"),
        allocation_model_inputs.get("value_baseline"),
    )
    # PPO on-policy entry lineage: each field is recovered only under its own
    # name from the entry fill record; no cross-field backfill here (the
    # feedback builder owns its own eligibility fallbacks).
    selected_action_log_prob = first_number(
        fill.get("selected_action_log_prob"),
        allocation.get("selected_action_log_prob"),
        allocation_model_inputs.get("selected_action_log_prob"),
    )
    old_log_prob = first_number(
        fill.get("old_log_prob"),
        allocation.get("old_log_prob"),
        allocation_model_inputs.get("old_log_prob"),
    )
    old_value = first_number(
        fill.get("old_value"),
        allocation.get("old_value"),
        allocation_model_inputs.get("old_value"),
    )
    rollout_id = first_present(
        fill.get("rollout_id"),
        allocation.get("rollout_id"),
        allocation_model_inputs.get("rollout_id"),
    )
    trajectory_index_raw = first_number(
        fill.get("trajectory_index"),
        allocation.get("trajectory_index"),
        allocation_model_inputs.get("trajectory_index"),
    )
    ppo_on_policy_entry_fields_present = first_present(
        fill.get("ppo_on_policy_entry_fields_present"),
        allocation.get("ppo_on_policy_entry_fields_present"),
        allocation_model_inputs.get("ppo_on_policy_entry_fields_present"),
    )
    behavior_policy_receipt_write_success = first_present(
        fill.get("behavior_policy_receipt_write_success"),
        allocation.get("behavior_policy_receipt_write_success"),
        allocation_model_inputs.get("behavior_policy_receipt_write_success"),
    )
    on_policy_action_receipt_valid = first_present(
        fill.get("on_policy_action_receipt_valid"),
        allocation.get("on_policy_action_receipt_valid"),
        allocation_model_inputs.get("on_policy_action_receipt_valid"),
    )
    on_policy_action_receipt_prevalidated = first_present(
        fill.get("on_policy_action_receipt_prevalidated"),
        allocation.get("on_policy_action_receipt_prevalidated"),
        allocation_model_inputs.get("on_policy_action_receipt_prevalidated"),
    )
    behavior_policy_receipt_entry_event_pending = first_present(
        fill.get("behavior_policy_receipt_entry_event_pending"),
        allocation.get("behavior_policy_receipt_entry_event_pending"),
        allocation_model_inputs.get(
            "behavior_policy_receipt_entry_event_pending"
        ),
    )
    on_policy_sampling_selected = first_present(
        fill.get("on_policy_sampling_selected"),
        allocation.get("on_policy_sampling_selected"),
        allocation_model_inputs.get("on_policy_sampling_selected"),
    )
    on_policy_sampling_requested = first_present(
        fill.get("on_policy_sampling_requested"),
        allocation.get("on_policy_sampling_requested"),
        allocation_model_inputs.get("on_policy_sampling_requested"),
    )
    on_policy_sampling_counts_as_a_plus_evidence = first_present(
        fill.get("on_policy_sampling_counts_as_a_plus_evidence"),
        allocation.get("on_policy_sampling_counts_as_a_plus_evidence"),
        allocation_model_inputs.get(
            "on_policy_sampling_counts_as_a_plus_evidence"
        ),
    )
    on_policy_sampling_routes_to_live = first_present(
        fill.get("on_policy_sampling_routes_to_live"),
        allocation.get("on_policy_sampling_routes_to_live"),
        allocation_model_inputs.get("on_policy_sampling_routes_to_live"),
    )
    strategy_supply_hypothesis = first_present(
        fill.get("strategy_supply_hypothesis"),
        allocation.get("strategy_supply_hypothesis"),
        allocation_model_inputs.get("strategy_supply_hypothesis"),
    )
    entry_policy_fields_source = first_present(
        fill.get("entry_policy_fields_source"),
        allocation.get("entry_policy_fields_source"),
        allocation_model_inputs.get("entry_policy_fields_source"),
    )
    paper_learning_lane = first_present(
        fill.get("paper_learning_lane"),
        allocation.get("paper_learning_lane"),
        allocation_model_inputs.get("paper_learning_lane"),
    )
    missing_score_fields = [
        field
        for field, value in (
            ("confidence_calibrated", confidence_calibrated),
            ("expected_move_after_cost_bps", expected_move_after_cost_bps),
        )
        if value is None
    ]
    prediction_score_source = (
        "ENTRY_FILL_VERIFIED_PREDICTION_SCORE_FIELDS"
        if not missing_score_fields
        else None
    )
    prediction_score_missing_reason = (
        None
        if not missing_score_fields
        else "MISSING_ENTRY_PREDICTION_SCORE_FIELDS:" + ",".join(missing_score_fields)
    )
    is_hedge_child = bool(fill.get("hedge_intent") is True and fill.get("hedge_parent_id"))
    legacy_position_id = (
        f"paper_pos_{symbol}_hedge" if is_hedge_child else f"paper_pos_{symbol}"
    )
    position_id = f"{legacy_position_id}_{generation.generation_id[:16]}"
    position = PaperNetPosition(
        position_id=position_id,
        symbol=symbol,
        side=side,
        net_quantity=quantity,
        avg_entry_price=price,
        opened_est=opened,
        legacy_position_id=legacy_position_id,
        position_generation_id=generation.generation_id,
        position_id_version=POSITION_ID_VERSION,
        entry_generation_time_utc=generation.entry_time_utc,
        source_signal_id=fill.get("signal_id"),
        prediction_id=fill.get("prediction_id") or fill.get("source_prediction_id"),
        preemptive_decision_id=first_present(
            fill.get("preemptive_decision_id"),
            fill.get("runtime_revalidated_preemptive_decision_id"),
            allocation.get("preemptive_decision_id"),
            allocation.get("runtime_revalidated_preemptive_decision_id"),
            allocation_model_inputs.get("preemptive_decision_id"),
            allocation_model_inputs.get("runtime_revalidated_preemptive_decision_id"),
        ),
        risk_decision_id=fill.get("risk_decision_id"),
        orchestrator_decision_id=fill.get("orchestrator_decision_id"),
        allocator_decision_id=allocator_decision_id,
        materialization_queue_id=materialization_queue_id,
        materialization_queue_accepted_at=first_present(
            fill.get("materialization_queue_accepted_at"),
            allocation.get("materialization_queue_accepted_at"),
        ),
        materialization_queue_expires_at=first_present(
            fill.get("materialization_queue_expires_at"),
            allocation.get("materialization_queue_expires_at"),
        ),
        market_state_id=fill.get("market_state_id"),
        trainer_source=fill.get("trainer_source"),
        timeframe=fill.get("timeframe"),
        feature_snapshot_id=(
            fill.get("feature_snapshot_id")
            or fill.get("entry_feature_snapshot_id")
        ),
        feature_tensor_id=first_present(
            fill.get("feature_tensor_id"),
            allocation.get("feature_tensor_id"),
            allocation_model_inputs.get("feature_tensor_id"),
        ),
        decision_id=fill.get("decision_id") or fill.get("orchestrator_decision_id"),
        mtf_snapshot_id=fill.get("mtf_snapshot_id"),
        feature_cutoff=first_present(fill.get("feature_cutoff"), fill.get("entry_feature_cutoff")),
        decision_time=first_present(fill.get("decision_time"), fill.get("entry_feature_decision_time")),
        available_at=first_present(fill.get("available_at"), fill.get("entry_feature_available_at")),
        selected_action=fill.get("selected_action") or fill.get("side") or side,
        model_version=first_present(fill.get("model_version"), fill.get("model_source"), fill.get("model_id")),
        checkpoint_id=fill.get("checkpoint_id"),
        checkpoint_id_source=fill.get("checkpoint_id_source"),
        entry_prediction_snapshot=fill.get("entry_prediction_snapshot")
        if isinstance(fill.get("entry_prediction_snapshot"), dict)
        else None,
        risk_decision_record_key=fill.get("risk_decision_record_key"),
        risk_decision_record_hash=fill.get("risk_decision_record_hash"),
        risk_decision_record_resolved=(
            fill.get("risk_decision_record_resolved")
            if isinstance(fill.get("risk_decision_record_resolved"), bool)
            else None
        ),
        risk_decision_source=fill.get("risk_decision_source"),
        orchestrator_decision_record_key=fill.get("orchestrator_decision_record_key"),
        orchestrator_decision_record_hash=fill.get("orchestrator_decision_record_hash"),
        orchestrator_decision_record_resolved=(
            fill.get("orchestrator_decision_record_resolved")
            if isinstance(fill.get("orchestrator_decision_record_resolved"), bool)
            else None
        ),
        orchestrator_decision_source=fill.get("orchestrator_decision_source"),
        decision_record_missing_reasons=(
            list(fill.get("decision_record_missing_reasons"))
            if isinstance(fill.get("decision_record_missing_reasons"), list)
            else None
        ),
        source_hashes=source_hashes or None,
        feature_vector_hash=feature_vector_hash,
        provider_hashes=dict(provider_hashes) if provider_hashes else None,
        confidence_raw=confidence_raw,
        confidence_calibrated=confidence_calibrated,
        confidence_executable_trade=confidence_executable_trade,
        dynamic_exploration_floor=dynamic_exploration_floor,
        dynamic_exploration_floor_formula=first_present(
            fill.get("dynamic_exploration_floor_formula"),
            allocation.get("dynamic_exploration_floor_formula"),
            allocation_model_inputs.get("dynamic_exploration_floor_formula"),
        ),
        exploration_floor_inputs=exploration_floor_inputs,
        paper_risk_controller_exploration_above_floor=first_present(
            fill.get("paper_risk_controller_exploration_above_floor"),
            fill.get("above_dynamic_floor"),
            allocation.get("paper_risk_controller_exploration_above_floor"),
            allocation.get("above_dynamic_floor"),
            allocation_model_inputs.get("paper_risk_controller_exploration_above_floor"),
            allocation_model_inputs.get("above_dynamic_floor"),
        ),
        paper_risk_controller_exploration_eligible=first_present(
            fill.get("paper_risk_controller_exploration_eligible"),
            allocation.get("paper_risk_controller_exploration_eligible"),
            allocation_model_inputs.get("paper_risk_controller_exploration_eligible"),
        ),
        bootstrap_exploration=first_present(
            fill.get("bootstrap_exploration"),
            allocation.get("bootstrap_exploration"),
            allocation_model_inputs.get("bootstrap_exploration"),
        ),
        bootstrap_overridden_blockers=bootstrap_overridden_blockers,
        action_labels=list(action_labels) if action_labels is not None else None,
        raw_action_logits=(
            list(raw_action_logits) if raw_action_logits is not None else None
        ),
        raw_action_probabilities=(
            list(raw_action_probabilities)
            if raw_action_probabilities is not None
            else None
        ),
        selected_action_probability=selected_action_probability,
        selected_action_index=(
            int(selected_action_index_raw)
            if selected_action_index_raw is not None
            else None
        ),
        expected_move_bps=expected_move_bps,
        action_probabilities=(
            list(action_probabilities)
            if isinstance(action_probabilities, tuple)
            else action_probabilities
        ),
        policy_value=policy_value,
        value_baseline=value_baseline,
        selected_action_log_prob=selected_action_log_prob,
        old_log_prob=old_log_prob,
        old_value=old_value,
        rollout_id=str(rollout_id) if rollout_id is not None else None,
        trajectory_index=(
            int(trajectory_index_raw) if trajectory_index_raw is not None else None
        ),
        ppo_on_policy_entry_fields_present=(
            bool(ppo_on_policy_entry_fields_present)
            if ppo_on_policy_entry_fields_present is not None
            else None
        ),
        ppo_on_policy_ineligible_reason=first_present(
            fill.get("ppo_on_policy_ineligible_reason"),
            allocation.get("ppo_on_policy_ineligible_reason"),
            allocation_model_inputs.get("ppo_on_policy_ineligible_reason"),
        ),
        behavior_action_index=(
            int(behavior_action_index_raw)
            if behavior_action_index_raw is not None
            else None
        ),
        behavior_action=first_present(
            fill.get("behavior_action"),
            allocation.get("behavior_action"),
            allocation_model_inputs.get("behavior_action"),
        ),
        behavior_action_mask=(
            list(behavior_action_mask)
            if behavior_action_mask is not None
            else None
        ),
        behavior_action_source=first_present(
            fill.get("behavior_action_source"),
            allocation.get("behavior_action_source"),
            allocation_model_inputs.get("behavior_action_source"),
        ),
        behavior_policy_sampling_mode=first_present(
            fill.get("behavior_policy_sampling_mode"),
            allocation.get("behavior_policy_sampling_mode"),
            allocation_model_inputs.get("behavior_policy_sampling_mode"),
        ),
        behavior_policy_distribution_contract=first_present(
            fill.get("behavior_policy_distribution_contract"),
            allocation.get("behavior_policy_distribution_contract"),
            allocation_model_inputs.get("behavior_policy_distribution_contract"),
        ),
        behavior_policy_fingerprint=first_present(
            fill.get("behavior_policy_fingerprint"),
            allocation.get("behavior_policy_fingerprint"),
            allocation_model_inputs.get("behavior_policy_fingerprint"),
        ),
        behavior_policy_checkpoint_hash=first_present(
            fill.get("behavior_policy_checkpoint_hash"),
            allocation.get("behavior_policy_checkpoint_hash"),
            allocation_model_inputs.get("behavior_policy_checkpoint_hash"),
        ),
        behavior_policy_receipt=(
            dict(behavior_policy_receipt)
            if behavior_policy_receipt is not None
            else None
        ),
        behavior_policy_receipt_hash=first_present(
            fill.get("behavior_policy_receipt_hash"),
            allocation.get("behavior_policy_receipt_hash"),
            allocation_model_inputs.get("behavior_policy_receipt_hash"),
        ),
        behavior_policy_receipt_key=first_present(
            fill.get("behavior_policy_receipt_key"),
            allocation.get("behavior_policy_receipt_key"),
            allocation_model_inputs.get("behavior_policy_receipt_key"),
        ),
        behavior_policy_receipt_write_success=(
            bool(behavior_policy_receipt_write_success)
            if behavior_policy_receipt_write_success is not None
            else None
        ),
        exact_on_policy_position_lineage_schema_version=(
            first_present(
                fill.get("exact_on_policy_position_lineage_schema_version"),
                allocation.get(
                    "exact_on_policy_position_lineage_schema_version"
                ),
                allocation_model_inputs.get(
                    "exact_on_policy_position_lineage_schema_version"
                ),
            )
            or (
                EXACT_ON_POLICY_POSITION_LINEAGE_SCHEMA_VERSION
                if ppo_on_policy_entry_fields_present is True
                else None
            )
        ),
        behavior_policy_receipt_archive_entry_event_hash=first_present(
            fill.get("behavior_policy_receipt_archive_entry_event_hash"),
            allocation.get("behavior_policy_receipt_archive_entry_event_hash"),
            allocation_model_inputs.get(
                "behavior_policy_receipt_archive_entry_event_hash"
            ),
        ),
        behavior_policy_receipt_archive_verified_at_entry=first_present(
            fill.get("behavior_policy_receipt_archive_verified_at_entry"),
            allocation.get("behavior_policy_receipt_archive_verified_at_entry"),
            allocation_model_inputs.get(
                "behavior_policy_receipt_archive_verified_at_entry"
            ),
        ),
        behavior_policy_receipt_archive_retention_required=first_present(
            fill.get("behavior_policy_receipt_archive_retention_required"),
            allocation.get(
                "behavior_policy_receipt_archive_retention_required"
            ),
            allocation_model_inputs.get(
                "behavior_policy_receipt_archive_retention_required"
            ),
        ),
        behavior_policy_receipt_entry_event_pending=(
            bool(behavior_policy_receipt_entry_event_pending)
            if behavior_policy_receipt_entry_event_pending is not None
            else None
        ),
        on_policy_action_receipt_prevalidated=(
            bool(on_policy_action_receipt_prevalidated)
            if on_policy_action_receipt_prevalidated is not None
            else None
        ),
        on_policy_action_receipt_valid=(
            bool(on_policy_action_receipt_valid)
            if on_policy_action_receipt_valid is not None
            else None
        ),
        exact_on_policy_entry_outbox_record_id=first_present(
            fill.get("exact_on_policy_entry_outbox_record_id"),
            allocation.get("exact_on_policy_entry_outbox_record_id"),
            allocation_model_inputs.get("exact_on_policy_entry_outbox_record_id"),
        ),
        exact_on_policy_entry_outbox_state=first_present(
            fill.get("exact_on_policy_entry_outbox_state"),
            allocation.get("exact_on_policy_entry_outbox_state"),
            allocation_model_inputs.get("exact_on_policy_entry_outbox_state"),
        ),
        exact_on_policy_sealed_fill_sha256=first_present(
            fill.get("exact_on_policy_sealed_fill_sha256"),
            allocation.get("exact_on_policy_sealed_fill_sha256"),
            allocation_model_inputs.get("exact_on_policy_sealed_fill_sha256"),
        ),
        on_policy_sampling_selected=(
            bool(on_policy_sampling_selected)
            if on_policy_sampling_selected is not None
            else None
        ),
        on_policy_sampling_requested=(
            bool(on_policy_sampling_requested)
            if on_policy_sampling_requested is not None
            else None
        ),
        on_policy_sampling_plan_hash=first_present(
            fill.get("on_policy_sampling_plan_hash"),
            allocation.get("on_policy_sampling_plan_hash"),
            allocation_model_inputs.get("on_policy_sampling_plan_hash"),
        ),
        on_policy_sampling_plan_input_hash=first_present(
            fill.get("on_policy_sampling_plan_input_hash"),
            allocation.get("on_policy_sampling_plan_input_hash"),
            allocation_model_inputs.get("on_policy_sampling_plan_input_hash"),
        ),
        on_policy_sampling_lane=first_present(
            fill.get("on_policy_sampling_lane"),
            allocation.get("on_policy_sampling_lane"),
            allocation_model_inputs.get("on_policy_sampling_lane"),
        ),
        on_policy_sampling_evidence_class=first_present(
            fill.get("on_policy_sampling_evidence_class"),
            allocation.get("on_policy_sampling_evidence_class"),
            allocation_model_inputs.get("on_policy_sampling_evidence_class"),
        ),
        on_policy_sampling_counts_as_a_plus_evidence=(
            bool(on_policy_sampling_counts_as_a_plus_evidence)
            if on_policy_sampling_counts_as_a_plus_evidence is not None
            else None
        ),
        on_policy_sampling_routes_to_live=(
            bool(on_policy_sampling_routes_to_live)
            if on_policy_sampling_routes_to_live is not None
            else None
        ),
        strategy_supply_hypothesis=(
            bool(strategy_supply_hypothesis)
            if strategy_supply_hypothesis is not None
            else None
        ),
        entry_policy_fields_source=entry_policy_fields_source,
        paper_learning_lane=paper_learning_lane,
        prediction_score_source=prediction_score_source,
        prediction_score_missing_reason=prediction_score_missing_reason,
        candidate_id=candidate_id,
        paper_policy_owner=first_present(
            fill.get("paper_policy_owner"),
            allocation.get("paper_policy_owner"),
            fill.get("current_allowed_paper_owner"),
            allocation.get("current_allowed_paper_owner"),
        ),
        policy_fingerprint=first_present(
            fill.get("policy_fingerprint"),
            allocation.get("policy_fingerprint"),
            fill.get("selector_policy_fingerprint"),
            allocation.get("selector_policy_fingerprint"),
            fill.get("frozen_selector_fingerprint"),
            allocation.get("frozen_selector_fingerprint"),
        ),
        model_source=first_present(
            fill.get("model_source"),
            allocation.get("model_source"),
            fill.get("model_version"),
            allocation.get("model_version"),
            fill.get("model_id"),
            allocation.get("model_id"),
        ),
        selector_policy_fingerprint=first_present(
            fill.get("selector_policy_fingerprint"),
            allocation.get("selector_policy_fingerprint"),
            allocation_model_inputs.get("selector_policy_fingerprint"),
        ),
        frozen_selector_fingerprint=first_present(
            fill.get("frozen_selector_fingerprint"),
            allocation.get("frozen_selector_fingerprint"),
            allocation_model_inputs.get("frozen_selector_fingerprint"),
        ),
        candidate_selected_before_outcome=fill.get("candidate_selected_before_outcome")
        if isinstance(fill.get("candidate_selected_before_outcome"), bool)
        else allocation.get("candidate_selected_before_outcome")
        if isinstance(allocation.get("candidate_selected_before_outcome"), bool)
        else None,
        candidate_selected_after_outcome=fill.get("candidate_selected_after_outcome")
        if isinstance(fill.get("candidate_selected_after_outcome"), bool)
        else allocation.get("candidate_selected_after_outcome")
        if isinstance(allocation.get("candidate_selected_after_outcome"), bool)
        else None,
        post_outcome_candidate_selection=fill.get("post_outcome_candidate_selection")
        if isinstance(fill.get("post_outcome_candidate_selection"), bool)
        else allocation.get("post_outcome_candidate_selection")
        if isinstance(allocation.get("post_outcome_candidate_selection"), bool)
        else None,
        future_labels_used_as_features=fill.get("future_labels_used_as_features")
        if isinstance(fill.get("future_labels_used_as_features"), bool)
        else allocation.get("future_labels_used_as_features")
        if isinstance(allocation.get("future_labels_used_as_features"), bool)
        else None,
        paper_opportunity_tier=paper_opportunity_tier,
        paper_opportunity_tier_reason=first_present(
            fill.get("paper_opportunity_tier_reason"),
            allocation.get("paper_opportunity_tier_reason"),
        ),
        explicit_paper_opportunity_tier=first_present(
            fill.get("explicit_paper_opportunity_tier"),
            allocation.get("explicit_paper_opportunity_tier"),
        ),
        paper_fill_allowed_source=first_present(
            fill.get("paper_fill_allowed_source"),
            allocation.get("paper_fill_allowed_source"),
        ),
        strict_paper_fill_allowed_upstream=fill.get("strict_paper_fill_allowed_upstream")
        if isinstance(fill.get("strict_paper_fill_allowed_upstream"), bool)
        else allocation.get("strict_paper_fill_allowed_upstream")
        if isinstance(allocation.get("strict_paper_fill_allowed_upstream"), bool)
        else None,
        calibration_label_purpose=first_present(fill.get("calibration_label_purpose"), allocation.get("calibration_label_purpose")),
        entry_market_state_id=fill.get("market_state_id"),
        strategy_id=fill.get("strategy_id") or fill.get("strategy_selected_mode"),
        strategy_family=fill.get("strategy_family") or fill.get("strategy_selected_mode"),
        strategy_selected_mode=fill.get("strategy_selected_mode"),
        hedge_state=fill.get("hedge_state") or "NO_HEDGE",
        hedge_reason=fill.get("hedge_reason") or "NO_HEDGE_CONTEXT",
        hedge_parent_id=(
            str(fill.get("hedge_parent_id"))
            if fill.get("hedge_intent") is True and fill.get("hedge_parent_id")
            else None
        ),
        hedge_child_id=(
            str(fill.get("hedge_child_id"))
            if fill.get("hedge_intent") is True and fill.get("hedge_child_id")
            else None
        ),
        hedge_ratio=(
            coerce_float(fill.get("hedge_ratio"))
            if fill.get("hedge_intent") is True
            else None
        ),
        hedge_entry_parent_pnl_bps=(
            coerce_float(fill.get("hedge_entry_parent_pnl_bps"))
            if fill.get("hedge_intent") is True
            else None
        ),
        drawdown_at_entry=first_present(fill.get("drawdown_at_entry"), fill.get("drawdown_bps")),
        market_regime_at_entry=",".join(str(item) for item in fill.get("strategy_regime_labels") or [])
        if isinstance(fill.get("strategy_regime_labels"), list)
        else fill.get("market_regime_at_entry"),
        liquidity_zone_context=fill.get("liquidity_zone_context"),
        liquidation_distance_context=fill.get("liquidation_distance_context"),
        microstructure_context=fill.get("microstructure_context"),
        oi_funding_context=fill.get("oi_funding_context"),
        public_intel_context=fill.get("public_intel_context"),
        major_move_signal_id=fill.get("major_move_signal_id"),
        squeeze_evidence_score=squeeze_score,
        squeeze_evidence_source=fill.get("squeeze_evidence_source"),
        squeeze_evidence_components=fill.get("squeeze_evidence_components")
        if isinstance(fill.get("squeeze_evidence_components"), dict)
        else None,
        squeeze_evidence_unavailable_reason=(
            fill.get("squeeze_evidence_unavailable_reason")
            if fill.get("squeeze_evidence_unavailable_reason")
            else (None if squeeze_score is not None else "MISSING_ENTRY_SQUEEZE_EVIDENCE_SCORE")
        ),
        future_window_label_source=fill.get("future_window_label_source"),
        adaptive_allocation=dict(allocation) if allocation else None,
        adaptive_policy_authoritative=(
            fill.get("adaptive_policy_authoritative") is True
        ),
        adaptive_policy_action_id=(
            str(fill.get("adaptive_policy_action_id"))
            if fill.get("adaptive_policy_action_id") not in (None, "")
            else None
        ),
        adaptive_policy_action_sha256=(
            str(fill.get("adaptive_policy_action_sha256"))
            if fill.get("adaptive_policy_action_sha256") not in (None, "")
            else None
        ),
        adaptive_paper_policy_authorization_sha256=(
            str(fill.get("adaptive_paper_policy_authorization_sha256"))
            if fill.get("adaptive_paper_policy_authorization_sha256")
            not in (None, "")
            else None
        ),
        adaptive_policy_exit_plan=(
            dict(
                fill.get("exit_plan")
                if isinstance(fill.get("exit_plan"), dict)
                else fill.get("adaptive_policy_exit_plan")
            )
            if isinstance(
                fill.get("exit_plan")
                if isinstance(fill.get("exit_plan"), dict)
                else fill.get("adaptive_policy_exit_plan"),
                dict,
            )
            else None
        ),
        adaptive_policy_stop_price=first_number(
            (fill.get("exit_plan") or {}).get("stop_loss_price")
            if isinstance(fill.get("exit_plan"), dict)
            else None,
            fill.get("adaptive_policy_stop_price"),
            fill.get("stop_loss_price"),
            fill.get("stop_price"),
        ),
        adaptive_policy_profit_target_price=first_number(
            (fill.get("exit_plan") or {}).get("take_profit_price")
            if isinstance(fill.get("exit_plan"), dict)
            else None,
            fill.get("adaptive_policy_profit_target_price"),
        ),
        adaptive_policy_max_hold_seconds=first_number(
            (fill.get("exit_plan") or {}).get("max_hold_seconds")
            if isinstance(fill.get("exit_plan"), dict)
            else None,
            fill.get("adaptive_policy_max_hold_seconds"),
            fill.get("expected_holding_horizon_seconds"),
        ),
        adaptive_policy_time_exit_at=(
            str((fill.get("exit_plan") or {}).get("time_exit_at"))
            if isinstance(fill.get("exit_plan"), dict)
            and (fill.get("exit_plan") or {}).get("time_exit_at") not in (None, "")
            else (
                str(fill.get("adaptive_policy_time_exit_at"))
                if fill.get("adaptive_policy_time_exit_at") not in (None, "")
                else None
            )
        ),
        adaptive_capital_policy_version=adaptive_capital_policy_version,
        policy_activated_at=policy_activated_at,
        gross_notional_usd=gross_notional,
        gross_notional_usd_upstream=gross_notional_upstream,
        allocated_margin_usd=allocated_margin,
        allocated_margin_usd_upstream=allocated_margin_upstream,
        effective_leverage=effective_leverage,
        recommended_leverage=recommended_leverage,
        leverage_source=effective_leverage_source,
        leverage_recommendation_tier=(
            str(fill.get("leverage_recommendation_tier"))
            if fill.get("leverage_recommendation_tier")
            else None
        ),
        leverage_exploration=(
            bool(fill.get("leverage_exploration"))
            if fill.get("leverage_exploration") is not None
            else None
        ),
        recommended_margin_mode=recommended_margin_mode,
        margin_mode_simulated=str(
            first_present(
                fill.get("margin_mode_simulated"),
                recommended_margin_mode,
                "isolated_paper_simulated",
            )
        ),
        maintenance_margin_rate=maintenance_rate,
        maintenance_margin_cum=maintenance_cum,
        maintenance_margin_estimate=maintenance_margin,
        maintenance_margin_notional_usd=gross_notional,
        maintenance_margin_mark_price=price,
        maintenance_margin_mark_time=entry_time_utc,
        liquidation_price_estimate=liquidation_price,
        liquidation_buffer_bps=liquidation_buffer,
        capital_accounting_reconciled=bool(reconciliation_reasons),
        capital_accounting_reconciliation_reasons=list(reconciliation_reasons),
        risk_budget_usd=risk_budget,
        risk_budget_source=risk_budget_source or ("provided" if risk_budget is not None else None),
        stop_distance_bps=first_number(fill.get("stop_distance_bps"), allocation.get("stop_distance_bps")),
        expected_fees_usd=expected_fees_usd,
        expected_funding_bps=expected_funding_bps,
        funding_rate=funding_rate,
        funding_interval_seconds=funding_interval_seconds,
        expected_funding_usd=expected_funding_usd,
        expected_net_pnl_usd=expected_net_pnl_usd,
        expected_max_loss_usd=first_number(
            fill.get("expected_max_loss_usd"),
            fill.get("max_loss_if_stop_hit"),
            allocation.get("expected_max_loss_usd"),
            allocation.get("max_loss_if_stop_hit"),
        ),
        expected_shortfall_usd=expected_shortfall_usd,
        hedge_budget_usd=hedge_budget_usd,
        capital_allocation_reason=first_present(
            fill.get("capital_allocation_reason"),
            allocation.get("capital_allocation_reason"),
            allocation.get("final_size_reason"),
        ),
        entry_atr_bps=atr_bps_from_payloads(fill, features, price=price),
        entry_feature_available_at=fill.get("entry_feature_available_at"),
        entry_feature_generated_at=fill.get("entry_feature_generated_at"),
        entry_feature_cutoff=fill.get("entry_feature_cutoff"),
        entry_feature_decision_time=fill.get("entry_feature_decision_time"),
        entry_feature_source=fill.get("entry_feature_source"),
        entry_feature_candle_closed_confirmed=(
            fill.get("entry_feature_candle_closed_confirmed")
            if isinstance(fill.get("entry_feature_candle_closed_confirmed"), bool)
            else None
        ),
        entry_feature_unavailable_reason=fill.get("entry_feature_unavailable_reason"),
        entry_feature_snapshot=fill.get("entry_feature_snapshot")
        if isinstance(fill.get("entry_feature_snapshot"), dict)
        else None,
        entry_observed_spread_bps=entry_spread,
        entry_spread_source=(
            str(first_present(fill.get("entry_spread_source"), micro.get("source"), "V2_ENTRY_MICROSTRUCTURE_CONTEXT"))
            if entry_spread is not None
            else None
        ),
        entry_spread_unavailable_reason=(
            None if entry_spread is not None else "MISSING_ENTRY_OBSERVED_SPREAD_BPS"
        ),
        observed_bid=first_number(fill.get("observed_bid"), fill.get("best_bid")),
        observed_ask=first_number(fill.get("observed_ask"), fill.get("best_ask")),
        observed_spread_bps=first_number(fill.get("observed_spread_bps"), entry_spread),
        order_size=first_number(fill.get("order_size"), fill.get("notional"), fill.get("notional_usdt")),
        order_size_usd=first_number(fill.get("order_size_usd"), fill.get("order_size"), fill.get("notional")),
        top_book_bid_depth_usd=first_number(fill.get("top_book_bid_depth_usd"), fill.get("bid_depth_usd")),
        top_book_ask_depth_usd=first_number(fill.get("top_book_ask_depth_usd"), fill.get("ask_depth_usd")),
        depth_derived_price_impact_bps=first_number(
            fill.get("depth_derived_price_impact_bps"),
            fill.get("depth_price_impact_bps"),
        ),
        bid_depth_usd=first_number(fill.get("bid_depth_usd")),
        ask_depth_usd=first_number(fill.get("ask_depth_usd")),
        orderbook_depth_usd=first_number(fill.get("orderbook_depth_usd")),
        entry_orderbook_depth_usd=first_number(fill.get("entry_orderbook_depth_usd")),
        entry_orderbook_depth_side=fill.get("entry_orderbook_depth_side"),
        top_of_book_depth_usd=first_number(fill.get("top_of_book_depth_usd")),
        market_depth_usd=first_number(fill.get("market_depth_usd")),
        orderbook_depth_source=fill.get("orderbook_depth_source"),
        depth_utilization_pct=first_number(fill.get("depth_utilization_pct")),
        depth_price_impact_bps=first_number(fill.get("depth_price_impact_bps")),
        depth_price_impact_source=fill.get("depth_price_impact_source"),
        depth_price_impact_model=fill.get("depth_price_impact_model"),
        depth_price_impact_side=fill.get("depth_price_impact_side"),
        depth_price_impact_quantity=first_number(fill.get("depth_price_impact_quantity")),
        depth_price_impact_filled_quantity=first_number(fill.get("depth_price_impact_filled_quantity")),
        depth_price_impact_fill_complete=fill.get("depth_price_impact_fill_complete")
        if isinstance(fill.get("depth_price_impact_fill_complete"), bool)
        else None,
        depth_price_impact_vwap=first_number(fill.get("depth_price_impact_vwap")),
        depth_price_impact_touch_price=first_number(fill.get("depth_price_impact_touch_price")),
        expected_slippage_bps=expected_slippage_bps,
        expected_slippage_usd=expected_slippage_usd,
        expected_slippage_source=fill.get("expected_slippage_source"),
        expected_slippage_modeled=fill.get("expected_slippage_modeled")
        if isinstance(fill.get("expected_slippage_modeled"), bool)
        else None,
        expected_slippage_unavailable_reason=fill.get("expected_slippage_unavailable_reason"),
        correlation_exposure_pct=correlation_exposure_pct,
        correlation_input_source=correlation_input_source,
        correlation_input_status=correlation_input_status,
        correlation_pair_count=correlation_pair_count,
        correlation_diagnostics=fill.get("correlation_diagnostics")
        if isinstance(fill.get("correlation_diagnostics"), dict)
        else None,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
        decision_latency_ms=first_number(fill.get("decision_latency_ms"), fill.get("latency_ms")),
        latency_source=fill.get("latency_source"),
        latency_reserve_bps=first_number(fill.get("latency_reserve_bps")),
        latency_reserve_source=fill.get("latency_reserve_source"),
        maker_taker_assumption=fill.get("maker_taker_assumption"),
        maker_probability=first_number(fill.get("maker_probability")),
        taker_probability=first_number(fill.get("taker_probability")),
        maker_taker_probability=first_number(fill.get("maker_taker_probability")),
        maker_taker_probability_detail=fill.get("maker_taker_probability_detail")
        if isinstance(fill.get("maker_taker_probability_detail"), dict)
        else None,
        maker_taker_probabilities=fill.get("maker_taker_probabilities")
        if isinstance(fill.get("maker_taker_probabilities"), dict)
        else None,
        maker_taker_probability_source=fill.get("maker_taker_probability_source"),
        fee_schedule=fill.get("fee_schedule") if isinstance(fill.get("fee_schedule"), dict) else None,
        fee_bps=entry_fee_bps,
        fee_bps_source=fill.get("fee_bps_source"),
        fee_bps_configured_schedule=fill.get("fee_bps_configured_schedule")
        if isinstance(fill.get("fee_bps_configured_schedule"), bool)
        else None,
        entry_fees_incurred_usd=(
            max(0.0, entry_fee_usd) if entry_fee_usd is not None else None
        ),
        entry_fees_remaining_usd=(
            max(0.0, entry_fee_usd) if entry_fee_usd is not None else None
        ),
        entry_fee_fallback_bps_per_side=first_number(
            fill.get("entry_fee_fallback_bps_per_side")
        ),
        entry_slippage_incurred_usd=(
            max(0.0, entry_slippage_usd)
            if entry_slippage_usd is not None
            else None
        ),
        entry_slippage_remaining_usd=(
            max(0.0, entry_slippage_usd)
            if entry_slippage_usd is not None
            else None
        ),
        entry_slippage_fallback_bps_per_side=first_number(
            fill.get("entry_slippage_fallback_bps_per_side")
        ),
        entry_fee_cost_sources=(
            [entry_fee_source] if entry_fee_source is not None else []
        ),
        entry_slippage_cost_sources=(
            [entry_slippage_source]
            if entry_slippage_source is not None
            else []
        ),
        entry_cost_basis_status=entry_cost_basis_status,
        holding_period_funding_bps=first_number(fill.get("holding_period_funding_bps")),
        holding_period_funding_source=fill.get("holding_period_funding_source"),
        partial_fill_count=int(first_number(fill.get("partial_fill_count"), fill.get("fill_count")) or 0)
        if first_number(fill.get("partial_fill_count"), fill.get("fill_count")) is not None
        else None,
        partial_fill_estimate=fill.get("partial_fill_estimate")
        if isinstance(fill.get("partial_fill_estimate"), dict)
        else None,
        partial_fill_probability=first_number(fill.get("partial_fill_probability")),
        partial_fill_adjustment_bps=first_number(fill.get("partial_fill_adjustment_bps")),
        partial_fills=fill.get("partial_fills") if isinstance(fill.get("partial_fills"), list) else None,
        fill_count=int(first_number(fill.get("fill_count"), fill.get("partial_fill_count")) or 0)
        if first_number(fill.get("fill_count"), fill.get("partial_fill_count")) is not None
        else None,
        all_partial_fills=fill.get("all_partial_fills") if isinstance(fill.get("all_partial_fills"), list) else None,
        partial_fill_plan=fill.get("partial_fill_plan")
        if isinstance(fill.get("partial_fill_plan"), (dict, list))
        else None,
        execution_probability=first_number(fill.get("execution_probability")),
        mark_index_divergence_bps=first_number(fill.get("mark_index_divergence_bps")),
        mark_index_divergence=first_number(fill.get("mark_index_divergence")),
        mark_index_source=fill.get("mark_index_source"),
        mark_index_available_at=fill.get("mark_index_available_at"),
        mark_price=first_number(fill.get("mark_price")),
        index_price=first_number(fill.get("index_price")),
        cost_source=fill.get("cost_source"),
        cost_source_timestamp=fill.get("cost_source_timestamp"),
        source_timestamp=fill.get("source_timestamp"),
        cost_evidence_freshness_ms=first_number(fill.get("cost_evidence_freshness_ms")),
        cost_evidence_source_fields=fill.get("cost_evidence_source_fields")
        if isinstance(fill.get("cost_evidence_source_fields"), dict)
        else None,
        runtime_cost_capture_source=fill.get("runtime_cost_capture_source"),
        runtime_cost_capture_status=fill.get("runtime_cost_capture_status"),
        runtime_cost_capture_required_fields=list(fill.get("runtime_cost_capture_required_fields"))
        if isinstance(fill.get("runtime_cost_capture_required_fields"), list)
        else None,
        runtime_cost_capture_missing_fields=list(fill.get("runtime_cost_capture_missing_fields"))
        if isinstance(fill.get("runtime_cost_capture_missing_fields"), list)
        else None,
        runtime_cost_capture_explained_missing_fields=list(fill.get("runtime_cost_capture_explained_missing_fields"))
        if isinstance(fill.get("runtime_cost_capture_explained_missing_fields"), list)
        else None,
        runtime_cost_capture_unexplained_missing_fields=list(fill.get("runtime_cost_capture_unexplained_missing_fields"))
        if isinstance(fill.get("runtime_cost_capture_unexplained_missing_fields"), list)
        else None,
        runtime_cost_capture_order_cost_applicable=fill.get("runtime_cost_capture_order_cost_applicable")
        if isinstance(fill.get("runtime_cost_capture_order_cost_applicable"), bool)
        else None,
        runtime_cost_capture_no_order_reason=fill.get("runtime_cost_capture_no_order_reason"),
        runtime_cost_capture_temporal_reject_reasons=list(fill.get("runtime_cost_capture_temporal_reject_reasons"))
        if isinstance(fill.get("runtime_cost_capture_temporal_reject_reasons"), list)
        else None,
        fallback_cost_flag=fill.get("fallback_cost_flag")
        if isinstance(fill.get("fallback_cost_flag"), bool)
        else None,
        fallback=fill.get("fallback") if isinstance(fill.get("fallback"), bool) else None,
        production_grade_cost_flag=fill.get("production_grade_cost_flag")
        if isinstance(fill.get("production_grade_cost_flag"), bool)
        else None,
        production_grade_cost_evidence=fill.get("production_grade_cost_evidence")
        if isinstance(fill.get("production_grade_cost_evidence"), bool)
        else None,
        estimated_production_cost=first_number(fill.get("estimated_production_cost")),
        estimated_production_cost_bps=first_number(fill.get("estimated_production_cost_bps")),
        counts_as_production_grade_training_evidence=fill.get("counts_as_production_grade_training_evidence")
        if isinstance(fill.get("counts_as_production_grade_training_evidence"), bool)
        else None,
        fill_ids=[fill_id],
        best_favorable_price=price,
        worst_adverse_price=price,
        intra_trade_high_price=price,
        intra_trade_low_price=price,
        last_mark_price=price,
        last_mark_est=opened,  # initial mark uses same EST-converted open time
    )
    position.apply_maintenance_bracket_evidence(
        bracket_evidence,
        mark_price=price,
        mark_time=entry_time_utc,
    )
    return position
