from __future__ import annotations

import importlib.util
import json
import sys
import time
from collections import deque
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[5]


def _load_script(path: Path, module_name: str, monkeypatch) -> ModuleType:
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    monkeypatch.setenv("V2_REDIS_PREFIX", "v2:")
    monkeypatch.setenv("LIVE_GATE", "blocked_human_only")
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeRedisBridge:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.writes: list[tuple[str, str]] = []

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value, *args, **kwargs):
        self.writes.append(("set", key))
        self.values[key] = str(value)
        return True

    def llen(self, key: str) -> int:
        return len(self.lists.get(key, []))

    def lrange(self, key: str, start: int, end: int):
        return self.lists.get(key, [])[start : end + 1]

    def xadd(self, stream: str, fields: dict):
        self.writes.append(("xadd", stream))
        return "1-0"


class FakePipeline:
    def __init__(self, parent: "FakeRedisLevels") -> None:
        self.parent = parent

    def hset(self, key: str, *args, **kwargs):
        self.parent.writes.append(("hset", key))
        return self

    def expire(self, key: str, ttl: int):
        self.parent.writes.append(("expire", key))
        return self

    def execute(self):
        return True


class FakeRedisLevels:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str]] = []

    def get(self, key: str):
        if key == "v2:features:latest:BTCUSDT:1m":
            return json.dumps({"features": {"micro_price": 100.0}})
        return None

    def pipeline(self):
        return FakePipeline(self)


def test_copied_liquidation_bridge_maps_all_writes_to_v2(monkeypatch):
    mod = _load_script(
        REPO_ROOT / "v2/legacy_owned_runtime/ingest/liquidation_bridge.py",
        "test_v2_copied_liquidation_bridge",
        monkeypatch,
    )
    fake = FakeRedisBridge()
    fake.lists[mod.BINANCE_KEY] = [
        json.dumps({
            "symbol": "BTCUSDT",
            "ts": int(time.time() * 1000),
            "price": 100.0,
            "qty": 2.0,
            "side": "SELL",
        })
    ]
    monkeypatch.setattr(mod, "r", fake)

    assert mod.STREAM == "v2:liquidations:events"
    assert mod.BINANCE_KEY == "v2:binance:force:raw"
    assert mod.COINANK_KEY == "v2:raw:coinank:liquidation_orders:global"
    assert mod._dedup_key("binance", "abc").startswith("v2:")
    assert mod.process_binance_force() == 1
    assert fake.writes
    assert all(key.startswith("v2:") for _op, key in fake.writes)


def test_copied_liquidation_levels_maps_stream_and_feature_writes_to_v2(monkeypatch):
    mod = _load_script(
        REPO_ROOT / "v2/legacy_owned_runtime/ingest/liquidation_levels_engine.py",
        "test_v2_copied_liquidation_levels_engine",
        monkeypatch,
    )
    fake = FakeRedisLevels()
    monkeypatch.setattr(mod, "r", fake)
    monkeypatch.setattr(mod, "RUNTIME_SYMBOLS", ("BTCUSDT",))
    monkeypatch.setattr(mod, "RUNTIME_TIMEFRAMES", ("1m",))

    engine = object.__new__(mod.LevelEngine)
    now_ms = int(time.time() * 1000)
    engine.state = {
        "BTCUSDT": {
            "1m": deque([
                {
                    "ts": now_ms,
                    "price": 99.5,
                    "qty": 2.0,
                    "notional": 199.0,
                    "side": "LONG_LIQ",
                    "symbol": "BTCUSDT",
                }
            ])
        }
    }
    engine.ewma_price = {"BTCUSDT": None}
    engine.last_publish = {}

    assert mod.STREAM_NAME == "v2:liquidations:events"
    assert mod.GROUP_NAME == "v2_liq_levels"
    engine._publish_updates([("BTCUSDT", "1m")])
    assert fake.writes
    assert all(key.startswith("v2:") for _op, key in fake.writes)
    assert any(key == "v2:unified_features:BTCUSDT:1m" for _op, key in fake.writes)


def test_liquidation_systemd_units_are_paper_only_and_do_not_start_live_binance():
    bridge_unit = Path("/home/wali/.config/systemd/user/ai-bot-v2-liquidation-bridge.service")
    if bridge_unit.is_symlink():
        assert bridge_unit.resolve() == Path("/dev/null")

    for unit in (Path("/home/wali/.config/systemd/user/ai-bot-v2-liquidation-levels-engine.service"),):
        text = unit.read_text(encoding="utf-8")
        assert "LIVE_GATE=blocked_human_only" in text
        assert "V2_LIVE=0" in text
        assert "V2_CANARY=0" in text
        assert "V2_REDIS_PREFIX=v2:" in text
        assert "live_binance_liquidations.py" not in text
