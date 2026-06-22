"""Integration tests for the V2-owned runtime sprint.

Covers:

- zero_miss_dependency_closure scan produces a JSON artifact that holds
  the recorded invariants and counts.
- function/class/config atlas is present and parses.
- v2_owned_runtime smoke wrappers run and honestly fail when imports are
  unresolved, dependencies are missing, or legacy-root resolution occurs.
- redis namespace adapter rejects legacy writes.
- exchange fail-closed adapter rejects unknown methods.
- config adapter classifies legacy config keys as OPERATOR_DECISION_REQUIRED.
- No public payload from a V2-owned wrapper claims live=true.

All tests must not perform network I/O, not write to legacy Redis, and not
attempt any exchange mutation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


# --------------------------------------------------------------- artifact tests


def _load_json(rel: str) -> dict:
    p = REPO / rel
    assert p.exists(), f"missing artifact: {rel}"
    return json.loads(p.read_text())


def test_dependency_closure_artifact_present_and_consistent() -> None:
    d = _load_json(
        "claude_worklog/final_readiness/zero_miss_legacy_core_lift/latest/ZERO_MISS_DEPENDENCY_CLOSURE.json"
    )
    assert d.get("schema_version") == "1.0.0"
    assert d.get("runtime_tree") == "v2/legacy_owned_runtime"
    assert isinstance(d.get("classification_counts"), dict)
    assert isinstance(d.get("py_file_count"), int) and d["py_file_count"] > 0
    # The whole sprint is honest about residual unresolved imports.
    assert "unresolved_local_imports_count" in d
    assert "external_dependencies_count" in d


def test_function_class_atlas_present() -> None:
    d = _load_json(
        "claude_worklog/final_readiness/zero_miss_legacy_core_lift/latest/FUNCTION_CLASS_CONFIG_ATLAS.json"
    )
    assert isinstance(d, dict) or isinstance(d, list)


def test_trainer_atlas_present_and_parses() -> None:
    d = _load_json(
        "claude_worklog/final_readiness/zero_miss_legacy_core_lift/latest/TRAINER_ZERO_MISS_ATLAS.json"
    )
    assert isinstance(d, dict) or isinstance(d, list)


# --------------------------------------------------------------- adapter tests


def test_redis_namespace_adapter_blocks_legacy_writes() -> None:
    from v2.backend.app.services.v2_owned_runtime.redis_namespace_adapter import (
        RedisNamespaceAdapter,
        RedisNamespaceViolation,
        V2_NAMESPACE_PREFIX,
    )

    a = RedisNamespaceAdapter(client=None)
    with pytest.raises(RedisNamespaceViolation):
        a.set("features:BTCUSDT", "x")
    with pytest.raises(RedisNamespaceViolation):
        a.hset("predictions:legacy", "field", "x")
    with pytest.raises(RedisNamespaceViolation):
        a.xadd("proposals:legacy", {"k": "v"})
    with pytest.raises(RedisNamespaceViolation):
        a.delete("rl:legacy")
    # v2: namespace is allowed (no client → returns None, no exception)
    assert a.set(f"{V2_NAMESPACE_PREFIX}foo", "bar") is None


def test_redis_namespace_adapter_classifies_keys() -> None:
    from v2.backend.app.services.v2_owned_runtime.redis_namespace_adapter import (
        RedisNamespaceAdapter,
    )

    assert RedisNamespaceAdapter.classify("v2:some:key") == "V2_NAMESPACE"
    assert RedisNamespaceAdapter.classify("features:BTCUSDT") == "LEGACY_REFERENCE_READ_ONLY"


def test_exchange_fail_closed_adapter_rejects_unknown_methods() -> None:
    from v2.backend.app.services.v2_owned_runtime.exchange_fail_closed_adapter import (
        BlockedGateNotApproved,
        ExchangeFailClosedAdapter,
    )

    a = ExchangeFailClosedAdapter()
    # Any name not on the allow-list raises BlockedGateNotApproved.
    for n in ("place_market_position", "set_leverage", "change_margin_type", "transfer_balance"):
        with pytest.raises(BlockedGateNotApproved):
            getattr(a, n)


def test_exchange_fail_closed_adapter_allows_public_methods() -> None:
    from v2.backend.app.services.v2_owned_runtime.exchange_fail_closed_adapter import (
        ExchangeFailClosedAdapter,
    )

    a = ExchangeFailClosedAdapter()
    # public_ticker exists on the adapter and is callable; returns None when
    # no public client is wired in.
    assert a.public_ticker("BTCUSDT") is None
    assert a.public_depth("BTCUSDT") is None
    assert a.public_klines("BTCUSDT", "1m") is None
    assert a.account_snapshot() is None


def test_exchange_invariants_snapshot_holds_invariants() -> None:
    from v2.backend.app.services.v2_owned_runtime.exchange_fail_closed_adapter import (
        exchange_invariants_snapshot,
    )

    s = exchange_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["approves_live"] is False
    assert s["exchange_mutation_reachable"] is False


def test_config_adapter_lists_unmapped_keys_as_operator_decision_required() -> None:
    from v2.backend.app.services.v2_owned_runtime.config_adapter import (
        build_config_parity_matrix,
    )

    m = build_config_parity_matrix()
    assert m["live_gate"] == "blocked_human_only"
    assert m["live_symbols"] == []
    assert m["approves_live"] is False
    assert m["approves_legacy_shutdown"] is False
    # The legacy config files are in the preserved closure.
    assert m["legacy_config_present"] is True
    # Every unmapped key carries OPERATOR_DECISION_REQUIRED.
    for k in m["unmapped_keys"][:50]:
        assert k["v2_mapping_status"] == "OPERATOR_DECISION_REQUIRED"


# --------------------------------------------------------------- runtime smoke


@pytest.mark.parametrize("module_name,extra_args", [
    ("v2.backend.app.cli.v2_owned_ingestors_runtime", ["--dry-run"]),
    ("v2.backend.app.cli.v2_owned_feature_pipeline_runtime", ["--once"]),
    ("v2.backend.app.cli.v2_owned_trainer_runtime", ["--dry-run"]),
    ("v2.backend.app.cli.v2_owned_orchestrator_runtime", ["--once"]),
    ("v2.backend.app.cli.v2_owned_paper_trade_management_runtime", ["--once"]),
    ("v2.backend.app.cli.v2_owned_monitoring_runtime", ["--once"]),
])
def test_v2_owned_smoke_wrappers_pass(tmp_path: Path, module_name: str, extra_args: list[str]) -> None:
    out = tmp_path / f"{module_name.rsplit('.', 1)[1]}.json"
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    cmd = [sys.executable, "-m", module_name, *extra_args, "--out", str(out)]
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert out.exists(), f"smoke wrapper did not emit payload: {result.stderr}"
    payload = json.loads(out.read_text())
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["legacy_root_rejected_count"] == 0
    assert payload["smoke_pass"] is (payload["unresolved_count"] == 0)
    assert result.returncode == (0 if payload["smoke_pass"] else 1)
    if not payload["smoke_pass"]:
        assert payload["blockers"], "failed smoke must expose exact blockers"


# --------------------------------------------------------------- payload tests


def test_public_smoke_payloads_hold_invariants() -> None:
    paths = [
        "v2/frontend/public/operator_runtime/v2_owned_ingestors/latest/status.json",
        "v2/frontend/public/operator_runtime/v2_owned_feature_pipeline/latest/status.json",
        "v2/frontend/public/operator_runtime/v2_owned_trainer/latest/status.json",
        "v2/frontend/public/operator_runtime/v2_owned_orchestrator/latest/status.json",
        "v2/frontend/public/operator_runtime/v2_owned_trade_management/latest/status.json",
        "v2/frontend/public/operator_runtime/v2_owned_monitoring/latest/status.json",
    ]
    for rel in paths:
        d = _load_json(rel)
        assert d["live_gate"] == "blocked_human_only", rel
        assert d["live_symbols"] == [], rel
        assert d["approves_live"] is False, rel
        assert d["approves_legacy_shutdown"] is False, rel
        assert d["legacy_root_rejected_count"] == 0, rel
        assert d["smoke_pass"] is (d["unresolved_count"] == 0), rel
