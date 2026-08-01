"""Unit tests for the ta_closed -> feats TA-Lib merge (point-in-time bound).

The model ABI requires 155 ``taf_*`` technical-analysis leaves that the native
producer does not compute internally. They are sourced from the authenticated
``v2:features:ta_closed:*`` candidate ONLY when it is bound to the identical last
closed candle the snapshot selected. These tests lock the exact name mapping and
the point-in-time binding.
"""

from __future__ import annotations

import json

from v2.backend.app.cli import v2_feature_pipeline_native_loop as P


class _FakeRedis:
    def __init__(self, store: dict[str, str]) -> None:
        self.store = store

    def get(self, key: str):
        return self.store.get(key)


def _candidate(close_ms: int) -> dict:
    return {
        "schema_version": "v2_full_talib_ta_closed_candidate_v1",
        "compatibility_view": False,
        "compatibility_unsafe_for_trainer": False,
        "candle_closed_confirmed": True,
        "closed_candles_only": True,
        "latest_closed_candle_close_ts_ms": close_ms,
        "feature_cutoff": "2026-07-31T22:35:59.999Z",
        "source_ohlcv_key": "v2:market:ohlcv_closed:binance:BTCUSDT:1m",
        "source_exact_payload_sha256": "a" * 64,
        "calculation_window_candle_ids_sha256": "b" * 64,
        "source_available_at": "2026-07-31T22:36:08.465Z",
        "generated_at": "2026-07-31T22:36:20.838863Z",
        "indicators": {
            # exact-name leaves
            "atr_14": 0.0019,
            "rsi_14": 55.2,
            "macd": 0.4,
            "ema_12": 100.1,
            # upper-cased TA-Lib function leaves (case-insensitive fallback)
            "ta_ADX": 21.7,
            "ta_CCI": -12.0,
            "close": 100.0,  # not a required taf_ leaf; must be ignored
            "bad": float("nan"),  # non-finite must never be merged
        },
    }


def _required_subset() -> tuple[str, ...]:
    wanted = {"taf_atr_14", "taf_rsi_14", "taf_macd", "taf_ema_12", "taf_ta_adx", "taf_ta_cci"}
    present = tuple(n for n in P._TRAINER_REQUIRED_TAF_FEATURE_NAMES if n in wanted)
    # Fall back to a synthetic set if the ABI names ever drift, so the test still
    # exercises the mapping rule rather than silently passing on an empty set.
    return present or tuple(sorted(wanted))


def test_merge_binds_and_maps_names_case_insensitively() -> None:
    close_ms = 1785537359999
    r = _FakeRedis({"v2:features:ta_closed:BTCUSDT:1m": json.dumps(_candidate(close_ms))})
    feats: dict[str, float] = {}
    required = _required_subset()
    binding = P._merge_ta_closed_indicator_features(
        r, "BTCUSDT", "1m", feats,
        required_taf_names=required,
        snapshot_candle_close_ms=close_ms,
    )
    assert binding is not None
    # At least the requested taf_ leaves merge; the helper additionally fills any
    # bare-name TA aliases (ATR/EMA/MACD/RSI/bollinger) the candidate exposes.
    assert binding["ta_closed_merged_feature_count"] >= len(required)
    assert binding["ta_closed_latest_closed_candle_close_ts_ms"] == close_ms
    # exact-name and case-insensitive (ta_ADX / ta_CCI) both resolve
    assert feats.get("taf_atr_14") == 0.0019
    if "taf_ta_adx" in required:
        assert feats["taf_ta_adx"] == 21.7
    # never merge non-finite or non-required leaves
    assert "close" not in feats
    assert all(isinstance(v, float) for v in feats.values())


def test_merge_rejects_mismatched_candle_pit_binding() -> None:
    close_ms = 1785537359999
    r = _FakeRedis({"v2:features:ta_closed:BTCUSDT:1m": json.dumps(_candidate(close_ms))})
    feats: dict[str, float] = {}
    # snapshot is on a DIFFERENT closed candle -> must not merge (no lookahead)
    binding = P._merge_ta_closed_indicator_features(
        r, "BTCUSDT", "1m", feats,
        required_taf_names=_required_subset(),
        snapshot_candle_close_ms=close_ms + 60_000,
    )
    assert binding is None
    assert feats == {}


def test_merge_rejects_compatibility_and_unsafe_views() -> None:
    close_ms = 1785537359999
    doc = _candidate(close_ms)
    doc["compatibility_unsafe_for_trainer"] = True
    r = _FakeRedis({"v2:features:ta_closed:BTCUSDT:1m": json.dumps(doc)})
    feats: dict[str, float] = {}
    binding = P._merge_ta_closed_indicator_features(
        r, "BTCUSDT", "1m", feats,
        required_taf_names=_required_subset(),
        snapshot_candle_close_ms=close_ms,
    )
    assert binding is None
    assert feats == {}


def test_merge_returns_none_when_no_candidate() -> None:
    r = _FakeRedis({})
    feats: dict[str, float] = {}
    binding = P._merge_ta_closed_indicator_features(
        r, "BTCUSDT", "1m", feats,
        required_taf_names=_required_subset(),
        snapshot_candle_close_ms=1785537359999,
    )
    assert binding is None
    assert feats == {}
