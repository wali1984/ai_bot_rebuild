"""Tests for the V2 checkpoint promotion scanner + CLI.

Paper-only. No torch import. No pickle deserialization. No legacy
filesystem reads. No weight load. Shape contract is torch-native
output-first ``[out, in]`` (see ``checkpoint_promotion`` module docstring
for rationale).
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

_LEGACY_DIR_BASENAME = "AI" + " " + "BOT"
_LEGACY_DIR_TOKEN = _LEGACY_DIR_BASENAME + "/"


def _torch_native_metadata() -> dict:
    """Canonical torch-native output-first sidecar."""
    return {
        "checkpoint_id": "v2_ckpt_2026_05_26_torch_native_operator_signed",
        "source_legacy_path": "legacy_reference/.backups/collapsed_checkpoint_2026_05_17.pt",
        "source_legacy_sha256": "a" * 64,
        "training_window_utc": "2026-05-10T00:00:00Z..2026-05-16T00:00:00Z",
        "obs_dim": 26,
        "action_count": 5,
        "action_labels": ["hold", "long", "short", "close", "hedge"],
        "tensor_shape_layout": "TORCH_OUTPUT_FIRST",
        "tensor_shapes_per_layer": {
            "w1": [16, 26],
            "b1": [16],
            "w2": [5, 16],
            "b2": [5],
            "w_exp": [1, 16],
            "b_exp": [1],
        },
        "operator_signature_id": "operator_key_id_42",
        "paper_only": True,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }


def _input_first_legacy_metadata() -> dict:
    """Legacy input-first ``[in, out]`` sidecar with explicit layout marker."""
    md = _torch_native_metadata()
    md["checkpoint_id"] = "v2_ckpt_2026_05_26_input_first_legacy_operator_signed"
    md["tensor_shape_layout"] = "INPUT_FIRST"
    md["tensor_shapes_per_layer"] = {
        "w1": [26, 16],
        "b1": [16],
        "w2": [16, 5],
        "b2": [5],
        "w_exp": [16, 1],
        "b_exp": [1],
    }
    return md


def _good_metadata() -> dict:
    """Back-compat alias used by older fixture call sites in this file."""
    return _torch_native_metadata()


def test_scan_returns_operator_required_when_root_absent(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    payload = svc.scan_local_models(tmp_path / "does_not_exist")
    assert payload["approved_root_status"] == "ABSENT"
    assert payload["overall_state"] == svc.STATE_OPERATOR_REQUIRED
    assert payload["candidate_count"] == 0


def test_scan_returns_operator_required_when_root_empty(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    empty = tmp_path / "empty_models"
    empty.mkdir()
    payload = svc.scan_local_models(empty)
    assert payload["approved_root_status"] == "EMPTY"
    assert payload["overall_state"] == svc.STATE_OPERATOR_REQUIRED


def test_blob_without_metadata_reports_metadata_missing(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_a.pt").write_bytes(b"\x00" * 32)
    payload = svc.scan_local_models(root)
    assert payload["overall_state"] == svc.STATE_METADATA_MISSING
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["state"] == svc.STATE_METADATA_MISSING


def test_metadata_without_blob_reports_blob_missing(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_b_metadata.json").write_text(json.dumps(_torch_native_metadata()))
    payload = svc.scan_local_models(root)
    assert payload["overall_state"] == svc.STATE_BLOB_MISSING


def test_torch_output_first_metadata_promotes_with_orientation_marker(
    tmp_path: Path,
) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_c.pt").write_bytes(b"\x00" * 32)
    (root / "ckpt_c_metadata.json").write_text(json.dumps(_torch_native_metadata()))
    payload = svc.scan_local_models(root)
    assert payload["overall_state"] == svc.STATE_READY
    cand = payload["candidates"][0]
    assert cand["state"] == svc.STATE_READY
    assert cand["metadata_errors"] == []
    assert cand["shape_mismatch_fields"] == []
    assert cand["shape_contract_orientation"] == svc.ORIENTATION_TORCH_OUTPUT_FIRST
    assert cand["declared_tensor_shape_layout"] == "TORCH_OUTPUT_FIRST"
    assert payload["orientation_counts"][svc.ORIENTATION_TORCH_OUTPUT_FIRST] == 1


def test_torch_native_metadata_without_layout_marker_defaults_to_torch_output_first(
    tmp_path: Path,
) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_default.pt").write_bytes(b"\x00" * 32)
    md = _torch_native_metadata()
    md.pop("tensor_shape_layout", None)
    (root / "ckpt_default_metadata.json").write_text(json.dumps(md))
    payload = svc.scan_local_models(root)
    cand = payload["candidates"][0]
    assert cand["state"] == svc.STATE_READY
    assert cand["shape_contract_orientation"] == svc.ORIENTATION_TORCH_OUTPUT_FIRST
    assert cand["declared_tensor_shape_layout"] is None


def test_input_first_metadata_normalizes_when_layout_marker_explicit(
    tmp_path: Path,
) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_inp.pt").write_bytes(b"\x00" * 32)
    (root / "ckpt_inp_metadata.json").write_text(
        json.dumps(_input_first_legacy_metadata())
    )
    payload = svc.scan_local_models(root)
    assert payload["overall_state"] == svc.STATE_READY
    cand = payload["candidates"][0]
    assert cand["state"] == svc.STATE_READY
    assert cand["shape_mismatch_fields"] == []
    assert (
        cand["shape_contract_orientation"]
        == svc.ORIENTATION_METADATA_INPUT_FIRST_NORMALIZED
    )
    assert cand["declared_tensor_shape_layout"] == "INPUT_FIRST"


def test_input_first_metadata_fails_closed_without_layout_marker(
    tmp_path: Path,
) -> None:
    """Regression guard: input-first ``[in, out]`` shapes without the
    explicit INPUT_FIRST marker must be rejected, otherwise a real torch
    sidecar emitted as ``[out, in]`` would be misclassified."""
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_bad.pt").write_bytes(b"\x00" * 32)
    md = _input_first_legacy_metadata()
    md.pop("tensor_shape_layout", None)
    (root / "ckpt_bad_metadata.json").write_text(json.dumps(md))
    payload = svc.scan_local_models(root)
    assert payload["overall_state"] == svc.STATE_SHAPE_MISMATCH
    cand = payload["candidates"][0]
    assert cand["shape_contract_orientation"] == svc.ORIENTATION_SHAPE_MISMATCH
    assert "tensor_shapes_per_layer.w1" in cand["shape_mismatch_fields"]
    assert "tensor_shapes_per_layer.w2" in cand["shape_mismatch_fields"]
    assert "tensor_shapes_per_layer.w_exp" in cand["shape_mismatch_fields"]


def test_shape_mismatch_is_reported_per_layer(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_d.pt").write_bytes(b"\x00" * 32)
    bad = _torch_native_metadata()
    bad["obs_dim"] = 13
    bad["tensor_shapes_per_layer"]["w1"] = [16, 13]
    (root / "ckpt_d_metadata.json").write_text(json.dumps(bad))
    payload = svc.scan_local_models(root)
    assert payload["overall_state"] == svc.STATE_SHAPE_MISMATCH
    fields = payload["candidates"][0]["shape_mismatch_fields"]
    assert "obs_dim" in fields
    assert "tensor_shapes_per_layer.w1" in fields
    assert payload["candidates"][0][
        "shape_contract_orientation"
    ] == svc.ORIENTATION_SHAPE_MISMATCH


def test_shape_mismatch_when_layer_dim_swapped_under_torch_layout(
    tmp_path: Path,
) -> None:
    """Bare ``[26, 16]`` declared as TORCH_OUTPUT_FIRST is wrong-shaped."""
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_swap.pt").write_bytes(b"\x00" * 32)
    bad = _torch_native_metadata()
    bad["tensor_shape_layout"] = "TORCH_OUTPUT_FIRST"
    bad["tensor_shapes_per_layer"]["w1"] = [26, 16]
    (root / "ckpt_swap_metadata.json").write_text(json.dumps(bad))
    payload = svc.scan_local_models(root)
    cand = payload["candidates"][0]
    assert cand["state"] == svc.STATE_SHAPE_MISMATCH
    assert "tensor_shapes_per_layer.w1" in cand["shape_mismatch_fields"]


def test_invalid_layout_value_fails_closed(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_inv.pt").write_bytes(b"\x00" * 32)
    bad = _torch_native_metadata()
    bad["tensor_shape_layout"] = "UNKNOWN_LAYOUT"
    (root / "ckpt_inv_metadata.json").write_text(json.dumps(bad))
    payload = svc.scan_local_models(root)
    cand = payload["candidates"][0]
    assert cand["state"] == svc.STATE_SHAPE_MISMATCH
    assert cand["shape_contract_orientation"] == svc.ORIENTATION_SHAPE_MISMATCH
    assert any(
        "tensor_shape_layout_invalid_value" in f
        for f in cand["shape_mismatch_fields"]
    )


def test_metadata_with_live_approval_is_refused(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_e.pt").write_bytes(b"\x00" * 32)
    bad = _torch_native_metadata()
    bad["approves_live"] = True
    (root / "ckpt_e_metadata.json").write_text(json.dumps(bad))
    payload = svc.scan_local_models(root)
    assert payload["overall_state"] == svc.STATE_METADATA_MISSING
    assert any(
        "approves_live_must_be_false" in e
        for e in payload["candidates"][0]["metadata_errors"]
    )


def test_paper_only_must_be_true(tmp_path: Path) -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_f.pt").write_bytes(b"\x00" * 32)
    bad = _torch_native_metadata()
    bad["paper_only"] = False
    (root / "ckpt_f_metadata.json").write_text(json.dumps(bad))
    payload = svc.scan_local_models(root)
    assert any(
        "paper_only_must_be_true" in e
        for e in payload["candidates"][0]["metadata_errors"]
    )


def test_v2_policy_shape_contract_is_torch_native_output_first() -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    contract = svc.V2_POLICY_SHAPE_CONTRACT["tensor_shapes_per_layer"]
    assert contract["w1"] == [16, 26]
    assert contract["w2"] == [5, 16]
    assert contract["w_exp"] == [1, 16]
    assert svc.V2_POLICY_SHAPE_CONTRACT["tensor_shape_layout_convention"] == (
        "TORCH_NATIVE_OUTPUT_FIRST_OUT_IN"
    )


def test_flat_counts_remain_unchanged() -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    flat = svc.V2_POLICY_SHAPE_CONTRACT["tensor_flat_counts"]
    assert flat == {
        "w1": 416,
        "b1": 16,
        "w2": 80,
        "b2": 5,
        "w_exp": 16,
        "b_exp": 1,
    }


def test_cli_emits_operator_required_when_root_absent(
    tmp_path: Path, capsys
) -> None:
    cli = importlib.import_module(
        "v2.backend.app.cli.v2_checkpoint_promotion_status"
    )
    worklog_out = tmp_path / "worklog/checkpoint_promotion_status.json"
    public_out = tmp_path / "public/operator_dashboard_payload.json"
    root = tmp_path / "no_models_here"
    rc = cli.main(
        [
            "--once",
            "--out-worklog",
            str(worklog_out),
            "--out-public",
            str(public_out),
            "--root",
            str(root),
        ]
    )
    assert rc == 0
    payload = json.loads(worklog_out.read_text())
    assert payload["go_no_go"] == "V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED"
    assert payload["overall_state"] == "CHECKPOINT_OPERATOR_REQUIRED"
    assert "operator_instruction" in payload and payload["operator_instruction"]
    # Both worklog and public mirrors must be identical and JSON-valid.
    assert worklog_out.read_text() == public_out.read_text()
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["tensor_shape_layout_convention"] == (
        "TORCH_NATIVE_OUTPUT_FIRST_OUT_IN"
    )


def test_module_does_not_import_torch() -> None:
    script = """
import importlib
import json
import sys

importlib.import_module(
    "v2.backend.app.services.rl_core.checkpoint_promotion"
)
print(json.dumps({"torch_imported": "torch" in sys.modules}))
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test script
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[5],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json.loads(completed.stdout)["torch_imported"] is False


def test_module_does_not_deserialize_pickle(tmp_path: Path) -> None:
    """Scanner must not import or invoke pickle / torch.load loaders."""
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_pkl_guard.pt").write_bytes(b"\x80\x04(garbage_pickle_payload)")
    (root / "ckpt_pkl_guard_metadata.json").write_text(
        json.dumps(_torch_native_metadata())
    )
    script = """
import importlib
import json
import sys
from pathlib import Path

svc = importlib.import_module(
    "v2.backend.app.services.rl_core.checkpoint_promotion"
)
payload = svc.scan_local_models(Path(sys.argv[1]))
source = Path(svc.__file__).read_text(encoding="utf-8")
print(
    json.dumps(
        {
            "overall_state": payload["overall_state"],
            "state_ready": svc.STATE_READY,
            "torch_imported": "torch" in sys.modules,
            "source": source,
        }
    )
)
"""
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and test script
        [sys.executable, "-c", script, str(root)],
        cwd=Path(__file__).resolve().parents[5],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    observed = json.loads(completed.stdout)
    assert observed["overall_state"] == observed["state_ready"]
    assert observed["torch_imported"] is False
    source = observed["source"]
    assert "import pickle" not in source
    assert "pickle.loads" not in source
    assert "pickle.load(" not in source
    assert "torch.load" not in source


def test_scanner_only_reads_within_approved_root(tmp_path: Path) -> None:
    """All filesystem paths in the result must live under the supplied root."""
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    root = tmp_path / "models"
    root.mkdir()
    (root / "ckpt_scope.pt").write_bytes(b"\x00" * 32)
    (root / "ckpt_scope_metadata.json").write_text(
        json.dumps(_torch_native_metadata())
    )
    payload = svc.scan_local_models(root)
    assert payload["approved_root"] == str(root)
    for cand in payload["candidates"]:
        if cand["blob_path"]:
            assert cand["blob_path"].startswith(str(root))
        if cand["metadata_path"]:
            assert cand["metadata_path"].startswith(str(root))


def test_scanner_does_not_touch_legacy_dir_path() -> None:
    """Verify the module source contains no hard-coded legacy directory reads."""
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    source = Path(svc.__file__).read_text(encoding="utf-8")
    legacy_token = _LEGACY_DIR_TOKEN
    assert f"/home/wali/Desktop/{legacy_token}" not in source
    assert f"{legacy_token}logs/" not in source
    assert f"{legacy_token}rl/" not in source
    assert 'APPROVED_ROOT = Path(".local_models")' in source


def test_default_approved_root_is_local_models() -> None:
    svc = importlib.import_module(
        "v2.backend.app.services.rl_core.checkpoint_promotion"
    )
    assert str(svc.APPROVED_ROOT) == ".local_models"
