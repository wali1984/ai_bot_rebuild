"""Tests for the V2 full-observation missing-feature source-map.

Paper-only. No torch import. No legacy mutation.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def _mod():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.missing_feature_source_map"
    )


def test_classifies_all_unified_families_and_onchain() -> None:
    mod = _mod()
    payload = mod.build_missing_feature_source_map()
    family_ids = {f["family_id"] for f in payload["families"]}
    assert "unified_feature_family.token_metrics" in family_ids
    assert "unified_feature_family.coinank" in family_ids
    assert "unified_feature_family.binance_klines" in family_ids
    assert "portfolio_state.extended" in family_ids
    assert "position_context.extended" in family_ids
    assert "onchain_btc" in family_ids
    assert "onchain_eth" in family_ids


def test_token_metrics_and_onchain_marked_external_source_required() -> None:
    mod = _mod()
    payload = mod.build_missing_feature_source_map()
    by_id = {f["family_id"]: f for f in payload["families"]}
    assert by_id["unified_feature_family.token_metrics"][
        "v2_source_status"
    ] == "EXTERNAL_SOURCE_REQUIRED"
    assert by_id["onchain_btc"]["v2_source_status"] == "EXTERNAL_SOURCE_REQUIRED"
    assert by_id["onchain_eth"]["v2_source_status"] == "EXTERNAL_SOURCE_REQUIRED"


def test_one_narrow_task_per_missing_source_family() -> None:
    mod = _mod()
    payload = mod.build_missing_feature_source_map()
    families_requiring_task = [
        f for f in payload["families"]
        if f["v2_source_status"] in {
            "V2_SOURCE_MISSING_BUT_BUILDABLE",
            "EXTERNAL_SOURCE_REQUIRED",
            "OPERATOR_DECISION_REQUIRED",
        }
    ]
    assert len(payload["narrow_tasks_required"]) == len(families_requiring_task)
    task_ids = {t["task_id"] for t in payload["narrow_tasks_required"]}
    # Tasks must be unique (no duplicates across families).
    assert len(task_ids) == len(payload["narrow_tasks_required"])
    # Every task pairs with a unique codex review id.
    codex_ids = {t["paired_codex_review_task_id"] for t in payload["narrow_tasks_required"]}
    assert len(codex_ids) == len(task_ids)


def test_safety_invariants_in_payload() -> None:
    mod = _mod()
    payload = mod.build_missing_feature_source_map()
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_port_implementation_claimed"] is False


def test_cli_writes_payloads_and_idempotent_task_pair(
    tmp_path: Path, monkeypatch
) -> None:
    cli = importlib.import_module(
        "v2.backend.app.cli.v2_full_observation_missing_feature_source_map_status"
    )
    worklog = tmp_path / "wl/missing_source.json"
    dash = tmp_path / "dash/op.json"
    tasks = tmp_path / "tasks"
    monkeypatch.setattr(cli, "WORKLOG_STATUS", worklog)
    monkeypatch.setattr(cli, "PUBLIC_DASHBOARD", dash)
    monkeypatch.setattr(cli, "TASKS_DIR", tasks)
    rc1 = cli.main(["--once"])
    rc2 = cli.main(["--once"])  # second run must be idempotent
    assert rc1 == rc2 == 0
    a = json.loads(worklog.read_text())
    b = json.loads(dash.read_text())
    assert a == b
    assert a["go_no_go"] == "V2_FULL_OBSERVATION_MISSING_FEATURE_SOURCE_MAP_READY"
    # First call creates tasks; second sees them already on disk and
    # doesn't duplicate.
    assert a["narrow_tasks_required_count"] > 0
    # On the second run all pairs must be reported as existed-before.
    second_pairs = a["task_pairs_written_or_existing"]
    assert all(p["claude_existed_before"] for p in second_pairs)
    assert all(p["codex_existed_before"] for p in second_pairs)


def test_no_torch_imported() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.rl_core.missing_feature_source_map"
    )
    importlib.import_module(
        "v2.backend.app.cli.v2_full_observation_missing_feature_source_map_status"
    )
    assert "torch" not in sys.modules
