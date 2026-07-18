from __future__ import annotations

from datetime import datetime

import pytest
from app.cli import v2_trainer_scheduled_pretrain as scheduled


def test_scheduled_pretrain_passes_risk_gate_to_h2l(monkeypatch) -> None:
    captured: dict[str, object] = {}
    training_rows = list(range(80))
    heldout_rows = list(range(10))

    monkeypatch.setattr(scheduled, "_gpu_free_vram_mb", lambda: None)
    monkeypatch.setattr(
        scheduled,
        "load_h2l_heldout_examples",
        lambda **_kwargs: (
            heldout_rows,
            training_rows,
            {"cache_hit": True},
        ),
    )
    monkeypatch.setattr(
        scheduled,
        "run_batch_training",
        lambda *_args, **_kwargs: {
            "trained_model": object(),
            "epochs_run": 1,
            "best_epoch": 1,
            "best_validation_loss": 1.0,
            "stopped_early": False,
            "gpu": {},
            "rows_per_second": 1.0,
        },
    )
    monkeypatch.setattr(
        scheduled,
        "save_offline_weights",
        lambda *_args, **_kwargs: {"checkpoint_id": "offline"},
    )
    monkeypatch.setattr(scheduled, "_publish", lambda _status: None)

    def fake_run_h2l(**kwargs):
        captured.update(kwargs)
        return {
            "decision": "DRY_RUN_OFFLINE_WINS_PASS_CONFIRM_TO_PROMOTE",
            "promoted": False,
            "risk_adjusted_validation": {"gate": {"required": True, "passed": True}},
        }

    monkeypatch.setattr(scheduled, "run_h2l", fake_run_h2l)

    status = scheduled.run_scheduled_pretrain(
        symbols=["BTCUSDT"],
        timeframes=["5m"],
        train_rows=80,
        heldout_rows=10,
        epochs=1,
        steps_per_epoch=1,
        batch_size=4,
        early_stop_patience=1,
        min_epochs=1,
        min_improvement=1.0,
        offline_dir="offline",
        live_dir="live",
        cache_path="cache.pkl",
        auto_promote=False,
        auto_restart=False,
        require_risk_gate=True,
        min_sortino=0.5,
        max_cvar_loss_bps=25.0,
    )

    assert status["require_risk_gate"] is True
    assert captured["require_risk_gate"] is True
    assert captured["min_sortino"] == 0.5
    assert captured["max_cvar_loss_bps"] == 25.0
    assert captured["confirm"] is False
    assert status["phase"] == "COMPLETE_PAPER_DIAGNOSTIC_ONLY"
    assert status["promoted"] is False


@pytest.mark.parametrize(
    ("auto_promote", "auto_restart"),
    [(True, False), (False, True), (True, True)],
)
def test_installed_auto_flags_fail_before_data_checkpoint_or_service_touch(
    monkeypatch, auto_promote: bool, auto_restart: bool
) -> None:
    published: list[dict[str, object]] = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("quarantined scheduled mutation must touch nothing")

    monkeypatch.setattr(scheduled, "load_h2l_heldout_examples", forbidden)
    monkeypatch.setattr(scheduled, "run_batch_training", forbidden)
    monkeypatch.setattr(scheduled, "save_offline_weights", forbidden)
    monkeypatch.setattr(scheduled, "run_h2l", forbidden)
    monkeypatch.setattr(scheduled.subprocess, "run", forbidden)
    monkeypatch.setattr(scheduled, "_publish", lambda status: published.append(status))

    status = scheduled.run_scheduled_pretrain(
        symbols=["BTCUSDT"],
        timeframes=["1m"],
        train_rows=1,
        heldout_rows=1,
        epochs=1,
        steps_per_epoch=1,
        batch_size=1,
        early_stop_patience=1,
        min_epochs=1,
        min_improvement=-999.0,
        offline_dir="offline",
        live_dir="live",
        cache_path="malicious.pkl",
        auto_promote=auto_promote,
        auto_restart=auto_restart,
        require_risk_gate=False,
        min_sortino=-999.0,
        max_cvar_loss_bps=999999.0,
    )

    assert status["phase"] == scheduled.LEGACY_H2L_MUTATION_BLOCKER
    assert status["data_load_attempted"] is False
    assert status["training_attempted"] is False
    assert status["offline_checkpoint_write_attempted"] is False
    assert status["serving_checkpoint_read_attempted"] is False
    assert status["serving_checkpoint_mutated"] is False
    assert status["service_restart_attempted"] is False
    assert status["trainer_restarted"] is False
    assert status["promoted"] is False
    assert published == [status]


def test_scheduled_module_contains_no_systemctl_command() -> None:
    source = scheduled.Path(scheduled.__file__).read_text(encoding="utf-8")
    assert "systemctl" not in source


def test_publish_uses_expiring_noncanonical_diagnostic_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import safety
    from v2.backend.app.services.native_trainer import persistent_cuda_trainer_runtime

    captured: dict[str, object] = {}

    def capture_set_json_expiring(self, key, payload, *, ex):  # noqa: ANN001, ARG001
        captured.update({"key": key, "payload": payload, "ex": ex})
        return True

    monkeypatch.setenv(scheduled.SCHEDULE_CADENCE_ENV, "30")
    monkeypatch.delenv(scheduled.STATUS_TTL_ENV, raising=False)
    monkeypatch.setattr(
        persistent_cuda_trainer_runtime,
        "connect_redis",
        lambda: object(),
    )
    monkeypatch.setattr(
        safety.V2OnlyJsonIO,
        "set_json_expiring",
        capture_set_json_expiring,
    )

    scheduled._publish({"generated_utc": "2026-07-18T12:00:00Z"})  # noqa: SLF001

    assert captured["key"] == scheduled.STATUS_REDIS_KEY
    assert captured["ex"] == 60
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["runtime_readiness_authority"] is False
    assert payload["serving_checkpoint_authority"] is False
    assert payload["status_scope"] == "NONCANONICAL_SCHEDULED_PRETRAIN_DIAGNOSTIC"
    assert datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00")) > datetime.fromisoformat(
        str(payload["published_utc"]).replace("Z", "+00:00")
    )


def test_gpu_busy_aborts_gracefully_before_training(monkeypatch) -> None:
    """Regression (2026-07-15 00:46 run): a concurrent offline trainer held
    9GiB VRAM and the scheduled run crashed with CUDA OOM (unit failed,
    exit 1). Insufficient free VRAM must abort gracefully BEFORE training so
    the timer retries later."""
    from v2.backend.app.cli import v2_trainer_scheduled_pretrain as sp

    monkeypatch.setattr(sp, "_gpu_free_vram_mb", lambda: 900.0)
    monkeypatch.setattr(sp, "_publish", lambda status: None)
    monkeypatch.setattr(
        sp, "load_h2l_heldout_examples",
        lambda **kw: ([object()] * 100, [object()] * 500, {"cache_hit": True}),
    )
    called = {"train": False}

    def _no_train(*a, **kw):
        called["train"] = True
        raise AssertionError("training must not start when GPU is busy")

    monkeypatch.setattr(sp, "run_batch_training", _no_train)
    status = sp.run_scheduled_pretrain(
        symbols=["BTCUSDT"], timeframes=["1m"], train_rows=500, heldout_rows=100,
        epochs=1, steps_per_epoch=1, batch_size=64, early_stop_patience=2,
        min_epochs=1, min_improvement=0.0, offline_dir="x", live_dir="y",
        cache_path=None, auto_promote=False, auto_restart=False,
        require_risk_gate=True, min_sortino=0.0, max_cvar_loss_bps=None,
    )
    assert status["phase"] == "ABORT_GPU_BUSY_INSUFFICIENT_VRAM"
    assert called["train"] is False
    assert status["gpu_free_vram_mb"] == 900.0


def test_gpu_telemetry_unavailable_proceeds(monkeypatch) -> None:
    """No nvidia-smi (None) must not block the run."""
    from v2.backend.app.cli import v2_trainer_scheduled_pretrain as sp

    monkeypatch.setattr(sp, "_gpu_free_vram_mb", lambda: None)
    monkeypatch.setattr(sp, "_publish", lambda status: None)
    monkeypatch.setattr(
        sp, "load_h2l_heldout_examples",
        lambda **kw: ([object()] * 100, [object()] * 500, {"cache_hit": True}),
    )
    seen = {}

    def _train_marker(*a, **kw):
        seen["train_started"] = True
        raise RuntimeError("stop_after_gate_check")

    monkeypatch.setattr(sp, "run_batch_training", _train_marker)
    try:
        sp.run_scheduled_pretrain(
            symbols=["BTCUSDT"], timeframes=["1m"], train_rows=500, heldout_rows=100,
            epochs=1, steps_per_epoch=1, batch_size=64, early_stop_patience=2,
            min_epochs=1, min_improvement=0.0, offline_dir="x", live_dir="y",
            cache_path=None, auto_promote=False, auto_restart=False,
            require_risk_gate=True, min_sortino=0.0, max_cvar_loss_bps=None,
        )
    except RuntimeError as exc:
        assert str(exc) == "stop_after_gate_check"
    assert seen.get("train_started") is True
