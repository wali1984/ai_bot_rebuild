"""Tests for paper-only outcome-memory rebuild CLI.

No exchange calls. Default mode is read-only for Redis.
"""
from __future__ import annotations

import json

from v2.backend.app.cli import v2_paper_outcome_memory_rebuild as cli


class _RedisStub:
    def __init__(self, store: dict[str, str]):
        self.store = dict(store)
        self.set_calls: list[tuple[str, str]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str) -> None:
        self.set_calls.append((key, value))
        self.store[key] = value


def _closed_rows() -> list[dict]:
    return [
        {
            "symbol": "SOLUSDT",
            "timeframe": "5m",
            "realized_pnl_usd": -1.0,
            "realized_pnl_bps": -10.0,
            "exit_price_utc": f"2026-06-19T00:{i:02d}:00Z",
        }
        for i in range(20)
    ]


def test_cli_dry_run_writes_report_but_not_redis(monkeypatch, tmp_path) -> None:
    redis_stub = _RedisStub({"v2:paper:closed_trades": json.dumps(_closed_rows())})
    monkeypatch.setattr(cli, "_connect_redis", lambda: redis_stub)

    out = tmp_path / "outcome_memory_dry_run.json"
    code = cli.main(["--out", out.as_posix()])

    assert code == 0
    assert redis_stub.set_calls == []
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["dry_run"] is True
    assert report["writes_redis"] is False
    assert report["degraded_bucket_count"] == 2


def test_cli_write_mode_only_writes_v2_paper_outcome_memory(monkeypatch, tmp_path) -> None:
    redis_stub = _RedisStub({"v2:paper:closed_trades": json.dumps(_closed_rows())})
    monkeypatch.setattr(cli, "_connect_redis", lambda: redis_stub)

    out = tmp_path / "outcome_memory_write.json"
    code = cli.main(["--write-v2-paper-outcome-memory", "--out", out.as_posix()])

    assert code == 0
    assert len(redis_stub.set_calls) == 2
    written = {key: json.loads(payload) for key, payload in redis_stub.set_calls}
    assert set(written) == {
        "v2:paper:outcome_memory:SOLUSDT:5m",
        "v2:paper:outcome_memory:__ALL__:5m",
    }
    assert written["v2:paper:outcome_memory:SOLUSDT:5m"]["degraded"] is True
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["dry_run"] is False
    assert report["writes_redis"] is True
    assert report["writes_old_redis"] is False
