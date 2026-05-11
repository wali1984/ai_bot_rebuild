"""Unit tests for `GET /api/v1/live-readiness/banner`.

The handler must:
- read each required lane marker under the supplied repo root
- return the aggregator's rollup dict as JSON
- never write any file, touch Redis, an exchange client, or a child
  process

These tests seed a synthetic repo root under `tmp_path` with marker files
that mirror the aggregator's lane spec (LANES), then exercise the
endpoint through FastAPI's TestClient. The repo-root override is plumbed
via the `V2_ONLINE_READINESS_REPO_ROOT` environment variable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.proof.online_readiness_aggregator import (
    GO_NO_GO_MARKER_BLOCKED,
    GO_NO_GO_MARKER_READY,
    LANES,
    LIVE_GATE_STATUS,
)


_BANNER_PATH = "/api/v1/live-readiness/banner"


def _seed_marker(repo_root: Path, relative_path: str, content: str) -> None:
    p = repo_root / relative_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content + "\n", encoding="utf-8")


def _seed_all_ready(repo_root: Path) -> None:
    for lane in LANES:
        _seed_marker(repo_root, lane.relative_marker_path, lane.required_marker)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("V2_ONLINE_READINESS_REPO_ROOT", str(tmp_path))
    return TestClient(create_app())


def test_banner_returns_ready_when_all_lane_markers_match(
    tmp_path: Path, client: TestClient
) -> None:
    _seed_all_ready(tmp_path)

    res = client.get(_BANNER_PATH)
    assert res.status_code == 200
    body = res.json()

    assert body["go_no_go_marker"] == GO_NO_GO_MARKER_READY
    assert body["all_required_matched"] is True
    assert body["blocking_lanes"] == []
    assert body["live_gate_status"] == LIVE_GATE_STATUS
    assert all(lane["matched"] for lane in body["lanes"])
    lane_ids = [lane["lane_id"] for lane in body["lanes"]]
    assert lane_ids == [lane.lane_id for lane in LANES]


def test_banner_returns_blocked_when_required_marker_missing(
    tmp_path: Path, client: TestClient
) -> None:
    _seed_all_ready(tmp_path)
    (tmp_path / LANES[0].relative_marker_path).unlink()

    res = client.get(_BANNER_PATH)
    assert res.status_code == 200
    body = res.json()

    assert body["go_no_go_marker"] == GO_NO_GO_MARKER_BLOCKED
    assert body["all_required_matched"] is False
    assert LANES[0].lane_id in body["blocking_lanes"]
    assert body["live_gate_status"] == LIVE_GATE_STATUS

    missing = next(
        lane for lane in body["lanes"] if lane["lane_id"] == LANES[0].lane_id
    )
    assert missing["found"] is False
    assert missing["matched"] is False
    assert missing["error"] == "missing"


def test_banner_returns_blocked_when_marker_text_diverges(
    tmp_path: Path, client: TestClient
) -> None:
    _seed_all_ready(tmp_path)
    _seed_marker(tmp_path, LANES[-1].relative_marker_path, "SOMETHING_ELSE")

    res = client.get(_BANNER_PATH)
    assert res.status_code == 200
    body = res.json()

    assert body["go_no_go_marker"] == GO_NO_GO_MARKER_BLOCKED
    assert body["all_required_matched"] is False
    assert LANES[-1].lane_id in body["blocking_lanes"]

    diverged = next(
        lane for lane in body["lanes"] if lane["lane_id"] == LANES[-1].lane_id
    )
    assert diverged["found"] is True
    assert diverged["matched"] is False
    assert diverged["actual_marker"] == "SOMETHING_ELSE"


def test_banner_does_not_write_inside_repo_root(
    tmp_path: Path, client: TestClient
) -> None:
    _seed_all_ready(tmp_path)

    def snapshot() -> dict[str, tuple[int, float]]:
        out: dict[str, tuple[int, float]] = {}
        for p in tmp_path.rglob("*"):
            if p.is_file():
                st = p.stat()
                out[str(p.relative_to(tmp_path))] = (st.st_size, st.st_mtime)
        return out

    before = snapshot()
    for _ in range(3):
        assert client.get(_BANNER_PATH).status_code == 200
    after = snapshot()

    assert before == after, (
        "GET /banner mutated files under the synthetic repo root; "
        f"diff={set(after.items()) ^ set(before.items())}"
    )


def test_banner_handler_imports_no_live_runtime_clients() -> None:
    import app.api.v1.live_readiness as mod

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
        "write_online_readiness_rollup",
    )
    offenders = [needle for needle in banned_imports if needle in source]
    assert offenders == [], (
        f"live_readiness handler must not reference: {offenders}"
    )
