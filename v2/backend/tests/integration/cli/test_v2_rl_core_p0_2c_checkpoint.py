"""P0.2C integration tests: checkpoint inventory + safe-load shim."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def test_inventory_empty_root_returns_no_candidates(tmp_path: Path) -> None:
    from v2.backend.app.services.rl_core.checkpoints import inventory_checkpoints

    inv = inventory_checkpoints([tmp_path])
    assert inv.candidate_count == 0
    assert inv.status == "NO_CHECKPOINT_CANDIDATES_FOUND"


def test_inventory_picks_up_pt_pth_zip(tmp_path: Path) -> None:
    from v2.backend.app.services.rl_core.checkpoints import inventory_checkpoints

    (tmp_path / "legacy_live_checkpoint_1700000000.zip").write_bytes(b"FAKEZIP")
    (tmp_path / "hybrid_trainer_ckpt_1700000123_v1.pt").write_bytes(b"FAKEPT")
    (tmp_path / "noise.txt").write_text("ignored")
    (tmp_path / "ppo_masa_ckpt_1700000456_v2.pth").write_bytes(b"FAKEPTH")
    inv = inventory_checkpoints([tmp_path])
    assert inv.candidate_count == 3
    exts = sorted(c.extension for c in inv.candidates)
    assert exts == [".pt", ".pth", ".zip"]
    parsed_any = [c.parsed_metadata for c in inv.candidates if c.parsed_metadata is not None]
    assert len(parsed_any) >= 1


def test_inventory_parses_real_legacy_checkpoint_names(tmp_path: Path) -> None:
    from v2.backend.app.services.rl_core.checkpoints import inventory_checkpoints

    (tmp_path / "ppo_checkpoint_1772163701.zip").write_bytes(b"FAKEPPO")
    (tmp_path / "masa_checkpoint_1772262146.pkl").write_bytes(b"FAKEMASA")
    (tmp_path / "enterprise_modules_1772163701.pt").write_bytes(b"FAKEENT")
    inv = inventory_checkpoints([tmp_path])
    assert inv.candidate_count == 3
    parsed = {
        c.parsed_metadata.prefix: c.parsed_metadata.checkpoint_id
        for c in inv.candidates
        if c.parsed_metadata is not None
    }
    assert parsed["ppo_checkpoint"] == "ppo_checkpoint_1772163701"
    assert parsed["masa_checkpoint"] == "masa_checkpoint_1772262146"
    assert parsed["enterprise_modules"] == "enterprise_modules_1772163701"


def test_inventory_computes_sha256_for_small_files(tmp_path: Path) -> None:
    import hashlib
    from v2.backend.app.services.rl_core.checkpoints import inventory_checkpoints

    body = b"V2_CHECKPOINT_PROBE"
    p = tmp_path / "legacy_live_checkpoint_1700000789.zip"
    p.write_bytes(body)
    inv = inventory_checkpoints([tmp_path])
    assert inv.candidates[0].sha256_hex == hashlib.sha256(body).hexdigest()


def test_safe_load_when_inventory_empty_returns_operator_required(tmp_path: Path) -> None:
    from v2.backend.app.services.rl_core.checkpoints import (
        inventory_checkpoints,
        safe_load_checkpoint,
    )

    inv = inventory_checkpoints([tmp_path])
    res = safe_load_checkpoint(inv)
    assert res.checkpoint_id is None
    assert res.weight_loading_status == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    assert res.model_shape_status == "MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH"
    assert "no_checkpoint_candidates_in_scan_roots" in res.missing_checkpoint_blockers


def test_safe_load_when_inventory_has_candidate_refuses_to_load_weights(tmp_path: Path) -> None:
    from v2.backend.app.services.rl_core.checkpoints import (
        inventory_checkpoints,
        safe_load_checkpoint,
    )

    (tmp_path / "ppo_masa_ckpt_1700001000_v1.pt").write_bytes(b"FAKE")
    inv = inventory_checkpoints([tmp_path])
    res = safe_load_checkpoint(inv)
    assert res.weight_loading_status == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    assert res.model_shape_status == "MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH"
    assert res.checkpoint_id is not None
    assert "v2_control_plane_does_not_load_torch_weights" in res.missing_checkpoint_blockers


def test_p0_2c_module_has_no_forbidden_imports() -> None:
    text = (REPO / "v2/backend/app/services/rl_core/checkpoints.py").read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import stable_baselines3", "from stable_baselines3",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
    ):
        assert forbidden not in text, f"checkpoints.py contains forbidden: {forbidden}"


def test_checkpoints_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.rl_core.checkpoints import checkpoints_invariants_snapshot

    s = checkpoints_invariants_snapshot()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["loads_torch_weights"] is False
    assert s["imports_torch"] is False
