from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

import fnmatch
import json

from v2.backend.app.cli.run_pass3a_live_canary_safety_dry_run import run_dry_run
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


class FakeRedis:
    def __init__(self) -> None:
        self.data = {
            "v2:live_gate:state": {
                "live_gate": "blocked_human_only",
                "order_transport_submit_enabled": False,
                "live_trading_enabled": False,
                "live_blocked": True,
                "operator_approved": False,
                "places_real_order": False,
                "exchange_action_taken": False,
                "release_mode": "NON_LIVE",
            },
            "v2:trader:execution_state": {"trader_execution_enabled": False},
            "v2:live_order_transport:status": {"order_submitted": False, "places_real_order": False},
            "v2:prediction:BTCUSDT:1m": {
                "trust_schema_version": TRUST_SCHEMA_VERSION,
                "decision_id": "d1",
                "prediction_id": "p1",
                "mtf_snapshot_id": "mtf1",
                "replay_snapshot_id": "rs1",
                "feature_cutoff": "2026-06-13T00:00:00Z",
                "available_at": "2026-06-13T00:00:01Z",
                "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
                "routes_to_live": False,
                "live_order_allowed": False,
                "selected_action": "hold",
                "symbol": "BTCUSDT",
            },
            "v2:replay:snapshots:p1": {"prediction_id": "p1", "replay_snapshot_id": "rs1"},
            "v2:market:mtf_snapshot:mtf1": {"prediction_id": "p1", "mtf_snapshot_id": "mtf1", "valid": True},
        }

    def get(self, key: str):
        value = self.data.get(key)
        return json.dumps(value) if value is not None else None

    def scan_iter(self, match: str, count: int = 500):
        del count
        for key in sorted(self.data):
            if fnmatch.fnmatch(key, match):
                yield key


def test_pass3a_dry_run_blocks_by_default_without_mutation(tmp_path: Path) -> None:
    report = run_dry_run(
        client=FakeRedis(),
        redis_url="redis://127.0.0.1:6379/0",
        run_id="20260613_000000",
        output_dir=tmp_path,
    )

    assert report["submit_allowed"] is False
    assert report["live_canary_enabled"] is False
    assert report["places_real_order"] is False
    assert report["exchange_action_taken"] is False
    assert report["live_order_submitted"] is False
    assert report["trusted_prediction_count"] == 1
    assert report["replay_snapshot_count"] == 1
    assert report["mtf_snapshot_count"] == 1
    assert "LIVE_CANARY_DISABLED" in report["preflight"]["blockers"]
    assert "RELEASE_MODE_NON_LIVE" in report["preflight"]["blockers"]
