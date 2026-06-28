from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import main as backend_main


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _prepare_dist(root: Path) -> Path:
    dist = root / "v2" / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    return dist


def test_operator_runtime_mount_uses_env_live_dir_before_release_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dist = _prepare_dist(tmp_path / "release")
    release_snapshot = (
        dist
        / "operator_runtime"
        / "v2_paper_trade_management"
        / "latest"
        / "paper_forward_canary_evidence_status.json"
    )
    live_payload = (
        tmp_path
        / "workspace"
        / "v2"
        / "frontend"
        / "public"
        / "operator_runtime"
        / "v2_paper_trade_management"
        / "latest"
        / "paper_forward_canary_evidence_status.json"
    )
    _write_json(release_snapshot, {"source": "release-stale"})
    _write_json(
        live_payload,
        {"source": "workspace-live", "valid_forward_canary_economic_outcomes": 15},
    )

    monkeypatch.setattr(backend_main, "_DIST_DIR", str(dist))
    monkeypatch.setattr(
        backend_main,
        "_PUBLIC_DIR",
        str(tmp_path / "release" / "v2" / "frontend" / "public"),
    )
    monkeypatch.setenv(
        backend_main._OPERATOR_RUNTIME_STATIC_DIR_ENV,
        str(live_payload.parents[2]),
    )

    client = TestClient(backend_main.create_app())
    res = client.get(
        "/operator_runtime/v2_paper_trade_management/latest/"
        "paper_forward_canary_evidence_status.json"
    )

    assert res.status_code == 200
    assert res.json()["source"] == "workspace-live"


def test_operator_runtime_mount_prefers_public_runtime_over_dist_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dist = _prepare_dist(tmp_path)
    public = tmp_path / "v2" / "frontend" / "public"
    runtime_rel = (
        "operator_runtime/v2_paper_trade_management/latest/"
        "paper_forward_canary_evidence_status.json"
    )
    _write_json(dist / runtime_rel, {"source": "dist-stale"})
    _write_json(public / runtime_rel, {"source": "public-live"})

    monkeypatch.setattr(backend_main, "_DIST_DIR", str(dist))
    monkeypatch.setattr(backend_main, "_PUBLIC_DIR", str(public))
    monkeypatch.delenv(backend_main._OPERATOR_RUNTIME_STATIC_DIR_ENV, raising=False)

    client = TestClient(backend_main.create_app())
    res = client.get(f"/{runtime_rel}")

    assert res.status_code == 200
    assert res.json()["source"] == "public-live"
