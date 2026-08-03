from __future__ import annotations

from v2.backend.app.cli.v2_same_day_production_cutover_status import build_cutover_packet
from v2.backend.app.services.provider_features import CONSUMER_ROLES


class FakeRedis:
    def get(self, _key: str):
        return None

    def ttl(self, _key: str) -> int:
        return -2


def test_same_day_cutover_packet_never_marks_live_ready_from_probation() -> None:
    packet = build_cutover_packet(
        redis_client=FakeRedis(),
        symbol="BTCUSDT",
        timeframe="1m",
        symbols=["BTCUSDT", "ETHUSDT"],
        wallets=[],
        tokens=[],
    )
    assert packet["live_ready"] is False
    assert packet["live_ready_from_probation_allowed"] is False
    assert packet["optional_provider_failures_core_blocking"] is False
    assert packet["heartbeat_only_green_allowed"] is False
    assert packet["status"] == "LIVE_CANARY_NOT_READY"
    assert packet["final_marker"].endswith("_BLOCKED")
    assert packet["primary_blocker"].startswith("coinglass_actual_payload_absent")
    assert set(packet["provider_consumption"].keys()) == set(CONSUMER_ROLES)
