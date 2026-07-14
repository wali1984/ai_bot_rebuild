"""Unit tests for the H2L promotion decision gate (no CUDA/checkpoints needed)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

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


def test_promote_refuses_if_offline_checkpoint_reload_fails(monkeypatch, tmp_path) -> None:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (  # noqa: PLC0415
        checkpoint as checkpoint_mod,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (  # noqa: PLC0415
        model as model_mod,
    )

    class FakeModel:
        def __init__(self, *, input_dim):
            self.input_dim = input_dim

    class FakeCheckpointManager:
        def __init__(self, _path):
            pass

        def load_latest_weights(self, _model):
            return {
                "latest_checkpoint_loadable": False,
                "model_state_restored": False,
                "load_status": "NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST",
            }

        def write_checkpoint(self, **_kwargs):
            raise AssertionError("promotion must not write if reload failed")

    monkeypatch.setattr(h2l, "_infer_input_dim", lambda _path: 1248)
    monkeypatch.setattr(model_mod, "V2HybridPolicyModel", FakeModel)
    monkeypatch.setattr(checkpoint_mod, "V2HybridCheckpointManager", FakeCheckpointManager)

    with pytest.raises(RuntimeError, match="offline checkpoint reload failed"):
        h2l._promote(str(tmp_path / "offline"), str(tmp_path / "live"))  # noqa: SLF001


def _row(move):
    return SimpleNamespace(label_expected_move_after_cost_bps=move)


def test_returns_from_actions_direction_mapping() -> None:
    # long(1)=+move, short(2)=-move, everything else = no trade (skipped).
    rows = [_row(10.0), _row(10.0), _row(10.0), _row(-4.0), _row(-4.0)]
    actions = [1, 2, 0, 1, 2]
    assert h2l._returns_from_actions(rows, actions) == [10.0, -10.0, -4.0, 4.0]


def test_returns_from_actions_missing_label_is_zero() -> None:
    rows = [SimpleNamespace(), _row(None), _row(5.0)]
    # missing / None label -> 0.0 move; only the long trade contributes 5.0.
    assert h2l._returns_from_actions(rows, [1, 2, 1]) == [0.0, -0.0, 5.0]


def test_returns_from_actions_all_flat_is_empty() -> None:
    rows = [_row(9.0), _row(9.0)]
    assert h2l._returns_from_actions(rows, [0, 3]) == []


def test_aborts_when_heldout_rows_overlap_excluded_training_prefix(monkeypatch) -> None:
    tensor = SimpleNamespace(tensor_id="tensor-1", feature_snapshot_id="snapshot-1")
    row = SimpleNamespace(
        symbol="BTCUSDT",
        timeframe="5m",
        tensor=tensor,
        label_action_index=1,
        payload_keys=("feature_vector_hash",),
    )

    monkeypatch.setattr(h2l, "_infer_input_dim", lambda _path: 1248)

    def fail_score(*_args, **_kwargs):
        raise AssertionError("overlapping validation rows must abort before scoring")

    monkeypatch.setattr(h2l, "_score_checkpoint", fail_score)

    r = h2l.run_h2l(
        offline_dir="x/offline",
        live_dir="x/live",
        rows=[row],
        excluded_rows=[row],
        min_improvement=0.0,
        confirm=True,
    )

    assert r["decision"] == "ABORT_HELDOUT_OVERLAPS_TRAINING_ROWS"
    assert r["promoted"] is False
    assert r["heldout_overlap"]["overlap_count"] == 1


def test_load_h2l_heldout_examples_skips_training_prefix(monkeypatch) -> None:
    examples = list(range(10))

    def fake_loader(**kwargs):
        assert kwargs["limit"] == 7
        assert kwargs["rebuild_cache"] is False
        return examples, {"cache_hit": False}

    monkeypatch.setattr(h2l, "load_or_build_examples", fake_loader)

    heldout, excluded, meta = h2l.load_h2l_heldout_examples(
        symbols=["BTCUSDT"],
        timeframes=["5m"],
        limit=4,
        heldout_offset=3,
        cache_path="cache.pkl",
        rebuild_cache=False,
    )

    assert excluded == [0, 1, 2]
    assert heldout == [3, 4, 5, 6]
    assert meta["h2l_heldout_offset"] == 3
    assert meta["h2l_heldout_rows"] == 4


def test_risk_gate_refuses_offline_with_worse_downside_even_when_loss_better(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=84.0, offline_loss=70.0)

    def fake_risk(checkpoint_dir, input_dim, rows):  # noqa: ARG001
        is_offline = "offline" in checkpoint_dir
        if is_offline:
            return {
                "loaded": True,
                "trades": 5,
                "sortino_ratio": 0.4,
                "cvar": -90.0,
            }
        return {
            "loaded": True,
            "trades": 5,
            "sortino_ratio": 1.2,
            "cvar": -15.0,
        }

    monkeypatch.setattr(h2l, "_candidate_risk_summary", fake_risk)

    r = h2l.run_h2l(
        offline_dir="x/offline",
        live_dir="x/live",
        rows=[1, 2, 3, 4, 5],
        min_improvement=1.0,
        confirm=True,
        require_risk_gate=True,
        min_sortino=0.0,
        max_cvar_loss_bps=50.0,
    )

    failures = r["risk_adjusted_validation"]["gate"]["failures"]
    assert r["decision"] == "REFUSE_RISK_ADJUSTED_PROMOTION_GATE"
    assert r["promoted"] is False
    assert "OFFLINE_SORTINO_WORSE_THAN_LIVE" in failures
    assert "OFFLINE_CVAR_TAIL_LOSS_EXCEEDS_LIMIT" in failures
    assert "OFFLINE_CVAR_WORSE_THAN_LIVE" in failures


def test_risk_gate_passes_before_dry_run_promotion_decision(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=84.0, offline_loss=70.0)

    def fake_risk(checkpoint_dir, input_dim, rows):  # noqa: ARG001
        is_offline = "offline" in checkpoint_dir
        return {
            "loaded": True,
            "trades": 5,
            "sortino_ratio": 2.0 if is_offline else 1.0,
            "cvar": -5.0 if is_offline else -15.0,
        }

    monkeypatch.setattr(h2l, "_candidate_risk_summary", fake_risk)

    r = h2l.run_h2l(
        offline_dir="x/offline",
        live_dir="x/live",
        rows=[1, 2, 3, 4, 5],
        min_improvement=1.0,
        confirm=False,
        require_risk_gate=True,
        min_sortino=0.0,
        max_cvar_loss_bps=50.0,
    )

    assert r["decision"] == "DRY_RUN_OFFLINE_WINS_PASS_CONFIRM_TO_PROMOTE"
    assert r["promoted"] is False
    assert r["risk_adjusted_validation"]["gate"]["passed"] is True


def test_h2l_cli_requires_risk_gate_by_default(monkeypatch) -> None:
    monkeypatch.delenv("V2_H2L_REQUIRE_RISK_GATE", raising=False)

    args = h2l.parse_args([])

    assert args.require_risk_gate is True


def test_infer_input_dim_uses_newest_manifest_not_alphabetical(tmp_path) -> None:
    """Regression: manifests accumulate across arch generations; the alphabetical
    scan returned a stale-arch width (1832) even after a fresh 1908 candidate was
    saved, so H2L scored both sides through the old arch slot and aborted every
    run with ABORT_NO_VALIDATION_SIGNAL. Newest-mtime manifest must win."""
    import json as _json
    import os as _os

    stale = tmp_path / "v2_hybrid_ckpt_28e95fec1b4b711ee41bf6a1.json"  # sorts FIRST
    fresh = tmp_path / "v2_hybrid_ckpt_4260cdcc506bf3393b2ac488.json"
    stale.write_text(_json.dumps({"input_dim": 1832}))
    fresh.write_text(_json.dumps({"input_dim": 1908}))
    now = stale.stat().st_mtime
    _os.utime(stale, (now - 3600, now - 3600))  # stale is an hour older
    _os.utime(fresh, (now, now))
    assert h2l._infer_input_dim(str(tmp_path)) == 1908


def test_infer_input_dim_skips_manifests_without_dim(tmp_path) -> None:
    """checkpoint_retention_manifest.json (no input_dim) may be the newest file;
    it must be skipped, not treated as the candidate manifest."""
    import json as _json
    import os as _os

    manifest = tmp_path / "v2_hybrid_ckpt_4260cdcc506bf3393b2ac488.json"
    retention = tmp_path / "checkpoint_retention_manifest.json"
    manifest.write_text(_json.dumps({"input_dim": 1908}))
    retention.write_text(_json.dumps({"retained": []}))
    now = retention.stat().st_mtime
    _os.utime(manifest, (now - 60, now - 60))  # retention manifest is newest
    assert h2l._infer_input_dim(str(tmp_path)) == 1908


def test_heldout_proportional_split_when_supply_below_offset(monkeypatch) -> None:
    """Regression: 12,198 fresh-tail examples < the 16,000 training-prefix
    offset left an EMPTY heldout, so both H2L sides scored None and every run
    aborted with NO_VALIDATION_SIGNAL. Short supply must fall back to a
    proportional (still disjoint, suffix-newest) split."""
    rows = [SimpleNamespace(idx=i) for i in range(1000)]
    monkeypatch.setattr(
        h2l, "load_or_build_examples", lambda **kw: (rows, {"cache_hit": True})
    )
    heldout, prefix, meta = h2l.load_h2l_heldout_examples(
        symbols=["BTCUSDT"], timeframes=["1m"], limit=5000,
        heldout_offset=16000, cache_path=None, rebuild_cache=False,
    )
    assert len(prefix) == 760 and len(heldout) == 240
    assert meta["h2l_proportional_split_fallback"]["supply"] == 1000
    # disjoint and ordered: heldout is the NEWEST suffix
    assert prefix[-1].idx == 759 and heldout[0].idx == 760 and heldout[-1].idx == 999


def test_heldout_normal_split_unchanged_when_supply_sufficient(monkeypatch) -> None:
    rows = [SimpleNamespace(idx=i) for i in range(21000)]
    monkeypatch.setattr(
        h2l, "load_or_build_examples", lambda **kw: (rows, {"cache_hit": True})
    )
    heldout, prefix, meta = h2l.load_h2l_heldout_examples(
        symbols=["BTCUSDT"], timeframes=["1m"], limit=5000,
        heldout_offset=16000, cache_path=None, rebuild_cache=False,
    )
    assert len(prefix) == 16000 and len(heldout) == 5000
    assert "h2l_proportional_split_fallback" not in meta
