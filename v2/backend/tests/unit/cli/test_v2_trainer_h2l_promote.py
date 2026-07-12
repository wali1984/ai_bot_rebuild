"""Unit tests for the H2L promotion decision gate (no CUDA/checkpoints needed)."""
from __future__ import annotations

from types import SimpleNamespace

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
