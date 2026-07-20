"""Fail-closed isolation tests for stale provider feature payloads."""

from __future__ import annotations

import json
from typing import Any

import pytest

# isort: split
from v2.backend.app.services.provider_features import build_provider_consumer_context

_REMOVE = object()


class _FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, *, ex: int) -> None:
        self.data[key] = value
        self.ttls[key] = ex

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return self.ttls.get(key, -1)


def _context(
    provider_fields: dict[str, Any],
    *,
    required_providers: tuple[str, ...] = (),
) -> dict[str, Any]:
    redis_client = _FakeRedis()
    payload: dict[str, Any] = {
        "subscription_status": "READY",
        "actual_payload_present": True,
        "heartbeat_only": False,
        "event_time": "2026-07-08T11:58:00Z",
        "feature_cutoff": "2026-07-08T11:59:00Z",
        "available_at": "2026-07-08T12:00:00Z",
        "features": {"coinglass_funding_rate": 0.125},
    }
    payload.update(provider_fields)
    for field in tuple(payload):
        if payload[field] is _REMOVE:
            del payload[field]
    redis_client.set(
        "v2:features:coinglass:BTCUSDT:1m",
        json.dumps(payload),
        ex=180,
    )
    return build_provider_consumer_context(
        redis_client,
        role="trainer",
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time="2026-07-08T12:01:00Z",
        required_providers=required_providers,
    )


def _assert_no_stale_value_admitted(context: dict[str, Any], reason: str) -> None:
    provider = context["provider_payloads"]["coinglass"]
    assert provider["stale"] is True
    assert provider["excluded_from_features"] is True
    assert reason in provider["exclusion_reasons"]
    assert provider["features"] == {}
    assert context["provider_features"] == {}
    assert all(not payload for payload in context["payloads_for_tensor"].values())
    assert context.get("feature_source_lineage", {}) == {}
    diagnostic_lineage = context.get("source_lineage", {})
    if diagnostic_lineage:
        assert diagnostic_lineage["coinglass"]["excluded_from_features"] is True
    assert context["actual_provider_count"] == 0


def _assert_no_provider_value_admitted(context: dict[str, Any], reason: str) -> None:
    provider = context["provider_payloads"]["coinglass"]
    assert provider["actual_payload_present"] is False
    assert provider["heartbeat_only"] is True
    assert provider["excluded_from_features"] is True
    assert reason in provider["exclusion_reasons"]
    assert provider["features"] == {}
    assert context["provider_features"] == {}
    assert all(not payload for payload in context["payloads_for_tensor"].values())
    assert context.get("feature_source_lineage", {}) == {}
    assert context["actual_provider_count"] == 0


@pytest.mark.parametrize(
    ("provider_fields", "reason"),
    (
        ({"stale": True}, "coinglass:stale_payload_flag:stale"),
        ({"is_stale": " TrUe "}, "coinglass:stale_payload_flag:is_stale"),
        (
            {"subscription_status": " rate_limited "},
            "coinglass:stale_provider_status:RATE_LIMITED",
        ),
        (
            {"subscription_status": "DeGrAdEd"},
            "coinglass:stale_provider_status:DEGRADED",
        ),
        (
            {"stale": {"hostile": "value"}},
            "coinglass:stale_payload_flag:stale",
        ),
        (
            {"subscription_status": {"hostile": "READY"}},
            "coinglass:provider_status_invalid",
        ),
    ),
)
def test_stale_or_degraded_optional_provider_is_isolated_without_core_block(
    provider_fields: dict[str, Any],
    reason: str,
) -> None:
    context = _context(provider_fields)

    _assert_no_stale_value_admitted(context, reason)
    assert "coinglass" in context["optional_provider_failures"]
    assert context["core_system_blocked"] is False


@pytest.mark.parametrize(
    ("provider_fields", "reason"),
    (
        ({"stale": True}, "coinglass:stale_payload_flag:stale"),
        (
            {"subscription_status": "rAtE_lImItEd"},
            "coinglass:stale_provider_status:RATE_LIMITED",
        ),
        (
            {"subscription_status": "degraded"},
            "coinglass:stale_provider_status:DEGRADED",
        ),
    ),
)
def test_stale_or_degraded_required_provider_blocks_core(
    provider_fields: dict[str, Any],
    reason: str,
) -> None:
    context = _context(provider_fields, required_providers=("coinglass",))

    _assert_no_stale_value_admitted(context, reason)
    assert "coinglass" not in context["optional_provider_failures"]
    assert context["core_system_blocked"] is True


@pytest.mark.parametrize("value", (False, 0, "0", " false ", "NO", "off", ""))
def test_explicit_false_stale_spellings_do_not_discard_fresh_payload(value: Any) -> None:
    context = _context({"stale": value})

    assert context["provider_payloads"]["coinglass"]["stale"] is False
    assert context["provider_features"]["funding_rate"] == pytest.approx(0.125)
    assert context["core_system_blocked"] is False


@pytest.mark.parametrize(
    ("provider_fields", "reason"),
    (
        (
            {"actual_payload_present": 1},
            "coinglass:actual_payload_present_not_literal_true",
        ),
        (
            {"actual_payload_present": "true"},
            "coinglass:actual_payload_present_not_literal_true",
        ),
        (
            {"actual_payload_present": _REMOVE},
            "coinglass:actual_payload_present_not_literal_true",
        ),
        (
            {"heartbeat_only": 0},
            "coinglass:heartbeat_only_not_literal_false",
        ),
        (
            {"heartbeat_only": "false"},
            "coinglass:heartbeat_only_not_literal_false",
        ),
        (
            {"heartbeat_only": _REMOVE},
            "coinglass:heartbeat_only_not_literal_false",
        ),
    ),
)
def test_non_literal_or_missing_admission_flags_fail_closed(
    provider_fields: dict[str, Any],
    reason: str,
) -> None:
    optional_context = _context(provider_fields)
    required_context = _context(
        provider_fields,
        required_providers=("coinglass",),
    )

    _assert_no_provider_value_admitted(optional_context, reason)
    assert "coinglass" in optional_context["optional_provider_failures"]
    assert optional_context["core_system_blocked"] is False
    _assert_no_provider_value_admitted(required_context, reason)
    assert "coinglass" not in required_context["optional_provider_failures"]
    assert required_context["core_system_blocked"] is True
