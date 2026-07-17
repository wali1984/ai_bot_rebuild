from __future__ import annotations

import fnmatch
import json

from app.cli import v2_altdata_confluence_loop as loop


class _FakeRedis:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self._data = dict(data or {})
        self.set_calls: list[tuple[str, object, int | None]] = []

    def get(self, key: str):
        value = self._data.get(key)
        return None if value is None else json.dumps(value)

    def set(self, key: str, value: object, ex: int | None = None):
        self.set_calls.append((key, value, ex))
        try:
            self._data[key] = json.loads(str(value))
        except Exception:
            self._data[key] = value
        return True

    def scan_iter(self, match: str = "*", count: int = 500):  # noqa: ARG002
        for key in sorted(self._data):
            if fnmatch.fnmatch(key, match):
                yield key


def test_run_once_publishes_current_candidate_symbol_timeframes_when_enabled() -> None:
    client = _FakeRedis(
        {
            "v2:paper:preemptive_candidate_decision_matrix": {
                "rows": [
                    {"symbol": "DOGEUSDT", "timeframe": "5m"},
                    {"symbol": "SOLUSDT", "timeframe": "1h"},
                ]
            },
            "v2:features:coinglass:DOGEUSDT:5m": {
                "actual_payload_present": True,
                "generated_utc": "2026-07-12T00:00:00Z",
                "available_at": "2026-07-12T00:00:00Z",
                "feature_cutoff": "2026-07-11T23:59:00Z",
                "features": {
                    "coinglass_liquidation_cascade_score": 0.8,
                    "coinglass_liquidation_imbalance_usd": 2_000_000.0,
                },
            },
        }
    )

    report = loop.run_once(
        client,
        symbols=["BTCUSDT"],
        timeframe="1m",
        include_current_candidates=True,
        max_candidate_pairs=10,
    )
    written_keys = {key for key, _value, _ex in client.set_calls}

    assert report["include_current_candidates"] is True
    assert report["dynamic_candidate_pair_count"] == 2
    assert report["pair_count"] == 3
    assert "v2:altdata:confluence:BTCUSDT:1m" in written_keys
    assert "v2:altdata:confluence:DOGEUSDT:5m" in written_keys
    assert "v2:altdata:confluence:SOLUSDT:1h" in written_keys
    assert report["places_real_order"] is False
    assert report["approves_live"] is False


def test_run_once_keeps_legacy_symbol_list_when_current_candidates_disabled() -> None:
    client = _FakeRedis(
        {
            "v2:paper:preemptive_candidate_decision_matrix": {
                "rows": [{"symbol": "DOGEUSDT", "timeframe": "5m"}]
            }
        }
    )

    report = loop.run_once(
        client,
        symbols=["BTCUSDT"],
        timeframe="1m",
        include_current_candidates=False,
    )
    written_keys = {key for key, _value, _ex in client.set_calls}

    assert report["include_current_candidates"] is False
    assert report["dynamic_candidate_pair_count"] == 0
    assert report["pair_count"] == 1
    assert "v2:altdata:confluence:BTCUSDT:1m" in written_keys
    assert "v2:altdata:confluence:DOGEUSDT:5m" not in written_keys


def test_compact_report_summarizes_rows_for_log_output() -> None:
    report = {
        "schema_version": "altdata_confluence_loop_status_v1",
        "pair_count": 3,
        "rows": [
            {"symbol": "BTCUSDT", "actual_payload_present": True, "providers_present": ["coinank", "santiment"]},
            {"symbol": "ETHUSDT", "actual_payload_present": True, "providers_present": ["santiment"]},
            {"symbol": "SUNUSDT", "actual_payload_present": False, "providers_present": []},
        ],
    }
    compact = loop._compact_report(report)
    assert "rows" not in compact
    assert compact["row_count"] == 3
    assert compact["actual_payload_present_count"] == 2
    assert compact["providers_present_counts"] == {"coinank": 1, "santiment": 2}
    assert compact["pair_count"] == 3


def test_main_universe_sentinel_resolves_runtime_universe(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(loop, "_redis_client", lambda url: _FakeRedis())
    monkeypatch.setattr(loop, "_universe_symbols", lambda: ["BTCUSDT", "SUNUSDT"])

    def fake_run_once(client, *, symbols, timeframe, include_current_candidates, max_candidate_pairs):
        captured["symbols"] = list(symbols)
        return {"rows": [], "pair_count": len(symbols)}

    monkeypatch.setattr(loop, "run_once", fake_run_once)
    rc = loop.main(["--once", "--symbols", "UNIVERSE"])
    assert rc == 0
    assert captured["symbols"] == ["BTCUSDT", "SUNUSDT"]


def test_main_explicit_symbols_stay_pinned(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(loop, "_redis_client", lambda url: _FakeRedis())
    monkeypatch.setattr(
        loop, "_universe_symbols", lambda: (_ for _ in ()).throw(AssertionError("must not resolve universe"))
    )

    def fake_run_once(client, *, symbols, timeframe, include_current_candidates, max_candidate_pairs):
        captured["symbols"] = list(symbols)
        return {"rows": [], "pair_count": len(symbols)}

    monkeypatch.setattr(loop, "run_once", fake_run_once)
    rc = loop.main(["--once", "--symbols", "BTCUSDT,ETHUSDT"])
    assert rc == 0
    assert captured["symbols"] == ["BTCUSDT", "ETHUSDT"]
