"""Freshness / audit-history extension tests for online_readiness_aggregator.

These tests cover the additive layer introduced by the V2 online-readiness
acceleration slice:

- per-lane ``marker_mtime_iso`` / ``marker_size_bytes`` / ``marker_sha256``
- per-lane ``marker_age_seconds`` / ``stale`` (relative to caller-supplied ``now``)
- top-level ``evidence_evaluated_at`` / ``evidence_freshness_window_seconds``
- top-level ``most_recent_lane_mtime_iso`` / ``oldest_lane_mtime_iso``
- top-level ``stale_lanes`` informational list
- invariant: staleness NEVER demotes the aggregate go/no-go marker from
  READY to BLOCKED (text-match remains the sole gating predicate)
- invariant: SHA-256 digest is taken over file bytes (tamper-evident)
- invariant: ``hashlib`` is the only new stdlib import; no live/runtime
  clients leak into the module

The fixtures mirror the existing test_online_readiness_aggregator.py helpers
so this file can run alongside without redefining shared marker constants.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.proof.online_readiness_aggregator import (
    DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS,
    GO_NO_GO_MARKER_BLOCKED,
    GO_NO_GO_MARKER_READY,
    LANES,
    LIVE_GATE_STATUS,
    ROLLUP_VERSION,
    build_online_readiness_rollup,
    write_online_readiness_rollup,
)


def _seed_marker(repo_root: Path, relative_path: str, content: str) -> None:
    p = repo_root / relative_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content + "\n", encoding="utf-8")


def _seed_all_ready(repo_root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for lane in LANES:
        _seed_marker(repo_root, lane.relative_marker_path, lane.required_marker)
        paths.append(repo_root / lane.relative_marker_path)
    return tuple(paths)


def test_rollup_version_bumped_to_v2(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    rollup = build_online_readiness_rollup(
        tmp_path, generated_at="2026-05-11T00:00:00+00:00"
    )
    assert ROLLUP_VERSION == "v2"
    assert rollup["rollup_version"] == "v2"


def test_default_freshness_window_is_thirty_days() -> None:
    assert DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS == 30 * 24 * 60 * 60


def test_each_lane_carries_mtime_size_and_sha256(tmp_path: Path) -> None:
    paths = _seed_all_ready(tmp_path)
    rollup = build_online_readiness_rollup(
        tmp_path, generated_at="2026-05-11T00:00:00+00:00"
    )
    assert len(rollup["lanes"]) == len(paths)
    for lane_status, marker_path in zip(rollup["lanes"], paths):
        assert lane_status["marker_mtime_iso"] is not None
        assert lane_status["marker_mtime_iso"].endswith("+00:00")
        expected_size = marker_path.stat().st_size
        assert lane_status["marker_size_bytes"] == expected_size
        expected_sha = hashlib.sha256(marker_path.read_bytes()).hexdigest()
        assert lane_status["marker_sha256"] == expected_sha


def test_marker_age_and_stale_disabled_when_now_omitted(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    rollup = build_online_readiness_rollup(
        tmp_path, generated_at="2026-05-11T00:00:00+00:00"
    )
    for lane_status in rollup["lanes"]:
        assert lane_status["marker_age_seconds"] is None
        assert lane_status["stale"] is False
    assert rollup["stale_lanes"] == []
    assert rollup["evidence_evaluated_at"] is None
    assert (
        rollup["evidence_freshness_window_seconds"]
        == DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS
    )


def test_stale_lanes_detected_when_marker_age_exceeds_window(tmp_path: Path) -> None:
    paths = _seed_all_ready(tmp_path)
    old_path = paths[0]
    old_epoch = time.time() - 60 * 24 * 60 * 60
    os.utime(old_path, (old_epoch, old_epoch))

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    rollup = build_online_readiness_rollup(
        tmp_path,
        generated_at="2026-05-11T00:00:00+00:00",
        now=now_iso,
        freshness_window_seconds=30 * 24 * 60 * 60,
    )
    assert LANES[0].lane_id in rollup["stale_lanes"]
    stale_lane = next(
        lane for lane in rollup["lanes"] if lane["lane_id"] == LANES[0].lane_id
    )
    assert stale_lane["stale"] is True
    assert stale_lane["marker_age_seconds"] is not None
    assert stale_lane["marker_age_seconds"] > 30 * 24 * 60 * 60


def test_freshly_seeded_lanes_are_not_stale(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    rollup = build_online_readiness_rollup(
        tmp_path,
        generated_at="2026-05-11T00:00:00+00:00",
        now=now_iso,
    )
    assert rollup["stale_lanes"] == []
    for lane_status in rollup["lanes"]:
        assert lane_status["stale"] is False
        assert lane_status["marker_age_seconds"] is not None
        assert lane_status["marker_age_seconds"] >= 0


def test_staleness_does_not_demote_go_no_go_marker(tmp_path: Path) -> None:
    """Staleness signal must NEVER flip aggregate marker to BLOCKED."""
    paths = _seed_all_ready(tmp_path)
    old_epoch = time.time() - 365 * 24 * 60 * 60
    for p in paths:
        os.utime(p, (old_epoch, old_epoch))

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    rollup = build_online_readiness_rollup(
        tmp_path,
        generated_at="2026-05-11T00:00:00+00:00",
        now=now_iso,
        freshness_window_seconds=30 * 24 * 60 * 60,
    )

    assert len(rollup["stale_lanes"]) == len(LANES)
    assert rollup["all_required_matched"] is True
    assert rollup["go_no_go_marker"] == GO_NO_GO_MARKER_READY
    assert rollup["blocking_lanes"] == []
    assert rollup["live_gate_status"] == LIVE_GATE_STATUS


def test_text_mismatch_still_blocks_even_when_fresh(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    _seed_marker(tmp_path, LANES[-1].relative_marker_path, "DIVERGED_MARKER")
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    rollup = build_online_readiness_rollup(
        tmp_path,
        generated_at="2026-05-11T00:00:00+00:00",
        now=now_iso,
    )
    assert rollup["all_required_matched"] is False
    assert rollup["go_no_go_marker"] == GO_NO_GO_MARKER_BLOCKED
    assert LANES[-1].lane_id in rollup["blocking_lanes"]


def test_most_recent_and_oldest_lane_mtime_are_computed(tmp_path: Path) -> None:
    paths = _seed_all_ready(tmp_path)
    base_epoch = time.time() - 7 * 24 * 60 * 60
    for i, p in enumerate(paths):
        ts = base_epoch + i * 86400
        os.utime(p, (ts, ts))

    rollup = build_online_readiness_rollup(
        tmp_path, generated_at="2026-05-11T00:00:00+00:00"
    )
    mtimes = [lane["marker_mtime_iso"] for lane in rollup["lanes"]]
    assert rollup["most_recent_lane_mtime_iso"] == max(mtimes)
    assert rollup["oldest_lane_mtime_iso"] == min(mtimes)
    assert rollup["most_recent_lane_mtime_iso"] != rollup["oldest_lane_mtime_iso"]


def test_missing_marker_has_empty_freshness(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    (tmp_path / LANES[0].relative_marker_path).unlink()
    rollup = build_online_readiness_rollup(
        tmp_path,
        generated_at="2026-05-11T00:00:00+00:00",
        now="2026-05-11T00:00:00+00:00",
    )
    missing = next(
        lane for lane in rollup["lanes"] if lane["lane_id"] == LANES[0].lane_id
    )
    assert missing["marker_mtime_iso"] is None
    assert missing["marker_size_bytes"] is None
    assert missing["marker_sha256"] is None
    assert missing["marker_age_seconds"] is None
    assert missing["stale"] is False
    assert rollup["go_no_go_marker"] == GO_NO_GO_MARKER_BLOCKED


def test_write_persists_freshness_fields_to_disk(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    output_dir = tmp_path / "out"
    _seed_all_ready(repo_root)
    write_online_readiness_rollup(
        repo_root,
        output_dir,
        generated_at="2026-05-11T00:00:00+00:00",
        now="2026-05-11T00:00:00+00:00",
    )
    payload = json.loads((output_dir / "ONLINE_READINESS_ROLLUP.json").read_text())
    assert (
        payload["evidence_freshness_window_seconds"]
        == DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS
    )
    assert payload["evidence_evaluated_at"] == "2026-05-11T00:00:00+00:00"
    assert payload["rollup_version"] == "v2"
    for lane in payload["lanes"]:
        assert "marker_mtime_iso" in lane
        assert "marker_sha256" in lane
        assert "marker_size_bytes" in lane
        assert "stale" in lane
        assert "marker_age_seconds" in lane


def test_contract_md_describes_freshness_layer(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    output_dir = tmp_path / "out"
    _seed_all_ready(repo_root)
    write_online_readiness_rollup(
        repo_root,
        output_dir,
        generated_at="2026-05-11T00:00:00+00:00",
        now="2026-05-11T00:00:00+00:00",
    )
    contract = (output_dir / "ONLINE_READINESS_CONTRACT.md").read_text()
    assert "Freshness" in contract
    assert "sha256" in contract
    assert "blocked_human_only" in contract


def test_invalid_now_string_is_treated_as_freshness_disabled(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    rollup = build_online_readiness_rollup(
        tmp_path,
        generated_at="2026-05-11T00:00:00+00:00",
        now="not-a-valid-iso-date",
    )
    assert rollup["evidence_evaluated_at"] is None
    assert rollup["stale_lanes"] == []
    for lane_status in rollup["lanes"]:
        assert lane_status["marker_age_seconds"] is None
        assert lane_status["stale"] is False


def test_naive_datetime_now_is_assumed_utc(tmp_path: Path) -> None:
    _seed_all_ready(tmp_path)
    naive_now = datetime(2099, 1, 1, 0, 0, 0)
    rollup = build_online_readiness_rollup(
        tmp_path,
        generated_at="2026-05-11T00:00:00+00:00",
        now=naive_now,
    )
    assert rollup["evidence_evaluated_at"] is not None
    assert rollup["evidence_evaluated_at"].endswith("+00:00")
    assert len(rollup["stale_lanes"]) == len(LANES)


def test_sha256_changes_when_marker_bytes_change_even_if_text_match_holds(
    tmp_path: Path,
) -> None:
    _seed_all_ready(tmp_path)
    rollup_a = build_online_readiness_rollup(
        tmp_path, generated_at="2026-05-11T00:00:00+00:00"
    )
    sha_a = rollup_a["lanes"][0]["marker_sha256"]

    marker_path = tmp_path / LANES[0].relative_marker_path
    marker_path.write_text(LANES[0].required_marker + "\n\n", encoding="utf-8")

    rollup_b = build_online_readiness_rollup(
        tmp_path, generated_at="2026-05-11T00:00:00+00:00"
    )
    sha_b = rollup_b["lanes"][0]["marker_sha256"]
    assert sha_a != sha_b
    assert rollup_b["lanes"][0]["matched"] is True


def test_module_still_imports_no_live_runtime_clients() -> None:
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
    assert offenders == [], (
        f"online_readiness_aggregator must not import: {offenders}"
    )
