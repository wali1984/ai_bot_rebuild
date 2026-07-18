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


def test_diagnostic_reports_offline_relative_regression(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=70.0, offline_loss=72.0)  # offline worse
    r = h2l.run_h2l(offline_dir="x/offline", live_dir="x/live", rows=[1, 2, 3],
                    min_improvement=1.0, confirm=False)
    assert r["decision"] == "DIAGNOSTIC_OFFLINE_RELATIVE_REGRESSION"
    assert r["promoted"] is False
    assert r["promotion_mutation_authorized"] is False


def test_dry_run_when_offline_better_but_not_confirmed(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=84.0, offline_loss=70.0)  # offline better
    r = h2l.run_h2l(offline_dir="x/offline", live_dir="x/live", rows=[1, 2, 3],
                    min_improvement=1.0, confirm=False)
    assert r["decision"] == "DIAGNOSTIC_OFFLINE_RELATIVE_NON_REGRESSION"
    assert r["promoted"] is False
    assert r["offline_better_by"] == 14.0
    assert r["legacy_static_min_improvement_ignored"] == 1.0


def test_static_improvement_floor_is_ignored_by_relative_diagnostic(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=70.1, offline_loss=70.0)

    report = h2l.run_h2l(
        offline_dir="x/offline",
        live_dir="x/live",
        rows=[1],
        min_improvement=1_000_000.0,
        confirm=False,
    )

    assert report["decision"] == "DIAGNOSTIC_OFFLINE_RELATIVE_NON_REGRESSION"
    assert report["promotion_mutation_authorized"] is False


def test_aborts_on_load_failure(monkeypatch) -> None:
    _patch_scores(monkeypatch, live_loss=70.0, offline_loss=60.0, loaded=False)
    r = h2l.run_h2l(offline_dir="x/offline", live_dir="x/live", rows=[1],
                    min_improvement=0.0, confirm=False)
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


def test_confirm_fails_before_any_checkpoint_read_or_mutation(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("quarantined confirmation must touch no checkpoint")

    monkeypatch.setattr(h2l, "_infer_input_dim", forbidden)
    monkeypatch.setattr(h2l, "_score_checkpoint", forbidden)
    monkeypatch.setattr(h2l, "_backup_live_dir", forbidden)
    monkeypatch.setattr(h2l, "_promote", forbidden)

    report = h2l.run_h2l(
        offline_dir="offline",
        live_dir="live",
        rows=[object()],
        min_improvement=-999.0,
        confirm=True,
    )

    assert report["decision"] == h2l.LEGACY_H2L_MUTATION_BLOCKER
    assert report["promoted"] is False
    assert report["serving_checkpoint_mutated"] is False
    assert report["service_restart_attempted"] is False
    assert report["promotion_contract_verified"] is False


def test_confirm_cli_fails_before_archive_load(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        h2l,
        "load_h2l_heldout_examples",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("confirmation must not load the archive")
        ),
    )

    assert h2l.main(["--confirm"]) == 0
    assert h2l.LEGACY_H2L_MUTATION_BLOCKER in capsys.readouterr().out


def test_legacy_promote_helper_is_unconditionally_quarantined(tmp_path) -> None:
    with pytest.raises(RuntimeError, match=h2l.LEGACY_H2L_MUTATION_BLOCKER):
        h2l._promote(str(tmp_path / "offline"), str(tmp_path / "live"))  # noqa: SLF001

    assert not (tmp_path / "live").exists()


def _row(move):
    return SimpleNamespace(label_expected_move_after_cost_bps=move)


def test_returns_from_actions_direction_mapping() -> None:
    # long(1)=+move, short(2)=-move, everything else = no trade (skipped).
    rows = [_row(10.0), _row(10.0), _row(10.0), _row(-4.0), _row(-4.0)]
    actions = [1, 2, 0, 1, 2]
    assert h2l._returns_from_actions(rows, actions) == [10.0, -10.0, -4.0, 4.0]


def test_returns_from_actions_rejects_missing_label() -> None:
    rows = [SimpleNamespace(), _row(None), _row(5.0)]
    with pytest.raises(ValueError, match="H2L_MATURE_POST_COST_LABEL_MISSING"):
        h2l._returns_from_actions(rows, [1, 2, 1])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_returns_from_actions_rejects_nonfinite_mature_label(value) -> None:
    with pytest.raises(ValueError, match="H2L_MATURE_POST_COST_LABEL_NONFINITE"):
        h2l._returns_from_actions([_row(value)], [1])


def test_returns_from_actions_rejects_cardinality_mismatch() -> None:
    with pytest.raises(ValueError, match="H2L_ACTION_LABEL_CARDINALITY_MISMATCH"):
        h2l._returns_from_actions([_row(1.0)], [])


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
        confirm=False,
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
        confirm=False,
        require_risk_gate=True,
        min_sortino=0.0,
        max_cvar_loss_bps=50.0,
    )

    failures = r["risk_adjusted_validation"]["gate"]["failures"]
    assert r["decision"] == "REFUSE_RISK_ADJUSTED_PROMOTION_GATE"
    assert r["promoted"] is False
    assert "OFFLINE_SORTINO_WORSE_THAN_LIVE" in failures
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

    assert r["decision"] == "DIAGNOSTIC_OFFLINE_RELATIVE_NON_REGRESSION"
    assert r["promoted"] is False
    assert r["risk_adjusted_validation"]["gate"]["passed"] is True
    assert r["risk_adjusted_validation"]["gate"][
        "legacy_static_max_cvar_loss_bps_ignored"
    ] == 50.0


def test_h2l_cli_requires_risk_gate_by_default(monkeypatch) -> None:
    monkeypatch.delenv("V2_H2L_REQUIRE_RISK_GATE", raising=False)

    args = h2l.parse_args([])

    assert args.require_risk_gate is True


def _verified_manifest(*, input_dim: int = 1908, checkpoint_id: str = "ckpt"):
    return SimpleNamespace(
        checkpoint_id=checkpoint_id,
        input_dim=input_dim,
        model_id="model",
        lineage_kind="NON_SERVING_TRAINING_CANDIDATE",
        checkpoint_generation=7,
        checkpoint_semantic_digest="a" * 64,
        checkpoint_causal_record_digest="b" * 64,
    )


def _verified_report(manifest):
    return {
        "checkpoint_artifact_verified": True,
        "checkpoint_identity_verified": True,
        "checkpoint_evidence_verified": True,
        "weight_file_sha256_verified": True,
        "model_parameter_fingerprint_verified": True,
        "checkpoint_id": manifest.checkpoint_id,
        "weight_file_sha256": "c" * 64,
        "checkpoint_evidence_digest": "d" * 64,
    }


def test_infer_input_dim_uses_causal_verified_manifest_not_mtime(monkeypatch) -> None:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
        checkpoint as checkpoint_mod,
    )

    selected = _verified_manifest(input_dim=1908, checkpoint_id="causal-latest")
    older = _verified_manifest(input_dim=1832, checkpoint_id="causal-older")

    class FakeManager:
        def __init__(self, _path):
            pass

        def manifests(self, *, require_weight_blob):
            assert require_weight_blob is True
            return (selected, older)

        def verify_manifest_artifact(self, manifest):
            assert manifest is selected
            return _verified_report(manifest)

    monkeypatch.setattr(checkpoint_mod, "V2HybridCheckpointManager", FakeManager)

    assert h2l._infer_input_dim("ignored") == 1908


def test_infer_input_dim_rejects_arbitrary_json_and_mtime(tmp_path) -> None:
    manifest = tmp_path / "v2_hybrid_ckpt_arbitrary.json"
    manifest.write_text('{"input_dim": 1908}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkpoint_manifest_or_causal_ledger_invalid"):
        h2l._infer_input_dim(str(tmp_path))


def test_infer_input_dim_rejects_failed_artifact_verification(monkeypatch) -> None:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
        checkpoint as checkpoint_mod,
    )

    manifest = _verified_manifest()

    class FakeManager:
        def __init__(self, _path):
            pass

        def manifests(self, *, require_weight_blob):
            return (manifest,)

        def verify_manifest_artifact(self, _manifest):
            report = _verified_report(manifest)
            report["weight_file_sha256_verified"] = False
            return report

    monkeypatch.setattr(checkpoint_mod, "V2HybridCheckpointManager", FakeManager)

    with pytest.raises(RuntimeError, match="identity_or_lineage_unverified"):
        h2l._infer_input_dim("ignored")


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
