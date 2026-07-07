from __future__ import annotations

import zipfile

from v2.backend.app.services.orderbook_recorder.replay_engine import (
    build_local_replay_engine_status,
    summarize_local_orderbook_replay,
)
from v2.backend.app.services.orderbook_recorder.store import LocalReplayStore


def test_local_replay_summary_excludes_records_after_decision_time(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "orderbook_replay")
    store.append(
        exchange="binance",
        symbol="BTCUSDT",
        record_type="features",
        event_time="2026-06-01T00:00:00.000Z",
        payload={"available_at": "2026-06-01T00:00:00.000Z", "spread_bps": 1.0},
    )
    store.append(
        exchange="binance",
        symbol="BTCUSDT",
        record_type="features",
        event_time="2026-06-01T00:00:02.000Z",
        payload={"available_at": "2026-06-01T00:00:02.000Z", "spread_bps": 2.0},
    )

    status = summarize_local_orderbook_replay(
        replay_root=tmp_path / "orderbook_replay",
        decision_time="2026-06-01T00:00:01.000Z",
    )

    assert status["total_orderbook_records"] == 2
    assert status["included_orderbook_records"] == 1
    assert status["available_at_violations"] == 1


def test_replay_engine_status_counts_public_backfill_without_claiming_l2(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "v2/runtime/orderbook_replay")
    store.append(
        exchange="binance",
        symbol="BTCUSDT",
        record_type="features",
        event_time="2026-06-01T00:00:00.000Z",
        payload={"available_at": "2026-06-01T00:00:00.000Z", "spread_bps": 1.0},
    )
    backfill = tmp_path / "v2/runtime/binance_public_backfill/futures/um/daily/klines/BTCUSDT/1m"
    backfill.mkdir(parents=True)
    with zipfile.ZipFile(backfill / "BTCUSDT-1m-2026-06-01.zip", "w") as archive:
        archive.writestr("BTCUSDT-1m-2026-06-01.csv", "1,2,3,4,5,6\n")

    status = build_local_replay_engine_status(
        repo_root=tmp_path,
        replay_root=tmp_path / "v2/runtime/orderbook_replay",
        replay_store_status=store.status(),
    )

    assert status["uses_local_orderbook_recordings_after_recorder_start"] is True
    assert status["uses_binance_public_trades_klines"] is True
    assert status["missing_old_l2_explicit_not_fabricated"] is True
    assert status["binance_public_backfill"]["klines_files"] == 1
    assert status["binance_public_backfill"]["historical_l2_claimed"] is False
