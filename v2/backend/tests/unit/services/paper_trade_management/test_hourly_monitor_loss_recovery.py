"""Tests for hourly_monitor, outcome_memory_updater, and loss_recovery services.

Phase V2_CONTINUOUS_PAPER_RUNTIME_PROOF_AND_LOSS_RECOVERY companion tests.

No exchange calls. No legacy Redis writes. Gate: blocked_human_only.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from v2.backend.app.services.paper_trade_management.hourly_monitor import (
    build_3h_window_artifacts,
    build_cumulative_artifacts,
    build_hourly_artifacts,
    compute_paper_pnl_window,
    compute_prediction_accuracy_window,
    compute_risk_window,
    is_window_losing,
)
from v2.backend.app.services.paper_trade_management.loss_recovery import (
    LIVE_GATE as LR_GATE,
    evaluate_loss_recovery,
)
from v2.backend.app.services.paper_trade_management.outcome_memory_updater import (
    LIVE_GATE as OM_GATE,
    ROLLING_WINDOW,
    _bucket_key,
    _load_bucket,
    _update_bucket,
    build_outcome_memory_buckets_from_closed_trades,
    rebuild_outcome_memory_from_closed_trades,
    update_outcome_memory,
)
from v2.backend.app.services.paper_trade_management.outcome_memory import (
    OutcomeMemoryBucket,
    evaluate_outcome_memory_bucket,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _now_ts() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _fill_event(symbol="BTCUSDT", timeframe="15m", pnl=10.0, return_bps=20.0, ts: str | None = None):
    return {
        "paper_result": "FILLED_PAPER_ONLY",
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": ts if ts is not None else _now_ts(),
        "paper_action": "paper_long",
    }


def _closed_event(symbol="BTCUSDT", timeframe="15m", pnl=10.0, return_bps=20.0, ts: str | None = None):
    close_ts = ts if ts is not None else _now_ts()
    return {
        "paper_result": "POSITION_CLOSED_PAPER_ONLY",
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": close_ts,
        "exit_price_utc": close_ts,
        "outcome_available_at": close_ts,
        "realized_delta_usdt": pnl,
        "current_return_bps": return_bps,
        "paper_action": "paper_long",
        "exit_reason": "TP_HIT",
        "side": "long",
        "prediction_id": "prediction-1",
        "signal_id": "signal-1",
        "decision_id": "decision-1",
        "risk_decision_id": "risk-decision-1",
        "orchestrator_decision_id": "orchestrator-decision-1",
        "feature_snapshot_id": "feature-snapshot-1",
        "mtf_snapshot_id": "mtf-snapshot-1",
        "feature_cutoff": "2026-06-08T20:59:00Z",
        "decision_time": "2026-06-08T21:00:00Z",
        "available_at": "2026-06-08T20:59:59Z",
        "selected_action": "long",
        "model_version": "model-v1",
        "checkpoint_id": "checkpoint-v1",
        "source_hashes": {"feature_vector_hash": "hash-feature-vector-1"},
    }


def _blocked_event(reason="deny_entry_gate", ts: str | None = None):
    return {
        "paper_result": "NO_FILL_RISK_BLOCKED",
        "generated_at": ts if ts is not None else _now_ts(),
        "risk_reason_code": reason,
    }


def _make_jsonl(events: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    for ev in events:
        tmp.write(json.dumps(ev) + "\n")
    tmp.close()
    return Path(tmp.name)


def _fake_redis() -> MagicMock:
    store: dict[str, str] = {}
    r = MagicMock()
    r.get.side_effect = lambda k: store.get(k)
    r.set.side_effect = lambda k, v: store.update({k: v})
    r.delete.side_effect = lambda k: store.pop(k, None)
    return r


# ── hourly_monitor tests ───────────────────────────────────────────────────────

class TestComputePaperPnlWindow:
    def test_empty_events(self):
        result = compute_paper_pnl_window([])
        assert result["closed_trade_count"] == 0
        assert result["win_rate"] is None
        assert result["profit_factor"] is None
        assert result["live_mutation_count_must_be_zero"] == 0

    def test_single_win(self):
        events = [_fill_event(), _closed_event(pnl=15.0, return_bps=30.0)]
        result = compute_paper_pnl_window(events)
        assert result["closed_trade_count"] == 1
        assert result["win_count"] == 1
        assert result["loss_count"] == 0
        assert result["win_rate"] == 1.0
        assert result["paper_realized_pnl"] == 15.0

    def test_single_loss(self):
        events = [_fill_event(), _closed_event(pnl=-5.0, return_bps=-10.0)]
        result = compute_paper_pnl_window(events)
        assert result["loss_count"] == 1
        assert result["win_rate"] == 0.0
        assert result["paper_realized_pnl"] == -5.0
        assert result["profit_factor"] == 0.0

    def test_win_loss_mix(self):
        events = [
            _fill_event(),
            _closed_event(pnl=20.0, return_bps=30.0),
            _fill_event(),
            _closed_event(pnl=-10.0, return_bps=-15.0),
        ]
        result = compute_paper_pnl_window(events)
        assert result["closed_trade_count"] == 2
        assert result["win_rate"] == 0.5
        assert abs(result["profit_factor"] - 2.0) < 0.01
        assert result["paper_realized_pnl"] == 10.0

    def test_blocked_count(self):
        events = [_blocked_event("deny_entry_gate"), _blocked_event("deny_entry_gate")]
        result = compute_paper_pnl_window(events)
        assert result["blocked_count"] == 2
        assert result["top_block_reasons"][0]["reason"] == "deny_entry_gate"
        assert result["top_block_reasons"][0]["count"] == 2

    def test_live_mutation_always_zero(self):
        events = [_closed_event(pnl=100.0)]
        result = compute_paper_pnl_window(events)
        assert result["live_mutation_count_must_be_zero"] == 0

    def test_symbol_counts(self):
        events = [_closed_event(symbol="BTCUSDT"), _closed_event(symbol="ETHUSDT")]
        result = compute_paper_pnl_window(events)
        assert result["trade_count_by_symbol"]["BTCUSDT"] == 1
        assert result["trade_count_by_symbol"]["ETHUSDT"] == 1


class TestFeedbackConsumedAndLeverageCount:
    def test_feedback_consumed_from_feedback_sent_field(self):
        events = [
            _closed_event(pnl=10.0),
            _closed_event(pnl=-5.0),
            _fill_event(),
        ]
        events[0]["feedback_sent"] = True
        events[1]["feedback_sent"] = True
        path = _make_jsonl(events)
        now = dt.datetime.now(dt.timezone.utc)
        result = build_hourly_artifacts(
            jsonl_path=path,
            window_start=now - dt.timedelta(hours=1),
            window_end=now + dt.timedelta(hours=1),
        )
        assert result["trainer_hourly_status"]["trainer_feedback_consumed"] == 2
        path.unlink(missing_ok=True)

    def test_feedback_consumed_falls_back_to_closed_count_for_old_events(self):
        events = [_closed_event(pnl=10.0), _closed_event(pnl=-5.0)]
        # Old events: no feedback_sent field
        path = _make_jsonl(events)
        now = dt.datetime.now(dt.timezone.utc)
        result = build_hourly_artifacts(
            jsonl_path=path,
            window_start=now - dt.timedelta(hours=1),
            window_end=now + dt.timedelta(hours=1),
        )
        assert result["trainer_hourly_status"]["trainer_feedback_consumed"] == 2
        path.unlink(missing_ok=True)

    def test_leverage_rec_count_nonzero_for_new_events(self):
        ev = _fill_event()
        ev["leverage_recommendation"] = {"recommended_leverage": 2, "margin_mode": "isolated", "mutates_exchange": False}
        path = _make_jsonl([ev])
        now = dt.datetime.now(dt.timezone.utc)
        result = build_hourly_artifacts(
            jsonl_path=path,
            window_start=now - dt.timedelta(hours=1),
            window_end=now + dt.timedelta(hours=1),
        )
        assert result["adaptive_action_leverage_margin_hourly_status"]["adaptive_leverage_recommendation_count"] == 1
        path.unlink(missing_ok=True)

    def test_leverage_rec_count_zero_for_old_events_without_field(self):
        ev = _fill_event()
        # Old event: no leverage_recommendation field
        path = _make_jsonl([ev])
        now = dt.datetime.now(dt.timezone.utc)
        result = build_hourly_artifacts(
            jsonl_path=path,
            window_start=now - dt.timedelta(hours=1),
            window_end=now + dt.timedelta(hours=1),
        )
        assert result["adaptive_action_leverage_margin_hourly_status"]["adaptive_leverage_recommendation_count"] == 0
        path.unlink(missing_ok=True)


class TestComputePredictionAccuracyWindow:
    def test_empty(self):
        result = compute_prediction_accuracy_window([])
        assert result["filled_count"] == 0
        assert result["closed_count"] == 0

    def test_direction_accuracy_long_win(self):
        events = [
            _fill_event(),
            _closed_event(pnl=10.0),
        ]
        result = compute_prediction_accuracy_window(events)
        acc = result["prediction_accuracy_by_direction"]["long"]
        assert acc["total"] == 1
        assert acc["correct"] == 1
        assert acc["accuracy"] == 1.0


class TestComputeRiskWindow:
    def test_accept_rate(self):
        events = [
            _fill_event(),
            _fill_event(),
            _blocked_event(),
        ]
        result = compute_risk_window(events)
        assert result["risk_accepted"] == 2
        assert result["risk_blocked"] == 1
        assert abs(result["risk_accept_rate"] - 2 / 3) < 0.01


class TestIsWindowLosing:
    def test_no_closed_trades_is_not_losing(self):
        assert is_window_losing({"paper_trader_hourly_pnl": {"closed_trade_count": 0}}) is False

    def test_negative_pnl_is_losing(self):
        assert is_window_losing({"paper_trader_hourly_pnl": {
            "closed_trade_count": 2, "paper_realized_pnl": -5.0,
        }}) is True

    def test_low_win_rate_is_losing(self):
        assert is_window_losing({"paper_trader_hourly_pnl": {
            "closed_trade_count": 10, "paper_realized_pnl": 1.0, "win_rate": 0.3,
        }}) is True

    def test_positive_pnl_high_win_rate_clean(self):
        assert is_window_losing({"paper_trader_hourly_pnl": {
            "closed_trade_count": 10, "paper_realized_pnl": 10.0, "win_rate": 0.6,
        }}) is False


class TestBuildHourlyArtifacts:
    def test_returns_all_7_artifacts(self):
        events = [_fill_event(), _closed_event()]
        path = _make_jsonl(events)
        now = dt.datetime.now(dt.timezone.utc)
        result = build_hourly_artifacts(
            jsonl_path=path,
            window_start=now - dt.timedelta(hours=1),
            window_end=now + dt.timedelta(hours=1),
        )
        expected_keys = {
            "trainer_hourly_status",
            "signal_prediction_hourly_accuracy",
            "orchestrator_hourly_decision_quality",
            "risk_controller_hourly_status",
            "paper_trader_hourly_pnl",
            "hedge_exit_hourly_status",
            "adaptive_action_leverage_margin_hourly_status",
        }
        assert set(result.keys()) == expected_keys
        path.unlink(missing_ok=True)

    def test_all_artifacts_have_gate_and_no_mutation(self):
        path = _make_jsonl([_closed_event()])
        now = dt.datetime.now(dt.timezone.utc)
        result = build_hourly_artifacts(
            jsonl_path=path,
            window_start=now - dt.timedelta(hours=1),
            window_end=now + dt.timedelta(hours=1),
        )
        for name, artifact in result.items():
            assert artifact.get("mutates_exchange") is False, f"{name} mutates_exchange must be False"
        path.unlink(missing_ok=True)

    def test_empty_file_produces_clean_artifacts(self):
        path = _make_jsonl([])
        now = dt.datetime.now(dt.timezone.utc)
        result = build_hourly_artifacts(
            jsonl_path=path,
            window_start=now - dt.timedelta(hours=1),
            window_end=now + dt.timedelta(hours=1),
        )
        assert result["paper_trader_hourly_pnl"]["closed_trade_count"] == 0
        path.unlink(missing_ok=True)

    def test_3h_window_builder_returns_n_windows(self):
        path = _make_jsonl([_closed_event()])
        result = build_3h_window_artifacts(jsonl_path=path, hours=3)
        assert len(result) == 3
        path.unlink(missing_ok=True)

    def test_cumulative_includes_pnl(self):
        path = _make_jsonl([_fill_event(), _closed_event(pnl=50.0)])
        result = build_cumulative_artifacts(jsonl_path=path)
        assert result["paper_trader_hourly_pnl"]["paper_realized_pnl"] == 50.0
        path.unlink(missing_ok=True)


# ── outcome_memory_updater tests ───────────────────────────────────────────────

class TestUpdateBucket:
    def test_win_increments_win_count(self):
        bucket = _load_bucket(MagicMock(get=lambda k: None), "v2:test")
        bucket = _update_bucket(bucket, _closed_event(pnl=10.0, return_bps=20.0))
        assert bucket["win_count"] == 1
        assert bucket["loss_count"] == 0
        assert bucket["consecutive_losses"] == 0

    def test_loss_increments_consecutive_losses(self):
        bucket = _load_bucket(MagicMock(get=lambda k: None), "v2:test")
        bucket = _update_bucket(bucket, _closed_event(pnl=-5.0, return_bps=-10.0))
        assert bucket["loss_count"] == 1
        assert bucket["consecutive_losses"] == 1

    def test_rolling_win_rate_computed(self):
        r = MagicMock(get=lambda k: None)
        bucket = _load_bucket(r, "v2:test")
        for i in range(4):
            bucket = _update_bucket(bucket, _closed_event(pnl=10.0))
        bucket = _update_bucket(bucket, _closed_event(pnl=-5.0, return_bps=-10.0))
        assert bucket["rolling_win_rate"] == 0.8

    def test_rolling_window_capped(self):
        r = MagicMock(get=lambda k: None)
        bucket = _load_bucket(r, "v2:test")
        for i in range(ROLLING_WINDOW + 5):
            bucket = _update_bucket(bucket, _closed_event(pnl=10.0))
        assert len(bucket["recent_bps"]) == ROLLING_WINDOW
        assert len(bucket["recent_outcomes"]) == ROLLING_WINDOW

    def test_degraded_flag_set_on_low_win_rate(self):
        r = MagicMock(get=lambda k: None)
        bucket = _load_bucket(r, "v2:test")
        for i in range(20):
            bucket = _update_bucket(bucket, _closed_event(pnl=-5.0, return_bps=-10.0))
        assert bucket["degraded"] is True
        assert "WIN_RATE_DEGRADED" in bucket["block_reason"]

    def test_degraded_false_when_not_enough_trades(self):
        r = MagicMock(get=lambda k: None)
        bucket = _load_bucket(r, "v2:test")
        for i in range(4):
            bucket = _update_bucket(bucket, _closed_event(pnl=-5.0, return_bps=-10.0))
        assert bucket["degraded"] is False

    def test_bucket_shape_is_entry_gate_readable(self):
        r = MagicMock(get=lambda k: None)
        bucket = _load_bucket(r, "v2:test")
        for i in range(20):
            bucket = _update_bucket(bucket, _closed_event(pnl=-5.0, return_bps=-10.0))
        parsed = OutcomeMemoryBucket.from_dict(bucket)
        assert parsed.trade_count == 20
        result = evaluate_outcome_memory_bucket(parsed)
        assert result["blocked"] is True
        assert any("WIN_RATE_DEGRADED" in reason for reason in result["reasons"])


class TestUpdateOutcomeMemory:
    def test_updates_redis_buckets(self):
        events = [
            _closed_event(symbol="BTCUSDT", timeframe="15m", pnl=10.0),
            _closed_event(
                symbol="BTCUSDT",
                timeframe="15m",
                pnl=-5.0,
                return_bps=-10.0,
            ),
            _closed_event(symbol="ETHUSDT", timeframe="1h", pnl=8.0),
        ]
        path = _make_jsonl(events)
        r = _fake_redis()
        result = update_outcome_memory(jsonl_path=path, redis_client=r)
        assert result["events_processed"] == 3
        assert result["buckets_updated"] == 2
        assert result["mutates_exchange"] is False
        assert result["writes_old_redis"] is False
        path.unlink(missing_ok=True)

    def test_no_old_redis_keys_written(self):
        events = [_closed_event(symbol="BTCUSDT")]
        path = _make_jsonl(events)
        r = _fake_redis()
        update_outcome_memory(jsonl_path=path, redis_client=r)
        for call_args in r.set.call_args_list:
            key = call_args[0][0]
            assert key.startswith("v2:"), f"non-v2 key written: {key}"
            assert key.startswith("v2:paper:outcome_memory:"), f"entry_gate cannot read key: {key}"
        path.unlink(missing_ok=True)

    def test_bucket_key_matches_entry_gate_reader_prefix(self):
        assert _bucket_key("btcusdt", "15M") == "v2:paper:outcome_memory:BTCUSDT:15m"

    def test_empty_jsonl_produces_zero_updates(self):
        path = _make_jsonl([])
        r = _fake_redis()
        result = update_outcome_memory(jsonl_path=path, redis_client=r)
        assert result["events_processed"] == 0
        assert result["buckets_updated"] == 0
        path.unlink(missing_ok=True)

    def test_gate_status_in_result(self):
        path = _make_jsonl([])
        result = update_outcome_memory(jsonl_path=path, redis_client=_fake_redis())
        assert result.get("live_gate") == OM_GATE
        path.unlink(missing_ok=True)

    def test_build_buckets_from_closed_trades_sets_gate_fields(self):
        rows = [
            _closed_event(symbol="SOLUSDT", timeframe="5m", pnl=-1.0, return_bps=-12.0)
            for _ in range(20)
        ]
        buckets = build_outcome_memory_buckets_from_closed_trades(rows)
        key = _bucket_key("SOLUSDT", "5m")
        bucket = buckets[key]
        assert bucket["trade_count"] == 20
        assert bucket["total_trades"] == 20
        assert bucket["rolling_win_rate"] == 0.0
        assert bucket["rolling_ev_bps"] == -12.0
        assert bucket["drawdown_contribution_usd"] == -20.0
        assert bucket["degraded"] is True
        assert "ROLLING_EV_DEGRADED" in bucket["block_reason"]

    def test_rebuild_freshness_uses_outcome_availability_not_processing_time(
        self,
        monkeypatch,
    ):
        event = _closed_event(ts="2026-06-09T00:00:00Z")
        event["generated_at"] = "2099-01-01T00:00:00Z"
        monkeypatch.setattr(
            "v2.backend.app.services.paper_trade_management.outcome_memory_updater._now_iso",
            lambda: "2026-07-17T12:00:00Z",
        )

        first = build_outcome_memory_buckets_from_closed_trades([event])[
            _bucket_key("BTCUSDT", "15m")
        ]
        assert first["last_outcome_event_time"] == "2026-06-09T00:00:00Z"
        assert first["last_outcome_available_at"] == "2026-06-09T00:00:00Z"
        assert first["last_updated"] == "2026-07-17T12:00:00Z"

        monkeypatch.setattr(
            "v2.backend.app.services.paper_trade_management.outcome_memory_updater._now_iso",
            lambda: "2026-07-18T12:00:00Z",
        )
        rebuilt = build_outcome_memory_buckets_from_closed_trades([event])[
            _bucket_key("BTCUSDT", "15m")
        ]
        assert rebuilt["last_outcome_available_at"] == first["last_outcome_available_at"]
        assert rebuilt["last_updated"] == "2026-07-18T12:00:00Z"

    def test_future_feature_lineage_is_quarantined_not_trusted(self):
        event = _closed_event()
        event["feature_cutoff"] = "2099-01-01T00:00:00Z"
        event["available_at"] = "2099-01-01T00:00:01Z"

        buckets = build_outcome_memory_buckets_from_closed_trades([event])
        summary = rebuild_outcome_memory_from_closed_trades(
            closed_trade_rows=[event],
            write=False,
        )

        assert buckets == {}
        assert summary["events_processed"] == 0
        assert summary["quarantined_rows"] == 1
        assert summary["rejection_reason_counts"][
            "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME"
        ] == 1
        assert summary["rejection_reason_counts"][
            "FEATURE_CUTOFF_AFTER_DECISION_TIME"
        ] == 1

    @pytest.mark.parametrize(
        ("field", "invalid_value", "expected_reason"),
        [
            (
                "risk_decision_id",
                None,
                "MISSING_TRUST_FIELD:risk_decision_id",
            ),
            ("source_hashes", {}, "MISSING_TRUST_FIELD:source_hashes"),
            (
                "source_hashes",
                {"fake": "fake"},
                "MISSING_CANONICAL_SOURCE_HASH:feature_vector_hash",
            ),
            (
                "decision_time",
                "2026-06-08T21:00:00",
                "TRUST_TIMESTAMP_NOT_AWARE_UTC:decision_time",
            ),
            (
                "exit_price_utc",
                "2026-07-17T12:00:00",
                "CLOSE_EVENT_TIME_NOT_AWARE_UTC",
            ),
        ],
    )
    def test_missing_or_malformed_trust_contract_is_quarantined(
        self,
        field,
        invalid_value,
        expected_reason,
    ):
        event = _closed_event()
        event[field] = invalid_value

        summary = rebuild_outcome_memory_from_closed_trades(
            closed_trade_rows=[event],
            write=False,
        )

        assert summary["events_processed"] == 0
        assert summary["rejection_reason_counts"][expected_reason] == 1

    def test_close_event_time_is_labeled_availability_fallback(self):
        event = _closed_event()
        del event["outcome_available_at"]

        bucket = build_outcome_memory_buckets_from_closed_trades([event])[
            _bucket_key("BTCUSDT", "15m")
        ]

        assert bucket["last_outcome_available_at"] == bucket["last_outcome_event_time"]
        assert bucket["last_outcome_available_at_source"] == (
            "CLOSE_EVENT_TIME_SYNCHRONOUS_AVAILABILITY_FALLBACK"
        )

    @pytest.mark.parametrize("return_bps", [None, float("nan"), float("inf")])
    def test_missing_or_nonfinite_return_bps_is_quarantined(self, return_bps):
        event = _closed_event(return_bps=return_bps)
        summary = rebuild_outcome_memory_from_closed_trades(
            closed_trade_rows=[event],
            write=False,
        )

        assert summary["events_processed"] == 0
        assert summary["quarantined_rows"] == 1
        assert summary["rejection_reason_counts"][
            "MISSING_OR_NONFINITE_REALIZED_RETURN_BPS"
        ] == 1

    def test_profitable_alternating_sample_is_not_latched_by_lifetime_losses(self):
        rows = [
            _closed_event(
                pnl=100.0 if index % 2 == 0 else -2.0,
                return_bps=100.0 if index % 2 == 0 else -2.0,
            )
            for index in range(20)
        ]

        bucket = build_outcome_memory_buckets_from_closed_trades(rows)[
            _bucket_key("BTCUSDT", "15m")
        ]
        evaluated = evaluate_outcome_memory_bucket(OutcomeMemoryBucket.from_dict(bucket))

        assert sum(row["realized_delta_usdt"] for row in rows) == 980.0
        assert bucket["rolling_win_rate"] == 0.5
        assert bucket["rolling_ev_bps"] == 49.0
        assert bucket["max_drawdown_bps"] == 2.0
        assert bucket["drawdown_contribution_usd"] == -2.0
        assert bucket["degraded"] is False
        assert evaluated["allowed"] is True

    def test_rebuild_dry_run_does_not_write_redis(self):
        rows = [
            _closed_event(symbol="DOGEUSDT", timeframe="15m", pnl=-1.0, return_bps=-10.0)
            for _ in range(20)
        ]
        r = _fake_redis()
        result = rebuild_outcome_memory_from_closed_trades(
            closed_trade_rows=rows,
            redis_client=r,
            write=False,
        )
        assert result["dry_run"] is True
        assert result["writes_redis"] is False
        assert result["degraded_bucket_count"] == 2
        assert r.set.call_count == 0

    def test_rebuild_write_mode_writes_only_v2_paper_outcome_memory(self):
        rows = [
            _closed_event(symbol="DOGEUSDT", timeframe="15m", pnl=-1.0, return_bps=-10.0)
            for _ in range(20)
        ]
        r = _fake_redis()
        result = rebuild_outcome_memory_from_closed_trades(
            closed_trade_rows=rows,
            redis_client=r,
            write=True,
        )
        assert result["dry_run"] is False
        assert result["writes_redis"] is True
        assert result["buckets_updated"] == 2
        assert r.set.call_count == 2
        written_keys = {call_args[0][0] for call_args in r.set.call_args_list}
        assert written_keys == {
            "v2:paper:outcome_memory:DOGEUSDT:15m",
            "v2:paper:outcome_memory:__ALL__:15m",
        }
        payload = json.loads(r.get("v2:paper:outcome_memory:DOGEUSDT:15m"))
        assert payload["trade_count"] == 20
        assert payload["degraded"] is True


# ── loss_recovery tests ────────────────────────────────────────────────────────

def test_rebuild_tombstones_bucket_whose_only_close_was_newly_quarantined():
    quarantined = _closed_event(
        symbol="MORPHOUSDT",
        timeframe="15m",
        pnl=10.0,
        return_bps=20.0,
    )
    quarantined.update(
        {
            "close_id": "paper-close-quarantined",
            "unproved_fill_close_quarantined": True,
            "unproved_fill_close_quarantine_reasons": [
                "ENTRY_FILL_PERSISTED_ADMISSION_FINAL_CONTRACT_MISSING",
                "UNPROVED_ADAPTIVE_POLICY_CLOSE_ENTRY_FILL",
            ],
            "counts_as_economic_evidence": False,
            "economic_evidence_eligible": False,
            "counts_as_realized_paper_profit": False,
            "trainer_consumable": False,
        }
    )
    valid = _closed_event(
        symbol="SOLUSDT",
        timeframe="15m",
        pnl=5.0,
        return_bps=8.0,
    )
    valid["close_id"] = "paper-close-valid"
    stale_bucket = build_outcome_memory_buckets_from_closed_trades([quarantined])[
        _bucket_key("MORPHOUSDT", "15m")
    ]
    r = _fake_redis()
    r.set(
        _bucket_key("MORPHOUSDT", "15m"),
        json.dumps(stale_bucket),
    )

    result = rebuild_outcome_memory_from_closed_trades(
        closed_trade_rows=[valid],
        invalidated_rows=[quarantined],
        redis_client=r,
        write=True,
    )

    tombstone = json.loads(r.get(_bucket_key("MORPHOUSDT", "15m")))
    valid_bucket = json.loads(r.get(_bucket_key("SOLUSDT", "15m")))
    aggregate = json.loads(r.get(_bucket_key("__ALL__", "15m")))
    assert tombstone["trade_count"] == 0
    assert tombstone["total_trades"] == 0
    assert tombstone["trusted_trade_count"] == 0
    assert tombstone["untrusted_trade_count"] == 0
    assert tombstone["win_count"] == 0
    assert tombstone["recent_pnl_usd"] == []
    assert tombstone["recent_bps"] == []
    assert tombstone["trust_evidence_status"] != "TRUSTED_OUTCOME_MEMORY"
    assert tombstone["outcome_memory_can_block_entries"] is False
    assert tombstone["degraded"] is False
    assert tombstone["block_reason"] is None
    assert valid_bucket["trade_count"] == 1
    assert valid_bucket["recent_pnl_usd"] == [5.0]
    assert aggregate["trade_count"] == 1
    assert aggregate["recent_pnl_usd"] == [5.0]
    assert result["events_processed"] == 1
    assert result["invalidated_rows_seen"] == 1
    assert result["tombstone_bucket_count"] == 1
    assert result["buckets_updated"] == 3


def test_rebuild_does_not_tombstone_bucket_with_other_valid_outcomes():
    quarantined = _closed_event(
        symbol="MORPHOUSDT",
        timeframe="15m",
        pnl=10.0,
        return_bps=20.0,
    )
    quarantined["close_id"] = "paper-close-quarantined"
    valid = _closed_event(
        symbol="MORPHOUSDT",
        timeframe="15m",
        pnl=-2.0,
        return_bps=-4.0,
    )
    valid["close_id"] = "paper-close-valid"
    r = _fake_redis()

    result = rebuild_outcome_memory_from_closed_trades(
        closed_trade_rows=[valid],
        invalidated_rows=[quarantined],
        redis_client=r,
        write=True,
    )

    symbol_bucket = json.loads(r.get(_bucket_key("MORPHOUSDT", "15m")))
    aggregate = json.loads(r.get(_bucket_key("__ALL__", "15m")))
    assert symbol_bucket["trade_count"] == 1
    assert symbol_bucket["recent_pnl_usd"] == [-2.0]
    assert aggregate["trade_count"] == 1
    assert aggregate["recent_pnl_usd"] == [-2.0]
    assert result["invalidated_rows_seen"] == 1
    assert result["tombstone_bucket_count"] == 0


def _pnl_window(*, closed: int = 5, pnl: float = 10.0, win_rate: float = 0.6, pf: float = 1.5) -> dict:
    return {
        "closed_trade_count": closed,
        "paper_realized_pnl": pnl,
        "win_rate": win_rate,
        "profit_factor": pf,
    }


class TestEvaluateLossRecovery:
    def test_no_windows_no_tightening(self):
        r = _fake_redis()
        result = evaluate_loss_recovery(window_artifacts_list=[], redis_client=r)
        assert result["tightening_active"] is False
        assert result["tightening_applied"] is False

    def test_losing_window_triggers_tightening(self):
        r = _fake_redis()
        windows = [_pnl_window(pnl=-5.0, win_rate=0.3)]
        result = evaluate_loss_recovery(window_artifacts_list=windows, redis_client=r)
        assert result["tightening_applied"] is True
        assert result["tightening_active"] is True

    def test_clean_window_after_losing_counts_toward_recovery(self):
        r = _fake_redis()
        losing = _pnl_window(pnl=-5.0, win_rate=0.3)
        clean = _pnl_window(pnl=10.0, win_rate=0.65, pf=2.0)
        result = evaluate_loss_recovery(window_artifacts_list=[losing, clean, clean], redis_client=r)
        assert result["tightening_applied"] is True
        assert result["consecutive_clean_windows"] == 2
        assert result["tightening_active"] is True

    def test_3_consecutive_clean_clears_tightening(self):
        r = _fake_redis()
        losing = _pnl_window(pnl=-5.0, win_rate=0.3)
        clean = _pnl_window(pnl=10.0, win_rate=0.65, pf=2.0)
        windows = [losing, clean, clean, clean]
        result = evaluate_loss_recovery(window_artifacts_list=windows, redis_client=r)
        assert result["tightening_cleared"] is True
        assert result["tightening_active"] is False

    def test_no_closed_trades_window_skipped(self):
        r = _fake_redis()
        empty_window = _pnl_window(closed=0)
        result = evaluate_loss_recovery(window_artifacts_list=[empty_window], redis_client=r)
        assert result["tightening_applied"] is False

    def test_mutates_exchange_false(self):
        r = _fake_redis()
        result = evaluate_loss_recovery(window_artifacts_list=[], redis_client=r)
        assert result["mutates_exchange"] is False
        assert result["writes_old_redis"] is False

    def test_override_key_written_when_tightened(self):
        store: dict[str, str] = {}
        r = MagicMock()
        r.get.side_effect = lambda k: store.get(k)
        r.set.side_effect = lambda k, v: store.update({k: v})
        r.delete.side_effect = lambda k: store.pop(k, None)

        losing = _pnl_window(pnl=-5.0, win_rate=0.3)
        evaluate_loss_recovery(window_artifacts_list=[losing], redis_client=r, symbol="BTCUSDT", timeframe="15m")

        override_key = "v2:loss_recovery_override:BTCUSDT:15m"
        assert override_key in store
        override = json.loads(store[override_key])
        assert override["tightened"] is True
        assert override.get("mutates_exchange") is False
        assert all(k.startswith("v2:") for k in store)

    def test_override_key_deleted_when_cleared(self):
        store: dict[str, str] = {}
        r = MagicMock()
        r.get.side_effect = lambda k: store.get(k)
        r.set.side_effect = lambda k, v: store.update({k: v})
        r.delete.side_effect = lambda k: store.pop(k, None)

        losing = _pnl_window(pnl=-5.0, win_rate=0.3)
        clean = _pnl_window(pnl=10.0, win_rate=0.65, pf=2.0)
        evaluate_loss_recovery(
            window_artifacts_list=[losing, clean, clean, clean],
            redis_client=r, symbol="BTCUSDT", timeframe="15m",
        )
        assert "v2:loss_recovery_override:BTCUSDT:15m" not in store

    def test_gate_status_in_result(self):
        r = _fake_redis()
        result = evaluate_loss_recovery(window_artifacts_list=[], redis_client=r)
        assert result.get("live_gate") == LR_GATE
