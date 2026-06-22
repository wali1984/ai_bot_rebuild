from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from v2.backend.app.cli import v2_coinapi_wsds_loop as wsds


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        return True


def test_coinapi_wsds_once_emits_truthful_blocked_status_without_opt_in(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("V2_COINAPI_WSDS_OPT_IN", raising=False)
    monkeypatch.delenv("COINAPI_API_KEY", raising=False)
    monkeypatch.delenv("COINAPI_KEY", raising=False)
    monkeypatch.setattr(wsds, "DEFAULT_SECRET_PATHS", (tmp_path / "missing.env",))
    monkeypatch.setattr(wsds, "_connect_redis", lambda: FakeRedis())

    out = tmp_path / "status.json"
    public = tmp_path / "public.json"
    worklog = tmp_path / "worklog.json"
    rc = wsds.main([
        "--once",
        "--smoke-test",
        "--out",
        str(out),
        "--out-public",
        str(public),
        "--out-worklog",
        str(worklog),
    ])

    assert rc == 0
    payload = json.loads(out.read_text())
    assert payload["classification"] == "V2_COINAPI_WSDS_BLOCKED"
    assert payload["operator_opt_in_enabled"] is False
    assert payload["stream_connected"] is False
    assert payload["credential_value_emitted"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert public.exists()
    assert worklog.exists()


def test_coinapi_wsds_rejects_non_v2_redis_keys() -> None:
    fake = FakeRedis()

    try:
        wsds._safe_set_json(fake, "msnap:coinapi_wsds:BTCUSDT", {"x": 1}, ex=60)
    except ValueError as exc:
        assert "refused non-V2 Redis key" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("non-V2 key was not rejected")


def test_coinapi_wsds_registry_remains_operator_gated_when_key_name_exists(monkeypatch) -> None:
    from v2.backend.app.services.native_ingestors import registry as reg_mod

    monkeypatch.setattr(
        "v2.backend.app.services.native_ingestors.secret_decision.key_name_available",
        lambda name, **kwargs: True,
    )

    cls = reg_mod._classify("live_coinapi_wsds")
    assert cls.classification == "OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN"
    assert cls.v2_namespace_payload_path == "v2/frontend/public/operator_runtime/v2_coinapi_wsds/"


def test_persistent_start_stop_scripts_cover_liquidation_and_coinapi_wsds() -> None:
    repo = REPO
    start = (repo / "claude_worklog/tools/start_v2_production_replacement_runtime.sh").read_text()
    stop = (repo / "claude_worklog/tools/stop_v2_production_replacement_runtime.sh").read_text()
    units = "\n".join(path.name for path in (repo / "claude_worklog/systemd/user").glob("*.service"))

    for token in (
        "ai-bot-v2-liquidation-wss-paper-shadow.service",
        "ai-bot-v2-liquidation-levels-engine.service",
        "ai-bot-v2-coinapi-wsds-loop.service",
        "v2.backend.app.cli.v2_liquidation_wss_loop",
        "v2.backend.app.cli.v2_liquidation_levels_engine",
        "v2.backend.app.cli.v2_coinapi_wsds_loop",
    ):
        assert token in start or token in units
        assert token in stop or token.endswith(".service")
