"""Tests for the V2 per-symbol liquidation ingestor loop + aggregator
integration.

Paper-only. No torch import. No network IO in tests (uses in-memory
fake redis). No legacy mutation. No exchange mutation. No silent
zero-fill.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    def scan_iter(self, match: str | None = None):
        if match is None:
            yield from list(self.store.keys())
            return
        prefix = match.rstrip("*")
        for k in list(self.store.keys()):
            if match.endswith("*"):
                if k.startswith(prefix):
                    yield k
            elif k == match:
                yield k


def _service():
    return importlib.import_module(
        "v2.backend.app.services.native_ingestors.liquidations"
    )


def _agg():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.liquidation_observation_aggregator"
    )


def test_classifier_default_today_is_operator_decision_required(monkeypatch) -> None:
    svc = _service()
    monkeypatch.delenv("V2_LIQUIDATION_WSS_OPT_IN", raising=False)
    cls = svc.classify_liquidation_source()
    assert (
        cls.classification == svc.SOURCE_BLOCKED_BY_OPERATOR_DECISION
    )
    assert cls.operator_decision_required is True
    assert cls.public_no_credential_path_known is True
    assert "forceOrder" in (cls.public_no_credential_path_description or "")


def test_classifier_flips_to_available_when_opt_in(monkeypatch) -> None:
    svc = _service()
    monkeypatch.setenv("V2_LIQUIDATION_WSS_OPT_IN", "true")
    cls = svc.classify_liquidation_source()
    assert cls.classification == svc.SOURCE_AVAILABLE_V2_NATIVE
    assert cls.operator_decision_required is False


def test_write_contract_is_v2_namespace_only() -> None:
    svc = _service()
    cls = svc.classify_liquidation_source()
    for pattern in cls.v2_write_contract:
        assert pattern.startswith("v2:")


def test_write_heartbeat_refuses_without_redis() -> None:
    svc = _service()
    assert svc.write_heartbeat(None, {"x": 1}) is False


def test_write_heartbeat_writes_v2_key_only() -> None:
    svc = _service()
    r = FakeRedis()
    assert svc.write_heartbeat(r, {"go_no_go": "X"}) is True
    assert "v2:market:liquidations:heartbeat" in r.store
    raw = r.store["v2:market:liquidations:heartbeat"]
    assert json.loads(raw)["go_no_go"] == "X"
    # No non-v2 keys created.
    for k in r.store.keys():
        assert k.startswith("v2:")


def test_ingestor_status_payload_safety_invariants_when_blocked() -> None:
    svc = _service()
    p = svc.build_ingestor_status(redis_client=None, symbols=("BTCUSDT",))
    assert p["go_no_go"] == "V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED"
    assert (
        p["source_classification"]
        == svc.SOURCE_BLOCKED_BY_OPERATOR_DECISION
    )
    assert p["operator_decision_required"] is True
    assert p["writes_legacy_redis"] is False
    assert p["writes_exchange_orders"] is False
    assert p["no_synthetic_liquidation_events"] is True
    assert p["live_gate"] == "blocked_human_only"
    assert p["live_symbols"] == []
    assert p["approves_live"] is False
    assert p["approves_canary"] is False
    assert p["approves_legacy_shutdown"] is False
    assert p["approves_redis_trim"] is False


def test_cli_writes_payloads_with_blocked_go_no_go(
    tmp_path: Path, monkeypatch
) -> None:
    cli = importlib.import_module(
        "v2.backend.app.cli.v2_liquidation_ingestor_loop"
    )
    worklog = tmp_path / "wl/status.json"
    public_a = tmp_path / "public_a/status.json"
    public_b = tmp_path / "public_b/status.json"
    fake = FakeRedis()
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=fake,
        worklog_path=worklog,
        public_paths=(public_a, public_b),
        write_redis_heartbeat=True,
    )
    assert payload["go_no_go"] == "V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED"
    a = json.loads(worklog.read_text())
    b = json.loads(public_a.read_text())
    c = json.loads(public_b.read_text())
    assert a == b == c
    # Redis heartbeat is written under v2:* only.
    assert "v2:market:liquidations:heartbeat" in fake.store


def test_aggregator_uses_per_symbol_data_when_populated() -> None:
    agg = _agg()
    rows = agg.build_liquidation_subfamily(
        symbol="BTCUSDT",
        v2_features={"last_liq_bps_24h": 3.0},
        coinank_intel={"freshness_seconds": 12.5,
                       "global_aggregate_result": {"total_liquidations": 4.0}},
        v2_liquidation_per_symbol={
            "latest": {"notional": 250000.0, "side": "long"},
            "aggregate": {"notional_1h": 1750000.0},
            "any_populated": True,
            "v2_per_symbol_aggregator_present": True,
        },
    )
    by_name = {nm: (val, src) for (nm, val, src) in rows}
    val, src = by_name["liquidations.latest_liquidation_notional"]
    assert val == 250000.0
    assert src == "V2_MARKET_LIQUIDATIONS_LATEST"
    val, src = by_name["liquidations.latest_liquidation_side_long"]
    assert val == 1.0
    val, src = by_name["liquidations.latest_liquidation_side_short"]
    assert val == 0.0
    val, src = by_name["liquidations.liquidation_notional_1h_proxy"]
    assert val == 1750000.0
    assert src == "V2_MARKET_LIQUIDATIONS_AGGREGATE"
    val, src = by_name["liquidations.v2_liquidation_source_available"]
    assert val == 1.0
    assert src == "V2_MARKET_LIQUIDATIONS_PER_SYMBOL_PRESENT"


def test_aggregator_keeps_per_symbol_missing_when_keys_absent() -> None:
    agg = _agg()
    rows = agg.build_liquidation_subfamily(
        symbol="ETHUSDT",
        v2_features={"last_liq_bps_24h": 5.0},
        coinank_intel={"freshness_seconds": 30.0,
                       "global_aggregate_result": {"total_liquidations": 0.0}},
        v2_liquidation_per_symbol=None,
    )
    by_name = {nm: (val, src) for (nm, val, src) in rows}
    val, src = by_name["liquidations.latest_liquidation_notional"]
    assert val is None
    assert src == "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR"
    val, src = by_name["liquidations.latest_liquidation_side_long"]
    assert val is None
    val, src = by_name["liquidations.liquidation_notional_1h_proxy"]
    assert val is None
    val, src = by_name["liquidations.v2_liquidation_source_available"]
    assert val == 0.0
    assert src == "V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT"


def test_no_torch_imported_in_ingestor_modules() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.native_ingestors.liquidations"
    )
    importlib.import_module(
        "v2.backend.app.cli.v2_liquidation_ingestor_loop"
    )
    assert "torch" not in sys.modules
