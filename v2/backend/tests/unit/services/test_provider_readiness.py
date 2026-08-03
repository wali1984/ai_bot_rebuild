from __future__ import annotations

from v2.backend.app.services.coinglass_provider import build_coinglass_health
from v2.backend.app.services.smart_money_wallets import build_moralis_health


def test_coinglass_forbidden_subscription_is_non_blocking_and_does_not_expose_key() -> None:
    health = build_coinglass_health({"COINGLASS_API_KEY": "secret-value"}, last_http_status=403)

    assert health["status"] == "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"
    assert health["raw_key_exposed"] is False
    assert "secret-value" not in str(health)
    assert health["invalid_subscription_blocks_core_system"] is False


def test_moralis_missing_key_is_not_green() -> None:
    health = build_moralis_health({}, last_http_status=None)

    assert health["status"] == "NOT_CONFIGURED"
    assert health["provider_shown_green_when_forbidden"] is False
    assert health["raw_key_exposed"] is False
