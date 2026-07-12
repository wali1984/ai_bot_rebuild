"""Unit tests for the H2L promotion decision gate (no CUDA/checkpoints needed)."""
from __future__ import annotations

from app.cli import v2_trainer_h2l_promote as h2l


def _patch_scores(monkeypatch, live_loss, offline_loss, loaded=True):
    def fake_score(checkpoint_dir, input_dim, rows):
        is_offline = "offline" in checkpoint_dir
        return {
            "checkpoint_dir": checkpoint_dir,
            "loaded": loaded,
            "checkpoint_id": "offline_ckpt" if is_offline else "live_ckpt",
            "validation_supervised_loss": offline_loss if is_offline else live_loss,
            "validation_rows_evaluated": len(list(rows)),
        }

    monkeypatch.setattr(h2l, "_score_checkpoint", fake_score)
    monkeypatch.setattr(h2l, "_infer_input_dim", lambda d: 1248)


def test_refuses_when_offline_not_better(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=70.0, offline_loss=72.0)  # offline worse
    r = h2l.run_h2l(offline_dir="x/offline", live_dir="x/live", rows=[1, 2, 3],
                    min_improvement=1.0, confirm=True)
    assert r["decision"] == "REFUSE_OFFLINE_NOT_BETTER"
    assert r["promoted"] is False


def test_dry_run_when_offline_better_but_not_confirmed(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=84.0, offline_loss=70.0)  # offline better
    r = h2l.run_h2l(offline_dir="x/offline", live_dir="x/live", rows=[1, 2, 3],
                    min_improvement=1.0, confirm=False)
    assert r["decision"] == "DRY_RUN_OFFLINE_WINS_PASS_CONFIRM_TO_PROMOTE"
    assert r["promoted"] is False
    assert r["offline_better_by"] == 14.0


def test_aborts_on_load_failure(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=70.0, offline_loss=60.0, loaded=False)
    r = h2l.run_h2l(offline_dir="x/offline", live_dir="x/live", rows=[1],
                    min_improvement=0.0, confirm=True)
    assert r["decision"] == "ABORT_CHECKPOINT_LOAD_FAILED_OR_SHAPE_MISMATCH"
    assert r["promoted"] is False


def test_safety_posture_fields_present(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=84.0, offline_loss=70.0)
    r = h2l.run_h2l(offline_dir="x/offline", live_dir="x/live", rows=[1],
                    min_improvement=1.0, confirm=False)
    assert r["paper_only"] is True
    assert r["places_real_order"] is False
    assert r["routes_to_live"] is False
    assert r["live_gate"] == "blocked_human_only"
