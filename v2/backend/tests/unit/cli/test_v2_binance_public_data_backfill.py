from __future__ import annotations

import hashlib
import zipfile
from datetime import date

import pytest

from v2.backend.app.cli.v2_binance_public_data_backfill import (
    _download,
    build_archive_requests,
    verify_checksum,
)


def test_build_archive_requests_uses_futures_um_public_archive_paths() -> None:
    requests = build_archive_requests(
        symbols=["BTCUSDT"],
        market="futures_um",
        frequency="daily",
        data_types=["trades", "aggTrades", "klines"],
        intervals=["1m"],
        start=date(2026, 6, 1),
        end=date(2026, 6, 1),
    )
    urls = {request.url for request in requests}

    assert "https://data.binance.vision/data/futures/um/daily/trades/BTCUSDT/BTCUSDT-trades-2026-06-01.zip" in urls
    assert "https://data.binance.vision/data/futures/um/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-06-01.zip" in urls
    assert "https://data.binance.vision/data/futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-06-01.zip" in urls


def test_verify_checksum_accepts_binance_checksum_format(tmp_path) -> None:
    zip_path = tmp_path / "BTCUSDT-trades-2026-06-01.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("BTCUSDT-trades-2026-06-01.csv", "1,100,1,100,1780000000000,true\n")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path = tmp_path / "BTCUSDT-trades-2026-06-01.zip.CHECKSUM"
    checksum_path.write_text(f"{digest}  BTCUSDT-trades-2026-06-01.zip\n")

    assert verify_checksum(zip_path, checksum_path) is True


def test_archive_download_is_rest_fallback_only(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    target = tmp_path / "BTCUSDT-trades-2026-06-01.zip"

    with pytest.raises(RuntimeError, match="BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"):
        _download(
            "https://data.binance.vision/data/futures/um/daily/trades/BTCUSDT/BTCUSDT-trades-2026-06-01.zip",
            target,
        )

    assert not target.exists()
