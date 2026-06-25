from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from v2.backend.app.cli import v2_adaptive_capital_productivity_status as status_module
from v2.backend.app.cli import v2_out_of_sample_reverify_evidence_producer as producer


class _FakeRedis:
    def __init__(self, payloads: dict[str, object]):
        self.payloads = payloads

    def get(self, key: str):
        value = self.payloads.get(key)
        if value is None:
            return None
        return json.dumps(value)

    def scan_iter(self, match: str, count: int = 1000):  # noqa: ARG002
        return iter([])

    def ping(self) -> bool:
        return True


def _row(**overrides):
    row = {
        "row_id": "row-1",
        "source_redis_key": "unit:source:row-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "action": "long",
        "strategy": "range_reversion",
        "market_regime": "range",
        "volatility_bucket": "medium",
        "liquidity_bucket": "high",
        "decision_time": "2026-06-21T12:00:00Z",
        "available_at": "2026-06-21T11:59:30Z",
        "generated_at": "2026-06-21T11:59:20Z",
        "feature_cutoff": "2026-06-21T11:55:00Z",
        "future_label_close_time": "2026-06-21T13:00:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "future_label_used_as_outcome_only": True,
        "future_labels_used_as_features": False,
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": 45.0,
        "after_cost_return_bps": 35.0,
        "realized_after_cost_return_bps": 35.0,
        "realized_pnl_usd": 3.5,
        "gross_notional_usd": 1000.0,
        "allocated_margin_usd": 500.0,
        "recommended_leverage": 2.0,
        "effective_leverage": 2.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "stop_distance_bps": 75.0,
        "take_profit_structure": "single_target",
        "hedge_budget_usd": 0.0,
        "actual_observed_spread_entry_bps": 1.2,
        "depth_impact_bps": 0.2,
        "expected_slippage_bps": 1.4,
        "expected_slippage_usd": 0.14,
        "fee_bps": 4.0,
        "expected_fees_usd": 0.4,
        "expected_funding_bps": 0.2,
        "expected_funding_usd": 0.02,
        "funding_pnl_usd": -0.02,
        "liquidation_buffer_bps": 4000.0,
        "liquidation_price_estimate": 50.0,
        "orderbook_depth_usd": 300000.0,
        "correlation_exposure_pct": 0.12,
        "allocator_decision": "ALLOW_WITH_SIZE",
        "selector_policy_fingerprint": producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "candidate_selection_tier": "A_GRADE_EXECUTION_PAPER",
        "paper_only": True,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }
    row.update(overrides)
    return row


def _write_jsonl(path: Path, rows: list[dict], *, malformed: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
        if malformed:
            handle.write("{not-json\n")


def _bucket_matrix_for(path: Path, row: dict) -> Path:
    fields = (
        "strategy",
        "side",
        "symbol_cluster",
        "timeframe",
        "market_regime",
        "volatility_bucket",
        "liquidity_bucket",
        "confidence_bucket",
        "expected_move_bucket",
    )
    bucket = dict(zip(fields, status_module._a_grade_bucket_key(row), strict=True))
    bucket.update({
        "dynamic_a_grade_eligible": True,
        "sample_count": 30,
        "expectancy_after_cost_bps": 35.0,
        "profit_factor": 2.0,
        "lower_confidence_bound_positive_outcome": 0.6,
    })
    matrix_path = path / "a_grade_bucket_performance_matrix.json"
    matrix_path.write_text(json.dumps({"buckets": [bucket]}))
    return matrix_path


def _untouched_attestations() -> dict[str, bool]:
    return {
        attestation: True
        for attestation in producer.REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
    }


def _construction_subset_status_path(
    path: Path,
    *,
    rows: list[dict] | None = None,
) -> Path:
    construction_rows = rows or [
        {"row_id": "construction-subset-1"},
        {"row_id": "construction-subset-2"},
    ]
    status_path = path / "accelerated_counterfactual_replay_status.json"
    status_path.write_text(json.dumps({
        "validated_replay_candidate_count": len(construction_rows),
        "validated_replay_deployment_status": {
            "validated_replay_deployment_candidate_count": len(construction_rows),
            "validated_replay_candidates": construction_rows,
        },
    }))
    return status_path


def _construction_subset_identity_proof(
    path: Path,
    *,
    window_hashes: dict,
    rows: list[dict] | None = None,
) -> dict:
    status_path = _construction_subset_status_path(path, rows=rows)
    construction_status = producer._construction_subset_identity_source_status(status_path)
    return {
        "status": producer.CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS,
        "construction_subset_source_path": str(status_path),
        "construction_subset_source_sha256": construction_status["sha256"],
        "construction_subset_candidate_count": construction_status["candidate_count"],
        "construction_subset_identity_hash_set_sha256": construction_status[
            "identity_hash_set_sha256"
        ],
        "holdout_source_row_identity_hash_set_sha256": window_hashes[
            "source_row_identity_hash_set_sha256"
        ],
        "overlap_identity_hash_count": 0,
        "overlap_identity_hash_sample": [],
    }


def _registry(path: Path, source_path: Path) -> Path:
    registry_path = path / "out_of_sample_holdout_window_registry.json"
    rows, _ = producer._iter_jsonl(source_path)
    row_identity_hashes = [producer._sha256_text(producer._row_identity(row)) for row in rows]
    window_hashes = producer._holdout_window_hashes(
        window_id="unit-untouched-window",
        start_decision_time="2026-06-21T00:00:00Z",
        end_decision_time="2026-06-22T00:00:00Z",
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        timeframes=["5m"],
        source_row_identity_hashes=row_identity_hashes,
        decision_time_ready_row_identity_hashes=row_identity_hashes,
        source_sha256=producer._file_sha256(source_path),
    )
    registry_path.write_text(json.dumps({
        "schema_version": producer.SCHEMA_VERSION,
        "status": "PASSED",
        "selector_policy_fingerprint": producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "source_sha256": producer._file_sha256(source_path),
        "windows": [{
            "window_id": "unit-untouched-window",
            "start_decision_time": "2026-06-21T00:00:00Z",
            "end_decision_time": "2026-06-22T00:00:00Z",
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframes": ["5m"],
            "window_hashes": window_hashes,
            "eligible_for_holdout": True,
            "exclusion_proof": {
                "status": "PASSED_UNTOUCHED",
                "source_sha256": producer._file_sha256(source_path),
                "window_metadata_sha256": window_hashes["window_metadata_sha256"],
                "source_row_identity_hash_set_sha256": window_hashes[
                    "source_row_identity_hash_set_sha256"
                ],
                "construction_subset_identity_proof": (
                    _construction_subset_identity_proof(
                        path,
                        window_hashes=window_hashes,
                    )
                ),
                "attestations": _untouched_attestations(),
            },
        }],
    }))
    return registry_path


def _forward_registry(path: Path) -> Path:
    registry_path = path / "out_of_sample_holdout_window_registry.json"
    registry_path.write_text(json.dumps({
        "schema_version": producer.SCHEMA_VERSION,
        "status": "FORWARD_PRE_REGISTERED_AWAITING_OUTCOMES",
        "selector_policy_fingerprint": producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "source_sha256": None,
        "windows": [{
            "window_id": "unit-forward-window",
            "start_decision_time": "2026-06-21T00:00:00Z",
            "end_decision_time": "2026-06-22T00:00:00Z",
            "symbols": ["BTCUSDT"],
            "timeframes": ["5m"],
            "eligible_for_holdout": True,
            "forward_pre_registered": True,
            "exclusion_proof": {
                "status": producer.FORWARD_HOLDOUT_PROOF_STATUS,
                "proof_type": "FORWARD_TIME_LOCKED_PRE_REGISTRATION",
                "source_sha256_policy": "NOT_BOUND_BEFORE_FORWARD_ROWS_EXIST",
            },
        }],
    }))
    return registry_path


def _forward_candidate_allocation(**overrides) -> dict:
    row = producer._without_outcome_fields(_row(
        row_id="forward-candidate",
        source_redis_key="unit:forward-candidate",
        decision_time="2026-06-21T12:00:00Z",
        available_at="2026-06-21T11:59:30Z",
        generated_at="2026-06-21T11:59:20Z",
        feature_cutoff="2026-06-21T11:55:00Z",
    ))
    row.update({
        "allocation_id": "alloc-forward-candidate",
        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "explicit_paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
        "candidate_selected_before_outcome": True,
        "selected_before_outcome": True,
        "paper_only": True,
        "places_real_order": False,
        "live_order": False,
        "test_order": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
    })
    row.pop("candidate_selection_tier", None)
    row.update(overrides)
    return row


def _paper_candidate_source(path: Path, *allocations: dict) -> Path:
    source_path = path / "v2_trade_management_paper_live_status.json"
    source_path.write_text(json.dumps({
        "classification": "PAPER_RUNTIME_STATUS",
        "generated_utc": "2026-06-21T12:00:05Z",
        "paper_only": True,
        "places_real_order": False,
        "paper_adaptive_sizing_runtime_status": {
            "generated_utc": "2026-06-21T12:00:05Z",
            "paper_only": True,
            "candidate_allocations": list(allocations),
        },
    }))
    return source_path


def test_realtime_source_normalization_maps_decision_time_accounting_aliases() -> None:
    row = _row(
        row_id="alias-accounting",
        take_profit_structure=None,
        fee_bps=None,
        expected_fees_usd=None,
        recommended_margin_mode=None,
        hedge_budget_usd=None,
    )
    for field in (
        "take_profit_structure",
        "fee_bps",
        "expected_fees_usd",
        "recommended_margin_mode",
        "hedge_budget_usd",
    ):
        row.pop(field, None)
    row.update({
        "price_target": 101.25,
        "margin_mode_simulated": "isolated_paper_simulated",
        "hedge_state": "NO_HEDGE",
        "market_snapshot": {"fee_bps": 4.5},
    })

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="redis_paper_ledger_accepted",
        source_label="unit",
    )
    accounting_reasons = producer._accounting_reject_reasons(normalized)

    assert normalized["take_profit_price"] == 101.25
    assert normalized["recommended_margin_mode"] == "isolated_paper_simulated"
    assert normalized["fee_bps"] == 4.5
    assert normalized["hedge_enabled"] is False
    assert normalized["future_labels_used_as_features"] is False
    assert "MISSING_ACCOUNTING_TAKE_PROFIT_STRUCTURE" not in accounting_reasons
    assert "MISSING_ACCOUNTING_FEES" not in accounting_reasons
    assert "MISSING_ACCOUNTING_HEDGE" not in accounting_reasons
    assert {
        item["target_field"]
        for item in normalized["_producer_normalized_accounting_aliases"]
    } >= {"take_profit_price", "recommended_margin_mode", "fee_bps", "hedge_enabled"}

    summary = producer._accounting_alias_summary([normalized, _row(row_id="no-alias")])
    assert summary["rows_with_normalized_aliases_count"] == 1
    assert summary["rows_with_aliases_by_source_kind"]["redis_paper_ledger_accepted"] == 1
    assert summary["target_field_counts"]["take_profit_price"] == 1
    assert summary["target_field_counts_by_source_kind"]["redis_paper_ledger_accepted"]["fee_bps"] == 1


def test_realtime_source_normalization_preserves_fee_usdt_without_funding_assumption() -> None:
    row = _row(
        row_id="fee-usdt-alias",
        fee_usdt=0.11,
        funding_assumption="zero_until_funding_feed_adapter_current",
    )
    for field in (
        "fee_bps",
        "fee_usd",
        "expected_fee_bps",
        "expected_fees_usd",
        "funding_pnl_usd",
        "funding_pnl",
        "expected_funding_usd",
        "expected_funding_bps",
        "funding_rate",
        "funding_bps",
        "funding_rate_bps",
    ):
        row.pop(field, None)

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="filesystem_runtime_snapshot",
        source_label="unit",
    )
    accounting_reasons = producer._accounting_reject_reasons(normalized)

    assert normalized["fee_usd"] == 0.11
    assert normalized["funding_assumption"] == "zero_until_funding_feed_adapter_current"
    assert "funding_pnl_usd" not in normalized
    assert "expected_funding_bps" not in normalized
    assert "MISSING_ACCOUNTING_FEES" not in accounting_reasons
    assert "MISSING_ACCOUNTING_FUNDING" in accounting_reasons

    aliases = normalized["_producer_normalized_accounting_aliases"]
    assert {
        (item["target_field"], item["source_field"])
        for item in aliases
    } == {("fee_usd", "fee_usdt")}

    summary = producer._accounting_alias_summary([normalized])
    assert summary["target_field_counts"]["fee_usd"] == 1
    assert summary["source_field_counts"]["fee_usdt"] == 1


def test_realtime_source_normalization_preserves_notional_and_margin_usdt_aliases() -> None:
    row = _row(
        row_id="notional-margin-usdt-alias",
        notional_usdt=250.0,
        margin_usdt=125.0,
    )
    row.pop("gross_notional_usd", None)
    row.pop("allocated_margin_usd", None)

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="filesystem_runtime_snapshot",
        source_label="unit",
    )
    accounting_reasons = producer._accounting_reject_reasons(normalized)

    assert normalized["gross_notional_usd"] == 250.0
    assert normalized["allocated_margin_usd"] == 125.0
    assert "MISSING_ACCOUNTING_GROSS_NOTIONAL" not in accounting_reasons
    assert "MISSING_ACCOUNTING_ALLOCATED_MARGIN" not in accounting_reasons

    aliases = normalized["_producer_normalized_accounting_aliases"]
    assert {
        (item["target_field"], item["source_field"])
        for item in aliases
    } >= {
        ("gross_notional_usd", "notional_usdt"),
        ("allocated_margin_usd", "margin_usdt"),
    }

    summary = producer._accounting_alias_summary([normalized])
    assert summary["target_field_counts"]["gross_notional_usd"] == 1
    assert summary["target_field_counts"]["allocated_margin_usd"] == 1
    assert summary["source_field_counts"]["notional_usdt"] == 1
    assert summary["source_field_counts"]["margin_usdt"] == 1


def test_realtime_source_normalization_does_not_overwrite_notional_and_margin() -> None:
    row = _row(
        row_id="notional-margin-existing",
        gross_notional_usd=300.0,
        allocated_margin_usd=150.0,
        notional_usdt=250.0,
        margin_usdt=125.0,
    )

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="filesystem_runtime_snapshot",
        source_label="unit",
    )

    assert normalized["gross_notional_usd"] == 300.0
    assert normalized["allocated_margin_usd"] == 150.0
    aliases = normalized.get("_producer_normalized_accounting_aliases", [])
    assert {
        (item["target_field"], item["source_field"])
        for item in aliases
    }.isdisjoint({
        ("gross_notional_usd", "notional_usdt"),
        ("allocated_margin_usd", "margin_usdt"),
    })


def test_realtime_source_normalization_preserves_selector_context_aliases() -> None:
    row = _row(
        row_id="selector-context-alias",
        market_regime_at_entry="TREND",
        strategy_regime_labels=["MODEL_DISAGREEMENT", "TREND"],
        strategy_router_selected_mode="trend_mode",
    )
    for field in (
        "market_regime",
        "regime",
        "regime_label",
        "market_state",
        "strategy_mode",
        "strategy",
        "strategy_family",
        "signal_strategy",
        "model_strategy",
        "source_strategy",
        "capital_allocation_reason",
    ):
        row.pop(field, None)

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="redis_paper_intent",
        source_label="unit",
    )

    assert normalized["regime_label"] == "TREND"
    assert normalized["source_strategy"] == "trend_mode"
    assert status_module._market_regime_bucket(normalized) == "trend"
    assert status_module._row_strategy(normalized) == "trend_mode"
    assert normalized["decision_time"] == row["decision_time"]
    assert normalized["available_at"] == row["available_at"]
    assert normalized["feature_cutoff"] == row["feature_cutoff"]

    aliases = normalized["_producer_normalized_selector_context_aliases"]
    assert {
        (item["target_field"], item["source_field"])
        for item in aliases
    } == {
        ("regime_label", "market_regime_at_entry"),
        ("source_strategy", "strategy_router_selected_mode"),
    }

    summary = producer._selector_context_alias_summary([normalized, _row(row_id="no-alias")])
    assert summary["rows_with_normalized_aliases_count"] == 1
    assert summary["rows_with_aliases_by_source_kind"]["redis_paper_intent"] == 1
    assert summary["target_field_counts"]["regime_label"] == 1
    assert summary["target_field_counts"]["source_strategy"] == 1
    assert summary["source_field_counts"]["market_regime_at_entry"] == 1
    assert summary["source_field_counts"]["strategy_router_selected_mode"] == 1


def test_realtime_source_normalization_does_not_overwrite_selector_context() -> None:
    row = _row(
        row_id="selector-context-existing",
        market_regime="range",
        strategy="mean_reversion",
        strategy_regime_labels=["TREND"],
        strategy_router_selected_mode="trend_mode",
    )

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="redis_paper_intent",
        source_label="unit",
    )

    assert normalized["market_regime"] == "range"
    assert normalized["strategy"] == "mean_reversion"
    assert "regime_label" not in normalized
    assert "source_strategy" not in normalized
    assert "_producer_normalized_selector_context_aliases" not in normalized


def test_realtime_source_normalization_preserves_selector_field_aliases() -> None:
    row = _row(
        row_id="selector-field-alias",
        side="short",
        action="short",
        source_redis_timeframe="15m",
        paper_allocation_signed_expected_move_after_cost_bps=-32.5,
    )
    row.pop("timeframe", None)
    row.pop("expected_move_after_cost_bps", None)
    row.pop("expected_net_edge_bps", None)

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="redis_paper_ledger_accepted",
        source_label="unit",
    )
    bucket_payload = status_module._a_grade_bucket_key_payload(
        status_module._a_grade_bucket_key(normalized)
    )

    assert normalized["timeframe"] == "15m"
    assert normalized["expected_move_after_cost_bps"] == -32.5
    assert status_module._expected_edge_bps(normalized) == 32.5
    assert bucket_payload["timeframe"] == "15m"
    assert bucket_payload["expected_move_bucket"] == "<= 50bps"

    aliases = normalized["_producer_normalized_selector_context_aliases"]
    assert {
        (item["target_field"], item["source_field"], item["normalization"])
        for item in aliases
    } >= {
        (
            "timeframe",
            "source_redis_timeframe",
            "decision_time_selector_field_alias",
        ),
        (
            "expected_move_after_cost_bps",
            "paper_allocation_signed_expected_move_after_cost_bps",
            "decision_time_selector_field_alias",
        ),
    }

    summary = producer._selector_context_alias_summary([normalized])
    assert summary["target_field_counts"]["timeframe"] == 1
    assert summary["target_field_counts"]["expected_move_after_cost_bps"] == 1
    assert summary["source_field_counts"]["source_redis_timeframe"] == 1
    assert (
        summary["source_field_counts"][
            "paper_allocation_signed_expected_move_after_cost_bps"
        ]
        == 1
    )


def test_realtime_source_normalization_uses_path_timeframe_fallback() -> None:
    row = _row(
        row_id="selector-field-path-timeframe",
        path_telemetry_candle_timeframe="1h",
    )
    row.pop("timeframe", None)
    row.pop("source_redis_timeframe", None)

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="redis_path_telemetry_candidate",
        source_label="unit",
    )

    assert normalized["timeframe"] == "1h"
    aliases = normalized["_producer_normalized_selector_context_aliases"]
    assert {
        (item["target_field"], item["source_field"], item["normalization"])
        for item in aliases
    } >= {
        (
            "timeframe",
            "path_telemetry_candle_timeframe",
            "decision_time_selector_field_alias",
        )
    }


def test_realtime_source_normalization_does_not_overwrite_selector_fields() -> None:
    row = _row(
        row_id="selector-field-existing",
        timeframe="5m",
        source_redis_timeframe="15m",
        expected_move_after_cost_bps=45.0,
        expected_net_edge_bps=22.0,
        paper_allocation_signed_expected_move_after_cost_bps=75.0,
    )

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="redis_paper_ledger_accepted",
        source_label="unit",
    )

    assert normalized["timeframe"] == "5m"
    assert normalized["expected_move_after_cost_bps"] == 45.0
    assert normalized["expected_net_edge_bps"] == 22.0
    aliases = normalized.get("_producer_normalized_selector_context_aliases", [])
    assert {
        (item["target_field"], item["source_field"])
        for item in aliases
    }.isdisjoint({
        ("timeframe", "source_redis_timeframe"),
        (
            "expected_move_after_cost_bps",
            "paper_allocation_signed_expected_move_after_cost_bps",
        ),
    })


def test_realtime_source_normalization_does_not_treat_raw_expected_move_as_after_cost_edge() -> None:
    row = _row(
        row_id="selector-field-raw-expected-move",
        expected_move_bps=120.0,
    )
    row.pop("expected_move_after_cost_bps", None)
    row.pop("expected_net_edge_bps", None)
    row.pop("paper_allocation_signed_expected_move_after_cost_bps", None)

    normalized = producer._normalize_realtime_source_row(
        row,
        source_kind="redis_paper_ledger_accepted",
        source_label="unit",
    )
    bucket_payload = status_module._a_grade_bucket_key_payload(
        status_module._a_grade_bucket_key(normalized)
    )

    assert normalized["expected_move_bps"] == 120.0
    assert "expected_move_after_cost_bps" not in normalized
    assert status_module._expected_edge_bps(normalized) is None
    assert bucket_payload["expected_move_bucket"] == "__missing__"
    aliases = normalized.get("_producer_normalized_selector_context_aliases", [])
    assert all(
        item["target_field"] != "expected_move_after_cost_bps"
        for item in aliases
    )


def test_holdout_producer_rejects_missing_registry_and_malformed_jsonl(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [_row()], malformed=True)
    matrix = _bucket_matrix_for(tmp_path, _row())

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=tmp_path / "missing_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    assert manifest["accepted_appended_count"] == 0
    assert manifest["source_status"]["parse_error_count"] == 1
    assert manifest["rejection_reason_counts"]["NO_PRE_REGISTERED_HOLDOUT_WINDOW"] == 1
    assert manifest["sidecar_summary"]["row_count"] == 0
    assert manifest["holdout_registry_preflight"]["status"] == "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED"
    assert set(manifest["holdout_registry_preflight"]["global_reasons"]) == {
        "HOLDOUT_SOURCE_PARSE_ERRORS_PRESENT",
        "NO_REGISTERED_HOLDOUT_WINDOWS",
    }
    assert manifest["holdout_registry_preflight"]["registered_window_count"] == 0
    assert (tmp_path / "out_of_sample_holdout_window_registry_preflight.json").exists()
    assert (tmp_path / "missing_registry.json").exists()


def test_empty_holdout_registry_refreshes_source_metadata_without_promoting(
    tmp_path: Path,
) -> None:
    first_source = tmp_path / "first_source.jsonl"
    second_source = tmp_path / "second_source.jsonl"
    first_row = _row(row_id="first-source-row", source_redis_key="unit:first")
    second_row = _row(row_id="second-source-row", source_redis_key="unit:second")
    _write_jsonl(first_source, [first_row])
    _write_jsonl(second_source, [second_row])
    registry_path = tmp_path / "out_of_sample_holdout_window_registry.json"

    producer.produce_holdout(
        source_jsonl=first_source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=_bucket_matrix_for(tmp_path, first_row),
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )
    second_manifest = producer.produce_holdout(
        source_jsonl=second_source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=_bucket_matrix_for(tmp_path, second_row),
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T01:00:00Z",
    )
    registry = json.loads(registry_path.read_text())

    assert registry["source_path"] == str(second_source)
    assert registry["source_sha256"] == producer._file_sha256(second_source)
    assert registry["windows"] == []
    assert second_manifest["accepted_appended_count"] == 0
    assert second_manifest["pending_appended_count"] == 0
    assert second_manifest["holdout_registry_preflight"]["status"] == (
        "NO_GO_NO_REGISTERED_HOLDOUT_WINDOWS"
    )
    assert second_manifest["holdout_registry_preflight"]["global_reasons"] == [
        "NO_REGISTERED_HOLDOUT_WINDOWS"
    ]


def test_holdout_registry_manifest_history_is_append_only(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row()
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    rows_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl"
    registry_path = _registry(tmp_path, source)

    first_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )
    second_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T01:00:00Z",
    )

    registry_manifest_path = producer._holdout_registry_manifest_path(registry_path)
    registry_manifest = json.loads(registry_manifest_path.read_text())
    history_path = producer._manifest_history_path(registry_manifest_path)
    history_rows, _ = producer._iter_jsonl(history_path)
    history_status = producer.verify_manifest_history(
        manifest_path=registry_manifest_path,
        generated_utc="2026-06-21T01:00:00Z",
    )

    assert first_manifest["holdout_registry_manifest_path"] == str(registry_manifest_path)
    assert second_manifest["holdout_registry_manifest_path"] == str(registry_manifest_path)
    assert first_manifest["holdout_registry_manifest"]["registered_window_count"] == 1
    assert second_manifest["holdout_registry_manifest"]["registered_window_count"] == 1
    assert registry_manifest["registry_path"] == str(registry_path)
    assert registry_manifest["registry_sha256"] == producer._file_sha256(registry_path)
    assert registry_manifest["preflight_status"] == "READY_HOLDOUT_REGISTRY_PREFLIGHT"
    assert registry_manifest["window_summaries"][0]["window_id"] == "unit-untouched-window"
    assert registry_manifest["window_summaries"][0]["eligible_for_holdout"] is True
    assert (
        registry_manifest["window_summaries"][0]["exclusion_proof_status"]
        == "PASSED_UNTOUCHED"
    )
    assert len(history_rows) == 2
    assert history_rows[0]["previous_hash"] == "GENESIS"
    assert history_rows[1]["previous_hash"] == history_rows[0]["chain_hash"]
    assert all(row["manifest_path"] == str(registry_manifest_path) for row in history_rows)
    assert all(row["sidecar_path"] == str(registry_path) for row in history_rows)
    assert history_status["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"
    assert history_status["history_record_count"] == 2


def test_holdout_window_candidate_audit_is_non_countable_and_decision_time_only(tmp_path: Path) -> None:
    first_day_winner = _row(
        row_id="candidate-audit-day-1-win",
        symbol="BTCUSDT",
        decision_time="2026-06-21T12:00:00Z",
        available_at="2026-06-21T11:59:00Z",
        feature_cutoff="2026-06-21T11:55:00Z",
        after_cost_return_bps=400.0,
        realized_after_cost_return_bps=400.0,
    )
    first_day_loser = _row(
        row_id="candidate-audit-day-1-loss",
        symbol="ETHUSDT",
        decision_time="2026-06-21T13:00:00Z",
        available_at="2026-06-21T12:59:00Z",
        feature_cutoff="2026-06-21T12:55:00Z",
        after_cost_return_bps=-400.0,
        realized_after_cost_return_bps=-400.0,
    )
    second_day = _row(
        row_id="candidate-audit-day-2",
        symbol="SOLUSDT",
        decision_time="2026-06-22T01:00:00Z",
        available_at="2026-06-22T00:59:00Z",
        feature_cutoff="2026-06-22T00:55:00Z",
        after_cost_return_bps=50.0,
        realized_after_cost_return_bps=50.0,
    )
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [first_day_winner, first_day_loser, second_day])
    matrix = _bucket_matrix_for(tmp_path, first_day_winner)

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=tmp_path / "missing_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    audit_path = tmp_path / "out_of_sample_holdout_window_candidate_audit.json"
    promotion_packet_path = tmp_path / "out_of_sample_holdout_window_promotion_packet.json"
    construction_manifest_path = tmp_path / "out_of_sample_229_construction_identity_manifest.json"
    audit = json.loads(audit_path.read_text())
    promotion_packet = json.loads(promotion_packet_path.read_text())
    construction_manifest = json.loads(construction_manifest_path.read_text())
    first_window = audit["windows"][0]

    assert manifest["holdout_window_candidate_audit_path"] == str(audit_path)
    assert manifest["construction_subset_status_path"] == str(construction_manifest_path)
    assert manifest["construction_subset_identity_manifest_path"] == str(construction_manifest_path)
    assert manifest["construction_subset_identity_source_status"]["full_identity_set_available"] is True
    assert (
        manifest["construction_subset_identity_source_status"]["identity_hash_count"]
        == 2
    )
    assert manifest["construction_subset_identity_manifest"]["not_countable_holdout_evidence"] is True
    assert manifest["construction_subset_identity_manifest"]["selection_uses_outcome_fields"] is False
    assert (
        manifest["construction_subset_identity_manifest"][
            "outcome_fields_used_for_identity_derivation"
        ]
        == []
    )
    assert construction_manifest["not_countable_holdout_evidence"] is True
    assert construction_manifest["selection_uses_outcome_fields"] is False
    assert construction_manifest["outcome_fields_used_for_identity_derivation"] == []
    assert construction_manifest["validated_replay_candidate_count"] == 2
    assert construction_manifest["identity_hash_count"] == 2
    assert all(
        "after_cost_return_bps" not in row
        and "realized_after_cost_return_bps" not in row
        for row in construction_manifest["construction_subset_identity_rows"]
    )
    assert manifest["holdout_window_candidate_audit"]["draft_window_count"] == 2
    assert manifest["holdout_window_candidate_audit"]["readiness_uses_outcome_fields"] is False
    assert manifest["holdout_window_candidate_audit"]["outcome_fields_used_for_readiness"] == []
    assert (
        manifest["holdout_window_candidate_audit"]["draft_decision_time_candidate_ready_count"]
        == 2
    )
    assert manifest["holdout_window_candidate_audit"]["promotion_requires_source_sha256_match"] is True
    assert (
        manifest["holdout_window_candidate_audit"]["promotion_required_attestations"]
        == list(producer.REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS)
    )
    assert manifest["holdout_window_promotion_packet_path"] == str(promotion_packet_path)
    assert manifest["holdout_window_promotion_packet"]["packet_is_countable_evidence"] is False
    assert manifest["holdout_window_promotion_packet"]["draft_window_count"] == 2
    assert (
        manifest["holdout_window_promotion_packet"]["promotion_readiness_summary"]
        ["packet_is_countable_evidence"]
        is False
    )
    assert manifest["holdout_window_promotion_packet"]["readiness_uses_outcome_fields"] is False
    assert manifest["holdout_window_promotion_packet"]["outcome_fields_used_for_readiness"] == []
    assert (
        manifest["holdout_window_promotion_packet"]["draft_decision_time_candidate_ready_count"]
        == 2
    )
    assert audit["status"] == "DRAFT_HOLDOUT_WINDOW_CANDIDATES_NOT_COUNTABLE"
    assert audit["selection_uses_outcome_fields"] is False
    assert audit["readiness_uses_outcome_fields"] is False
    assert audit["outcome_fields_used_for_window_selection"] == []
    assert audit["outcome_fields_used_for_readiness"] == []
    assert audit["draft_windows_are_countable"] is False
    assert audit["promotion_requires_exclusion_proof_status"] == "PASSED_UNTOUCHED"
    assert audit["promotion_requires_source_sha256_match"] is True
    assert audit["promotion_required_attestations"] == list(
        producer.REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
    )
    assert promotion_packet["status"] == "READY_HOLDOUT_PROMOTION_PACKET_AWAITING_UNTOUCHED_PROOF"
    assert promotion_packet["packet_is_countable_evidence"] is False
    assert promotion_packet["selection_uses_outcome_fields"] is False
    assert promotion_packet["readiness_uses_outcome_fields"] is False
    assert promotion_packet["outcome_fields_used_for_window_selection"] == []
    assert promotion_packet["outcome_fields_used_for_readiness"] == []
    assert promotion_packet["source_sha256"] == audit["source_sha256"]
    assert promotion_packet["source_sha256_match_required"] is True
    assert promotion_packet["promotion_required_attestations"] == list(
        producer.REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
    )
    readiness_summary = promotion_packet["promotion_readiness_summary"]
    assert readiness_summary["status"] == "NO_COUNTABLE_HOLDOUT_WINDOWS_READY"
    assert readiness_summary["packet_is_countable_evidence"] is False
    assert readiness_summary["selection_uses_outcome_fields"] is False
    assert readiness_summary["readiness_uses_outcome_fields"] is False
    assert readiness_summary["draft_window_count"] == 2
    assert readiness_summary["draft_windows_with_decision_time_candidates_count"] == 1
    assert readiness_summary["draft_decision_time_candidate_ready_count"] == 2
    assert readiness_summary["draft_windows_with_overlap_proof_count"] == 1
    assert readiness_summary["draft_windows_with_no_overlap_proof_count"] == 1
    assert readiness_summary["draft_windows_with_no_overlap_ready_candidates_count"] == 0
    assert readiness_summary["draft_decision_time_ready_overlap_with_229_count"] == 2
    assert readiness_summary["draft_decision_time_ready_no_overlap_count"] == 0
    assert promotion_packet["registry_template"]["status"] == "DRAFT_NOT_COUNTABLE_AWAITING_UNTOUCHED_PROOF"
    assert promotion_packet["registry_template"]["windows"][0]["eligible_for_holdout"] is False
    assert (
        promotion_packet["registry_template"]["windows"][0]["exclusion_proof"]["status"]
        == "REQUIRES_PASSED_UNTOUCHED_PROOF"
    )
    assert first_window["window_id"] == "draft_holdout_decision_date_2026-06-21"
    assert first_window["source_row_count"] == 2
    first_window_hashes = first_window["window_hashes"]
    assert first_window_hashes["source_row_identity_hash_count"] == 2
    assert first_window_hashes["source_row_unique_identity_hash_count"] == 2
    assert first_window_hashes["decision_time_ready_identity_hash_count"] == 2
    assert first_window_hashes["selection_uses_outcome_fields"] is False
    assert first_window_hashes["outcome_fields_used_for_window_hash"] == []
    assert first_window["decision_time_candidate_ready_count"] == 2
    assert first_window["decision_time_ready_side_counts"] == {"long": 2}
    assert first_window["decision_time_reject_reason_counts"] == {}
    assert len(first_window["decision_time_ready_row_identity_hash_sample"]) == 2
    first_promotion_window = promotion_packet["draft_windows"][0]
    first_registry_template = promotion_packet["registry_template"]["windows"][0]
    assert (
        first_promotion_window["window_hashes"]["window_metadata_sha256"]
        == first_window_hashes["window_metadata_sha256"]
    )
    assert (
        first_registry_template["window_hashes"]["source_row_identity_hash_set_sha256"]
        == first_window_hashes["source_row_identity_hash_set_sha256"]
    )
    assert (
        first_registry_template["exclusion_proof"]["window_metadata_sha256"]
        == first_window_hashes["window_metadata_sha256"]
    )
    assert (
        first_registry_template["exclusion_proof"]["construction_subset_identity_proof"][
            "construction_subset_identity_hash_set_sha256"
        ]
        == construction_manifest["identity_hash_set_sha256"]
    )
    first_construction_proof = first_registry_template["exclusion_proof"][
        "construction_subset_identity_proof"
    ]
    assert first_construction_proof["status"] == "NO_GO_OVERLAPS_229_CONSTRUCTION_IDENTITIES"
    assert first_construction_proof["overlap_identity_hash_count"] == 2
    assert len(first_construction_proof["overlap_identity_hash_sample"]) == 2
    assert (
        first_construction_proof["overlap_identity_hashes_computed_from_exact_sets"]
        is True
    )
    assert (
        promotion_packet["draft_windows"][0]["decision_time_candidate_ready_count"]
        == 2
    )
    assert first_window["suggested_registry_window"]["eligible_for_holdout"] is False
    assert (
        first_window["suggested_registry_window"]["exclusion_proof"]["status"]
        == "REQUIRES_PASSED_UNTOUCHED_PROOF"
    )
    assert "expectancy_after_cost_bps" not in first_window
    assert "profit_factor" not in first_window


def test_broader_holdout_source_does_not_overwrite_exact_construction_manifest(
    tmp_path: Path,
) -> None:
    first = _row(row_id="broader-holdout-source-candidate-1")
    second = _row(
        row_id="broader-holdout-source-candidate-2",
        decision_time="2026-06-21T13:00:00Z",
    )
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [first, second])
    matrix = _bucket_matrix_for(tmp_path, first)
    canonical_manifest_path = (
        tmp_path / producer.DEFAULT_CONSTRUCTION_SUBSET_IDENTITY_MANIFEST_PATH.name
    )
    canonical_rows = [
        {"row_id": f"exact-construction-subset-{index:03d}"}
        for index in range(229)
    ]
    canonical_manifest = {
        "schema_version": producer.SCHEMA_VERSION,
        "status": "PASSED_DERIVED_229_CONSTRUCTION_SUBSET_IDENTITIES",
        "validated_replay_candidate_count": 229,
        "expected_construction_candidate_count": 229,
        "candidate_count_matches_expected_229": True,
        "selection_uses_outcome_fields": False,
        "outcome_fields_used_for_identity_derivation": [],
        "not_countable_holdout_evidence": True,
        "construction_subset_identity_rows": canonical_rows,
    }
    canonical_manifest_path.write_text(json.dumps(canonical_manifest, sort_keys=True))
    canonical_before = canonical_manifest_path.read_text()

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=tmp_path / "missing_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
        construction_subset_status_path=canonical_manifest_path,
    )

    holdout_source_manifest_path = (
        tmp_path
        / producer.DEFAULT_HOLDOUT_SOURCE_CANDIDATE_IDENTITY_MANIFEST_PATH.name
    )
    holdout_source_manifest = json.loads(holdout_source_manifest_path.read_text())

    assert canonical_manifest_path.read_text() == canonical_before
    assert holdout_source_manifest_path.exists()
    assert holdout_source_manifest["status"] == "NO_GO_DERIVED_CONSTRUCTION_SUBSET_COUNT_MISMATCH"
    assert holdout_source_manifest["validated_replay_candidate_count"] == 2
    assert holdout_source_manifest["candidate_count_matches_expected_229"] is False
    assert manifest["holdout_source_candidate_identity_manifest_path"] == str(
        holdout_source_manifest_path
    )
    assert (
        manifest["holdout_source_candidate_identity_manifest"][
            "validated_replay_candidate_count"
        ]
        == 2
    )
    assert (
        manifest["holdout_source_candidate_identity_manifest"][
            "candidate_count_matches_expected_229"
        ]
        is False
    )
    assert manifest["construction_subset_identity_manifest_path"] == str(
        canonical_manifest_path
    )
    assert manifest["construction_subset_status_path"] == str(canonical_manifest_path)
    assert manifest["construction_subset_identity_source_status"]["path"] == str(
        canonical_manifest_path
    )
    assert (
        manifest["construction_subset_identity_source_status"][
            "full_identity_set_available"
        ]
        is True
    )
    assert (
        manifest["construction_subset_identity_source_status"]["identity_hash_count"]
        == 229
    )
    assert (
        manifest["construction_subset_identity_manifest"][
            "validated_replay_candidate_count"
        ]
        == 229
    )


def test_holdout_audit_emits_clean_identity_filtered_template_for_mixed_overlap_day(
    tmp_path: Path,
) -> None:
    overlapping = _row(
        row_id="mixed-day-overlaps-construction",
        decision_time="2026-06-21T12:00:00Z",
    )
    clean = _row(
        row_id="mixed-day-clean-holdout-candidate",
        decision_time="2026-06-21T13:00:00Z",
    )
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [overlapping, clean])
    matrix = _bucket_matrix_for(tmp_path, overlapping)
    construction_status_path = _construction_subset_status_path(
        tmp_path,
        rows=[{"row_id": "mixed-day-overlaps-construction"}],
    )

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=tmp_path / "missing_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
        construction_subset_status_path=construction_status_path,
    )

    audit = json.loads(
        (tmp_path / "out_of_sample_holdout_window_candidate_audit.json").read_text()
    )
    promotion_packet = json.loads(
        (tmp_path / "out_of_sample_holdout_window_promotion_packet.json").read_text()
    )
    window = audit["windows"][0]
    clean_template = window["clean_no_overlap_registry_window_template"]
    clean_hash = producer._row_identity_hash(clean)
    overlapping_hash = producer._row_identity_hash(overlapping)
    readiness = promotion_packet["promotion_readiness_summary"]

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["holdout_window_candidate_audit"][
        "draft_decision_time_candidate_ready_count"
    ] == 2
    assert manifest["holdout_window_candidate_audit"][
        "draft_decision_time_ready_no_construction_overlap_count"
    ] == 1
    assert manifest["holdout_window_candidate_audit"][
        "draft_decision_time_ready_construction_overlap_count"
    ] == 1
    assert manifest["holdout_window_candidate_audit"][
        "clean_no_overlap_registry_template_count"
    ] == 1
    assert window["decision_time_candidate_ready_count"] == 2
    assert window["decision_time_ready_no_construction_overlap_count"] == 1
    assert window["decision_time_ready_construction_overlap_count"] == 1
    assert clean_template["eligible_for_holdout"] is False
    assert (
        clean_template["row_identity_filter_mode"]
        == "INCLUDE_ONLY_REGISTERED_SOURCE_ROW_IDENTITIES"
    )
    assert clean_template["registered_source_row_identity_hash_count"] == 1
    assert clean_template["registered_source_row_identity_hashes"] == [clean_hash]
    assert overlapping_hash not in clean_template["registered_source_row_identity_hashes"]
    assert (
        clean_template["exclusion_proof"]["construction_subset_identity_proof"][
            "status"
        ]
        == producer.CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
    )
    assert readiness["status"] == "DRAFT_HOLDOUT_WINDOWS_REQUIRE_UNTOUCHED_PROOF"
    assert readiness["draft_decision_time_ready_no_overlap_count"] == 0
    assert readiness["draft_decision_time_ready_row_level_no_overlap_count"] == 1
    assert readiness["clean_no_overlap_registry_template_count"] == 1
    assert promotion_packet["clean_no_overlap_registry_windows"][0][
        "registered_source_row_identity_hashes"
    ] == [clean_hash]
    assert promotion_packet["registry_template"]["windows"][-1][
        "row_identity_filter_mode"
    ] == "INCLUDE_ONLY_REGISTERED_SOURCE_ROW_IDENTITIES"
    assert promotion_packet["registry_template"]["windows"][-1][
        "eligible_for_holdout"
    ] is False


def test_window_for_row_enforces_registered_source_row_identity_hash_allowlist() -> None:
    allowed = _row(row_id="allowed-clean-row")
    blocked = _row(row_id="blocked-same-window-row")
    window = {
        "window_id": "identity-filtered-window",
        "start_decision_time": "2026-06-21T00:00:00Z",
        "end_decision_time": "2026-06-22T00:00:00Z",
        "symbols": ["BTCUSDT"],
        "timeframes": ["5m"],
        "row_identity_filter_mode": "INCLUDE_ONLY_REGISTERED_SOURCE_ROW_IDENTITIES",
        "registered_source_row_identity_hashes": [producer._row_identity_hash(allowed)],
    }
    registry = {"windows": [window]}

    assert producer._window_for_row(allowed, registry) == window
    assert producer._window_for_row(blocked, registry) is None


def test_holdout_registry_promotion_requires_passed_untouched_attestation(
    tmp_path: Path,
) -> None:
    clean = _row(row_id="clean-holdout-candidate")
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [clean])
    matrix = _bucket_matrix_for(tmp_path, clean)
    construction_status_path = _construction_subset_status_path(tmp_path)

    producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=tmp_path / "missing_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
        construction_subset_status_path=construction_status_path,
    )
    packet_path = tmp_path / "out_of_sample_holdout_window_promotion_packet.json"
    registry_path = tmp_path / "promoted_registry.json"
    manifest_path = (
        tmp_path / "out_of_sample_holdout_window_registry_promotion_manifest.json"
    )

    manifest = producer.promote_holdout_registry_from_packet(
        promotion_packet_path=packet_path,
        attestation_path=None,
        registry_path=registry_path,
        source_path=source,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T01:00:00Z",
        manifest_path=manifest_path,
    )

    history = producer.verify_manifest_history(
        manifest_path=manifest_path,
        generated_utc="2026-06-21T01:01:00Z",
    )

    assert manifest["status"] == "NO_GO_HOLDOUT_REGISTRY_PROMOTION_FAILED"
    assert manifest["registry_written"] is False
    assert registry_path.exists() is False
    assert "HOLDOUT_UNTOUCHED_ATTESTATION_PATH_MISSING" in manifest["global_reasons"]
    assert "NO_APPROVED_CLEAN_HOLDOUT_WINDOWS_IN_ATTESTATION" in manifest["global_reasons"]
    assert history["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"


def test_draft_holdout_registry_preregisters_clean_windows_without_counting(
    tmp_path: Path,
) -> None:
    overlapping = _row(
        row_id="draft-registry-overlaps-construction",
        decision_time="2026-06-21T12:00:00Z",
    )
    clean = _row(
        row_id="draft-registry-clean-holdout-candidate",
        source_redis_key="unit:draft-registry-clean-holdout-candidate",
        decision_time="2026-06-21T13:00:00Z",
    )
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [overlapping, clean])
    matrix = _bucket_matrix_for(tmp_path, overlapping)
    construction_status_path = _construction_subset_status_path(
        tmp_path,
        rows=[{"row_id": "draft-registry-overlaps-construction"}],
    )
    registry_path = tmp_path / "out_of_sample_holdout_window_registry.json"

    producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "initial_holdout_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
        construction_subset_status_path=construction_status_path,
    )
    packet_path = tmp_path / "out_of_sample_holdout_window_promotion_packet.json"
    draft_manifest_path = (
        tmp_path / "out_of_sample_holdout_window_registry_draft_manifest.json"
    )

    draft_manifest = producer.draft_holdout_registry_from_packet(
        promotion_packet_path=packet_path,
        registry_path=registry_path,
        source_path=source,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T01:00:00Z",
        construction_subset_status_path=construction_status_path,
        manifest_path=draft_manifest_path,
    )
    registry = json.loads(registry_path.read_text())
    registry_manifest_path = producer._holdout_registry_manifest_path(registry_path)
    registry_manifest = json.loads(registry_manifest_path.read_text())
    clean_hash = producer._row_identity_hash(clean)
    overlapping_hash = producer._row_identity_hash(overlapping)

    assert draft_manifest["status"] == "READY_DRAFT_HOLDOUT_REGISTRY_PREREGISTERED"
    assert draft_manifest["registry_written"] is True
    assert draft_manifest["clean_no_overlap_window_count"] == 1
    assert draft_manifest["draft_registered_window_count"] == 1
    assert draft_manifest["draft_policy"]["packet_is_countable_evidence"] is False
    assert draft_manifest["draft_policy"]["registry_windows_are_countable"] is False
    assert draft_manifest["registry_preflight"]["registered_window_count"] == 1
    assert draft_manifest["registry_preflight"]["status"] == (
        "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED"
    )
    assert "NO_STATICALLY_ELIGIBLE_HOLDOUT_WINDOWS" in draft_manifest[
        "registry_preflight"
    ]["global_reasons"]
    assert "NO_REGISTERED_HOLDOUT_WINDOWS" not in draft_manifest[
        "registry_preflight"
    ]["global_reasons"]
    assert registry["status"] == "DRAFT_NOT_COUNTABLE_AWAITING_UNTOUCHED_PROOF"
    assert registry["registered_window_count"] == 1
    assert registry["windows"][0]["eligible_for_holdout"] is False
    assert registry["windows"][0]["registered_source_row_identity_hashes"] == [clean_hash]
    assert overlapping_hash not in registry["windows"][0][
        "registered_source_row_identity_hashes"
    ]
    assert registry["windows"][0]["exclusion_proof"]["status"] == (
        "REQUIRES_PASSED_UNTOUCHED_PROOF"
    )
    assert registry_manifest["registered_window_count"] == 1
    assert registry_manifest["preflight_status"] == (
        "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED"
    )
    assert draft_manifest["history"]["history_path"] == str(
        producer._manifest_history_path(draft_manifest_path)
    )

    followup_dir = tmp_path / "draft_followup"
    followup_dir.mkdir()
    followup = producer.produce_holdout(
        source_jsonl=source,
        rows_path=followup_dir / "draft_holdout_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T02:00:00Z",
        construction_subset_status_path=construction_status_path,
    )

    assert followup["accepted_appended_count"] == 0
    assert followup["pending_appended_count"] == 0
    assert followup["holdout_registry_preflight"]["registered_window_count"] == 1
    assert followup["holdout_registry_preflight"]["status"] == (
        "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED"
    )
    assert (
        followup["rejection_reason_counts"]["HOLDOUT_WINDOW_NOT_MARKED_ELIGIBLE"]
        == 1
    )


def test_holdout_untouched_attestation_request_is_non_countable_template(
    tmp_path: Path,
) -> None:
    clean = _row(
        row_id="attestation-request-clean-holdout-candidate",
        source_redis_key="unit:attestation-request-clean-holdout-candidate",
        decision_time="2026-06-21T13:00:00Z",
    )
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [clean])
    matrix = _bucket_matrix_for(tmp_path, clean)
    construction_status_path = _construction_subset_status_path(tmp_path)

    producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "initial_holdout_rows.jsonl",
        registry_path=tmp_path / "out_of_sample_holdout_window_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
        construction_subset_status_path=construction_status_path,
    )
    packet_path = tmp_path / "out_of_sample_holdout_window_promotion_packet.json"
    request_path = tmp_path / "out_of_sample_holdout_untouched_attestation_request.json"

    request = producer.build_holdout_untouched_attestation_request(
        promotion_packet_path=packet_path,
        source_path=source,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T01:00:00Z",
        request_path=request_path,
    )
    request_from_disk = json.loads(request_path.read_text())
    history = producer.verify_manifest_history(
        manifest_path=request_path,
        generated_utc="2026-06-21T01:01:00Z",
    )

    assert request["status"] == "READY_HOLDOUT_UNTOUCHED_ATTESTATION_REQUEST"
    assert request_from_disk["status"] == "READY_HOLDOUT_UNTOUCHED_ATTESTATION_REQUEST"
    assert request["not_countable_holdout_evidence"] is True
    assert request["not_a_promotion_attestation"] is True
    assert request["selection_uses_outcome_fields"] is False
    assert request["outcome_fields_used_for_attestation_request"] == []
    assert request["request_path"] == str(request_path)
    assert request["clean_no_overlap_window_count"] == 1
    assert request["clean_no_overlap_identity_count"] == 1
    assert request["attestation_ready_window_count"] == 1
    assert request["total_registered_source_row_identity_hash_count"] == 1
    assert request["required_attestations"] == list(
        producer.REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
    )
    assert request["operator_attestation_required"] is True
    assert "independent reviewer" in request["next_required_actions"][0]
    assert request["window_requests"][0]["status"] == (
        "READY_FOR_INDEPENDENT_UNTOUCHED_ATTESTATION"
    )
    template = request["attestation_template"]
    assert template["status"] == "REQUIRES_INDEPENDENT_UNTOUCHED_REVIEW"
    assert template["required_final_status_for_promotion"] == "PASSED_UNTOUCHED"
    assert template["approve_all_clean_no_overlap_windows"] is True
    assert template["approved_window_ids"] == request["approved_window_ids"]
    assert set(template["attestations"]) == set(
        producer.REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
    )
    assert all(value is None for value in template["attestations"].values())
    assert history["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"


def test_cli_holdout_registry_promotion_does_not_clobber_producer_summary(
    tmp_path: Path,
) -> None:
    clean = _row(row_id="clean-holdout-candidate")
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [clean])
    matrix = _bucket_matrix_for(tmp_path, clean)
    construction_status_path = _construction_subset_status_path(tmp_path)

    producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=tmp_path / "missing_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
        construction_subset_status_path=construction_status_path,
    )
    existing_summary_path = tmp_path / "out_of_sample_evidence_producer_summary.json"
    existing_summary = {"status": "KEEP_EXISTING_PRODUCER_SUMMARY"}
    existing_summary_path.write_text(json.dumps(existing_summary))

    rc = producer.main([
        "promote-holdout-registry",
        "--out-dir",
        str(tmp_path),
        "--holdout-source-jsonl",
        str(source),
        "--holdout-promotion-packet",
        str(tmp_path / "out_of_sample_holdout_window_promotion_packet.json"),
        "--holdout-registry",
        str(tmp_path / "promoted_registry.json"),
        "--selector-policy-fingerprint",
        producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
    ])
    promotion_summary = json.loads(
        (tmp_path / "out_of_sample_holdout_window_registry_promotion_summary.json").read_text()
    )

    assert rc == 0
    assert json.loads(existing_summary_path.read_text()) == existing_summary
    assert (
        promotion_summary["holdout_registry_promotion"]["status"]
        == "NO_GO_HOLDOUT_REGISTRY_PROMOTION_FAILED"
    )


def test_holdout_registry_promotion_writes_clean_attested_registry_and_labels(
    tmp_path: Path,
) -> None:
    overlapping = _row(
        row_id="mixed-day-overlaps-construction",
        decision_time="2026-06-21T12:00:00Z",
    )
    clean = _row(
        row_id="mixed-day-clean-holdout-candidate",
        source_redis_key="unit:mixed-day-clean-holdout-candidate",
        decision_time="2026-06-21T13:00:00Z",
    )
    clean_later = _row(
        row_id="mixed-day-clean-holdout-candidate-later",
        source_redis_key="unit:mixed-day-clean-holdout-candidate-later",
        decision_time="2026-06-21T13:05:00Z",
    )
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [overlapping, clean, clean_later])
    matrix = _bucket_matrix_for(tmp_path, overlapping)
    construction_status_path = _construction_subset_status_path(
        tmp_path,
        rows=[{"row_id": "mixed-day-overlaps-construction"}],
    )

    producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=tmp_path / "missing_registry.json",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
        construction_subset_status_path=construction_status_path,
    )
    packet_path = tmp_path / "out_of_sample_holdout_window_promotion_packet.json"
    packet = json.loads(packet_path.read_text())
    clean_window = packet["clean_no_overlap_registry_windows"][0]
    attestation_path = tmp_path / "passed_untouched_attestation.json"
    attestation_path.write_text(json.dumps({
        "schema_version": producer.SCHEMA_VERSION,
        "status": "PASSED_UNTOUCHED",
        "selector_policy_fingerprint": producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "source_sha256": producer._file_sha256(source),
        "promotion_packet_sha256": producer._file_sha256(packet_path),
        "approved_window_ids": [clean_window["window_id"]],
        "attestations": _untouched_attestations(),
    }))
    registry_path = tmp_path / "promoted_registry.json"
    promotion_manifest_path = (
        tmp_path / "out_of_sample_holdout_window_registry_promotion_manifest.json"
    )

    promotion_manifest = producer.promote_holdout_registry_from_packet(
        promotion_packet_path=packet_path,
        attestation_path=attestation_path,
        registry_path=registry_path,
        source_path=source,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T01:00:00Z",
        manifest_path=promotion_manifest_path,
    )
    first_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "promoted_holdout_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T02:00:00Z",
        construction_subset_status_path=construction_status_path,
    )
    second_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "promoted_holdout_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T03:00:00Z",
        construction_subset_status_path=construction_status_path,
    )
    registry = json.loads(registry_path.read_text())
    final_rows, _ = producer._iter_jsonl(tmp_path / "promoted_holdout_rows.jsonl")
    promotion_history = producer.verify_manifest_history(
        manifest_path=promotion_manifest_path,
        generated_utc="2026-06-21T04:00:00Z",
    )

    assert promotion_manifest["status"] == "READY_HOLDOUT_REGISTRY_PROMOTED"
    assert promotion_manifest["registry_written"] is True
    assert promotion_manifest["promoted_window_count"] == 1
    assert registry["status"] == "READY_HOLDOUT_REGISTRY_PROMOTED_BY_UNTOUCHED_ATTESTATION"
    assert registry["windows"][0]["eligible_for_holdout"] is True
    assert registry["windows"][0]["exclusion_proof"]["status"] == "PASSED_UNTOUCHED"
    assert set(registry["windows"][0]["registered_source_row_identity_hashes"]) == {
        producer._row_identity_hash(clean),
        producer._row_identity_hash(clean_later),
    }
    assert first_manifest["pending_appended_count"] == 2
    assert first_manifest["accepted_appended_count"] == 0
    assert second_manifest["accepted_appended_count"] == 2
    assert len(final_rows) == 2
    assert {row["row_id"] for row in final_rows} == {
        "mixed-day-clean-holdout-candidate",
        "mixed-day-clean-holdout-candidate-later",
    }
    assert all(row["candidate_selected_before_outcome"] is True for row in final_rows)
    assert all(row["future_labels_used_as_features"] is False for row in final_rows)
    assert promotion_history["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"


def test_holdout_promotion_template_prefills_exact_no_overlap_proof(tmp_path: Path) -> None:
    holdout_row = _row(row_id="untouched-holdout-row")
    holdout_hashes = [producer._row_identity_hash(holdout_row)]
    window_hashes = producer._holdout_window_hashes(
        window_id="draft-holdout-no-overlap",
        start_decision_time="2026-06-21T00:00:00Z",
        end_decision_time="2026-06-21T01:00:00Z",
        symbols=["BTCUSDT"],
        timeframes=["5m"],
        source_row_identity_hashes=holdout_hashes,
        decision_time_ready_row_identity_hashes=holdout_hashes,
        source_sha256="unit-source-sha",
    )
    construction_status = producer._construction_subset_identity_source_status(
        _construction_subset_status_path(
            tmp_path,
            rows=[
                {"row_id": "construction-subset-not-holdout-1"},
                {"row_id": "construction-subset-not-holdout-2"},
            ],
        )
    )

    proof = producer._construction_subset_identity_proof_template(
        construction_subset_status=construction_status,
        window_hashes=window_hashes,
        source_row_identity_hashes=holdout_hashes,
    )

    assert proof["status"] == producer.CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
    assert proof["overlap_identity_hash_count"] == 0
    assert proof["overlap_identity_hash_sample"] == []
    assert proof["overlap_identity_hashes_computed_from_exact_sets"] is True


def test_holdout_registry_rejects_shallow_passed_untouched_proof(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row(row_id="shallow-proof")
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    _construction_subset_status_path(tmp_path)
    registry_path = tmp_path / "out_of_sample_holdout_window_registry.json"
    registry_path.write_text(json.dumps({
        "schema_version": producer.SCHEMA_VERSION,
        "status": "PASSED",
        "selector_policy_fingerprint": producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "windows": [{
            "window_id": "shallow-proof-window",
            "start_decision_time": "2026-06-21T00:00:00Z",
            "end_decision_time": "2026-06-22T00:00:00Z",
            "symbols": ["BTCUSDT"],
            "timeframes": ["5m"],
            "eligible_for_holdout": True,
            "exclusion_proof": {"status": "PASSED_UNTOUCHED"},
        }],
    }))

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    reasons = manifest["rejection_reason_counts"]
    window_summary = manifest["holdout_registry_preflight"]["windows"][0]["exclusion_proof_summary"]

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert reasons["HOLDOUT_EXCLUSION_PROOF_SOURCE_SHA256_MISSING"] == 1
    assert reasons[
        "HOLDOUT_EXCLUSION_PROOF_ATTESTATION_MISSING_NOT_USED_FOR_SELECTOR_DEVELOPMENT"
    ] == 1
    assert reasons["HOLDOUT_EXCLUSION_PROOF_WINDOW_METADATA_SHA256_MISSING"] == 1
    assert (
        reasons["HOLDOUT_EXCLUSION_PROOF_SOURCE_ROW_IDENTITY_HASH_SET_SHA256_MISSING"]
        == 1
    )
    assert reasons["HOLDOUT_CONSTRUCTION_SUBSET_IDENTITY_PROOF_NOT_PASSED"] == 1
    assert reasons["HOLDOUT_CONSTRUCTION_SUBSET_SOURCE_SHA256_MISSING"] == 1
    assert reasons["HOLDOUT_CONSTRUCTION_SUBSET_OVERLAP_COUNT_MISSING"] == 1
    assert window_summary["source_sha256_matches_current_source"] is None
    assert window_summary["window_metadata_sha256_matches_registry_window"] is None
    assert (
        window_summary["source_row_identity_hash_set_sha256_matches_registry_window"]
        is None
    )
    assert set(window_summary["missing_attestations"]) == set(
        producer.REQUIRED_HOLDOUT_UNTOUCHED_ATTESTATIONS
    )
    assert (
        window_summary["construction_subset_identity_proof"]["required_status"]
        == producer.CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS
    )
    assert (
        window_summary["construction_subset_identity_proof"][
            "construction_subset_full_identity_set_available"
        ]
        is True
    )


def test_holdout_registry_rejects_mismatched_untouched_proof_hashes(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row(row_id="mismatched-proof-hash")
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    registry_path = _registry(tmp_path, source)
    registry = json.loads(registry_path.read_text())
    registry["windows"][0]["exclusion_proof"]["window_metadata_sha256"] = "not-the-window-hash"
    registry["windows"][0]["exclusion_proof"][
        "source_row_identity_hash_set_sha256"
    ] = "not-the-source-row-set-hash"
    registry_path.write_text(json.dumps(registry))

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    reasons = manifest["rejection_reason_counts"]
    window_summary = manifest["holdout_registry_preflight"]["windows"][0][
        "exclusion_proof_summary"
    ]

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert reasons["HOLDOUT_EXCLUSION_PROOF_WINDOW_METADATA_SHA256_MISMATCH"] == 1
    assert (
        reasons["HOLDOUT_EXCLUSION_PROOF_SOURCE_ROW_IDENTITY_HASH_SET_SHA256_MISMATCH"]
        == 1
    )
    assert window_summary["window_metadata_sha256_matches_registry_window"] is False
    assert (
        window_summary["source_row_identity_hash_set_sha256_matches_registry_window"]
        is False
    )


def test_holdout_registry_rejects_mismatched_construction_subset_identity_proof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row(row_id="mismatched-construction-proof")
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    registry_path = _registry(tmp_path, source)
    registry = json.loads(registry_path.read_text())
    proof = registry["windows"][0]["exclusion_proof"][
        "construction_subset_identity_proof"
    ]
    proof["construction_subset_identity_hash_set_sha256"] = "not-the-construction-set"
    proof["overlap_identity_hash_count"] = "bad-count"
    registry_path.write_text(json.dumps(registry))

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    reasons = manifest["rejection_reason_counts"]
    construction_summary = (
        manifest["holdout_registry_preflight"]["windows"][0]
        ["exclusion_proof_summary"]["construction_subset_identity_proof"]
    )

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert (
        reasons["HOLDOUT_CONSTRUCTION_SUBSET_IDENTITY_HASH_SET_SHA256_MISMATCH"]
        == 1
    )
    assert reasons["HOLDOUT_CONSTRUCTION_SUBSET_OVERLAP_COUNT_MALFORMED"] == 1
    assert construction_summary["construction_subset_identity_hash_set_matches"] is False


def test_holdout_producer_rejects_construction_subset_identity_overlap(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    overlapping = _row(row_id="overlaps-construction-subset")
    _write_jsonl(source, [overlapping])
    matrix = _bucket_matrix_for(tmp_path, overlapping)
    registry_path = _registry(tmp_path, source)
    construction_status_path = _construction_subset_status_path(
        tmp_path,
        rows=[{"row_id": "overlaps-construction-subset"}],
    )
    construction_status = producer._construction_subset_identity_source_status(
        construction_status_path
    )
    registry = json.loads(registry_path.read_text())
    proof = registry["windows"][0]["exclusion_proof"][
        "construction_subset_identity_proof"
    ]
    proof["construction_subset_source_sha256"] = construction_status["sha256"]
    proof["construction_subset_candidate_count"] = construction_status["candidate_count"]
    proof["construction_subset_identity_hash_set_sha256"] = construction_status[
        "identity_hash_set_sha256"
    ]
    proof["overlap_identity_hash_count"] = 1
    proof["overlap_identity_hash_sample"] = construction_status["identity_hash_sample"][:1]
    registry_path.write_text(json.dumps(registry))

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    reasons = manifest["rejection_reason_counts"]

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert reasons["HOLDOUT_OVERLAPS_229_CANDIDATE_CONSTRUCTION_IDENTITY"] == 1
    assert reasons["HOLDOUT_CONSTRUCTION_SUBSET_IDENTITY_OVERLAP"] == 1
    assert manifest["holdout_registry_preflight"]["overlap_row_count"] == 1


def test_holdout_producer_appends_pending_then_labels_on_later_pass(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row()
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    rows_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl"
    registry_path = _registry(tmp_path, source)

    first_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )
    second_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T01:00:00Z",
    )

    sidecar_rows, _ = producer._iter_jsonl(rows_path)
    pending_rows, _ = producer._iter_jsonl(tmp_path / "out_of_sample_holdout_reverify_pending.jsonl")
    chain_rows, _ = producer._iter_jsonl(tmp_path / "out_of_sample_holdout_reverify_rows.jsonl.hash_chain.jsonl")

    assert first_manifest["accepted_appended_count"] == 0
    assert first_manifest["pending_appended_count"] == 1
    assert first_manifest["status"] == "READY_HOLDOUT_PENDING_SELECTIONS_APPENDED"
    assert first_manifest["pending_sidecar_summary"]["status"] == "READY_PENDING_SELECTIONS_WAITING_FOR_OUTCOMES"
    assert first_manifest["pending_sidecar_summary"]["row_count"] == 1
    assert first_manifest["pending_sidecar_summary"]["unresolved_pending_count"] == 1
    assert first_manifest["pending_sidecar_summary"]["outcome_field_presence_counts"] == {}
    assert second_manifest["accepted_appended_count"] == 1
    assert second_manifest["pending_appended_count"] == 0
    assert second_manifest["holdout_labeling_policy"] == "REQUIRES_PREEXISTING_PENDING_SELECTION_RECORD"
    assert second_manifest["labeled_from_preexisting_pending_count"] == 1
    assert second_manifest["pending_sidecar_summary"]["status"] == "READY_PENDING_SELECTIONS_ALL_FINALIZED"
    assert second_manifest["pending_sidecar_summary"]["finalized_pending_count"] == 1
    assert len(sidecar_rows) == 1
    assert len(pending_rows) == 1
    assert [row["event_type"] for row in chain_rows] == [
        "holdout_candidate_selected_before_label",
        "holdout_labeled",
    ]
    assert sidecar_rows[0]["selector_policy_fingerprint"] == producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT
    assert sidecar_rows[0]["candidate_selection_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert sidecar_rows[0]["candidate_selected_before_outcome"] is True
    assert sidecar_rows[0]["future_labels_used_as_features"] is False
    assert sidecar_rows[0]["after_cost_return_bps"] == 35.0
    assert "funding_pnl_usd" not in pending_rows[0]
    assert "funding_pnl_accounting_status" not in pending_rows[0]
    assert sidecar_rows[0]["funding_pnl_usd"] == -0.02


def test_forward_holdout_preregistration_arms_future_window_without_counting(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [])
    matrix_path = tmp_path / "a_grade_bucket_performance_matrix.json"
    matrix_path.write_text(json.dumps({"buckets": []}))
    construction_status_path = _construction_subset_status_path(tmp_path)
    registry_path = tmp_path / "out_of_sample_holdout_window_registry.json"
    manifest_path = tmp_path / "out_of_sample_forward_holdout_pre_registration.json"

    manifest = producer.forward_preregister_holdout_registry(
        registry_path=registry_path,
        source_path=source,
        bucket_matrix_path=matrix_path,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T23:55:00Z",
        window_start="2026-06-22T00:00:00Z",
        start_delay_minutes=5.0,
        window_minutes=60.0,
        window_count=1,
        construction_subset_status_path=construction_status_path,
        manifest_path=manifest_path,
    )

    registry = json.loads(registry_path.read_text())
    window = registry["windows"][0]
    proof = window["exclusion_proof"]

    assert manifest["status"] == "READY_FORWARD_HOLDOUT_REGISTRY_PREREGISTERED"
    assert manifest["not_countable_holdout_evidence"] is True
    assert manifest["does_not_mark_ready"] is True
    assert manifest["source_sha256_bound_to_registry"] is False
    assert registry["status"] == "FORWARD_PRE_REGISTERED_AWAITING_OUTCOMES"
    assert registry["source_sha256"] is None
    assert window["eligible_for_holdout"] is True
    assert window["forward_pre_registered"] is True
    assert proof["status"] == producer.FORWARD_HOLDOUT_PROOF_STATUS
    assert proof["source_sha256"] is None
    assert proof["source_sha256_policy"] == "NOT_BOUND_BEFORE_FORWARD_ROWS_EXIST"
    assert proof["construction_subset_identity_proof"]["status"] == (
        producer.FORWARD_CONSTRUCTION_SUBSET_PROOF_STATUS
    )
    assert manifest["registry_preflight"]["status"] == (
        "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED"
    )
    assert "REGISTERED_HOLDOUT_WINDOWS_MATCH_NO_SOURCE_ROWS" in manifest[
        "registry_preflight"
    ]["global_reasons"]


def test_forward_holdout_pending_must_precede_outcome_label(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    pending_source = producer._without_outcome_fields(_row(
        row_id="forward-preoutcome-candidate",
        source_redis_key="unit:forward-preoutcome-candidate",
        decision_time="2026-06-22T00:10:00Z",
        available_at="2026-06-22T00:09:30Z",
        generated_at="2026-06-22T00:09:20Z",
        future_label_close_time="2026-06-22T00:45:00Z",
    ))
    _write_jsonl(source, [pending_source])
    matrix = _bucket_matrix_for(tmp_path, pending_source)
    construction_status_path = _construction_subset_status_path(tmp_path)
    registry_path = tmp_path / "out_of_sample_holdout_window_registry.json"
    rows_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl"

    producer.forward_preregister_holdout_registry(
        registry_path=registry_path,
        source_path=source,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T23:55:00Z",
        window_start="2026-06-22T00:00:00Z",
        start_delay_minutes=5.0,
        window_minutes=60.0,
        window_count=1,
        construction_subset_status_path=construction_status_path,
        manifest_path=tmp_path / "out_of_sample_forward_holdout_pre_registration.json",
    )
    pending_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-22T00:11:00Z",
        construction_subset_status_path=construction_status_path,
    )

    labeled_source = _row(
        row_id="forward-preoutcome-candidate",
        source_redis_key="unit:forward-preoutcome-candidate",
        decision_time="2026-06-22T00:10:00Z",
        available_at="2026-06-22T00:09:30Z",
        generated_at="2026-06-22T00:09:20Z",
        future_label_close_time="2026-06-22T00:45:00Z",
        after_cost_return_bps=44.0,
        realized_after_cost_return_bps=44.0,
        realized_pnl_usd=4.4,
    )
    _write_jsonl(source, [labeled_source])
    final_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-22T00:46:00Z",
        construction_subset_status_path=construction_status_path,
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_holdout_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert pending_manifest["pending_appended_count"] == 1
    assert pending_manifest["accepted_appended_count"] == 0
    assert pending_manifest["rejected_appended_count"] == 0
    assert "after_cost_return_bps" not in pending_rows[0]
    assert pending_rows[0]["candidate_selected_at"] == "2026-06-22T00:11:00Z"
    assert final_manifest["accepted_appended_count"] == 1
    assert final_manifest["pending_appended_count"] == 0
    assert len(final_rows) == 1
    assert final_rows[0]["candidate_selected_at"] == "2026-06-22T00:11:00Z"
    assert final_rows[0]["future_label_close_time"] == "2026-06-22T00:45:00Z"
    assert final_rows[0]["after_cost_return_bps"] == 44.0


def test_forward_holdout_rejects_post_outcome_candidate_selection(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    labeled_source = _row(
        row_id="forward-postoutcome-candidate",
        source_redis_key="unit:forward-postoutcome-candidate",
        decision_time="2026-06-22T00:10:00Z",
        available_at="2026-06-22T00:09:30Z",
        generated_at="2026-06-22T00:09:20Z",
        future_label_close_time="2026-06-22T00:45:00Z",
    )
    _write_jsonl(source, [labeled_source])
    matrix = _bucket_matrix_for(tmp_path, labeled_source)
    construction_status_path = _construction_subset_status_path(tmp_path)
    registry_path = tmp_path / "out_of_sample_holdout_window_registry.json"

    producer.forward_preregister_holdout_registry(
        registry_path=registry_path,
        source_path=source,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T23:55:00Z",
        window_start="2026-06-22T00:00:00Z",
        start_delay_minutes=5.0,
        window_minutes=60.0,
        window_count=1,
        construction_subset_status_path=construction_status_path,
        manifest_path=tmp_path / "out_of_sample_forward_holdout_pre_registration.json",
    )
    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-22T00:46:00Z",
        construction_subset_status_path=construction_status_path,
    )

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert manifest["rejection_reason_counts"][
        "MISSING_PREOUTCOME_PENDING_SELECTION_RECORD_FOR_FORWARD_HOLDOUT"
    ] == 1


def test_holdout_registry_preflight_uses_decision_time_fields_not_outcome_value(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid_loser = _row(
        row_id="valid-loser",
        source_redis_key="unit:valid-loser",
        after_cost_return_bps=-42.0,
        realized_after_cost_return_bps=-42.0,
        realized_pnl_usd=-4.2,
    )
    _write_jsonl(source, [valid_loser])
    matrix = _bucket_matrix_for(tmp_path, valid_loser)
    rows_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl"
    registry_path = _registry(tmp_path, source)

    first_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )
    second_manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T01:00:00Z",
    )

    final_rows, _ = producer._iter_jsonl(rows_path)
    preflight = first_manifest["holdout_registry_preflight"]

    assert first_manifest["accepted_appended_count"] == 0
    assert first_manifest["pending_appended_count"] == 1
    assert second_manifest["accepted_appended_count"] == 1
    assert final_rows[0]["after_cost_return_bps"] == -42.0
    assert preflight["status"] == "READY_HOLDOUT_REGISTRY_PREFLIGHT"
    assert preflight["decision_time_candidate_ready_count"] == 1
    assert preflight["countable_after_label_count"] == 1
    assert preflight["candidate_selection_preflight"]["selection_does_not_filter_by_outcome"] is True
    assert "after_cost_return_bps" in preflight["candidate_selection_preflight"]["outcome_fields_excluded_before_selection"]


def test_holdout_producer_rejects_duplicate_bad_fingerprint_future_leak_post_selected_overlap_and_accounting(
    tmp_path: Path,
) -> None:
    valid = _row(row_id="valid", source_redis_key="unit:valid")
    source = tmp_path / "source.jsonl"
    rows = [
        valid,
        dict(valid),
        _row(row_id="missing-fingerprint", selector_policy_fingerprint=None),
        _row(row_id="bad-fingerprint", selector_policy_fingerprint="wrong"),
        _row(row_id="not-a-grade", candidate_selection_tier="B_GRADE_EXPLORATION_PAPER"),
        _row(row_id="future-leak", available_at="2026-06-21T12:01:00Z"),
        _row(row_id="post-selected", candidate_selected_before_outcome=False),
        _row(row_id="overlap", used_for_229_candidate_subset=True),
        _row(row_id="incomplete-accounting", gross_notional_usd=None),
    ]
    _write_jsonl(source, rows)
    matrix = _bucket_matrix_for(tmp_path, valid)

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=_registry(tmp_path, source),
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    reasons = manifest["rejection_reason_counts"]
    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 1
    assert manifest["duplicate_skipped_count"] == 1
    assert reasons["SOURCE_SELECTOR_POLICY_FINGERPRINT_MISSING"] == 1
    assert reasons["SOURCE_SELECTOR_POLICY_FINGERPRINT_MISMATCH"] == 1
    assert reasons["SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING"] == 1
    assert reasons["AVAILABLE_AT_AFTER_DECISION_TIME"] == 1
    assert reasons["CANDIDATE_SELECTION_MARKED_AFTER_OUTCOME"] == 1
    assert reasons["HOLDOUT_OVERLAPS_229_CANDIDATE_SUBSET"] == 1
    assert reasons["MISSING_ACCOUNTING_GROSS_NOTIONAL"] == 1


def test_realtime_producer_requires_pending_and_rejects_live_order_flags(tmp_path: Path) -> None:
    closed = _row(row_id="closed", source_redis_key="unit:closed")
    live = _row(row_id="live", source_redis_key="unit:live", live_order=True)
    source_json = tmp_path / "paper_ledger_tail.json"
    source_json.write_text(json.dumps({"entries": [closed, live]}))
    matrix = _bucket_matrix_for(tmp_path, closed)

    manifest = producer.produce_realtime(
        rows_path=tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    assert manifest["accepted_appended_count"] == 0
    assert manifest["rejection_reason_counts"]["MISSING_PENDING_SELECTION_RECORD_FOR_CLOSED_OUTCOME"] == 2
    assert manifest["rejection_reason_counts"]["REALTIME_SOURCE_REAL_ORDER_FLAG_TRUE"] == 1


def test_realtime_stale_source_cannot_create_new_pending(tmp_path: Path) -> None:
    stale_source = producer._without_outcome_fields(_row(
        row_id="stale-pending",
        source_redis_key="unit:stale-pending",
    ))
    source_json = tmp_path / "stale_runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [stale_source]}))
    matrix = _bucket_matrix_for(tmp_path, stale_source)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:30:01Z",
    )

    pending_rows, _ = producer._iter_jsonl(tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl")
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert manifest["pending_sidecar_summary"]["source_status"]["exists"] is True
    assert manifest["pending_sidecar_summary"]["row_count"] == 0
    assert (
        manifest["rejection_reason_counts"]["REALTIME_PENDING_SOURCE_STALE_FOR_NEW_PENDING_RECORD"]
        == 1
    )
    assert manifest["source_gate_breakdown"]["category_counts"]["evidence_protocol"] == 1
    assert manifest["realtime_pending_source_freshness_policy"]["maximum_source_age_seconds"] == 900
    assert pending_rows == []
    assert final_rows == []


def test_rows_from_json_extracts_current_signal_lineage_without_outcomes(tmp_path: Path) -> None:
    source_json = tmp_path / "current_signal_lineage.json"
    source_json.write_text(json.dumps({
        "classification": "REALTIME_RUNTIME_EVIDENCE",
        "generated_at": "2026-06-21T12:00:00Z",
        "signal": {
            "symbol": "ETHUSDT",
            "timeframe": "5m",
            "side": "short",
            "decision_time": "2026-06-21T12:00:00Z",
            "available_at": "2026-06-21T11:59:30Z",
            "feature_cutoff": "2026-06-21T11:55:00Z",
            "confidence_calibrated": 0.82,
            "expected_move_after_cost_bps": 45.0,
            "strategy": "range_reversion",
            "market_regime": "range",
            "volatility_bucket": "medium",
            "liquidity_bucket": "high",
            "signal_id": "sig-current",
            "prediction_id": "pred-current",
            "feature_snapshot_id": "fs-current",
        },
        "trainer_prediction": {
            "prediction_id": "pred-current",
            "realized_outcome_bps": -999.0,
            "realized_outcome_direction": "loss",
            "realized_at_ms": 1782110000000,
        },
        "execution_intent": {
            "exchange_order_allowed": False,
            "paper_only": True,
            "execution_intent_id": "intent-current",
            "risk_decision_id": "risk-current",
            "signal_id": "sig-current",
        },
        "lineage_ids": {
            "prediction_id": "pred-current",
            "signal_id": "sig-current",
            "feature_snapshot_id": "fs-current",
        },
    }))

    rows, status = producer._rows_from_json(source_json)

    assert status["row_count"] == 1
    assert status["extracted_row_counts"]["current_signal_lineage"] == 1
    assert rows[0]["_producer_extracted_from_json"] == "current_signal_lineage"
    assert rows[0]["symbol"] == "ETHUSDT"
    assert rows[0]["timeframe"] == "5m"
    assert rows[0]["side"] == "short"
    assert rows[0]["strategy"] == "range_reversion"
    assert rows[0]["future_labels_used_as_features"] is False
    assert rows[0]["places_real_order"] is False
    assert rows[0]["paper_only"] is True
    assert rows[0]["lineage_ids"]["prediction_id"] == "pred-current"
    assert "realized_outcome_bps" not in rows[0]
    assert "realized_outcome_direction" not in rows[0]
    assert "realized_at_ms" not in rows[0]


def test_realtime_current_signal_lineage_can_create_pending_when_gates_pass(
    tmp_path: Path,
) -> None:
    candidate = producer._without_outcome_fields(_row(
        row_id="current-lineage-ready",
        source_redis_key="unit:current-lineage-ready",
        signal_id="sig-ready",
        prediction_id="pred-ready",
    ))
    source_json = tmp_path / "current_signal_lineage.json"
    source_json.write_text(json.dumps({
        "classification": "REALTIME_RUNTIME_EVIDENCE",
        "generated_at": "2026-06-21T12:00:00Z",
        "signal": {
            key: value
            for key, value in candidate.items()
            if key
            not in {
                "row_id",
                "source_redis_key",
                "candidate_identity",
                "position_identity",
            }
        },
        "trainer_prediction": {
            "prediction_id": "pred-ready",
            "realized_outcome_bps": 123.0,
        },
        "execution_intent": {
            "exchange_order_allowed": False,
            "paper_only": True,
            "execution_intent_id": "intent-ready",
            "risk_decision_id": "risk-ready",
            "signal_id": "sig-ready",
        },
        "lineage_ids": {
            "prediction_id": "pred-ready",
            "signal_id": "sig-ready",
            "execution_intent_id": "intent-ready",
        },
    }))
    extracted_rows, _ = producer._rows_from_json(source_json)
    matrix = _bucket_matrix_for(tmp_path, extracted_rows[0])
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 1
    assert manifest["rejected_appended_count"] == 0
    assert manifest["source_statuses"][0]["extracted_row_counts"]["current_signal_lineage"] == 1
    assert (
        manifest["realtime_source_readiness_summary"]["candidate_ready_source_row_count"]
        == 1
    )
    assert pending_rows[0]["candidate_selection_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert pending_rows[0]["candidate_selected_before_outcome"] is True
    assert pending_rows[0]["future_labels_used_as_features"] is False
    assert pending_rows[0]["paper_only"] is True
    assert pending_rows[0]["places_real_order"] is False
    assert pending_rows[0]["lineage_ids"]["prediction_id"] == "pred-ready"
    assert "realized_outcome_bps" not in pending_rows[0]
    assert final_rows == []


def test_realtime_producer_rejects_missing_selector_policy_fingerprint(
    tmp_path: Path,
) -> None:
    source_row = producer._without_outcome_fields(_row(
        row_id="missing-realtime-fingerprint",
        source_redis_key="unit:missing-realtime-fingerprint",
        selector_policy_fingerprint=None,
    ))
    eligible_reference = _row(row_id="eligible-reference")
    source_json = tmp_path / "runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [source_row]}))
    matrix = _bucket_matrix_for(tmp_path, eligible_reference)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert manifest["rejection_reason_counts"] == {
        "SOURCE_SELECTOR_POLICY_FINGERPRINT_MISSING": 1,
    }
    assert (
        manifest["source_gate_breakdown"]["category_counts"]["fingerprint"]
        == 1
    )
    assert pending_rows == []
    assert final_rows == []


def test_realtime_producer_requires_source_a_grade_execution_admission(
    tmp_path: Path,
) -> None:
    source_row = producer._without_outcome_fields(_row(
        row_id="non-a-grade-realtime",
        source_redis_key="unit:non-a-grade-realtime",
        candidate_selection_tier="B_GRADE_EXPLORATION_PAPER",
    ))
    eligible_reference = _row(row_id="eligible-reference")
    source_json = tmp_path / "runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [source_row]}))
    matrix = _bucket_matrix_for(tmp_path, eligible_reference)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert manifest["rejection_reason_counts"] == {
        "SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING": 1,
    }
    assert (
        manifest["source_gate_breakdown"]["category_counts"]["frozen_selector"]
        == 1
    )
    assert pending_rows == []
    assert final_rows == []


def test_realtime_producer_rejects_missing_paper_only_source_flag(
    tmp_path: Path,
) -> None:
    source_row = producer._without_outcome_fields(_row(
        row_id="missing-paper-only",
        source_redis_key="unit:missing-paper-only",
    ))
    source_row.pop("paper_only", None)
    eligible_reference = _row(row_id="eligible-reference")
    source_json = tmp_path / "runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [source_row]}))
    matrix = _bucket_matrix_for(tmp_path, eligible_reference)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert manifest["rejection_reason_counts"] == {
        "REALTIME_SOURCE_PAPER_ONLY_FLAG_MISSING": 1,
    }
    assert manifest["source_gate_breakdown"]["category_counts"]["safety"] == 1
    assert pending_rows == []
    assert final_rows == []


def test_realtime_producer_rejects_missing_real_order_source_flag(
    tmp_path: Path,
) -> None:
    source_row = producer._without_outcome_fields(_row(
        row_id="missing-real-order-flag",
        source_redis_key="unit:missing-real-order-flag",
    ))
    source_row.pop("places_real_order", None)
    source_row.pop("live_order", None)
    eligible_reference = _row(row_id="eligible-reference")
    source_json = tmp_path / "runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [source_row]}))
    matrix = _bucket_matrix_for(tmp_path, eligible_reference)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert manifest["rejection_reason_counts"] == {
        "REALTIME_SOURCE_REAL_ORDER_FLAG_MISSING": 1,
    }
    assert manifest["source_gate_breakdown"]["category_counts"]["safety"] == 1
    assert pending_rows == []
    assert final_rows == []


def test_rows_from_json_extracts_paper_loop_once_allocations_without_outcomes(
    tmp_path: Path,
) -> None:
    source_json = tmp_path / "PAPER_LOOP_ONCE_STATUS.json"
    source_json.write_text(json.dumps({
        "classification": "PAPER_RUNTIME_STATUS",
        "started_at": "2026-06-21T11:59:00Z",
        "finished_at": "2026-06-21T12:00:00Z",
        "places_real_order": False,
        "paper_adaptive_sizing_runtime_status": {
            "status": "READY",
            "generated_utc": "2026-06-21T12:00:00Z",
            "paper_only": True,
            "sample_allocations": [{
                "allocation_id": "alloc-current",
                "policy_activated_at": "2026-06-21T11:59:59Z",
                "symbol": "ETHUSDT",
                "timeframe": "5m",
                "action": "short",
                "confidence_calibrated": 0.82,
                "expected_move_after_cost_bps": 45.0,
                "strategy": "range_reversion",
                "market_regime": "range",
                "volatility_bucket": "medium",
                "liquidity_bucket": "high",
                "target_notional_usdt": 2500.0,
                "target_quantity": 1.25,
                "risk_budget_pct_of_equity": 0.01,
                "model_inputs": {
                    "spread_bps": 1.7,
                    "slippage_bps": 2.1,
                    "correlation_exposure_pct": 0.08,
                    "volatility_bps": 80.0,
                    "liquidity_score": 0.9,
                    "selected_leverage": 2.0,
                    "selected_margin_mode": "isolated_paper_simulated",
                    "stop_distance_bps": 80.0,
                    "fee_bps": 4.0,
                    "expected_funding_bps": 0.2,
                    "funding_rate": 0.00002,
                    "orderbook_depth_usd": 500000.0,
                },
                "lineage_ids": {
                    "prediction_id": "pred-alloc",
                    "signal_id": "sig-alloc",
                    "risk_decision_id": "risk-alloc",
                },
                "after_cost_return_bps": 999.0,
                "realized_outcome_bps": 999.0,
                "closed_at": "2026-06-21T13:00:00Z",
            }],
        },
    }))

    rows, status = producer._rows_from_json(source_json)

    assert status["row_count"] == 1
    assert status["extracted_row_counts"]["paper_loop_once_sample_allocation"] == 1
    assert rows[0]["_producer_extracted_from_json"] == "paper_loop_once_sample_allocation"
    assert (
        rows[0]["_producer_source_payload_shape"]
        == "nested_paper_adaptive_sizing_runtime_status"
    )
    assert rows[0]["row_id"] == "paper_loop_once_allocation:alloc-current"
    assert rows[0]["policy_activated_at"] == "2026-06-21T11:59:59Z"
    assert rows[0]["symbol"] == "ETHUSDT"
    assert rows[0]["side"] == "short"
    assert rows[0]["paper_only"] is True
    assert rows[0]["places_real_order"] is False
    assert rows[0]["lineage_ids"]["prediction_id"] == "pred-alloc"
    assert rows[0]["gross_notional_usd"] == 2500.0
    assert rows[0]["entry_spread_bps"] == 1.7
    assert rows[0]["actual_observed_spread_entry_bps"] == 1.7
    assert rows[0]["expected_slippage_bps"] == 2.1
    assert rows[0]["correlation_exposure_pct"] == 0.08
    assert rows[0]["recommended_leverage"] == 2.0
    assert rows[0]["effective_leverage"] == 2.0
    assert rows[0]["allocated_margin_usd"] == 1250.0
    assert rows[0]["recommended_margin_mode"] == "isolated_paper_simulated"
    assert rows[0]["margin_mode"] == "isolated_paper_simulated"
    assert rows[0]["stop_distance_bps"] == 80.0
    assert rows[0]["fee_bps"] == 4.0
    assert rows[0]["expected_fees_usd"] == 1.0
    assert rows[0]["expected_funding_bps"] == 0.2
    assert rows[0]["expected_funding_usd"] == 0.05
    assert rows[0]["funding_rate"] == 0.00002
    assert rows[0]["orderbook_depth_usd"] == 500000.0
    alias_targets = {
        item["target_field"]: item
        for item in rows[0]["_producer_normalized_accounting_aliases"]
    }
    assert alias_targets["recommended_leverage"]["source_field"] == (
        "model_inputs.selected_leverage"
    )
    assert alias_targets["allocated_margin_usd"]["normalization"] == (
        "paper_loop_once_allocation_derived_accounting"
    )
    assert alias_targets["expected_fees_usd"]["formula"] == (
        "gross_notional_usd * fee_bps / 10000"
    )
    assert alias_targets["expected_funding_usd"]["formula"] == (
        "gross_notional_usd * expected_funding_bps / 10000"
    )
    assert rows[0]["future_labels_used_as_features"] is False
    assert "after_cost_return_bps" not in rows[0]
    assert "realized_outcome_bps" not in rows[0]
    assert "closed_at" not in rows[0]


def test_rows_from_json_extracts_top_level_paper_adaptive_sizing_status(
    tmp_path: Path,
) -> None:
    source_json = tmp_path / "paper_adaptive_sizing_runtime_status.json"
    source_json.write_text(json.dumps({
        "generated_utc": "2026-06-21T12:00:00Z",
        "paper_only": True,
        "allocator": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        "paper_candidates_with_allocation": 1,
        "sample_allocations": [{
            "allocation_id": "alloc-top-level",
            "policy_activated_at": "2026-06-21T11:59:58Z",
            "symbol": "SOLUSDT",
            "timeframe": "15m",
            "action": "short",
            "confidence_calibrated": 0.81,
            "expected_move_after_cost_bps": 55.0,
            "strategy": "mean_reversion",
            "market_regime": "whipsaw",
            "volatility_bucket": "medium",
            "liquidity_bucket": "low",
            "target_notional_usdt": 1200.0,
            "recommended_leverage": 3.0,
            "model_inputs": {
                "selected_margin_mode": "isolated_paper_simulated",
                "fee_bps": 4.0,
                "expected_funding_bps": 0.5,
                "spread_bps": 1.25,
            },
            "lineage_ids": {"prediction_id": "pred-top-level"},
            "realized_outcome_bps": 777.0,
        }],
    }))

    rows, status = producer._rows_from_json(source_json)

    assert status["row_count"] == 1
    assert status["extracted_row_counts"]["paper_loop_once_sample_allocation"] == 1
    assert rows[0]["_producer_extracted_from_json"] == "paper_loop_once_sample_allocation"
    assert (
        rows[0]["_producer_source_payload_shape"]
        == "top_level_paper_adaptive_sizing_runtime_status"
    )
    assert rows[0]["row_id"] == "paper_loop_once_allocation:alloc-top-level"
    assert rows[0]["policy_activated_at"] == "2026-06-21T11:59:58Z"
    assert rows[0]["symbol"] == "SOLUSDT"
    assert rows[0]["side"] == "short"
    assert rows[0]["paper_only"] is True
    assert rows[0]["source_runtime_generated_at"] == "2026-06-21T12:00:00Z"
    assert rows[0]["lineage_ids"]["prediction_id"] == "pred-top-level"
    assert rows[0]["gross_notional_usd"] == 1200.0
    assert rows[0]["entry_spread_bps"] == 1.25
    assert rows[0]["expected_fees_usd"] == 0.48
    assert rows[0]["expected_funding_usd"] == 0.06
    assert "decision_time" not in rows[0]
    assert "realized_outcome_bps" not in rows[0]


def test_rows_from_json_extracts_full_candidate_allocations_before_samples(
    tmp_path: Path,
) -> None:
    source_json = tmp_path / "paper_adaptive_sizing_runtime_status.json"
    candidate = {
        "allocation_id": "alloc-full-1",
        "policy_activated_at": "2026-06-21T11:59:58Z",
        "symbol": "SOLUSDT",
        "timeframe": "15m",
        "action": "short",
        "confidence_calibrated": 0.86,
        "expected_move_after_cost_bps": 85.0,
        "strategy": "mean_reversion",
        "market_regime": "bull",
        "volatility_bucket": "low",
        "liquidity_bucket": "low",
        "target_notional_usdt": 1200.0,
        "recommended_leverage": 3.0,
        "model_inputs": {
            "selected_margin_mode": "isolated_paper_simulated",
            "fee_bps": 4.0,
            "expected_funding_bps": 0.5,
            "spread_bps": 1.25,
        },
        "lineage_ids": {"prediction_id": "pred-full-1"},
    }
    source_json.write_text(json.dumps({
        "generated_utc": "2026-06-21T12:00:00Z",
        "paper_only": True,
        "allocator": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR",
        "paper_candidates_with_allocation": 3,
        "candidate_allocations": [
            candidate,
            {
                **candidate,
                "allocation_id": "alloc-full-2",
                "symbol": "TIAUSDT",
                "lineage_ids": {"prediction_id": "pred-full-2"},
            },
        ],
        "sample_allocations": [
            {**candidate, "expected_move_after_cost_bps": 999.0},
            {
                **candidate,
                "allocation_id": "alloc-sample-only",
                "symbol": "INJUSDT",
                "lineage_ids": {"prediction_id": "pred-sample-only"},
            },
        ],
    }))

    rows, status = producer._rows_from_json(source_json)

    assert status["row_count"] == 3
    assert status["extracted_row_counts"]["paper_loop_once_candidate_allocation"] == 2
    assert status["extracted_row_counts"]["paper_loop_once_sample_allocation"] == 1
    assert [row["allocation_id"] for row in rows] == [
        "alloc-full-1",
        "alloc-full-2",
        "alloc-sample-only",
    ]
    assert rows[0]["_producer_extracted_from_json"] == (
        "paper_loop_once_candidate_allocation"
    )
    assert rows[0]["_producer_source_list_field"] == "candidate_allocations"
    assert rows[0]["expected_move_after_cost_bps"] == 85.0
    assert rows[2]["_producer_extracted_from_json"] == (
        "paper_loop_once_sample_allocation"
    )
    assert rows[2]["_producer_source_list_field"] == "sample_allocations"
    assert rows[2]["lineage_ids"]["prediction_id"] == "pred-sample-only"
    assert all(row["future_labels_used_as_features"] is False for row in rows)


def test_forward_holdout_source_materializes_preoutcome_candidate_without_a_grade_promotion(
    tmp_path: Path,
) -> None:
    registry_path = _forward_registry(tmp_path)
    candidate = _forward_candidate_allocation(
        allocation_id="alloc-forward-visible",
        prediction_id="pred-forward-visible",
        signal_id="sig-forward-visible",
    )
    paper_status = _paper_candidate_source(tmp_path, candidate)
    source_jsonl = tmp_path / "out_of_sample_forward_holdout_source_rows.jsonl"

    manifest = producer.materialize_forward_holdout_source(
        source_jsonl=source_jsonl,
        registry_path=registry_path,
        json_sources=[paper_status],
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T12:00:10Z",
    )
    rows, _ = producer._iter_jsonl(source_jsonl)

    assert manifest["status"] == "READY_FORWARD_HOLDOUT_SOURCE_ROWS_APPENDED"
    assert manifest["appended_count"] == 1
    assert manifest["skipped_count"] == 0
    assert rows[0]["forward_holdout_source_candidate"] is True
    assert rows[0]["forward_holdout_window_id"] == "unit-forward-window"
    assert rows[0]["selected_before_outcome"] is True
    assert rows[0]["candidate_selected_before_outcome"] is True
    assert rows[0]["paper_opportunity_tier"] == "B_GRADE_EXPLORATION_PAPER"
    assert "candidate_selection_tier" not in rows[0]
    assert "after_cost_return_bps" not in rows[0]
    assert manifest["does_not_create_a_grade_admission"] is True


def test_forward_holdout_source_skips_raw_outcome_contaminated_candidates(
    tmp_path: Path,
) -> None:
    registry_path = _forward_registry(tmp_path)
    contaminated = _forward_candidate_allocation(
        allocation_id="alloc-forward-contaminated",
        after_cost_return_bps=99.0,
    )
    paper_status = _paper_candidate_source(tmp_path, contaminated)
    source_jsonl = tmp_path / "out_of_sample_forward_holdout_source_rows.jsonl"

    manifest = producer.materialize_forward_holdout_source(
        source_jsonl=source_jsonl,
        registry_path=registry_path,
        json_sources=[paper_status],
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T12:00:10Z",
    )
    rows, _ = producer._iter_jsonl(source_jsonl)

    assert manifest["status"] == "NO_GO_FORWARD_HOLDOUT_SOURCE_NO_ROWS_APPENDED"
    assert manifest["appended_count"] == 0
    assert manifest["skipped_count"] == 1
    assert manifest["skip_reason_counts"] == {
        "FORWARD_HOLDOUT_SOURCE_ROW_HAS_OUTCOME_FIELDS": 1,
    }
    assert rows == []


def test_materialized_forward_holdout_source_does_not_satisfy_a_grade_by_id_alone(
    tmp_path: Path,
) -> None:
    source_jsonl = tmp_path / "out_of_sample_forward_holdout_source_rows.jsonl"
    registry_path = _forward_registry(tmp_path)
    candidate = _forward_candidate_allocation(allocation_id="alloc-forward-b-grade")
    paper_status = _paper_candidate_source(tmp_path, candidate)
    producer.materialize_forward_holdout_source(
        source_jsonl=source_jsonl,
        registry_path=registry_path,
        json_sources=[paper_status],
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T12:00:10Z",
    )

    holdout_manifest = producer.produce_holdout(
        source_jsonl=source_jsonl,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=_bucket_matrix_for(tmp_path, _row()),
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T12:00:20Z",
        construction_subset_status_path=_construction_subset_status_path(tmp_path),
    )

    assert holdout_manifest["pending_appended_count"] == 0
    assert holdout_manifest["accepted_appended_count"] == 0
    assert (
        holdout_manifest["rejection_reason_counts"][
            "SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING"
        ]
        == 1
    )


def test_guardian_halted_pre_a_grade_source_remains_non_countable_with_specific_reason(
    tmp_path: Path,
) -> None:
    source_jsonl = tmp_path / "out_of_sample_forward_holdout_source_rows.jsonl"
    registry_path = _forward_registry(tmp_path)
    candidate = _forward_candidate_allocation(
        allocation_id="alloc-forward-guardian-halted",
        paper_opportunity_tier="SHADOW_ONLY",
        explicit_paper_opportunity_tier=None,
        paper_opportunity_tier_reason="CONTINUOUS_EDGE_GUARDIAN_A_GRADE_HALTED",
        pre_guardian_paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
        pre_guardian_paper_opportunity_tier_reason="STRICT_UPSTREAM_PAPER_FILL_GATE_ALLOWED",
        pre_guardian_paper_fill_allowed_source="STRICT_UPSTREAM_PAPER_FILL_GATE",
        continuous_edge_guardian_forced_shadow_only=True,
        continuous_edge_guardian_status="A_GRADE_HALTED_PERFORMANCE",
        paper_fill_allowed_source="CONTINUOUS_EDGE_GUARDIAN_BLOCKED_NEW_A_GRADE_ENTRIES",
        counts_as_a_grade_evidence=False,
    )
    paper_status = _paper_candidate_source(tmp_path, candidate)

    producer.materialize_forward_holdout_source(
        source_jsonl=source_jsonl,
        registry_path=registry_path,
        json_sources=[paper_status],
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T12:00:10Z",
    )
    rows, _ = producer._iter_jsonl(source_jsonl)
    holdout_manifest = producer.produce_holdout(
        source_jsonl=source_jsonl,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=registry_path,
        bucket_matrix_path=_bucket_matrix_for(tmp_path, _row()),
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T12:00:20Z",
        construction_subset_status_path=_construction_subset_status_path(tmp_path),
    )

    assert rows[0]["paper_opportunity_tier"] == "SHADOW_ONLY"
    assert rows[0]["pre_guardian_paper_opportunity_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert rows[0]["continuous_edge_guardian_forced_shadow_only"] is True
    assert holdout_manifest["pending_appended_count"] == 0
    assert holdout_manifest["accepted_appended_count"] == 0
    assert (
        holdout_manifest["rejection_reason_counts"][
            "A_GRADE_HALTED_BY_CONTINUOUS_EDGE_GUARDIAN"
        ]
        == 1
    )
    assert (
        "SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING"
        not in holdout_manifest["rejection_reason_counts"]
    )


def test_holdout_tail_source_rows_processes_newest_forward_source_rows(
    tmp_path: Path,
) -> None:
    source_jsonl = tmp_path / "out_of_sample_forward_holdout_source_rows.jsonl"
    old_row = _forward_candidate_allocation(
        allocation_id="alloc-forward-old",
        decision_time="2026-06-21T12:00:00Z",
    )
    new_row = _forward_candidate_allocation(
        allocation_id="alloc-forward-new",
        decision_time="2026-06-21T12:05:00Z",
    )
    _write_jsonl(source_jsonl, [old_row, new_row])

    manifest = producer.produce_holdout(
        source_jsonl=source_jsonl,
        rows_path=tmp_path / "out_of_sample_holdout_reverify_rows.jsonl",
        registry_path=_forward_registry(tmp_path),
        bucket_matrix_path=_bucket_matrix_for(tmp_path, _row()),
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=1,
        generated_utc="2026-06-21T12:06:00Z",
        construction_subset_status_path=_construction_subset_status_path(tmp_path),
        tail_source_rows=True,
    )
    rejected_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_holdout_reverify_rejected.jsonl"
    )

    assert manifest["source_row_selection_policy"] == "tail_source_rows"
    assert manifest["rejected_appended_count"] == 1
    assert rejected_rows[0]["decision_time"] == "2026-06-21T12:05:00Z"


def test_paper_allocation_diagnostics_separates_low_fidelity_mirrors(
    tmp_path: Path,
) -> None:
    low_fidelity_source = tmp_path / "paper_adaptive_sizing_runtime_status.json"
    low_fidelity_source.write_text(json.dumps({
        "generated_utc": "2026-06-21T12:00:00Z",
        "paper_only": True,
        "candidate_allocations": [{
            "allocation_id": "mirrored-allocation",
            "symbol": "SOLUSDT",
            "timeframe": "15m",
            "action": "short",
            "allocator_decision": "ALLOW_WITH_SIZE",
            "target_notional_usdt": 1200.0,
            "model_inputs": {"price": 150.0},
        }],
    }))
    frozen_source = tmp_path / "v2_trade_management_paper_live_status.json"
    frozen_source.write_text(json.dumps({
        "classification": "PAPER_RUNTIME_STATUS",
        "started_at": "2026-06-21T11:59:00Z",
        "finished_at": "2026-06-21T12:00:00Z",
        "places_real_order": False,
        "paper_adaptive_sizing_runtime_status": {
            "generated_utc": "2026-06-21T12:00:00Z",
            "paper_only": True,
            "candidate_allocations": [{
                "allocation_id": "mirrored-allocation",
                "symbol": "BTCUSDT",
                "timeframe": "5m",
                "side": "short",
                "action": "short",
                "strategy": "trend_mode",
                "allocator_decision": "BLOCK_LOW_CONFIDENCE",
                "selector_policy_fingerprint": (
                    producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT
                ),
                "decision_time": "2026-06-21T12:00:00Z",
                "generated_at": "2026-06-21T11:59:50Z",
                "available_at": "2026-06-21T11:59:50Z",
                "feature_cutoff": "2026-06-21T11:59:00Z",
                "paper_opportunity_tier": "B_GRADE_WATCH_ONLY",
            }],
        },
    }))
    rows: list[dict] = []
    for path in (low_fidelity_source, frozen_source):
        extracted, _ = producer._rows_from_json(path)
        rows.extend(extracted)

    diagnostics = producer._paper_allocation_source_diagnostics(
        rows,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        eligible_bucket_keys=set(),
        generated_utc="2026-06-21T12:01:00Z",
    )

    assert diagnostics["candidate_allocation_count"] == 2
    assert diagnostics["unique_allocation_identity_count"] == 1
    assert diagnostics["duplicate_allocation_row_count"] == 1
    assert diagnostics["duplicated_allocation_identity_count"] == 1
    assert diagnostics["duplicated_allocation_identity_sample"][0][
        "allocation_identity"
    ] == "mirrored-allocation"
    assert diagnostics["duplicated_allocation_identity_sample"][0]["row_count"] == 2
    assert diagnostics["duplicated_allocation_identity_sample"][0]["fidelity_buckets"] == [
        "full_fidelity_frozen_candidate_allocation",
        "low_fidelity_candidate_allocation_missing_fingerprint",
    ]
    assert diagnostics["allocation_fidelity_counts"] == {
        "full_fidelity_frozen_candidate_allocation": 1,
        "low_fidelity_candidate_allocation_missing_fingerprint": 1,
    }
    assert diagnostics["unique_allocation_identity_count_by_fidelity"] == {
        "full_fidelity_frozen_candidate_allocation": 1,
        "low_fidelity_candidate_allocation_missing_fingerprint": 1,
    }
    assert diagnostics["full_fidelity_frozen_candidate_allocation_count"] == 1
    assert diagnostics["low_fidelity_candidate_allocation_count"] == 1
    assert diagnostics["allocator_allowed_count"] == 1
    assert diagnostics["allocator_allowed_count_by_fidelity"] == {
        "low_fidelity_candidate_allocation_missing_fingerprint": 1
    }
    assert diagnostics["allocator_decision_counts_by_fidelity"][
        "full_fidelity_frozen_candidate_allocation"
    ] == {"BLOCK_LOW_CONFIDENCE": 1}
    assert diagnostics["allocator_decision_counts_by_fidelity"][
        "low_fidelity_candidate_allocation_missing_fingerprint"
    ] == {"ALLOW_WITH_SIZE": 1}
    assert diagnostics["tier_counts_by_fidelity"][
        "full_fidelity_frozen_candidate_allocation"
    ] == {"B_GRADE_WATCH_ONLY": 1}
    assert diagnostics["tier_counts_by_fidelity"][
        "low_fidelity_candidate_allocation_missing_fingerprint"
    ] == {"__missing__": 1}
    assert {
        sample["allocation_fidelity_bucket"]
        for sample in diagnostics["blocked_sample"]
    } == {
        "full_fidelity_frozen_candidate_allocation",
        "low_fidelity_candidate_allocation_missing_fingerprint",
    }


def test_realtime_paper_loop_once_allocation_can_create_pending_when_gates_pass(
    tmp_path: Path,
) -> None:
    candidate = producer._without_outcome_fields(_row(
        row_id="paper-loop-ready",
        source_redis_key="unit:paper-loop-ready",
        signal_id="sig-loop-ready",
        prediction_id="pred-loop-ready",
    ))
    allocation = {
        key: value
        for key, value in candidate.items()
        if key
        not in {
            "row_id",
            "source_redis_key",
            "candidate_identity",
            "position_identity",
        }
    }
    allocation.update({
        "allocation_id": "alloc-ready",
        "target_notional_usdt": candidate["gross_notional_usd"],
        "lineage_ids": {
            "prediction_id": "pred-loop-ready",
            "signal_id": "sig-loop-ready",
            "risk_decision_id": "risk-loop-ready",
        },
        "model_inputs": {
            "spread_bps": candidate["actual_observed_spread_entry_bps"],
            "slippage_bps": candidate["expected_slippage_bps"],
            "correlation_exposure_pct": candidate["correlation_exposure_pct"],
            "volatility_bps": 80.0,
            "liquidity_score": 0.9,
        },
        "realized_outcome_bps": 123.0,
    })
    source_json = tmp_path / "PAPER_LOOP_ONCE_STATUS.json"
    source_json.write_text(json.dumps({
        "classification": "PAPER_RUNTIME_STATUS",
        "started_at": "2026-06-21T11:59:00Z",
        "finished_at": "2026-06-21T12:00:00Z",
        "places_real_order": False,
        "paper_adaptive_sizing_runtime_status": {
            "status": "READY",
            "generated_utc": "2026-06-21T12:00:00Z",
            "paper_only": True,
            "sample_allocations": [allocation],
        },
    }))
    extracted_rows, _ = producer._rows_from_json(source_json)
    matrix = _bucket_matrix_for(tmp_path, extracted_rows[0])
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 1
    assert manifest["rejected_appended_count"] == 0
    allocation_diagnostics = manifest["paper_allocation_source_diagnostics"]
    assert allocation_diagnostics["status"] == (
        "NO_GO_NO_FULL_CANDIDATE_ALLOCATIONS_EXPOSED"
    )
    assert allocation_diagnostics["diagnostic_only"] is True
    assert allocation_diagnostics["counts_as_pending_or_final_evidence"] is False
    assert allocation_diagnostics["selection_uses_outcome_fields"] is False
    assert allocation_diagnostics["candidate_allocation_count"] == 0
    assert allocation_diagnostics["sample_allocation_count"] == 1
    assert allocation_diagnostics["full_candidate_allocation_source_exposed"] is False
    assert allocation_diagnostics["sample_allocations_are_context_only"] is True
    assert allocation_diagnostics["ready_for_pending_gate_count"] == 1
    assert allocation_diagnostics["ready_sample_allocation_count"] == 1
    assert allocation_diagnostics["ready_full_candidate_allocation_count"] == 0
    assert allocation_diagnostics["source_list_field_counts"] == {"sample_allocations": 1}
    assert allocation_diagnostics["reason_counts"] == {}
    assert (
        manifest["source_statuses"][0]["extracted_row_counts"]
        ["paper_loop_once_sample_allocation"]
        == 1
    )
    assert (
        manifest["realtime_source_readiness_summary"]["candidate_ready_source_row_count"]
        == 1
    )
    assert pending_rows[0]["candidate_selection_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert pending_rows[0]["candidate_selected_before_outcome"] is True
    assert pending_rows[0]["future_labels_used_as_features"] is False
    assert pending_rows[0]["paper_only"] is True
    assert pending_rows[0]["places_real_order"] is False
    assert pending_rows[0]["lineage_ids"]["prediction_id"] == "pred-loop-ready"
    assert "realized_outcome_bps" not in pending_rows[0]
    assert final_rows == []


def test_realtime_manifest_reports_sample_only_allocation_source_contract_gap(
    tmp_path: Path,
) -> None:
    reference = producer._without_outcome_fields(_row(row_id="sample-only-reference"))
    sample = {
        key: value
        for key, value in reference.items()
        if key
        not in {
            "row_id",
            "source_redis_key",
            "decision_time",
            "available_at",
            "generated_at",
            "feature_cutoff",
            "candidate_identity",
            "position_identity",
        }
    }
    sample.update({
        "allocation_id": "alloc-sample-only-no-full-source",
        "policy_activated_at": "2026-06-21T11:59:58Z",
        "target_notional_usdt": reference["gross_notional_usd"],
        "lineage_ids": {"prediction_id": "pred-sample-only-no-full-source"},
    })
    source_json = tmp_path / "PAPER_LOOP_ONCE_STATUS.json"
    source_json.write_text(json.dumps({
        "classification": "PAPER_RUNTIME_STATUS",
        "started_at": "2026-06-21T11:59:00Z",
        "finished_at": "2026-06-21T12:00:00Z",
        "places_real_order": False,
        "paper_adaptive_sizing_runtime_status": {
            "status": "READY",
            "generated_utc": "2026-06-21T12:00:00Z",
            "paper_only": True,
            "sample_allocations": [sample],
        },
    }))
    extracted_rows, _ = producer._rows_from_json(source_json)
    matrix = _bucket_matrix_for(tmp_path, extracted_rows[0])
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    diagnostics = manifest["paper_allocation_source_diagnostics"]
    assert manifest["pending_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert diagnostics["status"] == "NO_GO_NO_FULL_CANDIDATE_ALLOCATIONS_EXPOSED"
    assert diagnostics["candidate_allocation_count"] == 0
    assert diagnostics["sample_allocation_count"] == 1
    assert diagnostics["ready_for_pending_gate_count"] == 0
    assert diagnostics["row_counts_by_readiness_and_list_field"][
        "blocked_before_pending_gate"
    ] == {"sample_allocations": 1}
    assert diagnostics["timing_field_presence_counts"]["policy_activated_at"] == 1
    assert diagnostics["timing_field_presence_counts"]["decision_time"] == 0
    assert diagnostics["reason_counts"]["REALTIME_PENDING_SOURCE_FRESHNESS_TIMESTAMP_MISSING"] == 1
    assert diagnostics["stage_blocked_row_counts"]["evidence_protocol"] == 1
    assert diagnostics["source_list_field_counts"] == {"sample_allocations": 1}
    assert diagnostics["blocked_sample"][0]["source_list_field"] == "sample_allocations"
    assert diagnostics["blocked_sample"][0]["policy_activated_at"] == (
        "2026-06-21T11:59:58Z"
    )
    assert diagnostics["blocked_sample"][0]["reasons"]


def test_realtime_source_readiness_summary_reports_stage_intersections(tmp_path: Path) -> None:
    pending_source = producer._without_outcome_fields(_row(
        row_id="ready-pending",
        source_redis_key="unit:ready-pending",
    ))
    rejected_source = producer._without_outcome_fields(_row(
        row_id="not-ready",
        source_redis_key="unit:not-ready",
        expected_move_after_cost_bps=0.0,
    ))
    source_json = tmp_path / "runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [pending_source, rejected_source]}))
    matrix = _bucket_matrix_for(tmp_path, pending_source)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    readiness = manifest["realtime_source_readiness_summary"]
    bucket_diagnostics = manifest["selector_bucket_diagnostics"]
    source_contract = manifest["selector_source_contract_diagnostics"]

    assert manifest["pending_appended_count"] == 1
    assert manifest["rejected_appended_count"] == 1
    assert manifest["source_gate_breakdown"]["candidate_ready_source_row_count"] == 1
    assert readiness["processed_source_row_count"] == 2
    assert readiness["candidate_ready_source_row_count"] == 1
    assert readiness["source_kind_counts"]["filesystem_runtime_snapshot"] == 2
    assert readiness["candidate_ready_by_source_kind"]["filesystem_runtime_snapshot"] == 1
    assert readiness["stage_pass_counts"]["accounting"] == 2
    assert readiness["stage_pass_counts"]["evidence_protocol"] == 2
    assert readiness["stage_pass_counts"]["frozen_selector"] == 1
    assert readiness["stage_blocked_row_counts"]["frozen_selector"] == 1
    assert (
        readiness["stage_blocked_row_counts_by_source_kind"]["filesystem_runtime_snapshot"]
        ["frozen_selector"]
        == 1
    )
    acquisition = manifest["realtime_evidence_acquisition_status"]
    assert acquisition["status"] == "READY_REALTIME_PENDING_SELECTIONS_APPENDED"
    assert acquisition["pending_rows_appended_count"] == 1
    assert acquisition["countable_rows_appended_count"] == 0
    assert acquisition["candidate_ready_source_row_count"] == 1
    assert acquisition["selection_uses_outcome_fields"] is False
    assert acquisition["future_labels_used_as_features_allowed"] is False
    assert bucket_diagnostics["status"] == "READY_SELECTOR_BUCKET_DIAGNOSTICS"
    assert bucket_diagnostics["selection_uses_outcome_fields"] is False
    assert bucket_diagnostics["outcome_fields_used_for_bucket_diagnostics"] == []
    assert bucket_diagnostics["processed_source_row_count"] == 2
    assert bucket_diagnostics["dynamic_bucket_eligible_source_row_count"] == 1
    assert bucket_diagnostics["dynamic_bucket_noneligible_source_row_count"] == 1
    assert (
        bucket_diagnostics["dynamic_bucket_eligible_by_source_kind"]
        ["filesystem_runtime_snapshot"]
        == 1
    )
    assert (
        bucket_diagnostics["dynamic_bucket_noneligible_by_source_kind"]
        ["filesystem_runtime_snapshot"]
        == 1
    )
    assert bucket_diagnostics["top_dynamic_bucket_eligible_keys"][0]["row_count"] == 1
    assert bucket_diagnostics["top_dynamic_bucket_noneligible_keys"][0]["row_count"] == 1
    distance = bucket_diagnostics["eligible_bucket_distance_diagnostics"]
    assert distance["status"] == "READY_SELECTOR_BUCKET_DISTANCE_DIAGNOSTICS"
    assert distance["selection_uses_outcome_fields"] is False
    assert distance["outcome_fields_used_for_bucket_distance"] == []
    assert distance["processed_source_row_count"] == 2
    assert distance["eligible_bucket_count"] == 1
    assert distance["minimum_mismatch_count_distribution"] == {"0": 1, "1": 1}
    assert (
        distance["minimum_mismatch_count_distribution_by_source_kind"]
        ["filesystem_runtime_snapshot"]
        == {"0": 1, "1": 1}
    )
    assert distance["closest_eligible_mismatch_dimension_counts"] == {
        "expected_move_bucket": 1
    }
    assert distance["closest_sample"][0]["mismatch_count"] == 0
    assert source_contract["status"] == "WARN_SELECTOR_SOURCE_CONTRACT_PARTIAL_GAPS"
    assert source_contract["diagnostic_only"] is True
    assert source_contract["selection_uses_outcome_fields"] is False
    assert source_contract["outcome_fields_used_for_source_contract"] == []
    assert source_contract["processed_source_row_count"] == 2
    assert source_contract["full_bucket_match_count"] == 1
    assert source_contract["rows_with_all_bucket_dimensions_count"] == 2
    assert source_contract["rows_with_all_values_in_eligible_dimensions_count"] == 1
    assert source_contract["rows_with_value_not_in_eligible_dimensions_count"] == 1
    assert source_contract["value_not_in_eligible_counts_by_dimension"] == {
        "expected_move_bucket": 1
    }


def test_realtime_evidence_acquisition_status_surfaces_frozen_allocator_blocker() -> None:
    summary = producer._realtime_evidence_acquisition_status(
        source_gate_breakdown={
            "candidate_ready_source_row_count": 0,
            "rejected_source_row_count": 988,
            "category_counts": {"frozen_selector": 988},
            "reason_counts": {"ALLOCATOR_BLOCKED_CANDIDATE": 988},
            "top_reason_combinations": [{
                "reasons": ["ALLOCATOR_BLOCKED_CANDIDATE"],
                "row_count": 988,
            }],
        },
        source_readiness_summary={
            "processed_source_row_count": 5469,
            "candidate_ready_source_row_count": 0,
            "stage_blocked_row_counts": {"frozen_selector": 988},
        },
        paper_allocation_diagnostics={
            "status": "NO_GO_FULL_CANDIDATE_ALLOCATIONS_NOT_GATE_READY",
            "allocation_row_count": 5469,
            "candidate_allocation_count": 5469,
            "full_fidelity_frozen_candidate_allocation_count": 988,
            "low_fidelity_candidate_allocation_count": 4481,
            "allocator_allowed_count_by_fidelity": {
                "low_fidelity_candidate_allocation_missing_fingerprint": 4481,
            },
            "ready_for_pending_gate_count": 0,
            "ready_full_candidate_allocation_count": 0,
            "ready_for_pending_gate_count_by_fidelity": {},
            "allocator_decision_counts_by_fidelity": {
                "full_fidelity_frozen_candidate_allocation": {
                    "BLOCK_LOW_CONFIDENCE": 954,
                    "BLOCK_NO_EDGE": 34,
                },
                "low_fidelity_candidate_allocation_missing_fingerprint": {
                    "ALLOW_WITH_SIZE": 4481,
                },
            },
        },
        selector_source_contract_diagnostics={
            "status": "NO_GO_SELECTOR_SOURCE_CONTRACT_GAPS",
        },
        accepted_count=0,
        pending_count=0,
    )

    assert summary["status"] == "NO_GO_REALTIME_FROZEN_CANDIDATES_ALLOCATOR_BLOCKED"
    assert summary["full_fidelity_frozen_candidate_allocation_count"] == 988
    assert summary["full_fidelity_frozen_allocator_allowed_count"] == 0
    assert summary["low_fidelity_allocator_allowed_count"] == 4481
    assert summary["ready_for_pending_gate_count"] == 0
    assert summary["source_gate_reason_counts"] == {"ALLOCATOR_BLOCKED_CANDIDATE": 988}
    assert "Wait for frozen-policy" in summary["next_required_actions"][0]


def test_low_fidelity_allocation_lineage_bridge_reports_incomplete_contract() -> None:
    allocation = {
        "_producer_extracted_from_json": "paper_loop_once_candidate_allocation",
        "_producer_source_list_field": "candidate_allocations",
        "allocation_id": "alloc-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "action": "short",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "expected_move_after_cost_bps": 42.0,
        "lineage_ids": {
            "prediction_id": "pred-1",
            "signal_id": "sig-1",
            "risk_decision_id": "risk-1",
        },
    }
    bridge = {
        "_producer_source_kind": "filesystem_runtime_snapshot",
        "_producer_extracted_from_json": "current_signal_lineage",
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "risk_decision_id": "risk-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "short",
        "strategy": "range_reversion",
        "market_regime": "range",
        "decision_time": "2026-06-21T12:00:00Z",
        "generated_at": "2026-06-21T11:59:50Z",
        "available_at": "2026-06-21T11:59:55Z",
        "feature_cutoff": "2026-06-21T11:55:00Z",
    }

    diagnostics = producer._low_fidelity_allocation_lineage_bridge_diagnostics(
        [allocation, bridge],
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
    )

    assert diagnostics["status"] == "NO_GO_LINEAGE_BRIDGE_INCOMPLETE_FOR_LOW_FIDELITY_ALLOCATIONS"
    assert diagnostics["diagnostic_only"] is True
    assert diagnostics["counts_as_pending_or_final_evidence"] is False
    assert diagnostics["selection_uses_outcome_fields"] is False
    assert diagnostics["low_fidelity_allowed_allocation_count"] == 1
    assert diagnostics["allocations_with_lineage_alias_count"] == 1
    assert diagnostics["allocations_with_bridge_match_count"] == 1
    assert diagnostics["bridge_match_row_count"] == 1
    assert diagnostics["allocations_bridge_contract_complete_count"] == 0
    assert diagnostics["bridge_source_kind_counts"] == {
        "filesystem_runtime_snapshot": 1
    }
    assert diagnostics["bridge_extracted_from_json_counts"] == {
        "current_signal_lineage": 1
    }
    assert diagnostics["bridge_supplied_field_counts"] == {
        "available_at": 1,
        "decision_time": 1,
        "feature_cutoff": 1,
        "generated_at": 1,
        "market_regime": 1,
        "strategy": 1,
    }
    assert diagnostics["missing_after_bridge_field_counts"] == {
        "candidate_selection_tier": 1,
        "selector_policy_fingerprint": 1,
    }
    assert diagnostics["fingerprint_state_after_bridge_counts"] == {"missing": 1}
    assert diagnostics["sample"][0]["bridge_match_row_count"] == 1
    assert diagnostics["sample"][0]["missing_after_bridge"] == [
        "selector_policy_fingerprint",
        "candidate_selection_tier",
    ]


def test_low_fidelity_allocation_lineage_bridge_reports_no_match() -> None:
    allocation = {
        "_producer_extracted_from_json": "paper_loop_once_candidate_allocation",
        "_producer_source_list_field": "candidate_allocations",
        "allocation_id": "alloc-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "action": "long",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "lineage_ids": {"prediction_id": "pred-1"},
    }
    unrelated_bridge = {
        "_producer_source_kind": "filesystem_runtime_snapshot",
        "_producer_extracted_from_json": "current_signal_lineage",
        "prediction_id": "pred-2",
        "decision_time": "2026-06-21T12:00:00Z",
    }

    diagnostics = producer._low_fidelity_allocation_lineage_bridge_diagnostics(
        [allocation, unrelated_bridge],
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
    )

    assert diagnostics["status"] == "NO_GO_LOW_FIDELITY_ALLOWED_ALLOCATIONS_HAVE_NO_LINEAGE_BRIDGE"
    assert diagnostics["low_fidelity_allowed_allocation_count"] == 1
    assert diagnostics["allocations_with_lineage_alias_count"] == 1
    assert diagnostics["allocations_with_bridge_match_count"] == 0
    assert diagnostics["bridge_match_row_count"] == 0
    assert diagnostics["bridge_supplied_field_counts"] == {}
    assert diagnostics["missing_after_bridge_field_counts"]["selector_policy_fingerprint"] == 1
    assert diagnostics["missing_after_bridge_field_counts"]["decision_time"] == 1
    assert diagnostics["sample"][0]["bridge_match_row_count"] == 0


def test_realtime_manifest_reports_paper_event_source_diagnostics(tmp_path: Path) -> None:
    event_rows = [
        {
            "row_id": "event-fill",
            "symbol": "BTCUSDT",
            "ledger_action": "PAPER_FILL_SIMULATED",
            "feature_snapshot_id": "fs-1",
            "generated_at": "2026-06-21T12:00:00Z",
            "paper_realized_pnl": 1.23,
            "paper_pnl_delta": 0.45,
            "paper_result": "filled",
            "notional_usdt": 100.0,
            "fee_usdt": 0.04,
        },
        {
            "row_id": "event-close",
            "symbol": "ETHUSDT",
            "ledger_action": "PAPER_POSITION_CLOSED",
            "feature_snapshot_id": "fs-2",
            "generated_at": "2026-06-21T12:01:00Z",
            "gross_pnl_usdt": 2.0,
            "realized_delta_usdt": 2.0,
        },
    ]
    source_jsonl = tmp_path / "paper_events.jsonl"
    _write_jsonl(source_jsonl, event_rows)
    matrix = _bucket_matrix_for(tmp_path, _row())
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[source_jsonl],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:02:00Z",
    )

    diagnostics = manifest["paper_event_source_diagnostics"]
    assert diagnostics["status"] == "READY_PAPER_EVENT_SOURCE_DIAGNOSTICS"
    assert diagnostics["diagnostic_only"] is True
    assert diagnostics["counts_as_pending_or_final_evidence"] is False
    assert diagnostics["processed_paper_event_row_count"] == 2
    assert diagnostics["ledger_action_counts"] == {
        "PAPER_FILL_SIMULATED": 1,
        "PAPER_POSITION_CLOSED": 1,
    }
    assert diagnostics["rows_with_feature_snapshot_id_count"] == 2
    assert diagnostics["unique_feature_snapshot_id_count"] == 2
    assert diagnostics["timing_field_presence_counts"]["generated_at"] == 2
    assert diagnostics["timing_field_presence_counts"]["decision_time"] == 2
    assert diagnostics["timing_field_presence_counts"]["available_at"] == 0
    assert diagnostics["timing_field_presence_counts"]["feature_cutoff"] == 0
    assert diagnostics["selector_dimension_presence_counts"]["timeframe"] == 0
    assert diagnostics["selector_dimension_presence_counts"]["directional_side"] == 0
    assert diagnostics["selector_dimension_presence_counts"]["positive_after_cost_edge"] == 0
    assert diagnostics["outcome_like_field_presence_counts"] == {
        "gross_pnl_usdt": 1,
        "paper_pnl_delta": 1,
        "paper_realized_pnl": 1,
        "paper_result": 1,
        "realized_delta_usdt": 1,
    }
    assert diagnostics["recognized_closed_outcome_field_presence_counts"] == {}
    assert "paper_realized_pnl" in diagnostics["not_mapped_to_reconciled_outcome_fields"]
    assert manifest["pending_appended_count"] == 0
    assert manifest["accepted_appended_count"] == 0


def test_selector_bucket_diagnostics_strip_outcome_fields_and_report_missing_dimensions() -> None:
    eligible_reference = _row(row_id="eligible-reference")
    eligible_key = tuple(str(value) for value in status_module._a_grade_bucket_key(eligible_reference))
    outcome_edge_only = _row(
        row_id="outcome-edge-only",
        expected_move_after_cost_bps=None,
        strategy=None,
        market_regime=None,
        confidence_calibrated=None,
    )
    for field in (
        "expected_move_after_cost_bps",
        "strategy",
        "market_regime",
        "confidence_calibrated",
    ):
        outcome_edge_only.pop(field, None)

    diagnostics = producer._selector_bucket_diagnostics(
        [outcome_edge_only],
        eligible_bucket_keys={eligible_key},
    )

    assert diagnostics["selection_uses_outcome_fields"] is False
    assert diagnostics["outcome_fields_used_for_bucket_diagnostics"] == []
    assert diagnostics["processed_source_row_count"] == 1
    assert diagnostics["dynamic_bucket_eligible_source_row_count"] == 0
    assert diagnostics["dynamic_bucket_noneligible_source_row_count"] == 1
    assert diagnostics["rows_with_unknown_or_missing_bucket_dimension_count"] == 1
    assert diagnostics["unknown_or_missing_bucket_dimension_counts"]["strategy"] == 1
    assert diagnostics["unknown_or_missing_bucket_dimension_counts"]["market_regime"] == 1
    assert diagnostics["unknown_or_missing_bucket_dimension_counts"]["confidence_bucket"] == 1
    assert diagnostics["unknown_or_missing_bucket_dimension_counts"]["expected_move_bucket"] == 1
    bucket_key = diagnostics["top_dynamic_bucket_noneligible_keys"][0]["bucket_key"]
    assert bucket_key["strategy"] == "__unknown__"
    assert bucket_key["confidence_bucket"] == "__missing__"
    assert bucket_key["expected_move_bucket"] == "__missing__"
    distance = diagnostics["eligible_bucket_distance_diagnostics"]
    assert distance["selection_uses_outcome_fields"] is False
    assert distance["outcome_fields_used_for_bucket_distance"] == []
    assert distance["eligible_bucket_count"] == 1
    assert distance["processed_source_row_count"] == 1
    assert distance["minimum_mismatch_count_distribution"] == {"4": 1}
    assert set(distance["closest_sample"][0]["mismatch_fields"]) == {
        "strategy",
        "market_regime",
        "confidence_bucket",
        "expected_move_bucket",
    }


def test_selector_source_contract_diagnostics_reports_missing_and_noneligible_values() -> None:
    eligible_reference = _row(row_id="eligible-reference")
    eligible_key = tuple(str(value) for value in status_module._a_grade_bucket_key(eligible_reference))
    missing_dimensions = _row(
        row_id="missing-dimensions",
        strategy=None,
        market_regime=None,
        expected_move_after_cost_bps=None,
    )
    for field in (
        "strategy",
        "market_regime",
        "expected_move_after_cost_bps",
    ):
        missing_dimensions.pop(field, None)
    noneligible_values = _row(
        row_id="noneligible-values",
        strategy="mean_reversion_mode",
        liquidity_bucket="medium",
    )

    diagnostics = producer._selector_source_contract_diagnostics(
        [missing_dimensions, noneligible_values, eligible_reference],
        eligible_bucket_keys={eligible_key},
    )

    assert diagnostics["status"] == "WARN_SELECTOR_SOURCE_CONTRACT_PARTIAL_GAPS"
    assert diagnostics["diagnostic_only"] is True
    assert diagnostics["selection_uses_outcome_fields"] is False
    assert diagnostics["outcome_fields_used_for_source_contract"] == []
    assert diagnostics["processed_source_row_count"] == 3
    assert diagnostics["full_bucket_match_count"] == 1
    assert diagnostics["rows_with_all_bucket_dimensions_count"] == 2
    assert diagnostics["rows_with_missing_or_unknown_bucket_dimension_count"] == 1
    assert diagnostics["rows_with_all_values_in_eligible_dimensions_count"] == 1
    assert diagnostics["rows_with_value_not_in_eligible_dimensions_count"] == 1
    assert diagnostics["missing_or_unknown_dimension_counts"]["strategy"] == 1
    assert diagnostics["missing_or_unknown_dimension_counts"]["market_regime"] == 1
    assert diagnostics["missing_or_unknown_dimension_counts"]["expected_move_bucket"] == 1
    assert diagnostics["value_not_in_eligible_counts_by_dimension"] == {
        "liquidity_bucket": 1,
        "strategy": 1,
    }
    assert diagnostics["eligible_values_by_dimension"]["strategy"] == ["range_reversion"]
    observed_strategy = {
        item["value"]: item["row_count"]
        for item in diagnostics["observed_value_counts_by_dimension"]["strategy"]
    }
    assert observed_strategy["__unknown__"] == 1
    assert observed_strategy["mean_reversion_mode"] == 1
    assert observed_strategy["range_reversion"] == 1


def test_realtime_redis_pending_is_preserved_before_later_closed_label(tmp_path: Path, monkeypatch) -> None:
    pending_source = producer._without_outcome_fields(_row(
        row_id=None,
        intent_id="intent-pending-1",
        prediction_id="intent-pending-1",
        signal_id="intent-pending-1",
        quantity=1.0,
        adaptive_capital_policy_version=status_module.ADAPTIVE_CAPITAL_POLICY_VERSION,
    ))
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    matrix = _bucket_matrix_for(tmp_path, pending_source)

    monkeypatch.setattr(
        producer.status_module,
        "_connect_redis",
        lambda: _FakeRedis({
            "v2:paper:intents": {"rows": [pending_source]},
            "v2:paper:intents_held_by_paper_fill_gate": {"rows": []},
            "v2:paper:ledger": {"accepted": [], "closed_trades": [], "open_positions": []},
        }),
    )
    pending_manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[],
        include_redis=True,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    closed_source = {
        "entry_prediction_id": "intent-pending-1",
        "entry_signal_id": "intent-pending-1",
        "symbol": pending_source["symbol"],
        "timeframe": pending_source["timeframe"],
        "side": pending_source["side"],
        "paper_only": True,
        "places_real_order": False,
        "after_cost_return_bps": 35.0,
        "realized_after_cost_return_bps": 35.0,
        "realized_pnl_usd": 3.5,
        "exit_time": "2026-06-21T13:00:00Z",
    }
    monkeypatch.setattr(
        producer.status_module,
        "_connect_redis",
        lambda: _FakeRedis({
            "v2:paper:intents": {"rows": []},
            "v2:paper:intents_held_by_paper_fill_gate": {"rows": []},
            "v2:paper:ledger": {"accepted": [], "closed_trades": [closed_source], "open_positions": []},
        }),
    )
    final_manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[],
        include_redis=True,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T14:00:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl")
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert pending_manifest["pending_appended_count"] == 1
    assert pending_manifest["accepted_appended_count"] == 0
    assert pending_manifest["pending_sidecar_summary"]["status"] == "READY_PENDING_SELECTIONS_WAITING_FOR_OUTCOMES"
    assert pending_manifest["pending_sidecar_summary"]["unresolved_pending_count"] == 1
    assert pending_manifest["pending_sidecar_summary"]["selector_policy_fingerprint_mismatch_count"] == 0
    assert final_manifest["accepted_appended_count"] == 1
    assert final_manifest["pending_sidecar_summary"]["status"] == "READY_PENDING_SELECTIONS_ALL_FINALIZED"
    assert final_manifest["pending_sidecar_summary"]["finalized_pending_count"] == 1
    assert final_manifest["pending_sidecar_summary"]["outcome_field_presence_counts"] == {}
    assert len(pending_rows) == 1
    assert len(final_rows) == 1
    assert final_rows[0]["candidate_selected_at"] == "2026-06-21T12:01:00Z"
    assert final_rows[0]["realtime_pending_source_age_seconds"] == 60.0
    assert final_rows[0]["after_cost_return_bps"] == 35.0
    assert final_rows[0]["gross_notional_usd"] == pending_source["gross_notional_usd"]


def test_realtime_same_scan_pending_cannot_label_closed_outcome(tmp_path: Path) -> None:
    pending_source = producer._without_outcome_fields(_row(
        row_id=None,
        source_redis_key=None,
        intent_id="same-scan-pending-1",
        prediction_id="same-scan-pending-1",
        signal_id="same-scan-pending-1",
        quantity=1.0,
        adaptive_capital_policy_version=status_module.ADAPTIVE_CAPITAL_POLICY_VERSION,
    ))
    closed_source = _row(
        row_id="same-scan-close-1",
        source_redis_key=None,
        entry_prediction_id="same-scan-pending-1",
        entry_signal_id="same-scan-pending-1",
        after_cost_return_bps=40.0,
        realized_after_cost_return_bps=40.0,
        realized_pnl_usd=4.0,
        exit_time="2026-06-21T13:00:00Z",
    )
    source_json = tmp_path / "same_scan_runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [pending_source, closed_source]}))
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    matrix = _bucket_matrix_for(tmp_path, pending_source)

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl")
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["realtime_labeling_policy"] == "REQUIRES_PREEXISTING_PENDING_SELECTION_RECORD"
    assert manifest["pending_appended_count"] == 0
    assert manifest["accepted_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 2
    assert manifest["same_run_pending_rows_not_labeled_count"] == 0
    assert (
        manifest["rejection_reason_counts"]
        ["HISTORICAL_ACCEPTED_ROW_ALREADY_HAS_CLOSED_OUTCOME_NO_PRIOR_PENDING_RECORD"]
        == 1
    )
    assert manifest["rejection_reason_counts"]["PENDING_SELECTION_NOT_PREEXISTING_FOR_CLOSED_OUTCOME"] == 1
    assert pending_rows == []
    assert final_rows == []


def test_realtime_closed_source_cannot_label_without_preexisting_pending_when_relaxed(tmp_path: Path) -> None:
    closed_source = _row(
        row_id="closed-without-preexisting-1",
        source_redis_key=None,
        after_cost_return_bps=40.0,
        realized_after_cost_return_bps=40.0,
        realized_pnl_usd=4.0,
        exit_time="2026-06-21T13:00:00Z",
    )
    source_json = tmp_path / "closed_runtime_snapshot.json"
    source_json.write_text(json.dumps({"entries": [closed_source]}))
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    matrix = _bucket_matrix_for(tmp_path, closed_source)

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=10,
        require_pending_for_closed=False,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl")
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["pending_appended_count"] == 0
    assert manifest["accepted_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 1
    assert "MISSING_PENDING_SELECTION_RECORD_FOR_CLOSED_OUTCOME" not in manifest["rejection_reason_counts"]
    assert manifest["rejection_reason_counts"]["PENDING_SELECTION_NOT_PREEXISTING_FOR_CLOSED_OUTCOME"] == 1
    assert pending_rows == []
    assert final_rows == []


def test_realtime_closed_outcome_matches_pending_by_lineage_alias(tmp_path: Path, monkeypatch) -> None:
    pending_source = producer._without_outcome_fields(_row(
        row_id=None,
        intent_id="intent-alias-1",
        prediction_id=None,
        signal_id=None,
        fill_id="fill-alias-1",
        quantity=1.0,
        adaptive_capital_policy_version=status_module.ADAPTIVE_CAPITAL_POLICY_VERSION,
    ))
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    matrix = _bucket_matrix_for(tmp_path, pending_source)

    monkeypatch.setattr(
        producer.status_module,
        "_connect_redis",
        lambda: _FakeRedis({
            "v2:paper:intents": {"rows": [pending_source]},
            "v2:paper:intents_held_by_paper_fill_gate": {"rows": []},
            "v2:paper:ledger": {"accepted": [], "closed_trades": [], "open_positions": []},
        }),
    )
    pending_manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[],
        include_redis=True,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    close_source = {
        "source_fill_ids": ["fill-alias-1"],
        "position_id": "paper-pos-alias-1",
        "symbol": pending_source["symbol"],
        "timeframe": pending_source["timeframe"],
        "side": pending_source["side"],
        "paper_only": True,
        "places_real_order": False,
        "after_cost_return_bps": 28.0,
        "realized_after_cost_return_bps": 28.0,
        "realized_pnl_usd": 2.8,
        "funding_pnl_usd": -0.13,
        "funding_pnl_source": "PAPER_FUNDING_ACCRUAL_V1",
        "funding_pnl_accounting_version": "PAPER_FUNDING_ACCRUAL_V1",
        "funding_pnl_accounting_status": "READY_FUNDING_PNL_ACCRUED",
        "actual_fee_bps": 4.25,
        "actual_fees_usd": 0.43,
        "actual_slippage_bps": 1.75,
        "actual_slippage_usd": 0.18,
        "exit_time": "2026-06-21T13:00:00Z",
    }
    monkeypatch.setattr(
        producer.status_module,
        "_connect_redis",
        lambda: _FakeRedis({
            "v2:paper:intents": {"rows": []},
            "v2:paper:intents_held_by_paper_fill_gate": {"rows": []},
            "v2:paper:ledger": {"accepted": [], "closed_trades": [close_source], "open_positions": []},
        }),
    )
    final_manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[],
        include_redis=True,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T14:00:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl")
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert pending_manifest["pending_appended_count"] == 1
    assert final_manifest["accepted_appended_count"] == 1
    assert len(pending_rows) == 1
    assert len(final_rows) == 1
    assert final_rows[0]["candidate_identity"] == pending_rows[0]["candidate_identity"]
    assert final_rows[0]["after_cost_return_bps"] == 28.0
    assert "funding_pnl_usd" not in pending_rows[0]
    assert final_rows[0]["funding_pnl_usd"] == -0.13
    assert final_rows[0]["funding_pnl_accounting_status"] == "READY_FUNDING_PNL_ACCRUED"
    assert final_rows[0]["actual_fee_bps"] == 4.25
    assert final_rows[0]["actual_slippage_bps"] == 1.75


def test_realtime_redis_stale_accepted_cannot_create_new_pending(tmp_path: Path, monkeypatch) -> None:
    accepted_source = producer._without_outcome_fields(_row(
        row_id=None,
        intent_id="historical-accepted-1",
        prediction_id="historical-accepted-1",
        signal_id="historical-accepted-1",
        quantity=1.0,
        adaptive_capital_policy_version=status_module.ADAPTIVE_CAPITAL_POLICY_VERSION,
    ))
    matrix = _bucket_matrix_for(tmp_path, accepted_source)
    monkeypatch.setattr(
        producer.status_module,
        "_connect_redis",
        lambda: _FakeRedis({
            "v2:paper:intents": {"rows": []},
            "v2:paper:intents_held_by_paper_fill_gate": {"rows": []},
            "v2:paper:ledger": {
                "accepted": [accepted_source],
                "closed_trades": [],
                "open_positions": [],
            },
        }),
    )

    manifest = producer.produce_realtime(
        rows_path=tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl",
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[],
        include_redis=True,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:30:01Z",
    )

    assert manifest["pending_appended_count"] == 0
    assert manifest["accepted_appended_count"] == 0
    assert manifest["rejection_reason_counts"]["REALTIME_PENDING_SOURCE_STALE_FOR_NEW_PENDING_RECORD"] == 1


def test_realtime_redis_fresh_accepted_can_create_pending(tmp_path: Path, monkeypatch) -> None:
    accepted_source = producer._without_outcome_fields(_row(
        row_id=None,
        intent_id="fresh-accepted-1",
        prediction_id="fresh-accepted-1",
        signal_id="fresh-accepted-1",
        quantity=1.0,
        adaptive_capital_policy_version=status_module.ADAPTIVE_CAPITAL_POLICY_VERSION,
    ))
    matrix = _bucket_matrix_for(tmp_path, accepted_source)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    monkeypatch.setattr(
        producer.status_module,
        "_connect_redis",
        lambda: _FakeRedis({
            "v2:paper:intents": {"rows": []},
            "v2:paper:intents_held_by_paper_fill_gate": {"rows": []},
            "v2:paper:ledger": {
                "accepted": [accepted_source],
                "closed_trades": [],
                "open_positions": [],
            },
        }),
    )

    manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[],
        include_redis=True,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T12:01:00Z",
    )

    pending_rows, _ = producer._iter_jsonl(
        tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    )
    final_rows, _ = producer._iter_jsonl(rows_path)

    assert manifest["pending_appended_count"] == 1
    assert manifest["accepted_appended_count"] == 0
    assert manifest["rejected_appended_count"] == 0
    assert manifest["same_run_pending_rows_not_labeled_count"] == 1
    assert manifest["pending_sidecar_summary"]["status"] == "READY_PENDING_SELECTIONS_WAITING_FOR_OUTCOMES"
    assert len(pending_rows) == 1
    assert pending_rows[0]["candidate_selection_tier"] == "A_GRADE_EXECUTION_PAPER"
    assert pending_rows[0]["_producer_source_kind"] == "redis_paper_ledger_accepted"
    assert "after_cost_return_bps" not in pending_rows[0]
    assert final_rows == []


def test_realtime_watch_runs_bounded_cycles_without_exchange_side_effects(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_produce_realtime(**kwargs):
        calls.append(kwargs["generated_utc"])
        return {
            "status": "READY" if len(calls) == 2 else "NO_COUNTABLE_REALTIME_ROWS_APPENDED",
            "processed_source_row_count": 1,
            "accepted_appended_count": 1 if len(calls) == 2 else 0,
            "pending_appended_count": 1 if len(calls) == 1 else 0,
            "rejected_appended_count": 0,
            "duplicate_skipped_count": 0,
            "rejection_reason_counts": {},
        }

    monkeypatch.setattr(producer, "produce_realtime", fake_produce_realtime)
    monkeypatch.setattr(producer.time, "sleep", lambda _seconds: None)

    summary = producer.produce_realtime_watch(
        rows_path=tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl",
        bucket_matrix_path=tmp_path / "a_grade_bucket_performance_matrix.json",
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[],
        jsonl_sources=[],
        include_redis=True,
        redis_scan_limit=10,
        require_pending_for_closed=True,
        max_rows=None,
        cycles=2,
        poll_seconds=0.01,
    )

    assert len(calls) == 2
    assert summary["status"] == "READY_REALTIME_WATCH_CAPTURED_COUNTABLE_ROWS"
    assert summary["totals"]["pending_appended_count"] == 1
    assert summary["totals"]["accepted_appended_count"] == 1
    assert summary["paper_only"] is True
    assert summary["places_real_order"] is False
    assert summary["leverage_mutation"] is False
    assert summary["margin_mode_mutation"] is False
    assert summary["old_redis_writes"] is False


def test_hash_chain_verifier_passes_and_detects_tampered_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row()
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    rows_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl"

    registry_path = _registry(tmp_path, source)
    producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )
    producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=registry_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:01:00Z",
    )

    passed = producer.verify_hash_chain(
        chain_path=rows_path.with_suffix(rows_path.suffix + ".hash_chain.jsonl"),
        sidecar_paths=[
            rows_path,
            rows_path.with_name("out_of_sample_holdout_reverify_pending.jsonl"),
            rows_path.with_name("out_of_sample_holdout_reverify_rejected.jsonl"),
        ],
        generated_utc="2026-06-21T00:02:00Z",
    )
    assert passed["status"] == "PASSED_HASH_CHAIN_INTEGRITY"
    assert passed["failure_count"] == 0

    rows, _ = producer._iter_jsonl(rows_path)
    rows[0]["after_cost_return_bps"] = 99.0
    _write_jsonl(rows_path, rows)

    failed = producer.verify_hash_chain(
        chain_path=rows_path.with_suffix(rows_path.suffix + ".hash_chain.jsonl"),
        sidecar_paths=[
            rows_path,
            rows_path.with_name("out_of_sample_holdout_reverify_pending.jsonl"),
            rows_path.with_name("out_of_sample_holdout_reverify_rejected.jsonl"),
        ],
        generated_utc="2026-06-21T00:03:00Z",
    )
    assert failed["status"] == "NO_GO_HASH_CHAIN_INTEGRITY_FAILED"
    assert failed["failure_count"] >= 1
    assert {
        failure["reason"]
        for failure in failed["failure_sample"]
    } & {"CHAIN_RECORD_HASH_NOT_FOUND_IN_SIDECAR", "SIDECAR_ROWS_WITHOUT_CHAIN_RECORD"}


def test_verify_mode_preserves_sidecar_manifest_counts_in_summary(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    holdout_rows = out_dir / "out_of_sample_holdout_reverify_rows.jsonl"
    realtime_rows = out_dir / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    holdout_rows.write_text("")
    realtime_rows.write_text("")
    holdout_rows.with_suffix(holdout_rows.suffix + ".hash_chain.jsonl").write_text("")
    realtime_rows.with_suffix(realtime_rows.suffix + ".hash_chain.jsonl").write_text("")
    registry_path = out_dir / "out_of_sample_holdout_window_registry.json"
    registry_path.write_text(json.dumps({"status": "READY_HOLDOUT_REGISTRY_PREFLIGHT"}))
    holdout_rows.with_suffix(holdout_rows.suffix + ".manifest.json").write_text(json.dumps({
        "producer": "holdout",
        "accepted_appended_count": 3,
        "rejected_appended_count": 4,
    }))
    realtime_rows.with_suffix(realtime_rows.suffix + ".manifest.json").write_text(json.dumps({
        "producer": "realtime",
        "accepted_appended_count": 5,
        "pending_appended_count": 6,
        "rejected_appended_count": 7,
    }))
    producer._append_manifest_history(
        manifest_path=holdout_rows.with_suffix(holdout_rows.suffix + ".manifest.json"),
        sidecar_path=holdout_rows,
        manifest=json.loads(holdout_rows.with_suffix(holdout_rows.suffix + ".manifest.json").read_text()),
        generated_utc="2026-06-21T00:00:00Z",
    )
    producer._append_manifest_history(
        manifest_path=realtime_rows.with_suffix(realtime_rows.suffix + ".manifest.json"),
        sidecar_path=realtime_rows,
        manifest=json.loads(realtime_rows.with_suffix(realtime_rows.suffix + ".manifest.json").read_text()),
        generated_utc="2026-06-21T00:00:00Z",
    )
    registry_manifest_path = producer._holdout_registry_manifest_path(registry_path)
    registry_manifest_path.write_text(json.dumps({
        "producer": "holdout_registry",
        "status": "READY_HOLDOUT_REGISTRY_MANIFEST",
    }))
    producer._append_manifest_history(
        manifest_path=registry_manifest_path,
        sidecar_path=registry_path,
        manifest=json.loads(registry_manifest_path.read_text()),
        generated_utc="2026-06-21T00:00:00Z",
    )
    (out_dir / "out_of_sample_evidence_producer_summary.json").write_text(json.dumps({
        "realtime_watch": {"cycles_completed": 2},
    }))

    exit_code = producer.main([
        "verify",
        "--out-dir",
        str(out_dir),
        "--holdout-rows",
        str(holdout_rows),
        "--realtime-rows",
        str(realtime_rows),
        "--holdout-registry",
        str(registry_path),
    ])

    summary = json.loads((out_dir / "out_of_sample_evidence_producer_summary.json").read_text())
    assert exit_code == 0
    assert summary["holdout"]["accepted_appended_count"] == 3
    assert summary["realtime"]["accepted_appended_count"] == 5
    assert summary["realtime_watch"]["cycles_completed"] == 2
    assert summary["integrity"]["status"] == "PASSED_EVIDENCE_INTEGRITY"
    assert summary["integrity"]["holdout_manifest_history"]["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"
    assert summary["integrity"]["realtime_manifest_history"]["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"
    assert (
        summary["integrity"]["holdout_registry_manifest_history"]["status"]
        == "PASSED_MANIFEST_HISTORY_INTEGRITY"
    )


def test_manifest_history_verifier_passes_and_detects_current_manifest_tamper(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row()
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    rows_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl"

    manifest = producer.produce_holdout(
        source_jsonl=source,
        rows_path=rows_path,
        registry_path=_registry(tmp_path, source),
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )
    manifest_path = rows_path.with_suffix(rows_path.suffix + ".manifest.json")

    passed = producer.verify_manifest_history(
        manifest_path=manifest_path,
        generated_utc="2026-06-21T00:01:00Z",
    )
    assert manifest["manifest_history_path"] == str(producer._manifest_history_path(manifest_path))
    assert passed["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"
    assert passed["history_record_count"] == 1
    assert passed["current_manifest_hash"] == passed["latest_history_manifest_hash"]

    tampered = json.loads(manifest_path.read_text())
    tampered["accepted_appended_count"] = 99
    manifest_path.write_text(json.dumps(tampered))

    failed = producer.verify_manifest_history(
        manifest_path=manifest_path,
        generated_utc="2026-06-21T00:02:00Z",
    )
    assert failed["status"] == "NO_GO_MANIFEST_HISTORY_INTEGRITY_FAILED"
    assert {
        failure["reason"]
        for failure in failed["failure_sample"]
    } & {"LATEST_MANIFEST_HISTORY_NOT_CURRENT"}


def test_manifest_history_verifier_accepts_repo_relative_manifest_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(producer, "REPO_ROOT", tmp_path)
    manifest_path = tmp_path / "runtime" / "sidecar.jsonl.manifest.json"
    sidecar_path = tmp_path / "runtime" / "sidecar.jsonl"
    manifest = {
        "schema_version": producer.SCHEMA_VERSION,
        "producer": "unit",
        "status": "READY_UNIT_MANIFEST",
    }
    producer._write_json(manifest_path, manifest)
    producer._append_manifest_history(
        manifest_path=manifest_path,
        sidecar_path=sidecar_path,
        manifest=manifest,
        generated_utc="2026-06-21T00:00:00Z",
    )

    passed = producer.verify_manifest_history(
        manifest_path=manifest_path.relative_to(tmp_path),
        generated_utc="2026-06-21T00:01:00Z",
    )

    assert passed["status"] == "PASSED_MANIFEST_HISTORY_INTEGRITY"
    assert passed["history_record_count"] == 1
    assert passed["manifest_path"] == str(manifest_path)


def test_realtime_cli_default_filesystem_sources_include_runtime_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_produce_realtime(**kwargs):
        captured.update(kwargs)
        manifest_path = kwargs["rows_path"].with_suffix(kwargs["rows_path"].suffix + ".manifest.json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "producer": "realtime",
            "accepted_appended_count": 0,
            "pending_appended_count": 0,
            "rejected_appended_count": 0,
        }))
        return json.loads(manifest_path.read_text())

    monkeypatch.setattr(producer, "produce_realtime", fake_produce_realtime)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    exit_code = producer.main([
        "realtime",
        "--out-dir",
        str(tmp_path),
        "--realtime-rows",
        str(rows_path),
    ])

    source_names = [path.name for path in captured["json_sources"]]
    assert exit_code == 0
    assert source_names == [
        "v2_trade_management_paper_live_status.json",
        "paper_ledger_tail.json",
        "current_signal_lineage.json",
        "paper_runtime_status.json",
        "PAPER_LOOP_ONCE_STATUS.json",
        "paper_adaptive_sizing_runtime_status.json",
    ]
    assert captured["jsonl_sources"][0].name == "paper_events.jsonl"
    assert captured["include_redis"] is False


def test_realtime_redis_only_cli_skips_filesystem_sources(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_produce_realtime(**kwargs):
        captured.update(kwargs)
        manifest_path = kwargs["rows_path"].with_suffix(kwargs["rows_path"].suffix + ".manifest.json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "producer": "realtime",
            "accepted_appended_count": 0,
            "pending_appended_count": 0,
            "rejected_appended_count": 0,
        }))
        return json.loads(manifest_path.read_text())

    monkeypatch.setattr(producer, "produce_realtime", fake_produce_realtime)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    exit_code = producer.main([
        "realtime",
        "--out-dir",
        str(tmp_path),
        "--realtime-rows",
        str(rows_path),
        "--read-redis",
        "--realtime-redis-only",
    ])

    summary = json.loads((tmp_path / "out_of_sample_evidence_producer_summary.json").read_text())
    assert exit_code == 0
    assert captured["json_sources"] == []
    assert captured["jsonl_sources"] == []
    assert captured["include_redis"] is True
    assert summary["realtime"]["producer"] == "realtime"


def test_realtime_cli_can_skip_jsonl_history_while_using_current_snapshots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_produce_realtime(**kwargs):
        captured.update(kwargs)
        manifest_path = kwargs["rows_path"].with_suffix(kwargs["rows_path"].suffix + ".manifest.json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "producer": "realtime",
            "accepted_appended_count": 0,
            "pending_appended_count": 0,
            "rejected_appended_count": 0,
        }))
        return json.loads(manifest_path.read_text())

    monkeypatch.setattr(producer, "produce_realtime", fake_produce_realtime)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    exit_code = producer.main([
        "realtime",
        "--out-dir",
        str(tmp_path),
        "--realtime-rows",
        str(rows_path),
        "--read-redis",
        "--realtime-skip-jsonl-sources",
    ])

    source_names = [path.name for path in captured["json_sources"]]
    assert exit_code == 0
    assert source_names == [
        "v2_trade_management_paper_live_status.json",
        "paper_ledger_tail.json",
        "current_signal_lineage.json",
        "paper_runtime_status.json",
        "PAPER_LOOP_ONCE_STATUS.json",
        "paper_adaptive_sizing_runtime_status.json",
    ]
    assert captured["jsonl_sources"] == []
    assert captured["include_redis"] is True


def test_summary_only_prints_compact_safe_counts(tmp_path: Path, monkeypatch, capsys) -> None:
    def fake_produce_realtime(**kwargs):
        manifest_path = kwargs["rows_path"].with_suffix(kwargs["rows_path"].suffix + ".manifest.json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "producer": "realtime",
            "status": "NO_COUNTABLE_REALTIME_ROWS_APPENDED",
            "processed_source_row_count": 2,
            "accepted_appended_count": 0,
            "pending_appended_count": 1,
            "rejected_appended_count": 1,
            "duplicate_skipped_count": 0,
            "realtime_evidence_acquisition_status": {
                "status": "READY_REALTIME_PENDING_SELECTIONS_APPENDED",
                "candidate_ready_source_row_count": 1,
                "candidate_allocation_count": 2,
                "ready_full_candidate_allocation_count": 1,
            },
        }
        manifest_path.write_text(json.dumps(manifest))
        return manifest

    monkeypatch.setattr(producer, "produce_realtime", fake_produce_realtime)
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    exit_code = producer.main([
        "realtime",
        "--out-dir",
        str(tmp_path),
        "--realtime-rows",
        str(rows_path),
        "--summary-only",
    ])
    printed = json.loads(capsys.readouterr().out)
    persisted = json.loads((tmp_path / "out_of_sample_evidence_producer_summary.json").read_text())

    assert exit_code == 0
    assert printed["realtime"]["processed_source_row_count"] == 2
    assert printed["realtime"]["pending_appended_count"] == 1
    assert printed["realtime"]["acquisition_status"] == "READY_REALTIME_PENDING_SELECTIONS_APPENDED"
    assert printed["realtime"]["ready_full_candidate_allocation_count"] == 1
    assert printed["safety"]["paper_only"] is True
    assert printed["safety"]["places_real_order"] is False
    assert persisted["realtime"]["processed_source_row_count"] == 2


def test_regenerate_status_classifies_no_go_exit_after_artifacts_written(
    tmp_path: Path,
    monkeypatch,
) -> None:
    out_dir = tmp_path / "latest"
    out_dir.mkdir()
    monkeypatch.setattr(producer, "DEFAULT_OUT_DIR", out_dir)

    def fake_run(*_args, **_kwargs):
        (out_dir / "operator_dashboard_payload.json").write_text(json.dumps({
            "generated_utc": "2026-06-22T03:30:55Z",
            "overall_status": "NO_GO",
            "out_of_sample_live_grade_reverify_status": {
                "status": "NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE",
            },
        }))
        return SimpleNamespace(returncode=2, stdout="{\"overall_status\":\"NO_GO\"}", stderr="")

    monkeypatch.setattr(producer.subprocess, "run", fake_run)

    result = producer.regenerate_status(horizon_years=5.0)

    assert result["status"] == "READY_STATUS_REGENERATED_WITH_NO_GO_GATE"
    assert result["returncode"] == 2
    assert result["dashboard_overall_status"] == "NO_GO"
    assert (
        result["out_of_sample_live_grade_status"]
        == "NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE"
    )
    assert (out_dir / "out_of_sample_evidence_producer_status_regeneration.log").exists()


def test_sidecar_summary_flags_concentrated_profit(tmp_path: Path) -> None:
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    rows = [
        _row(row_id="btc-1", source_redis_key="unit:btc-1", symbol="BTCUSDT", after_cost_return_bps=100.0, realized_after_cost_return_bps=100.0),
        _row(row_id="eth-1", source_redis_key="unit:eth-1", symbol="ETHUSDT", after_cost_return_bps=1.0, realized_after_cost_return_bps=1.0),
        _row(row_id="sol-1", source_redis_key="unit:sol-1", symbol="SOLUSDT", after_cost_return_bps=1.0, realized_after_cost_return_bps=1.0),
    ]
    _write_jsonl(rows_path, rows)

    summary = producer._sidecar_summary(rows_path)

    assert summary["row_count"] == 3
    assert summary["profit_concentration_status"]["symbol"]["status"] == "PROFIT_CONCENTRATION_RISK"
    assert summary["profit_concentration_status"]["symbol"]["top_key"] == "BTCUSDT"


def test_pending_sidecar_summary_fails_closed_on_fingerprint_or_outcome_field_contamination(
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / "out_of_sample_realtime_paper_reverify_pending.jsonl"
    final_rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"
    contaminated = producer._without_outcome_fields(_row(
        row_id="pending-contaminated",
        source_redis_key="unit:pending-contaminated",
    ))
    contaminated.update({
        "candidate_identity": producer._candidate_identity(contaminated, scope="realtime"),
        "selector_policy_fingerprint": "wrong",
        "candidate_selection_tier": "A_GRADE_EXECUTION_PAPER",
        "candidate_selected_before_outcome": True,
        "selected_before_outcome": True,
        "candidate_selected_at": "2026-06-21T12:00:00Z",
        "future_labels_used_as_features": False,
        "after_cost_return_bps": 35.0,
        "funding_pnl_usd": -0.02,
    })
    _write_jsonl(pending_path, [contaminated])
    final_rows_path.write_text("")

    summary = producer._pending_sidecar_summary(
        pending_path,
        final_rows_path=final_rows_path,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        generated_utc="2026-06-21T12:10:00Z",
        scope="realtime",
    )

    assert summary["status"] == "NO_GO_PENDING_SIDECAR_INTEGRITY_GAP"
    assert summary["row_count"] == 1
    assert summary["unresolved_pending_count"] == 1
    assert summary["selector_policy_fingerprint_mismatch_count"] == 1
    assert summary["outcome_field_presence_counts"]["after_cost_return_bps"] == 1
    assert summary["outcome_field_presence_counts"]["funding_pnl_usd"] == 1


def test_holdout_evidence_acquisition_status_surfaces_clean_attestation_blocker() -> None:
    summary = producer._holdout_evidence_acquisition_status(
        registry_preflight={
            "status": "NO_GO_HOLDOUT_REGISTRY_PREFLIGHT_FAILED",
            "registered_window_count": 6,
            "statically_eligible_window_count": 0,
            "matching_source_row_count": 390,
            "decision_time_candidate_ready_count": 0,
            "countable_after_label_count": 0,
            "overlap_row_count": 0,
            "global_reasons": [
                "NO_STATICALLY_ELIGIBLE_HOLDOUT_WINDOWS",
                "NO_DECISION_TIME_A_GRADE_HOLDOUT_CANDIDATES",
            ],
            "windows": [{
                "matching_source_row_count": 390,
                "static_reasons": [
                    "HOLDOUT_EXCLUSION_PROOF_ATTESTATION_MISSING_NOT_USED_FOR_SELECTOR_DEVELOPMENT",
                    "HOLDOUT_EXCLUSION_PROOF_NOT_PASSED",
                    "HOLDOUT_WINDOW_NOT_MARKED_ELIGIBLE",
                ],
            }],
        },
        candidate_audit={"draft_window_count": 18},
        promotion_packet={
            "packet_is_countable_evidence": False,
            "selection_uses_outcome_fields": False,
            "readiness_uses_outcome_fields": False,
            "promotion_readiness_summary": {
                "draft_decision_time_candidate_ready_count": 402,
                "draft_decision_time_ready_no_overlap_count": 334,
                "draft_decision_time_ready_row_level_no_overlap_count": 390,
                "clean_no_overlap_registry_template_count": 6,
            },
            "clean_no_overlap_registry_windows": [
                {"registered_source_row_identity_hash_count": 151},
                {"registered_source_row_identity_hash_count": 239},
            ],
        },
        accepted_count=0,
        pending_count=0,
    )

    assert (
        summary["status"]
        == "NO_GO_HOLDOUT_CLEAN_NO_OVERLAP_ROWS_REQUIRE_UNTOUCHED_ATTESTATION"
    )
    assert summary["clean_no_overlap_registered_identity_count"] == 390
    assert summary["packet_is_countable_evidence"] is False
    assert summary["selection_uses_outcome_fields"] is False
    assert summary["readiness_uses_outcome_fields"] is False
    assert (
        summary["registered_window_static_reason_counts"][
            "HOLDOUT_EXCLUSION_PROOF_ATTESTATION_MISSING_NOT_USED_FOR_SELECTOR_DEVELOPMENT"
        ]
        == 390
    )
    assert "PASSED_UNTOUCHED attestation" in summary["next_required_actions"][0]


def test_holdout_prediction_coverage_counts_pit_no_trade_without_a_grade_admission() -> None:
    source_sha = "source-sha"
    source_row = producer._without_outcome_fields(_row(
        selected_action="NO_TRADE",
        action="NO_TRADE",
        paper_opportunity_tier="NO_TRADE",
        candidate_selection_tier=None,
        allocator_decision="BLOCK_NON_EXECUTABLE_PAPER_TIER",
        gross_notional_usd=0.0,
        allocated_margin_usd=0.0,
        liquidation_buffer_bps=None,
    ))
    registry = {
        "windows": [
            {
                "window_id": "holdout-window-1",
                "start_decision_time": "2026-06-21T11:00:00Z",
                "end_decision_time": "2026-06-21T13:00:00Z",
                "eligible_for_holdout": True,
                "exclusion_proof": {
                    "status": "PASSED_UNTOUCHED",
                    "source_sha256": source_sha,
                    "attestations": _untouched_attestations(),
                    "window_metadata_sha256": "meta-sha",
                    "source_row_identity_hash_set_sha256": "identity-sha",
                    "construction_subset_identity_proof": {
                        "status": producer.CONSTRUCTION_SUBSET_IDENTITY_PROOF_STATUS,
                        "construction_subset_source_sha256": "construction-source-sha",
                        "construction_subset_identity_hash_set_sha256": "construction-identity-sha",
                        "holdout_source_row_identity_hash_set_sha256": "identity-sha",
                        "overlap_identity_hash_count": 0,
                    },
                },
                "window_hashes": {
                    "window_metadata_sha256": "meta-sha",
                    "source_row_identity_hash_set_sha256": "identity-sha",
                },
            }
        ]
    }

    coverage = producer._holdout_prediction_coverage_status(
        [source_row],
        registry=registry,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        source_sha256=source_sha,
        construction_subset_status={
            "full_identity_set_available": True,
            "sha256": "construction-source-sha",
            "identity_hash_set_sha256": "construction-identity-sha",
            "identity_hashes": ["unrelated-construction-identity"],
        },
    )

    assert coverage["status"] == "READY_UNTOUCHED_HOLDOUT_PREDICTION_COVERAGE"
    assert coverage["point_in_time_valid_prediction_count"] == 1
    assert coverage["selected_policy_action_counts"]["NO_TRADE"] == 1
    assert coverage["counts_as_a_grade_evidence"] is False
    assert coverage["counts_no_trade_as_win"] is False
    assert coverage["prediction_reject_reason_counts"] == {}


def test_rejection_ledger_summary_reports_total_reasons_by_source_kind(tmp_path: Path) -> None:
    rejected_path = tmp_path / "out_of_sample_realtime_paper_reverify_rejected.jsonl"
    _write_jsonl(rejected_path, [
        {
            "candidate_identity": "candidate-1",
            "source_kind": "redis_paper_intent",
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "side": "long",
            "decision_time": "2026-06-21T12:00:00Z",
            "reasons": ["DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE", "MISSING_ACCOUNTING_FEES"],
        },
        {
            "candidate_identity": "candidate-1",
            "source_kind": "redis_paper_signal",
            "symbol": "ETHUSDT",
            "timeframe": "15m",
            "side": "short",
            "decision_time": "2026-06-21T12:05:00Z",
            "reasons": ["DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE"],
        },
    ])

    summary = producer._rejection_ledger_summary(rejected_path)

    assert summary["row_count"] == 2
    assert summary["unique_candidate_identity_count"] == 1
    assert summary["missing_candidate_identity_count"] == 0
    assert summary["duplicated_candidate_identity_count"] == 1
    assert summary["duplicate_candidate_identity_row_count"] == 1
    assert summary["duplicated_candidate_identity_sample"] == [
        {"candidate_identity": "candidate-1", "row_count": 2}
    ]
    assert summary["reason_counts"]["DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE"] == 2
    assert summary["reason_counts"]["MISSING_ACCOUNTING_FEES"] == 1
    assert summary["top_rejection_reasons"][0] == {
        "reason": "DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE",
        "row_count": 2,
    }
    assert summary["source_kind_counts"] == {
        "redis_paper_intent": 1,
        "redis_paper_signal": 1,
    }
    assert summary["source_kind_reason_counts"]["redis_paper_intent"]["MISSING_ACCOUNTING_FEES"] == 1
    assert summary["top_reason_combinations"][0]["row_count"] == 1
    assert summary["samples_by_reason"]["DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE"][0]["candidate_identity"] == "candidate-1"


def test_realtime_source_gate_breakdown_counts_duplicate_rejections(tmp_path: Path) -> None:
    rejected_source = producer._without_outcome_fields(_row(
        row_id="not-ready",
        source_redis_key="unit:not-ready",
        expected_move_after_cost_bps=0.0,
    ))
    source_json = tmp_path / "paper_ledger_tail.json"
    source_json.write_text(json.dumps({"entries": [rejected_source]}))
    matrix = _bucket_matrix_for(tmp_path, _row(row_id="bucket"))
    rows_path = tmp_path / "out_of_sample_realtime_paper_reverify_rows.jsonl"

    first_manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )
    second_manifest = producer.produce_realtime(
        rows_path=rows_path,
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        json_sources=[source_json],
        jsonl_sources=[],
        include_redis=False,
        redis_scan_limit=5000,
        require_pending_for_closed=True,
        max_rows=None,
        generated_utc="2026-06-21T00:01:00Z",
    )

    assert first_manifest["rejected_appended_count"] == 1
    assert second_manifest["rejected_appended_count"] == 0
    assert second_manifest["duplicate_skipped_count"] == 1
    breakdown = second_manifest["source_gate_breakdown"]
    assert breakdown["processed_source_row_count"] == 1
    assert breakdown["rejected_source_row_count"] == 1
    assert breakdown["reason_counts"]["NON_POSITIVE_DECISION_TIME_EXPECTED_EDGE"] == 1
    assert breakdown["category_counts"]["frozen_selector"] >= 1
