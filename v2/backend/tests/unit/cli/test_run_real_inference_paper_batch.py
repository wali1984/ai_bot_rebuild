from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli.run_real_inference_paper_batch import build_m1_report, main


class FakeRedis:
    def __init__(self, rows: dict[str, dict]) -> None:
        self.rows = rows

    def get(self, key: str) -> str | None:
        value = self.rows.get(key)
        return json.dumps(value) if value is not None else None

    def scan_iter(self, match: str, count: int = 500):
        prefix = match.replace("*", "")
        for key in sorted(self.rows):
            if key.startswith(prefix):
                yield key


def test_m1_no_go_when_only_proof_predictions_exist() -> None:
    client = FakeRedis(
        {
            "v2:prediction:BTCUSDT:1m": {
                "prediction_id": "p1",
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "confidence_raw": 0.0,
                "confidence_calibrated": 0.0,
                "confidence_source": "PROOF_DEFAULT",
                "proof_only": True,
                "model_consumable": False,
                "paper_intent_consumable": False,
                "routeability_candidate": False,
                "routes_to_live": False,
                "live_order_allowed": False,
            },
            "v2:live_gate:state": {
                "live_gate": "blocked_human_only",
                "order_transport_submit_enabled": False,
                "live_trading_enabled": False,
                "places_real_order": False,
                "exchange_action_taken": False,
            },
        }
    )

    report = build_m1_report(client=client, symbols=("BTCUSDT",), max_predictions=50)

    assert report["m1_release_gate"]["verdict"] == "M1 NO-GO"
    assert report["m1_release_gate"]["reason"] == "PREDICTION_WRITER_ONLY_PROOF_PUBLISHER_FOR_CURRENT_CANONICAL_KEYS"
    assert report["real_inference_batch_report"]["real_model_confidence_count"] == 0
    assert report["real_inference_batch_report"]["placeholder_or_default_confidence_count"] == 1


def test_m1_cli_requires_paper_only_and_no_live(tmp_path: Path) -> None:
    out = tmp_path / "out"

    assert main(["--redis-url", "redis://127.0.0.1:6379/0", "--output-dir", str(out)]) == 1

    gate = json.loads((out / "m1_release_gate.json").read_text(encoding="utf-8"))
    assert gate["reason"] == "PAPER_ONLY_AND_NO_LIVE_FLAGS_REQUIRED"
