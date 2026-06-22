from __future__ import annotations

import json
from pathlib import Path

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


def _registry(path: Path) -> Path:
    registry_path = path / "out_of_sample_holdout_window_registry.json"
    registry_path.write_text(json.dumps({
        "schema_version": producer.SCHEMA_VERSION,
        "status": "PASSED",
        "selector_policy_fingerprint": producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        "windows": [{
            "window_id": "unit-untouched-window",
            "start_decision_time": "2026-06-21T00:00:00Z",
            "end_decision_time": "2026-06-22T00:00:00Z",
            "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "timeframes": ["5m"],
            "eligible_for_holdout": True,
            "exclusion_proof": {"status": "PASSED_UNTOUCHED"},
        }],
    }))
    return registry_path


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


def test_holdout_producer_appends_pending_then_labels_on_later_pass(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    valid = _row()
    _write_jsonl(source, [valid])
    matrix = _bucket_matrix_for(tmp_path, valid)
    rows_path = tmp_path / "out_of_sample_holdout_reverify_rows.jsonl"
    registry_path = _registry(tmp_path)

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
    assert second_manifest["accepted_appended_count"] == 1
    assert second_manifest["pending_appended_count"] == 0
    assert second_manifest["holdout_labeling_policy"] == "REQUIRES_PREEXISTING_PENDING_SELECTION_RECORD"
    assert second_manifest["labeled_from_preexisting_pending_count"] == 1
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
    registry_path = _registry(tmp_path)

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
        _row(row_id="bad-fingerprint", selector_policy_fingerprint="wrong"),
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
        registry_path=_registry(tmp_path),
        bucket_matrix_path=matrix,
        expected_fingerprint=producer.EXPECTED_SELECTOR_POLICY_FINGERPRINT,
        max_rows=None,
        generated_utc="2026-06-21T00:00:00Z",
    )

    reasons = manifest["rejection_reason_counts"]
    assert manifest["accepted_appended_count"] == 0
    assert manifest["pending_appended_count"] == 1
    assert manifest["duplicate_skipped_count"] == 1
    assert reasons["SOURCE_SELECTOR_POLICY_FINGERPRINT_MISMATCH"] == 1
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
        generated_utc="2026-06-21T00:00:00Z",
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
    assert final_manifest["accepted_appended_count"] == 1
    assert len(pending_rows) == 1
    assert len(final_rows) == 1
    assert final_rows[0]["candidate_selected_at"] == "2026-06-21T00:00:00Z"
    assert final_rows[0]["after_cost_return_bps"] == 35.0
    assert final_rows[0]["gross_notional_usd"] == pending_source["gross_notional_usd"]


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
        generated_utc="2026-06-21T00:00:00Z",
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


def test_realtime_redis_historical_accepted_cannot_create_new_pending(tmp_path: Path, monkeypatch) -> None:
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
        generated_utc="2026-06-21T00:00:00Z",
    )

    assert manifest["pending_appended_count"] == 0
    assert manifest["accepted_appended_count"] == 0
    assert manifest["rejection_reason_counts"]["HISTORICAL_SOURCE_CANNOT_CREATE_NEW_PENDING_RECORD"] == 1


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

    registry_path = _registry(tmp_path)
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
    ])

    summary = json.loads((out_dir / "out_of_sample_evidence_producer_summary.json").read_text())
    assert exit_code == 0
    assert summary["holdout"]["accepted_appended_count"] == 3
    assert summary["realtime"]["accepted_appended_count"] == 5
    assert summary["realtime_watch"]["cycles_completed"] == 2
    assert summary["integrity"]["status"] == "PASSED_EVIDENCE_INTEGRITY"


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
            "candidate_identity": "candidate-2",
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
    assert summary["reason_counts"]["DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE"] == 2
    assert summary["reason_counts"]["MISSING_ACCOUNTING_FEES"] == 1
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
