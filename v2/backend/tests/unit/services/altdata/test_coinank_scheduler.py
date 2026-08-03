from __future__ import annotations

from app.services.altdata.coinank_scheduler import (
    advance_cursor,
    aligned_current_end_time_ms,
    canonical_usdt_symbol,
    derive_critical_call_budget,
    derive_critical_spend_budget_seconds,
    effective_capacity_satisfies_sla,
    effective_visit_interval_seconds,
    parameter_identity,
    select_due_critical_endpoint,
    select_parameter_batch,
)


def _params() -> list[dict[str, str]]:
    rows = []
    for symbol in ("AAAUSDT", "BTCUSDT", "BBBUSDT", "ETHUSDT", "SOLUSDT"):
        for timeframe in ("1h", "15m"):
            rows.append({
                "exchange": "Binance",
                "symbol": symbol,
                "interval": timeframe,
            })
    return rows


def test_persisted_cursor_is_fair_across_uneven_cycle_durations() -> None:
    params = _params()
    cursor = 0
    ledger: dict[str, int] = {}
    rotating_symbols: list[str] = []
    rotating_identities: list[str] = []
    cycle_times = (1_000_000, 1_073_000, 1_219_000, 1_410_000)

    for now_ms in cycle_times:
        batch = select_parameter_batch(
            "fundingRate_kline",
            params,
            cursor=cursor,
            max_calls=4,
            now_ms=now_ms,
            last_success_ms=ledger,
            endpoint_interval_seconds=60,
        )
        selection = batch["selection"]
        assert {row["symbol"] for row in selection[:3]} == {
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
        }
        rotating = [row for row in selection if row["selection_class"] == "rotating"]
        assert len(rotating) == 1
        rotating_symbols.append(rotating[0]["symbol"])
        rotating_identities.append(rotating[0]["identity"])
        for row in selection:
            ledger[row["identity"]] = now_ms
        cursor = advance_cursor(
            cursor,
            rotating_pool_size=batch["rotating_pool_size"],
            rotating_attempts=len(rotating),
        )

    assert rotating_symbols == ["AAAUSDT", "AAAUSDT", "BBBUSDT", "BBBUSDT"]
    assert len(set(rotating_identities)) == 4
    assert cursor == 0


def test_scheduler_reports_plan_capacity_that_cannot_meet_freshness_sla() -> None:
    params = [
        {"symbol": f"S{index}USDT", "interval": timeframe}
        for index in range(25)
        for timeframe in ("5m", "15m", "30m", "1h", "4h", "1d")
    ]
    params.extend(
        {"symbol": symbol, "interval": timeframe}
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT")
        for timeframe in ("5m", "15m", "30m", "1h", "4h", "1d")
    )

    batch = select_parameter_batch(
        "openInterest_kline",
        params,
        cursor=0,
        max_calls=4,
        now_ms=1_000_000,
        endpoint_interval_seconds=60,
        freshness_sla_seconds=600,
    )

    assert batch["preferred_estimated_revisit_seconds"] == 360
    assert batch["rotating_estimated_revisit_seconds"] > 600
    assert batch["coverage_partial"] is True
    assert parameter_identity("openInterest_kline", params[0]).startswith(
        "openInterest_kline:"
    )


def test_live_end_time_is_current_aligned_boundary_not_one_hour_old() -> None:
    now_ms = 1_800_000_953_123

    end_ms = aligned_current_end_time_ms(now_ms, "15m")

    assert end_ms <= now_ms
    assert now_ms - end_ms < 15 * 60 * 1000
    assert end_ms % (15 * 60 * 1000) == 0


def test_symbol_aliases_and_repeated_quote_suffixes_canonicalize_identically() -> None:
    aliases = ("btc", "BTCUSD", "btcusdt", "BTCUSDTUSDT")

    assert [canonical_usdt_symbol(value) for value in aliases] == [
        "BTCUSDT",
        "BTCUSDT",
        "BTCUSDT",
        "BTCUSDT",
    ]


def test_standard_plan_critical_budgets_meet_25_symbol_sla() -> None:
    params = [
        {"symbol": symbol, "interval": timeframe}
        for symbol in (
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            *(f"S{index}USDT" for index in range(22)),
        )
        for timeframe in ("5m", "15m", "30m", "1h", "4h", "1d")
    ]

    expected = ((15, 30, 7), (45, 20, 14), (60, 20, 17))
    for interval_seconds, rpm_share, expected_calls in expected:
        capacity = derive_critical_call_budget(
            params,
            endpoint_interval_seconds=interval_seconds,
            freshness_sla_seconds=600,
            rpm_share=rpm_share,
        )
        assert capacity["call_budget"] == expected_calls
        assert capacity["capacity_satisfies_sla"] is True

        batch = select_parameter_batch(
            "canonical_endpoint",
            params,
            cursor=0,
            max_calls=capacity["call_budget"],
            now_ms=1_000_000,
            endpoint_interval_seconds=interval_seconds,
            freshness_sla_seconds=600,
        )
        assert batch["preferred_estimated_revisit_seconds"] <= 600
        assert batch["rotating_estimated_revisit_seconds"] <= 600

    assert sum((30, 30, 20, 20, 20)) == 120


def test_expanded_universe_fails_closed_when_rpm_share_cannot_meet_sla() -> None:
    params = [
        {"symbol": symbol, "interval": timeframe}
        for symbol in (
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            *(f"S{index}USDT" for index in range(47)),
        )
        for timeframe in ("5m", "15m", "30m", "1h", "4h", "1d")
    ]

    capacity = derive_critical_call_budget(
        params,
        endpoint_interval_seconds=60,
        freshness_sla_seconds=600,
        rpm_share=20,
    )

    assert capacity["required_calls_for_sla"] == 32
    assert capacity["rpm_limited_calls"] == 20
    assert capacity["call_budget"] == 20
    assert capacity["capacity_satisfies_sla"] is False


def test_runtime_attempt_shortfall_fails_closed_even_when_plan_fits() -> None:
    assert effective_capacity_satisfies_sla(
        planned_capacity_satisfies_sla=True,
        call_budget=17,
        attempted_calls=17,
    ) is True
    assert effective_capacity_satisfies_sla(
        planned_capacity_satisfies_sla=True,
        call_budget=17,
        attempted_calls=16,
    ) is False

    params = [
        {"symbol": symbol, "interval": timeframe}
        for symbol in (
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            *(f"S{index}USDT" for index in range(22)),
        )
        for timeframe in ("5m", "15m", "30m", "1h", "4h", "1d")
    ]
    actual_throughput_plan = select_parameter_batch(
        "fundingRate_kline",
        params,
        cursor=0,
        max_calls=16,
        now_ms=1_000_000,
        endpoint_interval_seconds=60,
        freshness_sla_seconds=600,
    )
    assert actual_throughput_plan["rotating_estimated_revisit_seconds"] == 660
    assert actual_throughput_plan["coverage_partial"] is True


def test_cold_start_capacity_remains_warming_until_cadence_is_observed() -> None:
    planned_capacity = True
    full_batch_attempts = 25

    cold_start_capacity = effective_capacity_satisfies_sla(
        planned_capacity_satisfies_sla=planned_capacity and False,
        call_budget=25,
        attempted_calls=full_batch_attempts,
    )
    measured_second_visit_capacity = effective_capacity_satisfies_sla(
        planned_capacity_satisfies_sla=planned_capacity and True,
        call_budget=25,
        attempted_calls=full_batch_attempts,
    )

    assert cold_start_capacity is False
    assert measured_second_visit_capacity is True


def test_critical_due_queue_prioritizes_unstarted_then_oldest_endpoint() -> None:
    order = ("oi", "flow", "funding")

    first = select_due_critical_endpoint(
        order,
        last_started_ms={},
        now_ms=1_000_000,
        target_visit_interval_seconds=90,
    )
    second = select_due_critical_endpoint(
        order,
        last_started_ms={"oi": 1_000_000},
        now_ms=1_001_000,
        target_visit_interval_seconds=90,
    )
    oldest_due = select_due_critical_endpoint(
        order,
        last_started_ms={
            "oi": 900_000,
            "flow": 850_000,
            "funding": 950_000,
        },
        now_ms=1_050_000,
        target_visit_interval_seconds=90,
    )

    assert first["endpoint"] == "oi"
    assert second["endpoint"] == "flow"
    assert oldest_due["endpoint"] == "flow"


def test_critical_due_queue_respects_endpoint_adaptive_cooldown() -> None:
    last_started = {"oi": 1_000_000, "flow": 1_000_000}

    flow_due_first = select_due_critical_endpoint(
        ("oi", "flow"),
        last_started_ms=last_started,
        now_ms=1_095_000,
        target_visit_interval_seconds=90,
        minimum_visit_interval_seconds={"oi": 120, "flow": 90},
    )
    none_due = select_due_critical_endpoint(
        ("oi",),
        last_started_ms={"oi": 1_000_000},
        now_ms=1_095_000,
        target_visit_interval_seconds=90,
        minimum_visit_interval_seconds={"oi": 120},
    )

    assert flow_due_first["endpoint"] == "flow"
    assert none_due["endpoint"] is None
    assert none_due["seconds_until_next"] == 25


def test_capacity_uses_slower_measured_visit_cadence_not_optimistic_target() -> None:
    assert effective_visit_interval_seconds(
        target_visit_interval_seconds=90,
        previous_started_ms=1_000_000,
        current_started_ms=1_095_000,
    ) == 95
    assert effective_visit_interval_seconds(
        target_visit_interval_seconds=90,
        previous_started_ms=1_000_000,
        current_started_ms=1_050_000,
    ) == 90


def test_measured_95_second_cadence_has_sufficient_batch_and_deadline() -> None:
    params = [
        {"symbol": symbol, "interval": timeframe}
        for symbol in (
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            *(f"S{index}USDT" for index in range(22)),
        )
        for timeframe in ("5m", "15m", "30m", "1h", "4h", "1d")
    ]
    capacity = derive_critical_call_budget(
        params,
        endpoint_interval_seconds=95,
        freshness_sla_seconds=600,
        rpm_share=20,
    )
    plan = select_parameter_batch(
        "marketOrder_getBuySellValue",
        params,
        cursor=0,
        max_calls=capacity["call_budget"],
        now_ms=1_000_000,
        endpoint_interval_seconds=95,
        freshness_sla_seconds=600,
    )
    deadline = derive_critical_spend_budget_seconds(
        generic_spend_budget_seconds=6,
        call_budget=capacity["call_budget"],
        per_call_budget_seconds=3.5,
    )

    assert capacity["call_budget"] == 25
    assert capacity["capacity_satisfies_sla"] is True
    assert plan["rotating_estimated_revisit_seconds"] == 570
    assert deadline == 87.5
    assert 25 * 3.0 < deadline


def _semantic_validate(
    endpoint: str, response: object, *, available_at_ms: int
) -> dict[str, object]:
    from app.services.altdata.coinank_scheduler import validate_critical_response

    return validate_critical_response(
        endpoint,
        response,
        timeframe="1h",
        available_at_ms=available_at_ms,
    )


def test_semantic_validator_accepts_all_five_critical_response_shapes() -> None:
    interval_ms = 3_600_000
    boundary_ms = (1_800_000_000_000 // interval_ms) * interval_ms
    available_at_ms = boundary_ms + (interval_ms // 2)
    closed_open_ms = boundary_ms - interval_ms
    forming_open_ms = boundary_ms
    cases = (
        (
            "openInterest_kline",
            {
                "success": True,
                "code": "1",
                "data": [
                    {
                        "begin": closed_open_ms,
                        "open": 100.0,
                        "close": 110.0,
                        "low": 90.0,
                        "high": 120.0,
                    },
                    {
                        "begin": forming_open_ms,
                        "open": 110.0,
                        "close": 115.0,
                        "low": 105.0,
                        "high": 120.0,
                    },
                ],
            },
            {"open": 100.0, "close": 110.0, "low": 90.0, "high": 120.0},
        ),
        (
            "marketOrder_getBuySellValue",
            {
                "success": True,
                "code": "1",
                "data": {
                    "success": True,
                    "code": "1",
                    "data": [[closed_open_ms, 125.0, 80.0]],
                },
            },
            {"buy_value": 125.0, "sell_value": 80.0},
        ),
        (
            "liquidation_history",
            {
                "success": True,
                "code": "1",
                "data": [
                    {
                        "ts": closed_open_ms,
                        "longTurnover": 25.0,
                        "shortTurnover": 10.0,
                    }
                ],
            },
            {"long_turnover": 25.0, "short_turnover": 10.0},
        ),
        (
            "fundingRate_kline",
            {
                "success": True,
                "code": "1",
                "data": [
                    {
                        "begin": closed_open_ms,
                        "open": -0.002,
                        "close": 0.001,
                        "low": -0.003,
                        "high": 0.002,
                    }
                ],
            },
            {"open": -0.002, "close": 0.001, "low": -0.003, "high": 0.002},
        ),
        (
            "ls_global_account_ratio",
            {
                "success": True,
                "code": "1",
                "data": {
                    "tss": [closed_open_ms, forming_open_ms],
                    "longShortRatio": [1.25, 1.5],
                },
            },
            {"long_short_ratio": 1.25},
        ),
    )

    for endpoint, response, expected_values in cases:
        result = _semantic_validate(
            endpoint, response, available_at_ms=available_at_ms
        )
        assert result["valid"] is True
        assert result["bar_open_time_ms"] == closed_open_ms
        assert result["feature_cutoff_ms"] == boundary_ms
        assert result["closed_bar_age_seconds"] == interval_ms / 2000
        assert result["values"] == expected_values


def test_semantic_validator_requires_explicit_outer_and_nested_success() -> None:
    available_at_ms = 1_800_000_000_000
    open_ms = available_at_ms - 3_600_000

    missing_outer_success = _semantic_validate(
        "openInterest_kline",
        {
            "code": "1",
            "data": [
                {
                    "begin": open_ms,
                    "open": 1,
                    "close": 1,
                    "low": 1,
                    "high": 1,
                }
            ],
        },
        available_at_ms=available_at_ms,
    )
    missing_nested_code = _semantic_validate(
        "marketOrder_getBuySellValue",
        {
            "success": True,
            "code": "1",
            "data": {"success": True, "data": [[open_ms, 1, 1]]},
        },
        available_at_ms=available_at_ms,
    )

    assert missing_outer_success["reason"] == "api_success_not_explicit"
    assert missing_nested_code["reason"] == "nested_api_success_not_explicit"


def test_semantic_validator_rejects_forming_and_more_than_one_tf_old_rows() -> None:
    interval_ms = 3_600_000
    boundary_ms = (1_800_000_000_000 // interval_ms) * interval_ms
    available_at_ms = boundary_ms + (interval_ms // 2)

    def response(open_ms: int) -> dict[str, object]:
        return {
            "success": True,
            "code": "1",
            "data": [
                {
                    "begin": open_ms,
                    "open": 10,
                    "close": 10,
                    "low": 10,
                    "high": 10,
                }
            ],
        }

    forming = _semantic_validate(
        "openInterest_kline",
        response(boundary_ms),
        available_at_ms=available_at_ms,
    )
    stale = _semantic_validate(
        "openInterest_kline",
        response(boundary_ms - (3 * interval_ms)),
        available_at_ms=available_at_ms,
    )

    assert forming["reason"] == "no_recent_finalized_observation"
    assert stale["reason"] == "no_recent_finalized_observation"


def test_semantic_validator_rejects_missing_nonfinite_and_out_of_domain_values() -> None:
    available_at_ms = 1_800_000_000_000
    open_ms = available_at_ms - 3_600_000
    invalid_cases = (
        (
            "openInterest_kline",
            {
                "success": True,
                "code": "1",
                "data": [
                    {
                        "begin": open_ms,
                        "open": -1,
                        "close": -1,
                        "low": -1,
                        "high": -1,
                    }
                ],
            },
        ),
        (
            "openInterest_kline",
            {
                "success": True,
                "code": "1",
                "data": [
                    {
                        "begin": open_ms,
                        "open": 1,
                        "close": float("nan"),
                        "low": 1,
                        "high": 1,
                    }
                ],
            },
        ),
        (
            "marketOrder_getBuySellValue",
            {
                "success": True,
                "code": "1",
                "data": {
                    "success": True,
                    "code": "1",
                    "data": [[open_ms, 5, -1]],
                },
            },
        ),
        (
            "liquidation_history",
            {
                "success": True,
                "code": "1",
                "data": [{"ts": open_ms, "longTurnover": 1}],
            },
        ),
        (
            "fundingRate_kline",
            {
                "success": True,
                "code": "1",
                "data": [
                    {
                        "begin": open_ms,
                        "open": 0,
                        "close": 0,
                        "low": 0,
                        "high": 6,
                    }
                ],
            },
        ),
        (
            "ls_global_account_ratio",
            {
                "success": True,
                "code": "1",
                "data": {"tss": [open_ms], "longShortRatio": [0]},
            },
        ),
    )

    for endpoint, response in invalid_cases:
        result = _semantic_validate(
            endpoint, response, available_at_ms=available_at_ms
        )
        assert result["valid"] is False
        assert result["reason"] == "numeric_domain_invalid"


def test_invalid_http_200_preserves_seeded_latest_and_success_ledger() -> None:
    available_at_ms = 1_800_000_000_000
    latest_key = "latest:coinank:open_interest:BTCUSDT:1h"
    latest_store = {latest_key: {"close": 100.0, "usable": True}}
    success_ledger = {"existing_lane": available_at_ms - 1_000}
    stale_open_ms = available_at_ms - (3 * 3_600_000)
    invalid_payload = {
        "success": True,
        "code": "1",
        "data": [{
            "begin": stale_open_ms,
            "open": 999.0,
            "close": 999.0,
            "low": 999.0,
            "high": 999.0,
        }],
    }

    semantic = _semantic_validate(
        "openInterest_kline",
        invalid_payload,
        available_at_ms=available_at_ms,
    )
    if semantic["valid"]:
        latest_store[latest_key] = {"close": 999.0, "usable": False}
        success_ledger["invalid_lane"] = available_at_ms

    assert semantic["reason"] == "no_recent_finalized_observation"
    assert latest_store[latest_key] == {"close": 100.0, "usable": True}
    assert success_ledger == {"existing_lane": available_at_ms - 1_000}
