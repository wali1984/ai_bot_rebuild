from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from v2.backend.app.cli import v2_bounded_exploration_runtime_evaluator as evaluator
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    fit_candidate_outcome_calibration_v2,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_calibration_v2 import (
    _observation,
)

NOW_UTC = datetime(2026, 7, 28, 15, 0, 0, tzinfo=UTC)
FIT_METHOD = "BETA_POSTERIOR_MISSED_PROFITABLE_REJECTION_RATE"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _reseal(calibration: dict[str, Any]) -> dict[str, Any]:
    material = copy.deepcopy(calibration)
    material.pop("calibration_sha256", None)
    material["calibration_sha256"] = _canonical_sha256(material)
    return material


@pytest.fixture(scope="module")
def calibration_at_bound() -> dict[str, Any]:
    calibration = fit_candidate_outcome_calibration_v2(
        [_observation(index) for index in range(100)],
        generated_at_ms=3_000_000,
        source_archive_chain_sha256="c" * 64,
    )
    calibration["mode_allocation"] = {
        "champion_exploitation_probability": 0.5,
        "bounded_exploration_probability": 0.5,
        "fit_method": FIT_METHOD,
        "permanent_percentage": False,
    }
    return _reseal(calibration)


def _authority(
    calibration: dict[str, Any],
    *,
    generated_utc: datetime = NOW_UTC - timedelta(seconds=10),
) -> dict[str, Any]:
    return {
        "schema_version": "adaptive_paper_policy_runtime_status_v2",
        "status": "PASS_AUTHORITATIVE_PAPER_POLICY",
        "generated_utc": generated_utc.isoformat().replace("+00:00", "Z"),
        "calibration_sha256": calibration["calibration_sha256"],
        "checkpoint_generation": calibration["checkpoint_generation"],
        "checkpoint_id": calibration["checkpoint_id"],
        "adaptive_policy_authoritative": True,
        "reference_parity_disagreement_count": 0,
        "static_category_e_authority_removed": True,
        "physical_feasibility_is_policy": False,
        "performance_circuit_breaker_hard_trading_authority": False,
        "performance_circuit_breaker_adaptive_policy_role": (
            "CONTINUOUS_OBJECTIVE_RISK_INPUT"
        ),
        "adaptive_policy_paper_cycle_receipts_complete": True,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _raw(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _evaluate(
    calibration: dict[str, Any],
    authority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return evaluator.evaluate_bounded_exploration(
        _raw(calibration),
        _raw(authority or _authority(calibration)),
        now_utc=NOW_UTC,
    )


def test_current_half_ceiling_passes_with_exact_exhausted_semantics(
    calibration_at_bound: dict[str, Any],
) -> None:
    receipt = _evaluate(calibration_at_bound)

    assert receipt == {
        "schema_version": "bounded_exploration_runtime_evaluation_v1",
        "status": "PASS_BOUNDED_EXPLORATION_AT_CONFIGURED_LIMIT",
        "result": "NO_FURTHER_SAFE_INCREASE_WITHIN_CURRENT_BOUND",
        "calibration_source_key": evaluator.CALIBRATION_KEY,
        "authority_source_key": evaluator.AUTHORITY_STATUS_KEY,
        "calibration_sha256": calibration_at_bound["calibration_sha256"],
        "checkpoint_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "bounded_exploration_probability": 0.5,
        "champion_exploitation_probability": 0.5,
        "configured_max_bounded_exploration_probability": 0.5,
        "controllable_increase_remaining": False,
        "increase_applied": False,
        "permanent_percentage": False,
        "fit_method": FIT_METHOD,
        "authority_age_seconds": 10.0,
        "max_authority_age_seconds": 300.0,
        "evaluated_utc": "2026-07-28T15:00:00.000000Z",
        "adaptive_policy_authoritative": True,
        "reference_parity_disagreement_count": 0,
        "static_category_e_authority_removed": True,
        "physical_feasibility_is_policy": False,
        "evaluator_execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


@pytest.mark.parametrize("exploration", [0.49, math.nextafter(0.5, 0.0)])
def test_below_ceiling_blocks_while_controllable_increase_remains(
    calibration_at_bound: dict[str, Any],
    exploration: float,
) -> None:
    calibration = copy.deepcopy(calibration_at_bound)
    calibration["mode_allocation"]["bounded_exploration_probability"] = exploration
    calibration["mode_allocation"]["champion_exploitation_probability"] = (
        1.0 - exploration
    )

    with pytest.raises(
        ValueError,
        match="^CONTROLLABLE_BOUNDED_EXPLORATION_INCREASE_REMAINS$",
    ):
        _evaluate(_reseal(calibration))


def test_above_ceiling_fails_closed(calibration_at_bound: dict[str, Any]) -> None:
    calibration = copy.deepcopy(calibration_at_bound)
    calibration["mode_allocation"]["bounded_exploration_probability"] = 0.500001
    calibration["mode_allocation"]["champion_exploitation_probability"] = 0.499999

    with pytest.raises(
        ValueError,
        match="^calibration:EXPLORATION_ABOVE_CONFIGURED_BOUND$",
    ):
        _evaluate(_reseal(calibration))


@pytest.mark.parametrize(
    ("allocation", "reason"),
    [
        (
            {
                "champion_exploitation_probability": 0.4,
                "bounded_exploration_probability": 0.5,
                "fit_method": FIT_METHOD,
                "permanent_percentage": False,
            },
            "MODE_ALLOCATION_SUM_INVALID",
        ),
        (
            {
                "champion_exploitation_probability": math.nextafter(
                    math.nextafter(0.5, 1.0), 1.0
                ),
                "bounded_exploration_probability": 0.5,
                "fit_method": FIT_METHOD,
                "permanent_percentage": False,
            },
            "MODE_ALLOCATION_SUM_INVALID",
        ),
        (
            {
                "champion_exploitation_probability": -0.1,
                "bounded_exploration_probability": 1.1,
                "fit_method": FIT_METHOD,
                "permanent_percentage": False,
            },
            "MODE_ALLOCATION_RANGE_INVALID",
        ),
        (
            {
                "champion_exploitation_probability": 0.5,
                "bounded_exploration_probability": 0.5,
                "fit_method": "STATIC_UNAUTHENTICATED_PERCENTAGE",
                "permanent_percentage": False,
            },
            "MODE_ALLOCATION_FIT_METHOD_INVALID",
        ),
        (
            {
                "champion_exploitation_probability": 0.5,
                "bounded_exploration_probability": 0.5,
                "fit_method": FIT_METHOD,
                "permanent_percentage": True,
            },
            "PERMANENT_EXPLORATION_TIER_FORBIDDEN",
        ),
    ],
)
def test_invalid_allocation_contracts_fail_closed(
    calibration_at_bound: dict[str, Any],
    allocation: dict[str, Any],
    reason: str,
) -> None:
    calibration = copy.deepcopy(calibration_at_bound)
    calibration["mode_allocation"] = allocation

    with pytest.raises(ValueError, match=rf"^calibration:{reason}$"):
        _evaluate(_reseal(calibration))


@pytest.mark.parametrize(
    ("generated_utc", "reason"),
    [
        (NOW_UTC - timedelta(seconds=300.000001), "STALE"),
        (NOW_UTC + timedelta(seconds=5.000001), "FUTURE_GENERATED_AT"),
    ],
)
def test_stale_or_future_authority_fails_closed(
    calibration_at_bound: dict[str, Any],
    generated_utc: datetime,
    reason: str,
) -> None:
    authority = _authority(calibration_at_bound, generated_utc=generated_utc)

    with pytest.raises(ValueError, match=rf"^authority:{reason}$"):
        _evaluate(calibration_at_bound, authority)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("calibration_sha256", "f" * 64, "CALIBRATION_IDENTITY_MISMATCH"),
        ("checkpoint_generation", 4, "CHECKPOINT_GENERATION_MISMATCH"),
        ("checkpoint_id", "other-checkpoint", "CHECKPOINT_ID_MISMATCH"),
    ],
)
def test_authority_must_match_exact_calibration_and_checkpoint_identity(
    calibration_at_bound: dict[str, Any],
    field: str,
    value: object,
    reason: str,
) -> None:
    authority = _authority(calibration_at_bound)
    authority[field] = value

    with pytest.raises(ValueError, match=rf"^authority:{reason}$"):
        _evaluate(calibration_at_bound, authority)


def test_calibration_content_hash_tampering_fails_closed(
    calibration_at_bound: dict[str, Any],
) -> None:
    calibration = copy.deepcopy(calibration_at_bound)
    calibration["mode_allocation"]["bounded_exploration_probability"] = 0.49

    with pytest.raises(ValueError, match="calibration_sha256:content_hash_mismatch"):
        _evaluate(calibration)


@pytest.mark.parametrize(
    ("field", "unsafe_value", "reason"),
    [
        ("paper_only", False, "safety:paper_only_human_block_required"),
        ("live_gate", "open", "safety:paper_only_human_block_required"),
        ("routes_to_live", True, "safety:no_live_authority_required"),
        ("places_real_order", True, "safety:no_live_authority_required"),
        ("exchange_action_taken", True, "safety:no_live_authority_required"),
        (
            "execution_authority",
            True,
            "calibration:UNSAFE_AUTHORITY:execution_authority",
        ),
    ],
)
def test_calibration_safety_tampering_fails_closed(
    calibration_at_bound: dict[str, Any],
    field: str,
    unsafe_value: object,
    reason: str,
) -> None:
    calibration = copy.deepcopy(calibration_at_bound)
    calibration[field] = unsafe_value

    with pytest.raises(ValueError, match=rf"^{reason}$"):
        _evaluate(_reseal(calibration))


@pytest.mark.parametrize(
    ("field", "unsafe_value", "reason"),
    [
        ("schema_version", "wrong", "SCHEMA_VERSION_MISMATCH"),
        ("status", "BLOCKED", "STATUS_NOT_PASS"),
        ("paper_only", False, "PAPER_ONLY_REQUIRED"),
        ("live_gate", "open", "LIVE_GATE_BLOCK_REQUIRED"),
        ("routes_to_live", True, "UNSAFE_AUTHORITY:routes_to_live"),
        ("places_real_order", True, "UNSAFE_AUTHORITY:places_real_order"),
        ("exchange_action_taken", True, "UNSAFE_AUTHORITY:exchange_action_taken"),
        ("execution_authority", True, "UNSAFE_AUTHORITY:execution_authority"),
        (
            "adaptive_policy_authoritative",
            False,
            "ADAPTIVE_POLICY_NOT_AUTHORITATIVE",
        ),
        ("reference_parity_disagreement_count", 1, "REFERENCE_PARITY_DISAGREEMENT"),
        (
            "reference_parity_disagreement_count",
            False,
            "REFERENCE_PARITY_DISAGREEMENT",
        ),
        (
            "static_category_e_authority_removed",
            False,
            "STATIC_CATEGORY_E_AUTHORITY_PRESENT",
        ),
        (
            "physical_feasibility_is_policy",
            True,
            "PHYSICAL_FEASIBILITY_POLICY_CONFUSION",
        ),
        (
            "performance_circuit_breaker_hard_trading_authority",
            True,
            "PERFORMANCE_REGRESSION_HARD_VETO_PRESENT",
        ),
        (
            "performance_circuit_breaker_adaptive_policy_role",
            "HARD_TRADING_AUTHORITY",
            "PERFORMANCE_REGRESSION_ROLE_INVALID",
        ),
        (
            "adaptive_policy_paper_cycle_receipts_complete",
            False,
            "CYCLE_RECEIPTS_INCOMPLETE",
        ),
    ],
)
def test_authority_tampering_fails_closed(
    calibration_at_bound: dict[str, Any],
    field: str,
    unsafe_value: object,
    reason: str,
) -> None:
    authority = _authority(calibration_at_bound)
    authority[field] = unsafe_value

    with pytest.raises(ValueError, match=rf"{reason}$"):
        _evaluate(calibration_at_bound, authority)


def test_absent_optional_source_execution_authority_is_not_invented(
    calibration_at_bound: dict[str, Any],
) -> None:
    authority = _authority(calibration_at_bound)
    authority.pop("execution_authority")

    receipt = _evaluate(calibration_at_bound, authority)

    assert "execution_authority" not in receipt
    assert receipt["evaluator_execution_authority"] is False


@pytest.mark.parametrize(
    ("raw_calibration", "raw_authority", "reason"),
    [
        (b'{"paper_only":true,"paper_only":true}', b"{}", "DUPLICATE_JSON_KEY"),
        (b"{}", b'{"status":"x","status":"x"}', "DUPLICATE_JSON_KEY"),
        (b'{"value":NaN}', b"{}", "NONFINITE_JSON:NaN"),
        (b"{}", b'{"value":Infinity}', "NONFINITE_JSON:Infinity"),
        (b"{malformed", b"{}", "calibration:STRICT_JSON_REQUIRED"),
        (b"{}", b"[1,2,3]", "authority:OBJECT_REQUIRED"),
    ],
)
def test_duplicate_nonfinite_and_malformed_json_fail_closed(
    raw_calibration: bytes,
    raw_authority: bytes,
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        evaluator.evaluate_bounded_exploration(
            raw_calibration,
            raw_authority,
            now_utc=NOW_UTC,
        )


@pytest.mark.parametrize("maximum_age", [0, -1, float("nan"), float("inf"), True])
def test_invalid_maximum_authority_age_fails_closed(
    calibration_at_bound: dict[str, Any],
    maximum_age: object,
) -> None:
    with pytest.raises(ValueError, match="max_authority_age_seconds:"):
        evaluator.evaluate_bounded_exploration(
            _raw(calibration_at_bound),
            _raw(_authority(calibration_at_bound)),
            now_utc=NOW_UTC,
            max_authority_age_seconds=maximum_age,  # type: ignore[arg-type]
        )


def test_source_is_get_only_and_contains_no_filesystem_or_redis_writes() -> None:
    tree = ast.parse(inspect.getsource(evaluator))
    client_calls = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "client"
    ]
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    os_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
    }

    assert client_calls == ["get", "get"]
    assert "open" not in called_names
    assert not called_attributes.intersection(
        {
            "set",
            "delete",
            "hset",
            "lpush",
            "rpush",
            "publish",
            "execute_command",
            "write_text",
            "write_bytes",
            "mkdir",
            "touch",
            "unlink",
            "rename",
        }
    )
    assert not os_calls.intersection(
        {"replace", "rename", "remove", "unlink", "mkdir", "makedirs"}
    )


class _GetOnlyRedis:
    def __init__(self, values: dict[str, bytes]) -> None:
        self.values = values
        self.get_calls: list[str] = []

    def get(self, key: str) -> bytes:
        self.get_calls.append(key)
        return self.values[key]

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected Redis operation: {name}")


def test_main_reads_only_exact_sources_and_emits_no_increase_claim(
    calibration_at_bound: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authority = _authority(calibration_at_bound, generated_utc=datetime.now(UTC))
    client = _GetOnlyRedis(
        {
            evaluator.CALIBRATION_KEY: _raw(calibration_at_bound),
            evaluator.AUTHORITY_STATUS_KEY: _raw(authority),
        }
    )
    monkeypatch.setattr(evaluator, "_redis_client", lambda _url: client)
    monkeypatch.setenv("LIVE_GATE", "blocked_human_only")

    assert evaluator.main([]) == 0

    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert captured.err == ""
    assert client.get_calls == [evaluator.CALIBRATION_KEY, evaluator.AUTHORITY_STATUS_KEY]
    assert receipt["status"] == "PASS_BOUNDED_EXPLORATION_AT_CONFIGURED_LIMIT"
    assert receipt["result"] == "NO_FURTHER_SAFE_INCREASE_WITHIN_CURRENT_BOUND"
    assert receipt["controllable_increase_remaining"] is False
    assert receipt["increase_applied"] is False
    assert receipt["evaluator_execution_authority"] is False


def test_main_blocks_when_live_gate_is_not_human_blocked(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LIVE_GATE", raising=False)
    monkeypatch.setattr(
        evaluator,
        "_redis_client",
        lambda _url: pytest.fail("Redis must not be read before LIVE_GATE validation"),
    )

    assert evaluator.main([]) == 1

    captured = capsys.readouterr()
    receipt = json.loads(captured.err)
    assert captured.out == ""
    assert receipt["status"] == "BLOCKED"
    assert receipt["reason"] == "LIVE_GATE_BLOCK_REQUIRED"
    assert receipt["evaluator_execution_authority"] is False
    assert receipt["exchange_action_taken"] is False
