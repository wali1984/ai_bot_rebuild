from __future__ import annotations

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    build_archive_record_from_prediction_payload,
)

FIELDS = {
    "latest_unclosed_kline_excluded": True,
    "latest_unclosed_exclusion_method": "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1",
    "latest_unclosed_exclusion_decision_time_ms": 1785000000000,
    "latest_closed_kline_close_time_ms": 1784999700000,
}


def _payload() -> dict:
    return {
        "prediction_id": "pred_x",
        "signal_id": "sig_x",
        "decision_id": "dec_x",
        "feature_snapshot_id": "fsnap_x",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "feature_cutoff": "2026-07-25T16:59:58Z",
        "decision_time": "2026-07-25T17:00:00Z",
        "available_at": "2026-07-25T16:59:59Z",
        "mtf_snapshot_id": "mtf_x",
        "feature_snapshot": {
            "feature_snapshot_id": "fsnap_x",
            "features": {"ret_1": 0.1, "atr_bps": 30.0},
            "candle_closed_confirmed": True,
            "source_hashes": {"ret_1": "h1"},
            **FIELDS,
        },
    }


def test_all_four_finality_fields_reach_the_archive_record():
    record = build_archive_record_from_prediction_payload(_payload())
    assert record is not None
    for key, value in FIELDS.items():
        assert record[key] == value, f"{key}: {record.get(key)} != {value}"


def test_absent_finality_field_stays_absent_not_manufactured():
    payload = _payload()
    # Producer omitted the proof entirely -> archive must NOT synthesize True.
    payload["feature_snapshot"].pop("latest_unclosed_kline_excluded")
    payload.pop("latest_unclosed_kline_excluded", None)
    record = build_archive_record_from_prediction_payload(payload)
    assert record["latest_unclosed_kline_excluded"] is not True
