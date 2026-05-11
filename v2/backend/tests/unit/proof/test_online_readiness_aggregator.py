from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.proof.online_readiness_aggregator import (
    FORBIDDEN_OPERATIONS,
    GO_NO_GO_MARKER_BLOCKED,
    GO_NO_GO_MARKER_READY,
    LANES,
    LIVE_GATE_STATUS,
    REQUIRED_OUTPUT_ARTIFACTS,
    build_online_readiness_rollup,
    write_online_readiness_rollup,
)


def _seed_marker(repo_root: Path, relative_path: str, content: str) -> None:
    p = repo_root / relative_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content + "\n", encoding="utf-8")


def _seed_all_ready(repo_root: Path) -> None:
    for lane in LANES:
        _seed_marker(repo_root, lane.relative_marker_path, lane.required_marker)


def test_aggregator_marks_ready_when_all_markers_match(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    rollup = build_online_readiness_rollup(
        tmp_path, generated_at="2026-05-11T00:00:00+00:00"
    )

    assert rollup["all_required_matched"] is True
    assert rollup["go_no_go_marker"] == GO_NO_GO_MARKER_READY
    assert rollup["live_gate_status"] == LIVE_GATE_STATUS
    assert rollup["blocking_lanes"] == []
    assert all(lane["matched"] for lane in rollup["lanes"])


def test_aggregator_marks_blocked_when_required_marker_missing(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    (tmp_path / LANES[0].relative_marker_path).unlink()
    rollup = build_online_readiness_rollup(tmp_path)

    assert rollup["all_required_matched"] is False
    assert rollup["go_no_go_marker"] == GO_NO_GO_MARKER_BLOCKED
    assert LANES[0].lane_id in rollup["blocking_lanes"]
    missing_lane = next(lane for lane in rollup["lanes"] if lane["lane_id"] == LANES[0].lane_id)
    assert missing_lane["found"] is False
    assert missing_lane["matched"] is False
    assert missing_lane["error"] == "missing"


def test_aggregator_marks_blocked_when_marker_text_diverges(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    _seed_marker(tmp_path, LANES[-1].relative_marker_path, "SOMETHING_ELSE")
    rollup = build_online_readiness_rollup(tmp_path)

    assert rollup["all_required_matched"] is False
    assert rollup["go_no_go_marker"] == GO_NO_GO_MARKER_BLOCKED
    diverged = next(
        lane for lane in rollup["lanes"] if lane["lane_id"] == LANES[-1].lane_id
    )
    assert diverged["found"] is True
    assert diverged["matched"] is False
    assert diverged["actual_marker"] == "SOMETHING_ELSE"


def test_write_emits_all_required_artifacts(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    output_dir = tmp_path / "out"
    _seed_all_ready(repo_root)
    write_online_readiness_rollup(
        repo_root, output_dir, generated_at="2026-05-11T00:00:00+00:00"
    )

    missing = [name for name in REQUIRED_OUTPUT_ARTIFACTS if not (output_dir / name).exists()]
    assert missing == []
    assert (output_dir / "GO_NO_GO.md").read_text().strip() == GO_NO_GO_MARKER_READY

    payload = json.loads((output_dir / "ONLINE_READINESS_ROLLUP.json").read_text())
    assert payload["live_gate_status"] == LIVE_GATE_STATUS
    assert payload["go_no_go_marker"] == GO_NO_GO_MARKER_READY
    assert payload["all_required_matched"] is True

    contract = (output_dir / "ONLINE_READINESS_CONTRACT.md").read_text()
    assert "V2 Online Readiness Contract" in contract
    assert "blocked_human_only" in contract


def test_write_records_blocked_state_when_one_lane_missing(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    output_dir = tmp_path / "out"
    _seed_all_ready(repo_root)
    (repo_root / LANES[2].relative_marker_path).unlink()
    rollup = write_online_readiness_rollup(repo_root, output_dir)

    assert rollup["go_no_go_marker"] == GO_NO_GO_MARKER_BLOCKED
    assert (output_dir / "GO_NO_GO.md").read_text().strip() == GO_NO_GO_MARKER_BLOCKED
    assert LANES[2].lane_id in rollup["blocking_lanes"]


def test_forbidden_operations_cover_mutation_surfaces() -> None:
    expected_surfaces = {
        "place_exchange_order",
        "cancel_exchange_order",
        "modify_exchange_order",
        "change_leverage",
        "change_margin_mode",
        "change_position_mode",
        "activate_live_keys",
        "enable_live_trading",
        "restart_live_trader",
        "restart_live_trainer",
        "restart_orchestrator",
        "restart_redis",
        "write_redis_key",
        "delete_redis_key",
        "trim_redis_key",
        "mutate_legacy_bot",
    }
    assert expected_surfaces.issubset(set(FORBIDDEN_OPERATIONS))


def test_module_imports_no_live_runtime_clients() -> None:
    import v2.backend.app.proof.online_readiness_aggregator as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    banned_imports = (
        "import redis",
        "from redis",
        "import ccxt",
        "from ccxt",
        "import websockets",
        "from websockets",
        "import requests",
        "from requests",
        "subprocess",
    )
    offenders = [needle for needle in banned_imports if needle in source]
    assert offenders == [], f"online_readiness_aggregator must not import: {offenders}"
