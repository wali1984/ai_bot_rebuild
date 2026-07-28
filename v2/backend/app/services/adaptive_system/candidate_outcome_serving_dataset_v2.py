"""Serving-compatible training rows from authenticated candidate outcomes.

The candidate archive records every paper candidate, including rejected and
flat decisions.  This module turns complete matured revisions into supervised
rows without treating counterfactual outcomes as realized paper profit.  The
same :func:`build_serving_feature_vector` used by canonical serving constructs
every feature tensor.

This module has no execution, activation, registry, or Redis authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    CandidateDecisionOutcomeV2,
    CounterfactualScenarioV2,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_archive_v2 import (
    ARCHIVE_VERIFICATION_SCHEMA_VERSION,
    PINNED_PRODUCTION_WRITER_ID,
    PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_maturer_v2 import (
    counterfactual_reference_side,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    target_action_from_net_edges,
)
from v2.backend.app.services.prediction_serving.serving_dataset_v2 import (
    ACTION_LABELS,
)
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    build_serving_feature_vector,
    feature_abi_sha256,
    feature_builder_sha256,
)

DATASET_SCHEMA_VERSION = "adaptive_serving_compatible_dataset_v2"
MANIFEST_SCHEMA_VERSION = "adaptive_serving_compatible_dataset_manifest_v2"
PARITY_SCHEMA_VERSION = "adaptive_train_serve_feature_parity_report_v2"
SOURCE_SCHEMA_VERSION = "candidate_outcome_training_source_v2"
PURGE_POLICY = (
    "CHRONOLOGICAL_FEATURE_GROUP_SAFE;TRAIN_LABEL_AVAILABLE_BEFORE_VALIDATION;"
    "VALIDATION_LABEL_AVAILABLE_BEFORE_HOLDOUT;"
    "TWO_DECISION_TIME_GROUP_EMBARGO_BEFORE_VALIDATION_AND_HOLDOUT"
)
EMBARGO_GROUPS = 2
_SHA256_LENGTH = 64
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}$")
_SUPPORTED_TIMEFRAMES = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
)
_SOURCE_ARCHIVE_VERIFICATION_FIELDS = frozenset(
    {
        "schema_version",
        "archive_path",
        "writer_id",
        "writer_public_key_hex",
        "row_count",
        "decision_revision_count",
        "matured_revision_count",
        "candidate_count",
        "terminal_chain_sha256",
        "duplicate_archive_record_count",
        "invalid_row_count",
        "verified",
        "paper_only",
        "live_gate",
        "routes_to_live",
        "places_real_order",
        "exchange_action_taken",
    }
)


class CandidateOutcomeDatasetError(ValueError):
    """Raised when a dataset source or join is not exact and point-in-time safe."""


def _fail(reason: str, field: str) -> None:
    raise CandidateOutcomeDatasetError(f"{field}:{reason}")


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidateOutcomeDatasetError("payload:STRICT_JSON_REQUIRED") from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("LOWERCASE_SHA256_REQUIRED", field)
    return value


def _parse_utc(value: object, field: str) -> datetime:
    if type(value) is not str or not value:
        _fail("UTC_TIMESTAMP_REQUIRED", field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateOutcomeDatasetError(f"{field}:UTC_TIMESTAMP_REQUIRED") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("UTC_TIMESTAMP_REQUIRED", field)
    return parsed.astimezone(UTC)


def _utc_from_ms(value: object, field: str) -> str:
    if type(value) is not int or value < 1:
        _fail("POSITIVE_INT_MILLISECONDS_REQUIRED", field)
    try:
        return (
            datetime.fromtimestamp(value / 1_000.0, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    except (OSError, OverflowError, ValueError) as exc:
        raise CandidateOutcomeDatasetError(
            f"{field}:POSITIVE_INT_MILLISECONDS_REQUIRED"
        ) from exc


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        _fail("FINITE_NUMBER_REQUIRED", field)
    result = float(value)
    if not math.isfinite(result):
        _fail("FINITE_NUMBER_REQUIRED", field)
    return result


def _nonnegative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        _fail("NONNEGATIVE_INT_REQUIRED", field)
    return value


def _rejection_contract_counts(rejections: Mapping[str, int]) -> dict[str, int]:
    def count(*markers: str) -> int:
        return sum(
            amount
            for reason, amount in rejections.items()
            if any(marker in reason.upper() for marker in markers)
        )

    return {
        "candidate_rejection_count": sum(rejections.values()),
        "future_time_rejections": count(
            "AFTER_DECISION",
            "FUTURE_TIME",
            "POINT_IN_TIME_ORDER_INVALID",
            "POINT_IN_TIME_CLOCK_ORDER_INVALID",
        ),
        "finality_unproven": count(
            "FINALITY",
            "UNCLOSED",
            "CLOSED_KLINE",
        ),
        "missing_cost_evidence": count(
            "MISSING_COST",
            "COST_EVIDENCE_REQUIRED",
        ),
        "missing_label_evidence": count(
            "MATURED_LABELS_REQUIRED",
            "COMPLETE_MATURED_REVISION_TWO_REQUIRED",
            "MISSING_LABEL",
            "LABEL_EVIDENCE_REQUIRED",
        ),
    }


def _payload(record: CandidateDecisionOutcomeV2, name: str) -> dict[str, Any]:
    evidence = getattr(record.decision, name)
    try:
        result = json.loads(evidence.payload_json)
    except json.JSONDecodeError as exc:  # the nested contract normally prevents this
        raise CandidateOutcomeDatasetError(f"decision.{name}:INVALID_JSON") from exc
    if type(result) is not dict:
        _fail("OBJECT_REQUIRED", f"decision.{name}")
    return result


def _arm_scenarios(
    record: CandidateDecisionOutcomeV2,
    arm_name: str,
) -> tuple[CounterfactualScenarioV2, ...]:
    labels = record.matured_labels
    if labels is None:
        _fail("MATURED_LABELS_REQUIRED", "record")
    matches = tuple(
        arm.scenarios for arm in labels.counterfactual_outcomes if arm.arm_name == arm_name
    )
    if len(matches) != 1 or not matches[0]:
        _fail("EXACT_COMPLETE_ARM_REQUIRED", f"matured_labels.{arm_name}")
    for scenario in matches[0]:
        if scenario.counts_as_paper_profit is not False:
            _fail("COUNTERFACTUAL_PAPER_PROFIT_FORBIDDEN", f"{arm_name}.scenario")
        if scenario.actual_accounting_effect is not False:
            _fail("COUNTERFACTUAL_ACCOUNTING_EFFECT_FORBIDDEN", f"{arm_name}.scenario")
    return matches[0]


def _opposite_scenario_net(scenario: CounterfactualScenarioV2) -> float:
    """Invert side and signed funding while preserving all physical costs."""

    return float(
        -scenario.gross_pnl_bps
        - scenario.fees_bps
        - scenario.spread_bps
        - scenario.slippage_bps
        + scenario.funding_bps
        - scenario.market_impact_bps
    )


def candidate_directional_edges(
    record: CandidateDecisionOutcomeV2,
) -> tuple[float, float, str, dict[str, Any]]:
    """Return exact long/short after-cost labels and their derivation receipt."""

    proposed = str(
        _payload(record, "proposed_action").get("proposed_action") or ""
    ).upper()
    unhedged = _arm_scenarios(record, "unhedged")
    alternative = _arm_scenarios(record, "alternative_side")
    if proposed in {"LONG", "SHORT"}:
        if len(unhedged) != 1 or len(alternative) != 1:
            _fail("SINGLE_SCENARIO_REQUIRED", "directional_counterfactual")
        selected_net = float(unhedged[0].after_cost_pnl_bps)
        opposite_net = float(alternative[0].after_cost_pnl_bps)
        long_net, short_net = (
            (selected_net, opposite_net)
            if proposed == "LONG"
            else (opposite_net, selected_net)
        )
        method = "SELECTED_UNHEDGED_PLUS_PREDECLARED_ALTERNATIVE_SIDE"
    elif proposed == "HOLD":
        by_side = {
            scenario.scenario_id.rsplit("-", 1)[-1]: scenario
            for scenario in alternative
            if scenario.scenario_id.rsplit("-", 1)[-1] in {"LONG", "SHORT"}
        }
        if set(by_side) == {"LONG", "SHORT"} and len(alternative) == 2:
            long_net = float(by_side["LONG"].after_cost_pnl_bps)
            short_net = float(by_side["SHORT"].after_cost_pnl_bps)
            method = "PREDECLARED_BALANCED_LONG_SHORT_ALTERNATIVE_SIDE"
        elif len(alternative) == 1:
            # Revisions produced before the balanced-flat contract predeclared
            # one deterministic side.  Its opposite is a pure accounting
            # identity: invert gross return and signed funding, retain every
            # nonnegative physical cost.  The reference side was fixed from the
            # candidate id before outcomes existed.
            reference = counterfactual_reference_side(record.decision.candidate_id)
            reference_net = float(alternative[0].after_cost_pnl_bps)
            opposite_net = _opposite_scenario_net(alternative[0])
            long_net, short_net = (
                (reference_net, opposite_net)
                if reference == "LONG"
                else (opposite_net, reference_net)
            )
            method = "LEGACY_PREDECLARED_REFERENCE_SIDE_ACCOUNTING_INVERSION"
        else:
            _fail("BALANCED_OR_LEGACY_REFERENCE_SCENARIO_REQUIRED", "flat_counterfactual")
    else:
        _fail("LONG_SHORT_OR_HOLD_REQUIRED", "decision.proposed_action")
    long_net = _finite(long_net, "long_net_bps")
    short_net = _finite(short_net, "short_net_bps")
    target = target_action_from_net_edges(
        long_net_bps=long_net,
        short_net_bps=short_net,
    )
    material = {
        "schema_version": "candidate_directional_label_derivation_v2",
        "candidate_id": record.decision.candidate_id,
        "proposed_action": proposed,
        "derivation_method": method,
        "long_net_bps": long_net,
        "short_net_bps": short_net,
        "target_action": target,
        "counterfactual_counts_as_realized_paper_profit": False,
        "actual_accounting_effect": False,
        "unhedged_scenario_sha256s": [
            _sha256(asdict(scenario)) for scenario in unhedged
        ],
        "alternative_side_scenario_sha256s": [
            _sha256(asdict(scenario)) for scenario in alternative
        ],
    }
    material["derivation_sha256"] = _sha256(material)
    return long_net, short_net, target, material


def _source_receipts(record: CandidateDecisionOutcomeV2) -> list[str]:
    labels = record.matured_labels
    if labels is None:
        _fail("MATURED_LABELS_REQUIRED", "record")
    receipts: set[str] = set(labels.label_source_receipt_sha256s)
    receipts.add(labels.summary_receipt_sha256)
    receipts.update(label.source_receipt_sha256 for label in labels.horizon_labels)
    receipts.update(record.decision.counterfactual_evaluation_plan.source_receipt_sha256s)
    for name in (
        "model_distributions",
        "proposed_action",
        "selected_action",
        "component_estimates",
        "portfolio_state",
        "execution_state",
    ):
        receipts.update(getattr(record.decision, name).source_receipt_sha256s)
    for arm in labels.counterfactual_outcomes:
        for scenario in arm.scenarios:
            receipts.update(scenario.source_receipt_sha256s)
    for index, receipt in enumerate(sorted(receipts)):
        _require_sha256(receipt, f"source_receipts[{index}]")
    return sorted(receipts)


def build_candidate_outcome_row(
    record: CandidateDecisionOutcomeV2,
    *,
    snapshot_loader: Callable[[str], Mapping[str, Any] | None],
    source_archive_chain_sha256: str,
) -> dict[str, Any]:
    """Build one point-in-time row or fail with an exact exclusion reason."""

    if type(record) is not CandidateDecisionOutcomeV2:
        _fail("CANDIDATE_DECISION_OUTCOME_V2_REQUIRED", "record")
    labels = record.matured_labels
    if (
        record.archive_sequence != 2
        or labels is None
        or labels.matured is not True
        or labels.complete is not True
        or labels.summary_finality_proven is not True
    ):
        _fail("COMPLETE_MATURED_REVISION_TWO_REQUIRED", "record")
    if labels.actual_paper_outcome is None and labels.counts_as_paper_profit is not False:
        _fail("COUNTERFACTUAL_PAPER_PROFIT_FORBIDDEN", "matured_labels")
    if (
        record.paper_only is not True
        or record.live_gate != "blocked_human_only"
        or record.routes_to_live is not False
        or record.places_real_order is not False
        or record.exchange_action_taken is not False
    ):
        _fail("SAFE_PAPER_AUTHORITY_REQUIRED", "record")
    archive_chain = _require_sha256(
        source_archive_chain_sha256, "source_archive_chain_sha256"
    )
    model = _payload(record, "model_distributions")
    snapshot_id = model.get("feature_snapshot_id")
    if type(snapshot_id) is not str or not snapshot_id:
        _fail("IDENTIFIER_REQUIRED", "model_distributions.feature_snapshot_id")
    if model.get("feature_abi_sha256") != feature_abi_sha256():
        _fail("CURRENT_ABI_MISMATCH", "model_distributions.feature_abi_sha256")
    snapshot = snapshot_loader(snapshot_id)
    if not isinstance(snapshot, Mapping):
        _fail("VERIFIED_SNAPSHOT_MISSING", "feature_snapshot")
    snapshot_content_sha = _require_sha256(
        snapshot.get("content_sha256"), "feature_snapshot.content_sha256"
    )
    if snapshot.get("snapshot_id") != snapshot_id:
        _fail("IDENTITY_MISMATCH", "feature_snapshot.snapshot_id")
    if model.get("durable_feature_snapshot_content_sha256") != snapshot_content_sha:
        _fail("CONTENT_SHA256_MISMATCH", "feature_snapshot.content_sha256")
    if snapshot.get("symbol") != record.decision.symbol:
        _fail("IDENTITY_MISMATCH", "feature_snapshot.symbol")
    if snapshot.get("timeframe") != record.decision.timeframe:
        _fail("IDENTITY_MISMATCH", "feature_snapshot.timeframe")
    snapshot_latest_closed = snapshot.get("latest_closed_kline_close_time_ms")
    snapshot_exclusion = snapshot.get(
        "latest_unclosed_exclusion_decision_time_ms"
    )
    if snapshot.get("latest_unclosed_kline_excluded") is not True:
        _fail("MUST_BE_TRUE", "feature_snapshot.latest_unclosed_kline_excluded")
    if (
        snapshot_latest_closed
        != record.decision.latest_closed_kline_close_time_ms
    ):
        _fail("IDENTITY_MISMATCH", "feature_snapshot.latest_closed_kline_close_time_ms")
    if (
        snapshot.get("latest_unclosed_exclusion_method")
        != record.decision.latest_unclosed_exclusion_method
    ):
        _fail("IDENTITY_MISMATCH", "feature_snapshot.latest_unclosed_exclusion_method")
    if (
        snapshot_exclusion
        != record.decision.latest_unclosed_exclusion_decision_time_ms
    ):
        _fail(
            "IDENTITY_MISMATCH",
            "feature_snapshot.latest_unclosed_exclusion_decision_time_ms",
        )
    if (
        type(snapshot_latest_closed) is not int
        or type(snapshot_exclusion) is not int
        or not snapshot_latest_closed
        <= record.decision.feature_cutoff_ms
        <= snapshot_exclusion
        <= record.decision.decision_time_ms
    ):
        _fail("POINT_IN_TIME_ORDER_INVALID", "feature_snapshot.finality")
    decision_time = _utc_from_ms(
        record.decision.decision_time_ms, "decision.decision_time_ms"
    )
    label_available_at = _utc_from_ms(
        labels.record_available_at_ms, "matured_labels.record_available_at_ms"
    )
    if _parse_utc(label_available_at, "label_available_at") <= _parse_utc(
        decision_time, "decision_time"
    ):
        _fail("LABEL_NOT_STRICTLY_AFTER_DECISION", "label_available_at")
    try:
        vector = build_serving_feature_vector(
            feature_record=snapshot,
            decision_time=decision_time,
            exact_cost_record=None,
        )
    except ValueError as exc:
        raise CandidateOutcomeDatasetError(f"serving_feature_vector:{exc}") from exc
    if vector.feature_abi_sha256 != feature_abi_sha256():
        _fail("CURRENT_ABI_MISMATCH", "serving_feature_vector")
    if vector.feature_builder_sha256 != feature_builder_sha256():
        _fail("CURRENT_BUILDER_MISMATCH", "serving_feature_vector")
    cutoff_ms = int(_parse_utc(vector.feature_cutoff, "feature_cutoff").timestamp() * 1_000)
    if cutoff_ms != record.decision.feature_cutoff_ms:
        _fail("FEATURE_CUTOFF_IDENTITY_MISMATCH", "feature_cutoff")
    long_net, short_net, target_action, label_derivation = candidate_directional_edges(
        record
    )
    receipts = _source_receipts(record)
    label_material = {
        "schema_version": "candidate_outcome_training_label_binding_v2",
        "candidate_id": record.decision.candidate_id,
        "decision_snapshot_sha256": record.decision.content_sha256(),
        "matured_labels_sha256": labels.content_sha256(),
        "label_record_available_at_ms": labels.record_available_at_ms,
        "directional_label_derivation_sha256": label_derivation["derivation_sha256"],
        "label_source_receipt_sha256s": receipts,
        "future_labels_not_in_feature_tensor": True,
        "counterfactual_counts_as_realized_paper_profit": False,
    }
    label_sha = _sha256(label_material)
    return {
        "row_id": f"candidate_outcome:{record.decision.candidate_id}",
        "snapshot_id": snapshot_id,
        "feature_group_id": snapshot_id,
        "source_kind": "CANDIDATE_DECISION_OUTCOME_V2",
        "source_content_sha256": snapshot_content_sha,
        "symbol": record.decision.symbol,
        "timeframe": record.decision.timeframe,
        "decision_time": decision_time,
        "feature_cutoff": vector.feature_cutoff,
        "record_available_at": vector.record_available_at,
        "feature_values": list(vector.values),
        "missing_mask": list(vector.missing_mask),
        "feature_abi_sha256": vector.feature_abi_sha256,
        "feature_builder_sha256": vector.feature_builder_sha256,
        "target_action": target_action,
        "target_action_index": ACTION_LABELS.index(target_action),
        "long_net_bps": long_net,
        "short_net_bps": short_net,
        "label_available_at": label_available_at,
        "label_binding_sha256": label_sha,
        "cost_evidence_sha256": label_derivation["derivation_sha256"],
        "source_receipt_sha256s": receipts,
        "source_hashes": {
            "candidate_archive_terminal_chain_sha256": archive_chain,
            "candidate_record_content_sha256": record.content_sha256(),
            "decision_snapshot_sha256": record.decision.content_sha256(),
            "matured_labels_sha256": labels.content_sha256(),
            "feature_snapshot_content_sha256": snapshot_content_sha,
            "label_binding_sha256": label_sha,
        },
        "candidate_id": record.decision.candidate_id,
        "prediction_id": record.decision.prediction_id,
        "checkpoint_generation": record.decision.checkpoint_generation,
        "checkpoint_id": record.decision.checkpoint_id,
        "decision_disposition": record.decision.decision_disposition,
        "eventual_disposition": labels.eventual_disposition,
        "directional_label_derivation": label_derivation,
        "counterfactual_counts_as_realized_paper_profit": False,
        "actual_paper_outcome_present": labels.actual_paper_outcome is not None,
        "latest_unclosed_kline_excluded": vector.latest_unclosed_kline_excluded,
        "latest_unclosed_exclusion_method": vector.latest_unclosed_exclusion_method,
        "latest_unclosed_exclusion_decision_time_ms": (
            vector.latest_unclosed_exclusion_decision_time_ms
        ),
        "latest_closed_kline_close_time_ms": vector.latest_closed_kline_close_time_ms,
    }


def _validated_base_rows(base_dataset: Mapping[str, Any]) -> list[dict[str, Any]]:
    if base_dataset.get("schema_version") != "serving_compatible_dataset_v2":
        _fail("SCHEMA_MISMATCH", "base_dataset")
    dataset_sha = _require_sha256(base_dataset.get("dataset_sha256"), "base_dataset.sha256")
    material = {
        key: value
        for key, value in base_dataset.items()
        if key not in {"dataset_id", "dataset_sha256"}
    }
    if _sha256(material) != dataset_sha:
        _fail("CONTENT_SHA256_MISMATCH", "base_dataset")
    if (
        base_dataset.get("feature_abi_sha256") != feature_abi_sha256()
        or base_dataset.get("feature_builder_sha256") != feature_builder_sha256()
        or tuple(base_dataset.get("ordered_feature_names") or ())
        != ORDERED_FEATURE_NAMES
    ):
        _fail("CURRENT_ABI_OR_BUILDER_MISMATCH", "base_dataset")
    raw_rows = base_dataset.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        _fail("NONEMPTY_ROWS_REQUIRED", "base_dataset")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping):
            _fail("OBJECT_REQUIRED", f"base_dataset.rows[{index}]")
        row = dict(raw)
        row.pop("split", None)
        snapshot_id = row.get("snapshot_id")
        if type(snapshot_id) is not str or not snapshot_id:
            _fail("IDENTIFIER_REQUIRED", f"base_dataset.rows[{index}].snapshot_id")
        symbol = row.get("symbol")
        timeframe = row.get("timeframe")
        if type(symbol) is not str or _SYMBOL_RE.fullmatch(symbol) is None:
            _fail("CANONICAL_SYMBOL_REQUIRED", f"base_dataset.rows[{index}].symbol")
        if timeframe not in _SUPPORTED_TIMEFRAMES:
            _fail(
                "SUPPORTED_TIMEFRAME_REQUIRED",
                f"base_dataset.rows[{index}].timeframe",
            )
        if (
            row.get("feature_abi_sha256") != feature_abi_sha256()
            or row.get("feature_builder_sha256") != feature_builder_sha256()
            or len(row.get("feature_values") or ()) != len(ORDERED_FEATURE_NAMES)
            or any(row.get("missing_mask") or ())
        ):
            _fail("FEATURE_VECTOR_CONTRACT_MISMATCH", f"base_dataset.rows[{index}]")
        if _parse_utc(row.get("label_available_at"), "label_available_at") <= _parse_utc(
            row.get("decision_time"), "decision_time"
        ):
            _fail("LABEL_NOT_STRICTLY_AFTER_DECISION", f"base_dataset.rows[{index}]")
        target_action = row.get("target_action")
        if target_action not in ACTION_LABELS:
            _fail("ACTION_LABEL_REQUIRED", f"base_dataset.rows[{index}].target_action")
        if row.get("target_action_index") != ACTION_LABELS.index(target_action):
            _fail(
                "ACTION_INDEX_MISMATCH",
                f"base_dataset.rows[{index}].target_action_index",
            )
        long_net = _finite(
            row.get("long_net_bps"), f"base_dataset.rows[{index}].long_net_bps"
        )
        short_net = _finite(
            row.get("short_net_bps"), f"base_dataset.rows[{index}].short_net_bps"
        )
        if target_action_from_net_edges(
            long_net_bps=long_net,
            short_net_bps=short_net,
        ) != target_action:
            _fail(
                "ACTION_NET_EDGE_MISMATCH",
                f"base_dataset.rows[{index}].target_action",
            )
        row["feature_group_id"] = snapshot_id
        row["source_kind"] = "GEN5_AUTHENTICATED_PROFILED_OBSERVATION"
        row["counterfactual_counts_as_realized_paper_profit"] = False
        row["actual_paper_outcome_present"] = False
        rows.append(row)
    return rows


def _boundary_time(rows: list[dict[str, Any]], fraction: float) -> str:
    target_index = min(len(rows) - 1, max(1, int(len(rows) * fraction)))
    candidate = rows[target_index]["decision_time"]
    while target_index > 0 and rows[target_index - 1]["decision_time"] == candidate:
        target_index -= 1
    return rows[target_index]["decision_time"]


def _time_key(value: object, field: str) -> datetime:
    return _parse_utc(value, field)


def _purged_split(
    rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[str],
    dict[str, int],
    dict[str, Any],
    list[str],
]:
    if len(rows) < 104:
        _fail("DATASET_BELOW_MINIMUM_FOR_PURGED_SPLITS", "rows")
    ordered = sorted(
        rows,
        key=lambda row: (_time_key(row["decision_time"], "decision_time"), row["row_id"]),
    )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        group_id = row.get("feature_group_id")
        if type(group_id) is not str or not group_id:
            _fail("FEATURE_GROUP_ID_REQUIRED", "rows")
        grouped[group_id].append(row)
    minimum_validation = max(10, int(len(rows) * 0.05))
    minimum_holdout = max(10, int(len(rows) * 0.05))
    source_kinds = {str(row.get("source_kind") or "") for row in rows}
    if "" in source_kinds:
        _fail("SOURCE_KIND_REQUIRED", "rows")

    def assign(
        validation_start: str,
        holdout_start: str,
    ) -> tuple[list[dict[str, Any]], list[str], Counter[str], list[str]]:
        validation_clock = _time_key(validation_start, "validation_start")
        holdout_clock = _time_key(holdout_start, "holdout_start")
        if validation_clock >= holdout_clock:
            return [], [], Counter(), []
        admitted: list[dict[str, Any]] = []
        purged_ids: list[str] = []
        embargo_ids: list[str] = []
        purge_reasons: Counter[str] = Counter()
        for group_id in sorted(grouped):
            group = grouped[group_id]
            first = min(
                _time_key(row["decision_time"], "decision_time") for row in group
            )
            last = max(
                _time_key(row["decision_time"], "decision_time") for row in group
            )
            if first < validation_clock <= last or first < holdout_clock <= last:
                purge_reasons["FEATURE_GROUP_CROSSES_SPLIT_BOUNDARY"] += len(group)
                purged_ids.extend(row["row_id"] for row in group)
                continue
            if last < validation_clock:
                if any(
                    _time_key(row["label_available_at"], "label_available_at")
                    >= validation_clock
                    for row in group
                ):
                    purge_reasons["TRAIN_LABEL_NOT_AVAILABLE_BEFORE_VALIDATION"] += len(
                        group
                    )
                    purged_ids.extend(row["row_id"] for row in group)
                    continue
                split = "train"
            elif first < holdout_clock:
                if any(
                    _time_key(row["label_available_at"], "label_available_at")
                    >= holdout_clock
                    for row in group
                ):
                    purge_reasons[
                        "VALIDATION_LABEL_NOT_AVAILABLE_BEFORE_HOLDOUT"
                    ] += len(group)
                    purged_ids.extend(row["row_id"] for row in group)
                    continue
                split = "validation"
            else:
                split = "holdout"
            for row in group:
                admitted_row = dict(row)
                admitted_row["split"] = split
                admitted.append(admitted_row)
        for split in ("validation", "holdout"):
            split_times = sorted(
                {
                    row["decision_time"]
                    for row in admitted
                    if row["split"] == split
                }
            )
            embargo_times = set(split_times[:EMBARGO_GROUPS])
            split_embargo_ids = [
                row["row_id"]
                for row in admitted
                if row["split"] == split
                and row["decision_time"] in embargo_times
            ]
            if split_embargo_ids:
                embargo_id_set = set(split_embargo_ids)
                admitted = [
                    row for row in admitted if row["row_id"] not in embargo_id_set
                ]
                embargo_ids.extend(split_embargo_ids)
                purged_ids.extend(split_embargo_ids)
                purge_reasons["PREDECLARED_DECISION_TIME_EMBARGO"] += len(
                    split_embargo_ids
                )
        return admitted, purged_ids, purge_reasons, embargo_ids

    # Fractions are selected from decision identities only.  Outcomes and
    # target values cannot influence the boundary.  Multiple candidates are
    # needed because a dense six-hour candidate suffix follows a much smaller
    # multi-day base corpus; row-count 75/12/13 alone can leave less than one
    # label horizon between validation and holdout.
    boundary_candidates = (
        (0.50, 0.80),
        (0.45, 0.75),
        (0.40, 0.70),
        (0.35, 0.70),
        (0.30, 0.65),
        (0.55, 0.85),
        (0.70, 0.85),
        (0.68, 0.84),
        (0.66, 0.83),
    )
    valid: list[
        tuple[
            int,
            float,
            float,
            str,
            str,
            list[dict[str, Any]],
            list[str],
            Counter[str],
            list[str],
        ]
    ] = []
    for validation_fraction, holdout_fraction in boundary_candidates:
        validation_start = _boundary_time(ordered, validation_fraction)
        holdout_start = _boundary_time(ordered, holdout_fraction)
        admitted, purged_ids, purge_reasons, embargo_ids = assign(
            validation_start, holdout_start
        )
        counts = Counter(row["split"] for row in admitted)
        training_source_kinds = {
            row["source_kind"] for row in admitted if row["split"] == "train"
        }
        if (
            counts["train"] >= 80
            and counts["validation"] >= minimum_validation
            and counts["holdout"] >= minimum_holdout
            and training_source_kinds == source_kinds
        ):
            valid.append(
                (
                    len(admitted),
                    validation_fraction,
                    holdout_fraction,
                    validation_start,
                    holdout_start,
                    admitted,
                    purged_ids,
                    purge_reasons,
                    embargo_ids,
                )
            )
    if not valid:
        _fail("MINIMUM_PURGED_SPLIT_SIZE_UNSATISFIED", "rows")
    (
        _,
        selected_validation_fraction,
        selected_holdout_fraction,
        validation_start,
        holdout_start,
        admitted,
        purged_ids,
        purge_reasons,
        embargo_ids,
    ) = max(valid, key=lambda candidate: (candidate[0], -candidate[1], candidate[2]))
    if max(
        _time_key(row["label_available_at"], "label_available_at")
        for row in admitted
        if row["split"] == "train"
    ) >= min(
        _time_key(row["decision_time"], "decision_time")
        for row in admitted
        if row["split"] == "validation"
    ):
        _fail("TRAIN_LABEL_OVERLAPS_VALIDATION_DECISION", "rows")
    if max(
        _time_key(row["label_available_at"], "label_available_at")
        for row in admitted
        if row["split"] == "validation"
    ) >= min(
        _time_key(row["decision_time"], "decision_time")
        for row in admitted
        if row["split"] == "holdout"
    ):
        _fail("VALIDATION_LABEL_OVERLAPS_HOLDOUT_DECISION", "rows")
    return (
        sorted(
            admitted,
            key=lambda row: (
                _time_key(row["decision_time"], "decision_time"),
                row["row_id"],
            ),
        ),
        sorted(purged_ids),
        dict(sorted(purge_reasons.items())),
        {
            "validation_start_decision_time": validation_start,
            "holdout_start_decision_time": holdout_start,
            "validation_start_row_fraction": selected_validation_fraction,
            "holdout_start_row_fraction": selected_holdout_fraction,
            "minimum_validation_rows": minimum_validation,
            "minimum_holdout_rows": minimum_holdout,
            "embargo_groups_before_each_downstream_split": EMBARGO_GROUPS,
        },
        sorted(embargo_ids),
    )


def build_adaptive_serving_dataset_v2(
    *,
    base_dataset: Mapping[str, Any],
    candidate_records: Sequence[CandidateDecisionOutcomeV2],
    snapshot_loader: Callable[[str], Mapping[str, Any] | None],
    source_archive_chain_sha256: str,
    source_archive_verification: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Combine gen-5 and matured candidate evidence, then resplit from scratch."""

    archive_chain = _require_sha256(
        source_archive_chain_sha256, "source_archive_chain_sha256"
    )
    base_rows = _validated_base_rows(base_dataset)
    candidate_rows: list[dict[str, Any]] = []
    rejections: Counter[str] = Counter()
    seen_candidates: set[str] = set()
    for index, record in enumerate(candidate_records):
        if type(record) is not CandidateDecisionOutcomeV2:
            _fail("CANDIDATE_DECISION_OUTCOME_V2_REQUIRED", f"candidate_records[{index}]")
        if record.archive_sequence == 1:
            continue
        candidate_id = record.decision.candidate_id
        if candidate_id in seen_candidates:
            _fail("DUPLICATE_MATURED_CANDIDATE_ID", "candidate_records")
        seen_candidates.add(candidate_id)
        try:
            candidate_rows.append(
                build_candidate_outcome_row(
                    record,
                    snapshot_loader=snapshot_loader,
                    source_archive_chain_sha256=archive_chain,
                )
            )
        except CandidateOutcomeDatasetError as exc:
            rejections[str(exc)] += 1
    if not candidate_rows:
        _fail("NO_ELIGIBLE_MATURED_CANDIDATE_ROWS", "candidate_records")
    combined = [*base_rows, *candidate_rows]
    row_ids = [row["row_id"] for row in combined]
    if len(row_ids) != len(set(row_ids)):
        _fail("DUPLICATE_ROW_ID", "rows")
    rows, purged_ids, purge_reasons, boundaries, embargo_ids = _purged_split(combined)
    split_counts = Counter(row["split"] for row in rows)
    action_counts = Counter(row["target_action"] for row in rows)
    source_counts = Counter(row["source_kind"] for row in rows)
    symbol_counts = Counter(row["symbol"] for row in rows)
    timeframe_counts = Counter(row["timeframe"] for row in rows)
    source_split_counts = Counter(
        (row["source_kind"], row["split"]) for row in rows
    )
    receipts = sorted(
        {
            receipt
            for row in rows
            for receipt in row.get("source_receipt_sha256s", [])
        }
    )
    feature_groups = Counter(row["feature_group_id"] for row in rows)
    rejection_contract_counts = _rejection_contract_counts(rejections)
    if set(action_counts) - set(ACTION_LABELS) or sum(action_counts.values()) != len(rows):
        _fail("TARGET_ACTION_COUNT_MISMATCH", "rows")
    if not isinstance(source_archive_verification, Mapping):
        _fail("SOURCE_ARCHIVE_VERIFICATION_REQUIRED", "source_archive_verification")
    if set(source_archive_verification) != _SOURCE_ARCHIVE_VERIFICATION_FIELDS:
        _fail(
            "SOURCE_ARCHIVE_VERIFICATION_FIELDS_MISMATCH",
            "source_archive_verification",
        )
    archive_candidate_count = _nonnegative_int(
        source_archive_verification.get("candidate_count"),
        "source_archive_verification.candidate_count",
    )
    archive_decision_revision_count = _nonnegative_int(
        source_archive_verification.get("decision_revision_count"),
        "source_archive_verification.decision_revision_count",
    )
    archive_matured_revision_count = _nonnegative_int(
        source_archive_verification.get("matured_revision_count"),
        "source_archive_verification.matured_revision_count",
    )
    archive_row_count = _nonnegative_int(
        source_archive_verification.get("row_count"),
        "source_archive_verification.row_count",
    )
    archive_invalid_count = _nonnegative_int(
        source_archive_verification.get("invalid_row_count"),
        "source_archive_verification.invalid_row_count",
    )
    archive_duplicate_count = _nonnegative_int(
        source_archive_verification.get("duplicate_archive_record_count"),
        "source_archive_verification.duplicate_archive_record_count",
    )
    if (
        archive_candidate_count != archive_decision_revision_count
        or archive_matured_revision_count > archive_candidate_count
        or len(candidate_records) != archive_matured_revision_count
        or archive_matured_revision_count != len(seen_candidates)
        or archive_row_count
        != archive_decision_revision_count + archive_matured_revision_count
    ):
        _fail("SOURCE_ARCHIVE_COUNT_MISMATCH", "source_archive_verification")
    archive_path = source_archive_verification.get("archive_path")
    if (
        source_archive_verification.get("schema_version")
        != ARCHIVE_VERIFICATION_SCHEMA_VERSION
        or type(archive_path) is not str
        or not archive_path
        or archive_path.strip() != archive_path
        or not Path(archive_path).is_absolute()
        or source_archive_verification.get("writer_id")
        != PINNED_PRODUCTION_WRITER_ID
        or source_archive_verification.get("writer_public_key_hex")
        != PINNED_PRODUCTION_WRITER_PUBLIC_KEY_HEX
        or source_archive_verification.get("terminal_chain_sha256") != archive_chain
        or source_archive_verification.get("verified") is not True
        or archive_invalid_count != 0
        or archive_duplicate_count != 0
        or source_archive_verification.get("paper_only") is not True
        or source_archive_verification.get("live_gate") != "blocked_human_only"
        or source_archive_verification.get("routes_to_live") is not False
        or source_archive_verification.get("places_real_order") is not False
        or source_archive_verification.get("exchange_action_taken") is not False
    ):
        _fail("SOURCE_ARCHIVE_RECEIPT_UNSAFE", "source_archive_verification")
    dataset_material = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "ordered_feature_names": list(ORDERED_FEATURE_NAMES),
        "action_labels": list(ACTION_LABELS),
        "rows": rows,
    }
    dataset_sha = _sha256(dataset_material)
    dataset_id = f"adaptive_serving_dataset_v2_{dataset_sha[:24]}"
    dataset = {
        **dataset_material,
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha,
    }
    base_sha = _require_sha256(base_dataset.get("dataset_sha256"), "base_dataset.sha256")
    manifest_material = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "dataset_sha256": dataset_sha,
        "feature_abi_sha256": feature_abi_sha256(),
        "feature_builder_sha256": feature_builder_sha256(),
        "ordered_feature_names": list(ORDERED_FEATURE_NAMES),
        "training_rows": split_counts["train"],
        "validation_rows": split_counts["validation"],
        "holdout_rows": split_counts["holdout"],
        "earliest_decision_time": min(row["decision_time"] for row in rows),
        "latest_decision_time": max(row["decision_time"] for row in rows),
        "source_high_watermark": {
            "base_dataset_id": base_dataset.get("dataset_id"),
            "base_dataset_sha256": base_sha,
            "candidate_archive_terminal_chain_sha256": archive_chain,
            "candidate_archive_path": archive_path,
            "candidate_archive_writer_id": source_archive_verification["writer_id"],
            "candidate_archive_writer_public_key_hex": source_archive_verification[
                "writer_public_key_hex"
            ],
            "candidate_archive_candidate_count": archive_candidate_count,
            "candidate_archive_decision_revision_count": archive_decision_revision_count,
            "candidate_archive_matured_revision_count": archive_matured_revision_count,
            "candidate_archive_row_count": archive_row_count,
            "candidate_archive_latest_decision_only_count": (
                archive_candidate_count - archive_matured_revision_count
            ),
        },
        "source_receipt_sha256s": receipts,
        "source_receipt_sha256_count": len(receipts),
        "source_row_counts": dict(sorted(source_counts.items())),
        "symbol_count": len(symbol_counts),
        "symbol_counts": dict(sorted(symbol_counts.items())),
        "timeframe_count": len(timeframe_counts),
        "timeframe_counts": dict(sorted(timeframe_counts.items())),
        "source_split_counts": {
            source_kind: {
                split: source_split_counts[(source_kind, split)]
                for split in ("train", "validation", "holdout")
            }
            for source_kind in sorted(source_counts)
        },
        "target_action_counts": {
            action: action_counts[action] for action in ACTION_LABELS
        },
        "candidate_records_considered": archive_candidate_count,
        "candidate_records_loaded_for_dataset": len(candidate_records),
        "candidate_matured_records_considered": len(seen_candidates),
        "candidate_rows_before_split_purge": len(candidate_rows),
        "candidate_exclusion_reasons": dict(sorted(rejections.items())),
        "candidate_records_fully_accounted": (
            len(candidate_rows) + sum(rejections.values()) == len(seen_candidates)
        ),
        "purge_policy": PURGE_POLICY,
        "split_boundaries": boundaries,
        "purged_row_ids": purged_ids,
        "purge_reason_counts": purge_reasons,
        "embargo_groups": EMBARGO_GROUPS,
        "embargo_row_ids": embargo_ids,
        "embargo_row_count": len(embargo_ids),
        "feature_group_count": len(feature_groups),
        "reused_feature_group_count": sum(count > 1 for count in feature_groups.values()),
        "maximum_rows_per_feature_group": max(feature_groups.values()),
        "duplicate_rows": 0,
        **rejection_contract_counts,
        "admitted_future_time_violations": 0,
        "admitted_finality_violations": 0,
        "admitted_missing_cost_evidence": 0,
        "admitted_missing_label_evidence": 0,
        "counterfactual_counts_as_realized_paper_profit": False,
        "paper_only": True,
        "live_eligible": False,
    }
    if manifest_material["candidate_records_fully_accounted"] is not True:
        _fail("CANDIDATE_ACCOUNTING_MISMATCH", "manifest")
    manifest_sha = _sha256(manifest_material)
    manifest = {
        **manifest_material,
        "manifest_id": f"adaptive_serving_manifest_v2_{manifest_sha[:24]}",
        "manifest_sha256": manifest_sha,
    }
    parity = {
        "schema_version": PARITY_SCHEMA_VERSION,
        "feature_abi_sha256": feature_abi_sha256(),
        "training_feature_builder_sha256": feature_builder_sha256(),
        "serving_feature_builder_sha256": feature_builder_sha256(),
        "builder_match": True,
        "ordered_feature_names_match": True,
        "required_feature_missing_rate": 0.0,
        "training_rows": split_counts["train"],
        "validation_rows": split_counts["validation"],
        "holdout_rows": split_counts["holdout"],
        "activation_eligible": False,
        "activation_block_reason": "CURRENT_SERVING_DISTRIBUTION_NOT_YET_EVALUATED",
        "paper_only": True,
        "live_eligible": False,
    }
    return dataset, manifest, parity


__all__ = [
    "CandidateOutcomeDatasetError",
    "DATASET_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "PARITY_SCHEMA_VERSION",
    "build_adaptive_serving_dataset_v2",
    "build_candidate_outcome_row",
    "candidate_directional_edges",
]
